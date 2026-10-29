"""Replay pages must preserve cases beyond the old silent caps."""
import unittest
import tempfile
from contextlib import nullcontext
from unittest.mock import patch

import pandas as pd
import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import analyses


class ReplayPaginationTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(analyses.router)
        self.client = TestClient(app)
        self.meta = patch.object(analyses, '_get_analysis_or_404', return_value={
            'zone_places': {'Work': ['p']}})
        self.meta.start()
        self.addCleanup(self.meta.stop)

    def test_all_intervals_across_default_cap_without_losing_last_cases(self):
        frame = pd.DataFrame({'case_id': range(50003), 'place': 'p'})
        with patch.object(analyses.store, 'load_frame_page', side_effect=lambda _id, _name, offset, limit: (frame.iloc[offset:offset + limit].copy(), len(frame))):
            path = '/api/analyses/x/token-intervals'
            first = self.client.get(path).json()
            self.assertEqual(first['row_count'], 50000)
            self.assertEqual(first['total_count'], 50003)
            self.assertEqual(first['next_offset'], 50000)
            last = self.client.get(path, params={'offset': first['next_offset']}).json()
            self.assertEqual(last['offset'], 50000)
            self.assertIsNone(last['next_offset'])
            rows = first['rows'] + last['rows']
            self.assertEqual([r['case_id'] for r in rows], list(range(50003)))
            self.assertTrue(all(r['zone'] == 'Work' for r in rows))
            self.assertNotIn('zone', frame)  # cached source remains immutable
            empty = self.client.get(path, params={'offset': 60000}).json()
            self.assertEqual(empty['rows'], [])
            self.assertEqual(empty['total_count'], 50003)
            self.assertIsNone(empty['next_offset'])

    def test_stays_filter_then_page_and_expose_rows_after_old_cap(self):
        frame = pd.DataFrame({'case_id': range(200003), 'zone': 'Work'})
        with patch.object(analyses, '_zone_stays_frame', return_value=frame):
            path = '/api/analyses/x/zone-stays'
            last = self.client.get(path, params={'offset': 200000, 'limit': 10}).json()
            self.assertEqual(last['total_count'], 200003)
            self.assertEqual([r['case_id'] for r in last['rows']], [200000, 200001, 200002])
            self.assertIsNone(last['next_offset'])
            filtered = self.client.get(path, params={'zones': 'Other'}).json()
            self.assertEqual(filtered['total_count'], 0)
            self.assertEqual(filtered['rows'], [])

    def test_invalid_page_bounds_fail_explicitly(self):
        for endpoint, cap in [('token-intervals', 50000), ('zone-stays', 200000)]:
            for params in ({'offset': -1}, {'limit': 0}, {'limit': -1}, {'limit': cap + 1}):
                response = self.client.get('/api/analyses/x/' + endpoint, params=params)
                self.assertEqual(response.status_code, 422, response.text)

    def test_parquet_pages_preserve_persisted_order_and_nullable_timestamps(self):
        frame = pd.DataFrame({'case_id': list(range(50003))[::-1], 'place': 'p',
                              'consumed_ts': pd.to_datetime(['2024-01-01', None] * 25001 + [None], utc=True)})
        with tempfile.TemporaryDirectory() as directory, duckdb.connect() as con:
            con.register('source_frame', frame)
            con.execute('COPY source_frame TO ? (FORMAT PARQUET)', [directory + '/token_place.parquet'])
            persisted = con.execute('SELECT * FROM read_parquet(?)', [directory + '/token_place.parquet']).to_arrow_table().to_pandas()
            with patch.object(analyses.store, 'analysis_dir', return_value=directory), \
                 patch.object(analyses.store, '_connect', return_value=con), \
                 patch.object(analyses.store, '_access', side_effect=nullcontext), \
                 patch.object(analyses.store, 'load_frame', side_effect=AssertionError('Full frame read')):
                pages = []
                for offset in (0, 20000, 40000):
                    page, total = analyses.store.load_frame_page('x', 'token_place', offset, 20000)
                    self.assertEqual(total, len(frame))
                    pages.append(page)
                pd.testing.assert_frame_equal(pd.concat(pages, ignore_index=True), persisted)
                empty, total = analyses.store.load_frame_page('x', 'token_place', 60000, 20000)
                self.assertTrue(empty.empty)
                self.assertEqual(total, len(frame))
