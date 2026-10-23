import unittest

import pandas as pd

from analytics.alerts import (
    build_advanced_rules_caption,
    compute_advanced_alerts,
    compute_basic_alerts,
    summarize_basic_alerts_per_zone,
)
from analytics.dependencies import compute_propagation_table, lagged_best_corr
from analytics.metrics.compat import canonical_metric_name, canonicalize_metric_names
from analytics.metrics.groups import (
    get_default_alert_metrics,
    get_default_dependency_pair,
    get_default_prediction_target_metric,
)
from analytics.prediction import (
    build_binary_target_from_flag_table,
    build_binary_target_from_metric_threshold,
    make_wide_feature_table,
    make_supervised_dataset,
)
from analytics.trends import prepare_trend_long_df


class MetricUnificationTests(unittest.TestCase):
    def setUp(self):
        self.zf = pd.DataFrame(
            {
                "window_start": pd.to_datetime(
                    [
                        "2024-01-01",
                        "2024-01-02",
                        "2024-01-03",
                        "2024-01-04",
                        "2024-01-05",
                        "2024-01-01",
                        "2024-01-02",
                        "2024-01-03",
                        "2024-01-04",
                        "2024-01-05",
                    ]
                ),
                "zone": ["A", "A", "A", "A", "A", "B", "B", "B", "B", "B"],
                "token_enter": [1, 2, 3, 4, 5, 2, 3, 4, 5, 6],
                "token_exit": [0, 1, 2, 3, 4, 1, 2, 3, 4, 5],
                "token_present_end": [1, 2, 3, 4, 5, 2, 3, 4, 5, 6],
                "token_avg_duration_completed": [50, 70, 90, 110, 130, 40, 60, 80, 100, 120],
                "token_avg_age_open": [60, 80, 100, 120, 140, 50, 70, 90, 110, 130],
                "case_present_end": [1, 1, 2, 2, 3, 1, 2, 2, 3, 3],
            }
        )

    def test_metric_alias_helpers_normalize_legacy_names(self):
        self.assertEqual(canonical_metric_name("ATZ_seconds"), "token_avg_duration_completed")
        self.assertEqual(
            canonicalize_metric_names(["tokenproduced", "token_entered", "tokenleft"]),
            ["token_enter", "token_present_end"],
        )

    def test_advanced_alerts_accept_legacy_metric_aliases(self):
        flagged = compute_advanced_alerts(
            self.zf,
            rules=[("ATZ_seconds", "≥", 100.0), ("tokenleft", "≥", 5.0)],
            combine_mode="ANY",
        )
        self.assertFalse(flagged.empty)
        self.assertIn("token_avg_duration_completed", self.zf.columns)

    def test_basic_alerts_and_summary_use_canonical_metrics(self):
        flagged = compute_basic_alerts(
            self.zf,
            open_age_threshold=100.0,
            backlog_threshold=5.0,
        )
        summary = summarize_basic_alerts_per_zone(
            flagged,
            open_age_threshold=100.0,
            backlog_threshold=5.0,
        )
        self.assertFalse(summary.empty)
        self.assertIn("severity", summary.columns)
        self.assertIn("badge", summary.columns)

    def test_advanced_rule_caption_normalizes_aliases(self):
        caption = build_advanced_rules_caption(
            [("tokenleft", "≥", 5.0), ("ATZ_seconds", "≤", 100.0)],
            combine_mode="ANY",
        )
        self.assertIn("token_present_end", caption)
        self.assertIn("token_avg_duration_completed", caption)

    def test_dependencies_accept_legacy_metric_aliases(self):
        dep = compute_propagation_table(
            self.zf,
            src_metric="tokenproduced",
            tgt_metric="tokenleft",
            max_lag=2,
            min_points=3,
        )
        self.assertFalse(dep.empty)
        self.assertTrue((dep["src_metric"] == "token_enter").all())
        self.assertTrue((dep["tgt_metric"] == "token_present_end").all())

    def test_lagged_best_corr_detects_positive_lag(self):
        x = pd.Series([1, 0, 0, 1, 0, 0, 1, 0])
        y = pd.Series([0, 1, 0, 0, 1, 0, 0, 1])
        corr, lag, n = lagged_best_corr(x, y, max_lag=2, min_points=4)
        self.assertEqual(lag, 1)
        self.assertGreater(n, 0)
        self.assertGreater(corr, 0)

    def test_prediction_helpers_accept_legacy_metric_aliases(self):
        X = make_wide_feature_table(self.zf, metrics=["tokenproduced", "tokenleft"], history_lags=1)
        self.assertIn("A__token_enter", X.columns)
        self.assertIn("A__token_present_end", X.columns)

        y = build_binary_target_from_metric_threshold(
            self.zf,
            target_zone="A",
            target_metric="tokenleft",
            threshold=3.0,
            operator=">=",
        )
        self.assertEqual(y.iloc[-1], 1)

    def test_prediction_helpers_build_flag_target_and_supervised_dataset(self):
        flagged = self.zf.loc[self.zf["token_present_end"] >= 5, ["window_start", "zone"]].copy()
        y = build_binary_target_from_flag_table(self.zf, flagged, target_zone="A")
        self.assertEqual(int(y.iloc[-1]), 1)

        X = make_wide_feature_table(self.zf, metrics=["token_enter"], history_lags=1)
        Xf, yf = make_supervised_dataset(X, y, horizon=1)
        self.assertFalse(Xf.empty)
        self.assertFalse(yf.empty)
        self.assertEqual(yf.name, "target_future")

    def test_trends_accept_legacy_metric_aliases(self):
        _, long_df = prepare_trend_long_df(
            self.zf,
            zones=["A"],
            metrics=["ATZ_seconds", "tokenleft"],
            mode="Advanced",
            reverse_catalog={
                "token_avg_duration_completed": "Token average completed duration",
                "token_present_end": "Token present at window end",
            },
            atz_display_fn=lambda s: s / 10.0,
        )
        self.assertEqual(set(long_df["metric"].unique()), {"token_avg_duration_completed", "token_present_end"})

    def test_metric_group_defaults_use_canonical_metrics(self):
        cols = list(self.zf.columns)
        self.assertIn("token_present_end", get_default_alert_metrics(cols))
        self.assertEqual(get_default_dependency_pair(cols), ("token_enter", "token_avg_age_open"))
        self.assertEqual(get_default_prediction_target_metric(cols), "token_present_end")


if __name__ == "__main__":
    unittest.main()
