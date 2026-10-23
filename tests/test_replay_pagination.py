"""Replay pages must preserve cases beyond the old silent caps."""
import unittest
from unittest.mock import patch

import pandas as pd
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
        with patch.object(analyses.store, 'load_frame', return_value=frame):
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
