"""Independent causal/temporal tests, not retrospective alignment parity."""
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi import HTTPException
from pm4py.objects.log.obj import EventLog, Trace, Event
from pm4py.objects.petri_net.obj import PetriNet, Marking
from pm4py.objects.petri_net.utils.petri_utils import add_arc_from_to

from analytics.forecasting import (EXCLUDED, SUPPORTED, causal_features, eligible_training,
    explain_shap, pipeline, prepare_experiment, run_experiment)
from backend.forecasting import PredictionRequest, execute
from process_model.prefix import prefix_tokens, PrefixUnavailable


def model(weight=1):
    net = PetriNet('independent')
    p, q, r, unused = [PetriNet.Place(n) for n in ('start', 'zone', 'end', 'unused')]
    net.places.update([p, q, r, unused])
    a, b = [PetriNet.Transition(n, n) for n in ('A', 'B')]
    net.transitions.update([a, b])
    for source, dest in [(p, a), (a, q), (q, b), (b, r)]:
        add_arc_from_to(source, dest, net, weight=weight)
    return net, Marking({p: weight}), dict(Z=['zone'], Empty=['unused'])


def log_of(cases):
    return EventLog([Trace([Event({'concept:name': a, 'time:timestamp': pd.Timestamp(t)}) for t, a in events],
                         attributes={'concept:name': name}) for name, events in cases])


