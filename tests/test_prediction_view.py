"""Independent display-contract tests against a deterministic fitted classifier."""
import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier

from backend.prediction_view import decision_tree_view


class PredictionViewTests(unittest.TestCase):
    def result(self, y=(0, 0, 1, 1)):
        X = pd.DataFrame({'Zone__token_present_end': [0., 1., 4., 5.]})
        pipeline = Pipeline([('imputer', SimpleImputer(strategy='median')),
                             ('model', DecisionTreeClassifier(max_depth=3, random_state=42))]).fit(X, y)
        return SimpleNamespace(model_key='decision_tree', pipeline=pipeline, feature_names=list(X)), X

    def test_exact_nodes_reproduce_fitted_predictions_and_probabilities(self):
        result, X = self.result()
        view = decision_tree_view(result)
        self.assertEqual(len(view['nodes']), 3)
        root = view['nodes'][0]
        self.assertEqual(root['feature'], X.columns[0])
        self.assertEqual(root['threshold'], 2.5)
        self.assertEqual(root['samples'], 4)
        self.assertEqual(root['positive_share'], .5)
        for value in [0., 2.5, 2.50001, 5.]:
            child = root['left'] if value <= root['threshold'] else root['right']
            leaf = view['nodes'][child]
            frame = pd.DataFrame({X.columns[0]: [value]})
            self.assertEqual(leaf['predicted_class'], result.pipeline.predict(frame)[0])
            self.assertAlmostEqual(leaf['positive_share'], result.pipeline.predict_proba(frame)[0, 1])
            self.assertIsNone(leaf['feature'])
            self.assertIsNone(leaf['left'])

    def test_leaf_only_and_non_tree_models(self):
        result, _ = self.result((0, 0, 0, 0))
        node = decision_tree_view(result)['nodes'][0]
        self.assertEqual(node['positive_share'], 0)
        self.assertEqual(node['predicted_class'], 0)
        result.model_key = 'random_forest'
        self.assertIsNone(decision_tree_view(result))
