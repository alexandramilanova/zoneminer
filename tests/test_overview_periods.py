"""Independent API checks for snapshot and alert-period presentation metadata."""
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from backend.main import create_app


class TestOverviewPeriods(unittest.TestCase):
    def test_actual_snapshot_and_lookback_boundaries(self):
        client = TestClient(create_app())
        for tf in ('h', 'D', '7D', '30D'):
            with self.subTest(timeframe=tf):
                starts = pd.date_range('2024-01-01', periods=10, freq=tf)
                frame = pd.DataFrame([
                    dict(zone=zone, window_start=start, token_present_end=50 if i == 6 else 0,
                         case_present_end=0, token_avg_age_open=float('nan'))
                    for i, start in enumerate(starts) for zone in ('A', 'B')
                ])
                with patch('backend.routers.analyses._get_analysis_or_404', return_value={'timeframe': tf}), patch('backend.routers.analyses._load_features_or_409', return_value=frame):
                    overview = client.get('/api/analyses/test/overview').json()
                    alerts = client.get('/api/analyses/test/alerts?lookback_windows=7').json()
                    self.assertEqual(pd.Timestamp(overview['latest_window']), starts[9])
                    self.assertEqual(pd.Timestamp(overview['latest_window_end']), starts[9] + pd.tseries.frequencies.to_offset(tf))
                    self.assertEqual(alerts['period']['window_count'], 7)  # not 14 zone rows
                    self.assertEqual(pd.Timestamp(alerts['period']['window_start']), starts[3])
                    self.assertEqual(pd.Timestamp(alerts['period']['window_end']), pd.Timestamp(overview['latest_window_end']))
                    self.assertEqual({pd.Timestamp(r['window_start']) for r in alerts['per_zone_summary']}, {starts[6]})
                    self.assertTrue(all(r['token_present_end'] == 0 for r in overview['per_zone_latest']))
                    short = client.get('/api/analyses/test/alerts?lookback_windows=3').json()
                    self.assertEqual(short['period']['window_count'], 3)
                    self.assertEqual(short['per_zone_summary'], [])

    def test_empty_alert_period(self):
        frame = pd.DataFrame(columns=['zone', 'window_start', 'token_present_end', 'token_avg_age_open'])
        with patch('backend.routers.analyses._get_analysis_or_404', return_value={'timeframe': 'D'}), patch('backend.routers.analyses._load_features_or_409', return_value=frame):
            response = TestClient(create_app()).get('/api/analyses/test/alerts')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['period'], dict(window_start=None, window_end=None, window_count=0))