class PrefixScienceTests(unittest.TestCase):
    def test_23_metrics_retained_with_explicit_exclusions(self):
        self.assertEqual(len(SUPPORTED), 23)
        for name in ('token_avg_duration_completed', 'token_avg_age_open', 'case_duration_p90',
                     'case_fifo_inversion_ratio', 'case_revisit_enter'):
            self.assertIn(name, SUPPORTED)
        self.assertIn('whole-timeline', EXCLUDED['token_aged_open_share'])
        self.assertIn('later exits', EXCLUDED['case_batch_count'])

    def test_unfinished_weighted_prefix_and_backlog_conservation(self):
        net, im, zones = model(2)
        log = log_of([('one', [('2024-01-01T12:00Z', 'A'), ('2024-01-03T12:00Z', 'B')])])
        tokens = prefix_tokens(log, net, im, '2024-01-02T00:00Z')
        self.assertEqual(len(tokens[tokens.place == 'zone']), 2)
        self.assertTrue(tokens[tokens.place == 'zone'].consumed_ts.isna().all())
        self.assertFalse((tokens.place == 'end').any())  # no final-marking completion
        f = causal_features(log, net, im, zones, 'D', '2024-01-04T00:00Z')
        z = f[f.zone == 'Z'].sort_values('window_end')
        self.assertEqual(z.token_present_end.tolist(), [2, 2, 0])
        self.assertEqual(z.token_netflow.tolist(), [2, 0, -2])
        self.assertEqual(z.token_present_end.tolist(), z.token_netflow.cumsum().tolist())
        self.assertEqual(z.case_present_end.tolist(), [1, 1, 0])
        self.assertEqual(z.token_avg_age_open.iloc[0], 12 * 3600)
        self.assertEqual(z.token_avg_duration_completed.iloc[-1], 48 * 3600)
        self.assertTrue((f[f.zone == 'Empty'].token_present_end == 0).all())

    def test_identical_prefixes_have_identical_all_supported_features(self):
        net, im, zones = model()
        before = [('2024-01-01T12:00Z', 'A')]
        a = log_of([('one', before + [('2024-01-03T12:00Z', 'B')])])
        # Different future timestamp, activity, new case, and eventual completion.
        b = log_of([('one', before + [('2024-02-09T12:00Z', 'invalid')]),
                    ('future', [('2024-02-10T12:00Z', 'A')])])
        kwargs = dict(net=net, im=im, zones=zones, timeframe='D', observed_through='2024-01-03T00:00Z')
        pd.testing.assert_frame_equal(causal_features(a, **kwargs), causal_features(b, **kwargs))

    def test_boundary_events_belong_to_following_window(self):
        net, im, zones = model()
        log = log_of([('one', [('2024-01-01T12:00Z', 'A')]),
                      ('two', [('2024-01-02T00:00Z', 'A')])])
        f = causal_features(log, net, im, zones, 'D', '2024-01-03T00:00Z')
        z = f[f.zone == 'Z'].sort_values('window_end')
        self.assertEqual(z.token_present_end.tolist(), [1, 2])
        self.assertEqual(z.token_enter.tolist(), [1, 1])

    def test_ambiguity_invalid_firing_silent_choice_and_tied_order_rejected(self):
        net, im, _ = model()
        for events in [[('2024-01-01T12:00Z', 'B')],
                       [('2024-01-01T12:00Z', 'A'), ('2024-01-01T12:00Z', 'B')]]:
            with self.assertRaises(PrefixUnavailable):
                prefix_tokens(log_of([('one', events)]), net, im, '2024-01-02T00:00Z')
        duplicate = PetriNet.Transition('another_A', 'A'); net.transitions.add(duplicate)
        add_arc_from_to(next(p for p in net.places if p.name == 'start'), duplicate, net)
        with self.assertRaisesRegex(PrefixUnavailable, 'ambiguous'):
            prefix_tokens(log_of([('one', [('2024-01-01T12:00Z', 'A')])]), net, im, '2024-01-02T00:00Z')
        duplicate.label = None
        with self.assertRaisesRegex(PrefixUnavailable, 'competing transitions'):
            prefix_tokens(EventLog(), net, im, '2024-01-02T00:00Z')

    def test_concurrent_tokens_keep_one_case_and_boundary_join_is_not_forced(self):
        net = PetriNet('visible-concurrency')
        places = {name: PetriNet.Place(name) for name in ('start', 'left', 'right', 'doneL', 'doneR', 'end')}
        net.places.update(places.values())
        transitions = {name: PetriNet.Transition(name, name) for name in ('Start', 'L', 'R', 'Join')}
        net.transitions.update(transitions.values())
        for p, t in [('start','Start'),('left','L'),('right','R'),('doneL','Join'),('doneR','Join')]:
            add_arc_from_to(places[p], transitions[t], net)
        for t, p in [('Start','left'),('Start','right'),('L','doneL'),('R','doneR'),('Join','end')]:
            add_arc_from_to(transitions[t], places[p], net)
        log = log_of([('one',[('2024-01-01T09:00Z','Start'),('2024-01-01T09:15Z','L'),
                              ('2024-01-01T10:15Z','R'),('2024-01-01T11:00Z','Join')])])
        f = causal_features(log, net, Marking({places['start']:1}), {'Z':['left','right','doneL','doneR']}, 'h', '2024-01-01T12:00Z')
        self.assertEqual(f.token_present_end.tolist(), [2,2,0])
        self.assertEqual(f.case_present_end.tolist(), [1,1,0])
        self.assertEqual(f.token_avg_present_window.iloc[0], 2)
        self.assertEqual(f.token_enter.iloc[0], 3)  # split + internal place production
        self.assertEqual(f.token_exit.iloc[0], 1)
        self.assertEqual(f.token_netflow.cumsum().tolist(), f.token_present_end.tolist())

    def test_duplicate_labels_with_one_enabled_identity_are_supported(self):
        net, im, _ = model()
        for transition in net.transitions:
            transition.label = 'same'
        log = log_of([('one',[('2024-01-01T12:00Z','same'),('2024-01-01T13:00Z','same')])])
        tokens = prefix_tokens(log, net, im, '2024-01-02T00:00Z')
        self.assertTrue(tokens.loc[tokens.place == 'zone','consumed_ts'].notna().all())
        self.assertEqual(int((tokens.place == 'end').sum()), 1)

    def test_revisit_is_available_without_future_completion(self):
        net, im, zones = model()
        again = PetriNet.Transition('C','C'); net.transitions.add(again)
        add_arc_from_to(next(p for p in net.places if p.name == 'end'), again, net)
        add_arc_from_to(again, next(p for p in net.places if p.name == 'zone'), net)
        log = log_of([('one',[('2024-01-01T12:00Z','A'),('2024-01-01T13:00Z','B'),('2024-01-02T12:00Z','C')])])
        f = causal_features(log, net, im, zones, 'D', '2024-01-03T00:00Z')
        last = f[f.zone == 'Z'].iloc[-1]
        self.assertEqual(last.case_revisit_enter, 1)
        self.assertEqual(last.case_rework_ratio, 1)
        self.assertEqual(last.case_revisit_gap_mean, 23*3600)
        self.assertEqual(last.case_present_end, 1)


