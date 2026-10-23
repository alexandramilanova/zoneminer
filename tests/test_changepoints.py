import unittest

import numpy as np
import pandas as pd

from analytics.drift import zone_drift_scores


class ZoneDriftScoreTests(unittest.TestCase):
    """A9 drift scores: a planted regime shift must dominate a stationary zone."""

    def _zf(self):
        rng = np.random.RandomState(7)
        windows = pd.date_range("2024-01-01", periods=40, freq="D")
        rows = []
        for i, w in enumerate(windows):
            # zone A: mean shift on both metrics at window 20; zone B stationary
            shift = 8.0 if i >= 20 else 0.0
            rows.append(
                {
                    "zone": "A",
                    "window_start": w,
                    "m1": rng.normal(10 + shift, 1),
                    "m2": rng.normal(5 + shift / 2, 1),
                }
            )
            rows.append(
                {"zone": "B", "window_start": w, "m1": rng.normal(10, 1), "m2": rng.normal(5, 1)}
            )
        return pd.DataFrame(rows)

    def test_shifted_zone_scores_higher_and_peaks_at_the_shift(self):
        drift = zone_drift_scores(self._zf(), half_window=5)
        a = drift[drift["zone"] == "A"].dropna(subset=["drift_score"])
        b = drift[drift["zone"] == "B"].dropna(subset=["drift_score"])
        self.assertGreater(a["drift_score"].max(), 2 * b["drift_score"].max())
        peak_idx = a.loc[a["drift_score"].idxmax(), "window_start"]
        self.assertLessEqual(abs((peak_idx - pd.Timestamp("2024-01-21")).days), 3)

    def test_boundaries_are_nan(self):
        drift = zone_drift_scores(self._zf(), half_window=5)
        a = drift[drift["zone"] == "A"].sort_values("window_start")
        self.assertTrue(a["drift_score"].head(5).isna().all())
        self.assertTrue(a["drift_score"].tail(4).isna().all())

import pandas as pd

from analytics.changepoints import (
    collect_selection_changepoint_contributions,
    collect_selection_changepoints,
)


class ChangepointTests(unittest.TestCase):
    def test_selection_changepoints_can_keep_only_strongest_events(self):
        windows = pd.date_range("2024-01-01", periods=16, freq="D")
        values_a = [1, 1, 1, 1, 3, 3, 3, 3, 10, 10, 10, 10, 12, 12, 12, 12]
        values_b = [2, 2, 2, 2, 4, 4, 4, 4, 11, 11, 11, 11, 13, 13, 13, 13]
        zf = pd.DataFrame(
            {
                "window_start": list(windows) * 2,
                "zone": ["A"] * len(windows) + ["B"] * len(windows),
                "token_present_end": values_a + values_b,
            }
        )

        out = collect_selection_changepoints(
            zf=zf,
            zones=["A", "B"],
            metrics=["token_present_end"],
            cp_strictness=0,
            min_size=2,
            min_points=8,
            jump=1,
            aggregate_method="mean",
            selection_label="Current selection",
            max_selection_cps=1,
            flank_points=3,
        )

        self.assertEqual(len(out), 1)
        # The larger jump is around the shift from ~3.5 to ~10.5.
        self.assertEqual(pd.to_datetime(out.iloc[0]["timestamp"]), pd.Timestamp("2024-01-09"))

    def test_selection_changepoint_contributions_rank_top_series(self):
        windows = pd.date_range("2024-01-01", periods=12, freq="D")
        zf = pd.DataFrame(
            {
                "window_start": list(windows) * 2,
                "zone": ["A"] * len(windows) + ["B"] * len(windows),
                "token_present_end": [1, 1, 1, 1, 1, 1, 8, 8, 8, 8, 8, 8] + [2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3],
                "token_avg_age_open": [1, 1, 1, 1, 1, 1, 6, 6, 6, 6, 6, 6] + [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2],
            }
        )

        cp_events = collect_selection_changepoints(
            zf=zf,
            zones=["A", "B"],
            metrics=["token_present_end", "token_avg_age_open"],
            cp_strictness=0,
            min_size=2,
            min_points=8,
            jump=1,
            aggregate_method="mean",
            selection_label="Current selection",
            max_selection_cps=1,
            flank_points=3,
        )
        contrib = collect_selection_changepoint_contributions(
            zf=zf,
            zones=["A", "B"],
            metrics=["token_present_end", "token_avg_age_open"],
            selection_cp_events=cp_events,
            min_points=8,
            metric_display_map={
                "token_present_end": "Token present at window end",
                "token_avg_age_open": "Token average open age",
            },
            selection_label="Current selection",
            aggregate_method="mean",
            flank_points=3,
        )

        self.assertFalse(contrib.empty)
        top = contrib.sort_values("contribution_pct", ascending=False).iloc[0]
        self.assertEqual(top["zone"], "A")
        self.assertIn(top["metric_column"], {"token_present_end", "token_avg_age_open"})


if __name__ == "__main__":
    unittest.main()
