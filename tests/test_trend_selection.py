"""Independent exact-pair, segmentation and contribution examples."""
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from backend.main import create_app
from analytics.trend_selection import analyze_trend_selection, adjacent_segment_contributions
from analytics.changepoints import pelt_changepoints


class TestTrendSelection(unittest.TestCase):
    @staticmethod
    def frame():
        windows = pd.date_range('2024-01-01', periods=24, freq='D')
        return pd.DataFrame([dict(zone=z, window_start=t,
            token_present_end=(0 if i < 12 else 10) if z == 'A' else (0 if i < 8 else 6),
            case_present_end=(0 if i < 12 else 4) if z == 'B' else (i % 3),
            token_avg_age_open=(i + 1) * 3600,
            case_avg_duration_completed=100) for z in ['A', 'B'] for i, t in enumerate(windows)])

    def test_exact_pairs_no_cartesian_and_multiple_metrics_same_zone(self):
        result = analyze_trend_selection(self.frame(), [('A', 'token_present_end'), ('B', 'case_present_end'), ('A', 'token_avg_age_open')])
        self.assertEqual(set(zip(result['rows'].zone, result['rows'].metric)),
            {('A', 'token_present_end'), ('B', 'case_present_end'), ('A', 'token_avg_age_open')})
        self.assertEqual(len(result['rows']), 72)

    def test_invalid_and_duplicate_pairs_are_rejected(self):
        for pairs in [[('A', 'no_metric')], [('Missing', 'token_present_end')], [('A', 'token_present_end')] * 2]:
            with self.subTest(pairs=pairs), self.assertRaises(ValueError):
                analyze_trend_selection(self.frame(), pairs)

    def test_all_four_switch_combinations(self):
        for local in [False, True]:
            for overall in [False, True]:
                with self.subTest(local=local, overall=overall):
                    result = analyze_trend_selection(self.frame(), [('A', 'token_present_end'), ('B', 'case_present_end')],
                        local_enabled=local, overall_enabled=overall, cp_strictness=0)
                    self.assertEqual(result['local_changepoints'].empty, not local)
                    self.assertEqual(result['overall']['status'] == 'disabled', not overall)
                    self.assertEqual(result['overall']['changepoints'].empty, not overall)

    def test_independently_known_boundary_and_aggregate_standardization(self):
        # Positive affine transforms of the same step standardize identically:
        # 12 x -1, then 12 x +1; mean is that exact same signal.
        result = analyze_trend_selection(self.frame(), [('A', 'token_present_end'), ('B', 'case_present_end')], overall_enabled=True, cp_strictness=0)
        np.testing.assert_allclose(result['overall']['signal'].value, [-1] * 12 + [1] * 12)
        self.assertIn(pd.Timestamp('2024-01-13'), set(result['overall']['changepoints'].timestamp))
        self.assertEqual(pelt_changepoints(pd.Series([0.] * 12 + [10.] * 12), penalty=5), [12])
        contribution = result['overall']['contributions']
        np.testing.assert_allclose(contribution.contribution_pct, 50)

    def test_constants_insufficient_observations_and_single_component(self):
        frame = self.frame()
        frame.loc[(frame.zone == 'A') & (frame.index >= 5), 'token_avg_age_open'] = np.nan
        result = analyze_trend_selection(frame, [('A', 'case_avg_duration_completed'), ('A', 'token_avg_age_open'), ('B', 'case_present_end')], overall_enabled=True)
        self.assertEqual([s['status'] for s in result['series']], ['constant', 'insufficient_observations', 'usable'])
        self.assertEqual(result['overall']['status'], 'insufficient_components')
        self.assertEqual(result['overall']['n_series'], 1)

    def test_display_normalization_never_changes_detection_or_contributions(self):
        kwargs = dict(pairs=[('A', 'token_present_end'), ('B', 'case_present_end')], overall_enabled=True)
        raw = analyze_trend_selection(self.frame(), **kwargs)
        normalized = analyze_trend_selection(self.frame(), **kwargs, normalize=True)
        pd.testing.assert_frame_equal(raw['local_changepoints'], normalized['local_changepoints'])
        for key in ['signal', 'changepoints', 'contributions']:
            pd.testing.assert_frame_equal(raw['overall'][key], normalized['overall'][key])
        self.assertNotEqual(raw['rows'].value.tolist(), normalized['rows'].value.tolist())

    def test_strictness_is_forwarded_to_local_and_overall_and_100_returns_none(self):
        with patch('analytics.trend_selection.collect_changepoint_events', return_value=pd.DataFrame()) as local, patch('analytics.trend_selection.pelt_changepoints', return_value=[]) as overall:
            analyze_trend_selection(self.frame(), [('A', 'token_present_end'), ('B', 'case_present_end')], cp_strictness=75, overall_enabled=True)
            self.assertTrue(all(call.kwargs['cp_strictness'] == 75 for call in local.call_args_list))
            self.assertEqual(overall.call_args.kwargs['strictness'], 75)
        result = analyze_trend_selection(self.frame(), [('A', 'token_present_end'), ('B', 'case_present_end')], cp_strictness=100, overall_enabled=True)
        self.assertTrue(result['local_changepoints'].empty)
        self.assertTrue(result['overall']['changepoints'].empty)

    def test_adjacent_segment_contributions_use_full_segments_not_three_flanks(self):
        windows = pd.date_range('2024-01-01', periods=16)
        # Segment means: A: 0,3,4; B:0,1,4. Thus first boundary 75/25,
        # second 25/75. Near-boundary values alone give a different answer.
        a = [0] * 4 + [12] + [0] * 3 + [4] * 8
        b = [0] * 4 + [4] + [0] * 3 + [4] * 8
        wide = pd.DataFrame({('A__safe', 'token_present_end'): a, ('B', 'case_present_end'): b}, index=windows)
        out, details = adjacent_segment_contributions(wide, [4, 8], {})
        for stamp, expected in [(windows[4], {'A__safe': 75, 'B': 25}), (windows[8], {'A__safe': 25, 'B': 75})]:
            subset = out[out.timestamp == stamp]
            self.assertEqual(dict(zip(subset.zone, subset.contribution_pct)), expected)
            self.assertAlmostEqual(subset.contribution_pct.sum(), 100)
        self.assertEqual(out.iloc[0].before_n, 4)
        self.assertEqual(len(details), 2)

    def test_zero_jump_and_missing_segment_contributions_are_not_invented(self):
        idx = pd.date_range('2024-01-01', periods=8)
        empty, details = adjacent_segment_contributions(pd.DataFrame({('A', 'm'): [1.] * 8}, index=idx), [4], {})
        self.assertTrue(empty.empty)
        self.assertEqual(details[0]['status'], 'no_measurable_contribution')
        frame = pd.DataFrame({('A', 'm'): [np.nan] * 4 + [2.] * 4, ('B', 'n'): [0.] * 4 + [1.] * 4}, index=idx)
        out, details = adjacent_segment_contributions(frame, [4], {})
        self.assertEqual(out.zone.tolist(), ['B'])
        self.assertEqual(out.contribution_pct.tolist(), [100.])
        self.assertEqual(details[0]['omitted_components'][0]['zone'], 'A')

    def test_missing_windows_keep_timestamps_and_expose_coverage(self):
        frame = self.frame()
        frame.loc[(frame.zone == 'A') & (frame.window_start < '2024-01-04'), 'token_present_end'] = np.nan
        result = analyze_trend_selection(frame, [('A', 'token_present_end'), ('B', 'case_present_end')], overall_enabled=True)
        self.assertEqual(result['overall']['signal'].n_components.iloc[0], 1)
        self.assertEqual(result['overall']['signal'].n_components.iloc[-1], 2)
        for cp in result['local_changepoints'].itertuples():
            self.assertIn(cp.timestamp, set(frame.window_start))

    def test_one_zone_two_components_and_cancelling_aggregate(self):
        result = analyze_trend_selection(self.frame(), [('A', 'token_present_end'), ('A', 'token_avg_age_open')], overall_enabled=True)
        self.assertEqual(result['overall']['n_series'], 2)
        self.assertNotEqual(result['overall']['status'], 'insufficient_components')
        frame = self.frame()
        frame.loc[frame.zone == 'B', 'case_present_end'] = [4] * 12 + [0] * 12
        result = analyze_trend_selection(frame, [('A', 'token_present_end'), ('B', 'case_present_end')], overall_enabled=True)
        self.assertEqual(result['overall']['status'], 'constant')
        np.testing.assert_allclose(result['overall']['signal'].value, 0)

    def test_disabled_detection_does_not_call_pelt(self):
        with patch('analytics.trend_selection.collect_changepoint_events', side_effect=AssertionError('local called')), patch('analytics.trend_selection.pelt_changepoints', side_effect=AssertionError('overall called')):
            result = analyze_trend_selection(self.frame(), [('A', 'token_present_end')], local_enabled=False, overall_enabled=False)
            self.assertEqual(len(result['rows']), 24)

    def test_api_contract_validation_and_existing_get_unchanged(self):
        client = TestClient(create_app())
        with patch('backend.routers.analyses._get_analysis_or_404', return_value={}), patch('backend.routers.analyses._load_features_or_409', return_value=self.frame()):
            path = '/api/analyses/test/trends/selection'
            pairs = [dict(zone='A', metric='token_present_end'), dict(zone='B', metric='case_present_end')]
            response = client.post(path, json=dict(pairs=pairs, overall_enabled=True))
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertEqual({(r['zone'], r['metric']) for r in payload['rows']}, {('A', 'token_present_end'), ('B', 'case_present_end')})
            self.assertEqual(payload['protocol']['contribution_context'], 'adjacent_detected_segments')
            self.assertEqual(client.post(path, json=dict(pairs=pairs * 2)).status_code, 422)
            self.assertEqual(client.post(path, json=dict(pairs=pairs, cp_strictness=101)).status_code, 422)
            self.assertEqual(client.post(path, json=dict(pairs=[dict(zone='bad', metric='token_present_end')])).status_code, 422)
            self.assertEqual(client.post(path, json=dict(pairs=[])).json()['rows'], [])
            legacy = client.get('/api/analyses/test/trends?zones=A,B&metrics=token_present_end,case_present_end').json()
            self.assertEqual(len(legacy['rows']), 96)  # legacy Cartesian contract unchanged
