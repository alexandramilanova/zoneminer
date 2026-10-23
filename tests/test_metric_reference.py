"""Independent arithmetic examples and metadata/API contracts; no replay oracle."""
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient
from pm4py.objects.petri_net.obj import PetriNet
from pm4py.objects.petri_net.utils.petri_utils import add_arc_from_to

from analytics.metrics.schema import CANONICAL_METRICS
from analytics.metrics.reference import DETAILS, get_metric_reference
from backend.main import create_app
from process_model.features import build_zone_token_features_from_places
from process_model.conformance import add_window_conformance_features


class TestMetricReference(unittest.TestCase):
    def test_all_canonical_metrics_have_complete_reference(self):
        self.assertEqual(set(DETAILS), {m.name for m in CANONICAL_METRICS})
        for spec in CANONICAL_METRICS:
            with self.subTest(metric=spec.name):
                ref = get_metric_reference(spec.name)
                self.assertEqual(ref['canonical_unit'], spec.unit)
                self.assertNotIn('limitations', ref)
                for key in ('unit_label', 'scope', 'description', 'formula', 'unavailable'):
                    self.assertTrue(ref[key])
        self.assertEqual(get_metric_reference('alignment_trace_cost_mean')['unit_label'], 'alignment cost units')
        self.assertEqual(get_metric_reference('zone_deviation_weight')['unit_label'], 'move equivalents')
        self.assertIn('Weighted sync mass', get_metric_reference('zone_local_fitness')['formula'])

    @staticmethod
    def features(timeframe):
        # One case, internal p->q move at :15, leaves q at :30. This is
        # two completed PLACE intervals, one continuous CASE stay.
        start = pd.Timestamp('2024-01-01')
        df = pd.DataFrame([
            dict(case_id='one', token_id='a', place='p', produced_ts=start, consumed_ts=start + pd.Timedelta(minutes=15)),
            dict(case_id='one', token_id='b', place='q', produced_ts=start + pd.Timedelta(minutes=15), consumed_ts=start + pd.Timedelta(minutes=30)),
        ])
        return build_zone_token_features_from_places(df, {'Z': ['p', 'q']}, timeframe=timeframe)

    def test_independent_hourly_and_daily_units_and_populations(self):
        for timeframe, window_seconds in [('h', 3600), ('D', 86400)]:
            with self.subTest(timeframe=timeframe):
                row = self.features(timeframe).iloc[0]
                self.assertEqual(row.token_enter, 2)
                self.assertEqual(row.token_exit, 2)
                self.assertEqual(row.case_enter, 1)
                self.assertEqual(row.token_present_end, 0)
                self.assertAlmostEqual(row.token_avg_present_window, 1800 / window_seconds)
                self.assertEqual(row.token_avg_duration_completed, 900)  # seconds, not .25 hours
                self.assertEqual(row.case_avg_duration_completed, 1800)
                self.assertEqual(row.token_completion_ratio, 1)

    def test_api_reference_matches_canonical_values_for_hourly_and_daily(self):
        client = TestClient(create_app())
        for tf, label in [('h', 'Hourly'), ('D', 'Daily')]:
            frame = self.features(tf)
            with patch('backend.routers.analyses._get_analysis_or_404', return_value={'timeframe': tf}), patch('backend.routers.analyses._load_features_or_409', return_value=frame):
                response = client.get('/api/analyses/test/metrics')
                self.assertEqual(response.status_code, 200, response.text)
                catalog = response.json()
                self.assertEqual(catalog['timeframe_label'], label)
                self.assertEqual(catalog['duration_unit_label'], 'seconds')
                metrics = {m['name']: m for m in catalog['metrics']}
                for metric in metrics.values():
                    self.assertNotIn('limitations', metric)
                    self.assertNotIn('**Limitations:**', metric['explanation'])
                self.assertEqual(metrics['token_avg_duration_completed']['unit_label'], 'seconds')
                self.assertEqual(metrics['token_completion_ratio']['unit_label'], 'ratio (fraction)')
                self.assertEqual(metrics['token_avg_age_open']['non_null_count'], 0)
                raw = client.get('/api/analyses/test/features').json()['rows'][0]
                self.assertEqual(raw['token_avg_duration_completed'], 900)

    def test_boundary_snapshot_differs_from_activity_and_ratio_can_exceed_one(self):
        start = pd.Timestamp('2024-01-01')
        edge = start + pd.Timedelta(hours=1)
        intervals = pd.DataFrame([
            dict(case_id='a', place='p', produced_ts=start, consumed_ts=edge),
            dict(case_id='b', place='p', produced_ts=start, consumed_ts=edge),
            dict(case_id='c', place='p', produced_ts=edge, consumed_ts=edge + pd.Timedelta(minutes=30)),
        ])
        rows = build_zone_token_features_from_places(intervals, {'Z': ['p']}, timeframe='h')
        first, second = rows.iloc[0], rows.iloc[1]
        self.assertEqual((first.token_enter, first.token_exit, first.token_present_end), (2, 0, 2))
        self.assertEqual((second.token_enter, second.token_exit, second.token_present_end), (1, 3, 0))
        self.assertEqual(second.token_avg_present_window, .5)
        self.assertEqual(second.token_completion_ratio, 3)  # fraction, not 0..1 probability
        self.assertEqual(second.case_present_end, 0)
        self.assertEqual(second.case_active_window, 3)  # includes a,b ending exactly at start

    def test_independent_boundary_weighted_local_and_global_conformance(self):
        net = PetriNet('boundary')
        p, q = PetriNet.Place('p'), PetriNet.Place('q')
        t = PetriNet.Transition('boundary', 'go')
        inner = PetriNet.Transition('inner', 'internal')
        net.places.update([p, q]); net.transitions.update([t, inner])
        add_arc_from_to(p, t, net); add_arc_from_to(t, q, net)
        add_arc_from_to(p, inner, net); add_arc_from_to(inner, p, net)
        start = pd.Timestamp('2024-01-01')
        intervals = pd.DataFrame([
            dict(case_id='one', token_id='a', place='p', produced_ts=start, consumed_ts=start + pd.Timedelta(minutes=10)),
            dict(case_id='one', token_id='b', place='q', produced_ts=start + pd.Timedelta(minutes=10), consumed_ts=start + pd.Timedelta(minutes=20)),
        ])
        moves = pd.DataFrame([
            dict(case_id='one', ts=start, move_type='sync', t_name='inner'),
            dict(case_id='one', ts=start, move_type='model', t_name='boundary'),
        ])
        zf = build_zone_token_features_from_places(intervals, {'A': ['p'], 'B': ['q']}, timeframe='h', alignment_moves_df=moves, net=net)
        self.assertEqual(zf.zone_deviation_count.tolist(), [1, 1])
        self.assertEqual(zf.zone_deviation_weight.tolist(), [.5, .5])
        self.assertAlmostEqual(zf.zone_local_fitness.iloc[0], 2 / 3)  # 1 / (1 + .5)
        self.assertEqual(zf.zone_local_fitness.iloc[1], 0)
        traces = pd.DataFrame([dict(trace_end=start, alignment_trace_fitness=.75, alignment_trace_cost=10001,
            alignment_sync_move_count=1, alignment_log_move_count=0, alignment_model_move_count=1,
            alignment_deviation_count=1, alignment_has_deviation=1)])
        result = add_window_conformance_features(zf, traces)
        self.assertEqual(result.alignment_trace_fitness_mean.tolist(), [.75, .75])
        self.assertEqual(result.alignment_deviation_count.tolist(), [1, 1])  # repeated, not 2 deviations
        self.assertEqual(get_metric_reference('alignment_trace_fitness_mean')['scope'], 'process_window')
        self.assertEqual(get_metric_reference('zone_local_fitness')['scope'], 'zone_conformance')
