import unittest

import pandas as pd

from analytics.prediction import (
    build_binary_target_from_metric_threshold,
    list_supported_models,
    make_wide_feature_table,
    train_compare_models,
    train_evaluate_timeseries_model,
)
from analytics.prediction_explain import (
    build_global_shap_beeswarm_figure,
    shap_is_available,
)


class PredictionModelTests(unittest.TestCase):
    def setUp(self):
        windows = pd.date_range("2024-01-01", periods=20, freq="D")
        a_present = [0, 1, 1, 2, 2, 3, 2, 4, 3, 5, 4, 6, 5, 7, 6, 8, 7, 9, 8, 10]
        b_present = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10]
        rows = []
        for idx, window_start in enumerate(windows):
            rows.append(
                {
                    "window_start": window_start,
                    "zone": "A",
                    "token_enter": idx % 3 + 1,
                    "token_present_end": a_present[idx],
                    "token_avg_age_open": 10 + idx * 5,
                    "case_present_end": max(0, a_present[idx] - 1),
                }
            )
            rows.append(
                {
                    "window_start": window_start,
                    "zone": "B",
                    "token_enter": (idx + 1) % 4 + 1,
                    "token_present_end": b_present[idx],
                    "token_avg_age_open": 8 + idx * 4,
                    "case_present_end": max(0, b_present[idx] - 1),
                }
            )
        self.zf = pd.DataFrame(rows)
        self.X = make_wide_feature_table(
            self.zf,
            metrics=["token_enter", "token_present_end", "token_avg_age_open"],
            history_lags=1,
        )
        self.y = build_binary_target_from_metric_threshold(
            self.zf,
            target_zone="A",
            target_metric="token_present_end",
            threshold=3.0,
            operator=">=",
        )

    def test_each_supported_model_trains(self):
        for model_key in list_supported_models():
            result = train_evaluate_timeseries_model(
                self.X,
                self.y,
                model_key=model_key,
                horizon=1,
                max_depth=3,
                min_samples_leaf=1,
                n_splits=3,
            )
            self.assertEqual(result.model_key, model_key)
            self.assertGreater(result.n_rows, 0)
            self.assertFalse(result.feature_importance_df.empty)

    def test_model_comparison_returns_all_selected_models(self):
        results_by_model, horizon_scans_by_model, comparison_df = train_compare_models(
            self.X,
            self.y,
            model_keys=["decision_tree", "random_forest", "hist_gradient_boosting"],
            search_best_horizon=False,
            fixed_horizon=1,
            max_horizon=3,
            max_depth=3,
            min_samples_leaf=1,
            n_splits=3,
        )

        self.assertEqual(set(results_by_model), {"decision_tree", "random_forest", "hist_gradient_boosting"})
        self.assertEqual(set(horizon_scans_by_model), {"decision_tree", "random_forest", "hist_gradient_boosting"})
        self.assertEqual(set(comparison_df["model_key"]), {"decision_tree", "random_forest", "hist_gradient_boosting"})
        self.assertTrue((comparison_df["status"] == "ok").all())

    def test_random_forest_shap_beeswarm_builds_figure(self):
        if not shap_is_available():
            self.skipTest("SHAP is not available in the current environment.")

        result = train_evaluate_timeseries_model(
            self.X,
            self.y,
            model_key="random_forest",
            horizon=1,
            max_depth=3,
            min_samples_leaf=1,
            n_splits=3,
        )
        fig = build_global_shap_beeswarm_figure(
            result,
            self.X,
            self.y,
            top_n=10,
            max_rows=50,
        )

        self.assertIsNotNone(fig)
        self.assertGreaterEqual(len(fig.axes), 1)


if __name__ == "__main__":
    unittest.main()