class TemporalScienceTests(unittest.TestCase):
    def series(self, horizon=3):
        index = pd.date_range('2024-01-01', periods=80, freq='D', tz='UTC')
        X = pd.DataFrame({'zone__metric': np.arange(80) % 9, 'missing': np.where(np.arange(80) % 3, np.arange(80), np.nan)}, index=index)
        current = pd.Series((np.arange(80) // 4) % 2, index=index, dtype=float)
        y = current.shift(-horizon)
        available = pd.Series(index + pd.Timedelta(days=horizon), index=index)
        return X, y, available, current

    def run_model(self, **overrides):
        X, y, a, c = self.series()
        settings = dict(development_end=X.index[49], observed_through=X.index[-1], models=['decision_tree'], horizon=3, timeframe='D')
        settings.update(overrides)
        return run_experiment(X, y, a, c, **settings)

    def test_horizon_specific_label_availability_and_forecast_uses_latest_unlabeled_row(self):
        for horizon in (1, 3, 7):
            X, y, available, current = self.series(horizon)
            origin = X.index[49]
            eligible = eligible_training(X.index, available, origin)
            self.assertEqual(X.index[eligible][-1], origin - pd.Timedelta(days=horizon))
            result = run_experiment(X, y, available, current, development_end=origin,
                       observed_through=X.index[-1], models=['decision_tree'], horizon=horizon, timeframe='D')
            for fold in result['models'][0]['cv']['folds']:
                self.assertTrue(all(pd.Timestamp(a) <= pd.Timestamp(fold['prediction_origin']) for a in fold['train_label_available']))
            forecast = result['models'][0]['forecast']
            self.assertTrue(pd.isna(y.loc[X.index[-1]]))
            self.assertEqual(pd.Timestamp(forecast['feature_origin']), X.index[-1])
            self.assertEqual(pd.Timestamp(forecast['target_end']), X.index[-1] + pd.Timedelta(days=horizon))
            self.assertLessEqual(pd.Timestamp(forecast['latest_training_label_available']), X.index[-1])

    def test_holdout_changes_cannot_change_development_cv_or_model_selection(self):
        X, y, a, c = self.series()
        base = self.run_model()
        y.loc[X.index[50:]] = 1 - y.loc[X.index[50:]]
        X.loc[X.index[50:], 'zone__metric'] = 1e12
        changed = run_experiment(X, y, a, c, development_end=X.index[49], observed_through=X.index[-1], models=['decision_tree'], horizon=3, timeframe='D')
        self.assertEqual(base['models'][0]['cv'], changed['models'][0]['cv'])
        self.assertEqual(base['selected_model'], changed['selected_model'])

    def test_training_only_medians_and_deterministic_scores(self):
        X, y, a, c = self.series()
        fitted = []
        original = pipeline
        def recording(key):
            p = original(key)
            original_fit = p.fit
            def fit(frame, labels):
                result = original_fit(frame, labels)
                fitted.append((frame.copy(), p.named_steps['imputer'].statistics_.copy()))
                return result
            p.fit = fit
            return p
        with patch('analytics.forecasting.pipeline', side_effect=recording):
            first = self.run_model()
        for frame, medians in fitted:
            np.testing.assert_allclose(medians, frame.median().to_numpy())
        self.assertEqual(first, self.run_model())

    def test_invalid_conditions_are_explicit(self):
        X, y, a, c = self.series()
        for modified, message in [(y * 0, 'one class'), (y * np.nan, 'Insufficient')]:
            with self.assertRaisesRegex(ValueError, message):
                run_experiment(X, modified, a, c, development_end=X.index[49], observed_through=X.index[-1], models=['decision_tree'], horizon=3, timeframe='D')
        X['missing'] = np.nan
        with self.assertRaisesRegex(ValueError, 'no development observations'):
            run_experiment(X, y, a, c, development_end=X.index[49], observed_through=X.index[-1], models=['decision_tree'], horizon=3, timeframe='D')

    def test_three_models_share_folds_and_shap_is_real(self):
        X, y, a, c = self.series()
        result = run_experiment(X, y, a, c, development_end=X.index[49], observed_through=X.index[-1], models=['decision_tree', 'random_forest', 'hist_gradient_boosting'], horizon=3, timeframe='D')
        self.assertEqual(len(result['models']), 3)
        folds = [[(f['prediction_origin'], f['status']) for f in m['cv']['folds']] for m in result['models']]
        self.assertEqual(folds[0], folds[1]); self.assertEqual(folds[1], folds[2])
        for m in result['models'][1:]:
            self.assertEqual(m['shap']['status'], 'available', m['shap'])
            self.assertEqual(m['shap']['n_background'], 64)
            self.assertTrue(all(np.isfinite(r['mean_abs_shap']) for r in m['shap']['rows']))
        self.assertEqual(result['models'][1]['shap']['scale'], 'class-1 probability')
        self.assertEqual(result['models'][2]['shap']['scale'], 'class-1 log-odds')

    def test_missing_targets_not_negative_and_missing_history_removed(self):
        windows = pd.date_range('2024-01-01', periods=8, freq='D', tz='UTC')
        f = pd.DataFrame(dict(zone='Z', window_end=windows, token_avg_age_open=[np.nan, 2, 3, 4, 5, 6, 7, 8]))
        X, y, a, current = prepare_experiment(f, [{'zone':'Z','metric':'token_avg_age_open'}], 'Z', 'token_avg_age_open', 4, '>=', 2, 1, 'D')
        self.assertEqual(X.index[0], windows[1])
        self.assertTrue(np.isnan(y.iloc[-1]))
        self.assertEqual(a.iloc[0], windows[3])
        with self.assertRaisesRegex(ValueError, 'finite'):
            prepare_experiment(f, [{'zone':'Z','metric':'token_avg_age_open'}], 'Z', 'token_avg_age_open', np.nan, '>=', 2, 1, 'D')

class ForecastIntegrationTests(unittest.TestCase):
    def test_future_log_changes_cannot_change_earlier_forecast(self):
        net, im, zones = model()
        start = pd.Timestamp('2024-01-01', tz='UTC')
        cases = []
        for day in range(60):
            for n in range(1 if day % 8 < 4 else 4):
                at = start + pd.Timedelta(days=day, hours=6, minutes=n)
                cases.append((f'{day}-{n}', [(at.isoformat(), 'A'), ((at + pd.Timedelta(hours=30)).isoformat(), 'B')]))
        end = start + pd.Timedelta(days=50)
        original = log_of(cases)
        changed = log_of([(name, [(ts, activity if pd.Timestamp(ts) < end else 'future_changed') for ts, activity in events]) for name, events in cases]
                         + [('unseen', [((end + pd.Timedelta(days=100)).isoformat(), 'B')])])
        outputs = []
        for log in (original, changed):
            f = causal_features(log, net, im, zones, 'D', end)
            X, y, available, current = prepare_experiment(f, [{'zone':'Z','metric':'token_present_end'}], 'Z', 'token_present_end', 3., '>=', 2, 2, 'D')
            outputs.append(run_experiment(X, y, available, current, development_end=start + pd.Timedelta(days=35), observed_through=end, models=['decision_tree'], horizon=2, timeframe='D'))
        self.assertEqual(outputs[0], outputs[1])

    def test_recorded_holdout_is_cached_and_cannot_be_retuned(self):
        X, _, _, current = TemporalScienceTests().series(1)
        f = pd.DataFrame(dict(zone='Z', window_end=X.index, token_present_end=current.to_numpy() * 10))
        choices = dict(eligible=True, window_ends=[str(t) for t in X.index], assumptions=[])
        meta = dict(id='independent', dataset_id='fixture', zone_places={'Z':['zone']}, timeframe='D')
        request = dict(target_zone='Z', target_metric='token_present_end', threshold=5, horizon=1,
                       development_end=str(X.index[49]), observed_through=str(X.index[-1]),
                       feature_pairs=[dict(zone='Z', metric='token_present_end')], models=['decision_tree'],
                       history_lags=0, protocol_acknowledged=True)
        with tempfile.TemporaryDirectory() as tmp, patch('backend.forecasting.options', return_value=choices), \
             patch('backend.forecasting.store.dataset_dir', return_value=tmp), \
             patch('backend.forecasting.get_bundle', return_value=SimpleNamespace(log=[], net=None, im=None)), \
             patch('backend.forecasting.causal_features', return_value=f) as features:
            first = execute(meta, PredictionRequest(**request))
            cached = execute(meta, PredictionRequest(**request))
            self.assertTrue(cached['cached']); self.assertFalse(first['cached'])
            self.assertEqual(first['experiment_id'], cached['experiment_id'])
            self.assertEqual(features.call_count, 1)
            with self.assertRaises(HTTPException) as context:
                execute(meta, PredictionRequest(**dict(request, threshold=6)))
            self.assertEqual(context.exception.status_code, 409)
            self.assertIn('already been evaluated', context.exception.detail)
