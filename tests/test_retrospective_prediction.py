"""Independent tests of the retrospective workflow and explicit retrospective contract."""
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from analytics.retrospective_prediction import evaluate,prepare,fit_model
from backend.retrospective_prediction import options,suggest_threshold


def frame(n=45):
    return pd.DataFrame([dict(zone='Z',window_start=t,token_present_end=float(i%4),
        case_present_end=float(i%3),token_avg_duration_completed=float(i+1),
        token_aged_open_share=float(i%2),alignment_trace_fitness_mean=.5+(i%4)/10)
        for i,t in enumerate(pd.date_range('2024-01-01',periods=n))])


class RetrospectiveTests(unittest.TestCase):
    def test_balancing_weights_are_training_only_and_equalize_class_totals(self):
        X = pd.DataFrame({'x': range(8)})
        y = pd.Series([0, 0, 0, 0, 0, 0, 1, 1])
        with patch('analytics.retrospective_prediction.pipeline') as factory:
            fit_model('decision_tree', X, y, True)
            weights = factory.return_value.fit.call_args.kwargs['model__sample_weight']
            np.testing.assert_allclose(weights, [2/3]*6 + [2.]*2)
            self.assertAlmostEqual(weights[y == 0].sum(), weights[y == 1].sum())
            fit_model('decision_tree', X, y, False)
            self.assertEqual(factory.return_value.fit.call_args.kwargs, {})

    def test_balanced_models_keep_evaluation_rows_and_expose_class_support(self):
        f = frame()
        original = f.copy(deep=True)
        args = (f, [dict(zone='Z', metric='token_present_end')], 'Z', 'token_present_end', 2., '>=', 1, 'D')
        ordinary = evaluate(*args)
        balanced = evaluate(*args, balance_classes=True)
        self.assertFalse(ordinary['balance_classes'])
        self.assertTrue(balanced['balance_classes'])
        for left, right in zip(ordinary['models'], balanced['models']):
            self.assertEqual([(p['origin'], p['actual']) for p in left['predictions']],
                             [(p['origin'], p['actual']) for p in right['predictions']])
            for fold in right['folds']:
                self.assertEqual(fold['training_positive_windows'] + fold['training_negative_windows'], fold['n_train'])
                self.assertEqual(fold['evaluation_positive_windows'] + fold['evaluation_negative_windows'], fold['n_test'])
            for result in (left, right):
                score = result['evaluation']
                if score['positive_rows'] and score['confusion']['tp'] == 0:
                    self.assertIn(f"All {score['positive_rows']} positive evaluation windows were missed", result['diagnostic'])
        pd.testing.assert_frame_equal(f, original)
        later = f.copy(); later.loc[later.index >= 37, 'token_present_end'] = 1e9
        changed = evaluate(later, *args[1:], balance_classes=True)
        for left, right in zip(balanced['models'], changed['models']):
            first = next(fold for fold in left['folds'] if fold['status'] == 'valid')
            self.assertEqual(left['predictions'][:first['n_test']], right['predictions'][:first['n_test']])

    def test_threshold_defaults_use_values_not_model_scores(self):
        values=pd.Series([0.,1.,2.,3.,4.,5.,6.,7.,np.nan,np.inf])
        upper=suggest_threshold(values,'>=');lower=suggest_threshold(values,'<=')
        self.assertEqual(upper['value'],6.)
        self.assertEqual(lower['value'],2.)
        self.assertEqual(upper['positive_windows'],2)
        self.assertEqual(lower['positive_windows'],3)
        # Sparse events, fractional units and negative netflow retain scale.
        self.assertEqual(suggest_threshold(pd.Series([0]*9+[1]),'>=')['value'],1)
        self.assertEqual(suggest_threshold(pd.Series([1]*9+[0]),'<=')['value'],0)
        self.assertEqual(suggest_threshold(pd.Series([.1,.2,.3,.4]),'>=')['value'],.4)
        self.assertEqual(suggest_threshold(pd.Series([-4.,-3.,-2.,-1.]),'>=')['value'],-1)
        constant=suggest_threshold(pd.Series([1.23456789]*8),'>=')
        self.assertEqual(constant['value'],1.23456789)
        self.assertIn('Constant metric',constant['reason'])
        self.assertIsNone(suggest_threshold(pd.Series([np.nan]),'>=')['value'])

    def evaluate(self,f=None,horizon=1):
        return evaluate(frame() if f is None else f,[dict(zone='Z',metric='token_present_end')],
                        'Z','token_present_end',2.,'>=',horizon,'D')

    def test_threshold_shift_and_missing_targets_are_independently_known(self):
        f=frame(12);f.loc[5,'token_present_end']=np.nan
        X,y,a,current=prepare(f,[dict(zone='Z',metric='case_present_end')],'Z','token_present_end',2.,'>=',2,'D')
        # Feature row for Jan 4 ends Jan 5; target Jan 6 ends Jan 7 and is undefined.
        self.assertTrue(np.isnan(y.loc['2024-01-05T00:00Z']))
        self.assertEqual(a.loc['2024-01-05T00:00Z'],pd.Timestamp('2024-01-07T00:00Z'))
        self.assertEqual(X.loc['2024-01-05T00:00Z','Z__case_present_end__lag3'],0)
        self.assertEqual(current.loc['2024-01-05T00:00Z'],1)
        self.assertTrue(y.tail(2).isna().all())

    def test_all_metric_families_and_whole_series_metrics_are_explicitly_retrospective(self):
        f=frame();o=options(f)
        self.assertIn('token_aged_open_share',[m['name'] for m in o['metrics']])
        self.assertIn('alignment_trace_fitness_mean',[m['name'] for m in o['metrics']])
        self.assertIn('not',o['interpretation'])
        self.assertEqual(o['availability']['Z']['token_avg_duration_completed']['minimum'],1)
        prepare(f,[dict(zone='Z',metric='token_aged_open_share')],'Z','alignment_trace_fitness_mean',.6,'>=',1,'D')

    def test_three_models_purged_folds_latest_unlabeled_row_and_independent_scores(self):
        r=self.evaluate(horizon=3)
        self.assertEqual(len(r['models']),3)
        for m in r['models']:
            for fold in m['folds']:
                if fold['status']=='valid':
                    self.assertLessEqual(pd.Timestamp(fold['latest_training_label_available']),pd.Timestamp(fold['first_evaluation_origin']))
            self.assertEqual(m['estimate']['origin'],'2024-02-15 00:00:00+00:00')
            self.assertEqual(m['estimate']['latest_training_origin'],'2024-02-12 00:00:00+00:00')
            predictions=m['predictions'];tp=sum(p['actual']==p['predicted']==1 for p in predictions)
            fp=sum(p['actual']==0 and p['predicted']==1 for p in predictions)
            fn=sum(p['actual']==1 and p['predicted']==0 for p in predictions)
            expected=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.
            self.assertAlmostEqual(m['evaluation']['f1'],expected)
            self.assertTrue(all(f['importance']>=.005 for f in m['feature_importance']))
        self.assertIsNotNone(r['models'][0]['decision_tree'])
        persistence=next(b for b in r['baselines'] if b['model'].startswith('Persistence'))
        improves=max(m['evaluation']['f1'] for m in r['models'])>persistence['f1']
        self.assertTrue(r['baseline_note'].startswith('At least one classifier exceeded' if improves else 'No classifier exceeded'))

    def test_later_values_do_not_enter_earlier_fold_preprocessing(self):
        a=frame();b=a.copy();b.loc[b.index>=37,'token_present_end']=1e9
        left=self.evaluate(a);right=self.evaluate(b)
        for x,y in zip(left['models'],right['models']):
            first=[f for f in x['folds'] if f['status']=='valid'][0]
            n=first['n_test']
            self.assertEqual(x['predictions'][:n],y['predictions'][:n])

    def test_invalid_and_untrainable_conditions_are_not_silently_repaired(self):
        f=frame();f['token_present_end']=1
        with self.assertRaisesRegex(ValueError,'one class'):self.evaluate(f)
        with self.assertRaisesRegex(ValueError,'eight'):self.evaluate(frame(9))
        with self.assertRaisesRegex(ValueError,'Too few'):self.evaluate(frame(8),horizon=30)
        f=frame();f['token_present_end']=np.nan
        with self.assertRaisesRegex(ValueError,'eight'):self.evaluate(f)
        f=frame();f.loc[1,'window_start']=f.loc[0,'window_start']
        with self.assertRaisesRegex(ValueError,'duplicate'):self.evaluate(f)

    def test_api_validation_cache_repeated_exploration_and_unchanged_features(self):
        from backend.routers import analyses
        app=FastAPI();app.include_router(analyses.router)
        f=frame();original=f.copy(deep=True)
        body=dict(target_zone='Z',target_metric='token_present_end',threshold=2,horizon=1,
                  feature_pairs=[dict(zone='Z',metric='case_present_end')])
        with tempfile.TemporaryDirectory() as tmp,patch.object(analyses,'_get_analysis_or_404',return_value=dict(id='x',timeframe='D')), \
             patch.object(analyses,'_load_features_or_409',side_effect=lambda _:f.copy()), \
             patch('backend.retrospective_prediction.store.analysis_dir',return_value=tmp), \
             patch('backend.retrospective_prediction.store.load_frame',return_value=None),TestClient(app) as client:
            path='/api/analyses/x/prediction/retrospective'
            self.assertEqual(client.get(path+'/options').status_code,200)
            response=client.post(path,json=body);self.assertEqual(response.status_code,200,response.text)
            self.assertFalse(response.json()['cached'])
            self.assertTrue(client.post(path,json=body).json()['cached'])
            balanced=client.post(path,json=dict(body,balance_classes=True))
            self.assertEqual(balanced.status_code,200,balanced.text)
            self.assertTrue(balanced.json()['balance_classes'])
            self.assertNotEqual(balanced.json()['experiment_id'],response.json()['experiment_id'])
            suggested=client.post(path,json=dict(body,threshold=2,threshold_source='suggested'))
            self.assertEqual(suggested.status_code,200,suggested.text)
            self.assertEqual(suggested.json()['specification']['threshold_source'],'suggested')
            self.assertIn('independently of model scores',suggested.json()['specification']['threshold_policy'])
            self.assertEqual(client.post(path,json=dict(body,threshold=1,threshold_source='suggested')).status_code,422)
            # Repeated exploration is permitted and disclosed, not called an untouched test.
            other=client.post(path,json=dict(body,horizon=2));self.assertEqual(other.status_code,200,other.text)
            self.assertNotEqual(other.json()['experiment_id'],response.json()['experiment_id'])
            for bad in (dict(body,target_zone='Unknown'),dict(body,target_metric='unknown'),dict(body,horizon=0),dict(body,feature_pairs=[]),dict(body,threshold=1e300)):
                self.assertEqual(client.post(path,json=bad).status_code,422)
        pd.testing.assert_frame_equal(f,original)
