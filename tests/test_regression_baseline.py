"""End-to-end regression check against the recorded baseline.

Recomputes the full pipeline (load -> align -> replay -> zone features) on the
committed small demo dataset and compares the result to the reference outputs
under ``tests/baseline/`` (recorded by ``tools/record_baseline.py``).

If this test goes red after a change, the change altered computed values.
Either that was unintended (fix the change) or intended (review the diff, then
consciously re-record the baseline and say so in the commit message). Never
refresh the baseline just to silence the test.

Also asserts two domain invariants from the zone-metrics guardrails:
  * conformance columns are window-level: identical across zones per window
  * token- and case-level entries diverge under parallelism (Fulfillment zone)
"""

import json
import os
import unittest

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_DIR = os.path.join(REPO_ROOT, "data", "demo")
BASELINE_DIR = os.path.join(REPO_ROOT, "tests", "baseline")

_pipeline_result = None


def _run_pipeline_once():
    global _pipeline_result
    if _pipeline_result is None:
        from services import run_demo_pipeline

        with open(os.path.join(DEMO_DIR, "zones.json"), encoding="utf-8") as f:
            zone_places = json.load(f)
        _pipeline_result = run_demo_pipeline(
            log_path=os.path.join(DEMO_DIR, "demo_log_small.csv"),
            pnml_path=os.path.join(DEMO_DIR, "order_process.pnml"),
            zone_places=zone_places,
            timeframe="D",
        )
    return _pipeline_result


class TestRegressionBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(os.path.join(BASELINE_DIR, "zone_features_baseline.csv")):
            raise unittest.SkipTest("Baseline not recorded (run tools/record_baseline.py)")
        cls.res = _run_pipeline_once()
        cls.zf = (
            cls.res["zone_features"].sort_values(["zone", "window_start"]).reset_index(drop=True)
        )
        cls.baseline = pd.read_csv(os.path.join(BASELINE_DIR, "zone_features_baseline.csv"))
        with open(os.path.join(BASELINE_DIR, "baseline_summary.json"), encoding="utf-8") as f:
            cls.summary = json.load(f)

    def test_shape_and_columns_match_baseline(self):
        self.assertEqual(len(self.zf), len(self.baseline))
        self.assertEqual(sorted(self.zf.columns), sorted(self.baseline.columns))
        self.assertEqual(
            sorted(self.zf["zone"].dropna().unique().tolist()),
            self.summary["zones"],
        )

    def test_numeric_values_match_baseline(self):
        numeric_cols = [
            c
            for c in self.baseline.columns
            if pd.api.types.is_numeric_dtype(self.baseline[c])
        ]
        self.assertGreater(len(numeric_cols), 5)
        for col in numeric_cols:
            recomputed = pd.to_numeric(self.zf[col], errors="coerce").to_numpy(dtype=float)
            reference = pd.to_numeric(self.baseline[col], errors="coerce").to_numpy(dtype=float)
            self.assertTrue(
                np.allclose(recomputed, reference, rtol=1e-6, atol=1e-9, equal_nan=True),
                msg=f"Column '{col}' deviates from baseline",
            )

    def test_trace_counts_match_baseline(self):
        conf = self.res["trace_conformance_df"]
        self.assertEqual(len(conf), self.summary["conformance_trace_count"])
        self.assertAlmostEqual(
            float(conf["alignment_trace_fitness"].mean()),
            float(self.summary["fitness_mean"]),
            places=9,
        )

    def test_conformance_is_window_level(self):
        """Guardrail: conformance columns must be identical across zones per window."""
        conf_cols = [c for c in self.zf.columns if c.startswith("alignment_")]
        self.assertTrue(conf_cols, "expected alignment_* columns in the feature table")
        for _, grp in self.zf.groupby("window_start"):
            for col in conf_cols:
                vals = grp[col].dropna().unique()
                self.assertLessEqual(
                    len(vals),
                    1,
                    msg=f"{col} varies across zones within one window — "
                    "window-level conformance semantics broken",
                )

    def test_zone_conformance_is_zone_attributed(self):
        """The zone_* conformance metrics must VARY by zone (unlike the
        window-level alignment_* metrics) and be internally consistent."""
        for col in (
            "zone_sync_move_count",
            "zone_log_move_count",
            "zone_model_move_count",
            "zone_deviation_count",
        ):
            self.assertIn(col, self.zf.columns)
            self.assertTrue((self.zf[col] >= 0).all())
        self.assertTrue(
            (
                self.zf["zone_deviation_count"]
                == self.zf["zone_log_move_count"] + self.zf["zone_model_move_count"]
            ).all()
        )
        totals = self.zf.groupby("zone")["zone_sync_move_count"].sum()
        self.assertGreater(totals.sum(), 0, "no sync moves attributed to any zone")
        self.assertGreater(
            totals.nunique(), 1, "zone-attributed counts identical across zones — "
            "these must vary by zone, unlike window-level conformance"
        )

    def test_zone_fitness_normalization(self):
        """A8 guardrail: boundary-normalized weights never exceed the plain
        counts (a boundary move contributes 1/k instead of 1 per zone) and
        local fitness is a proper ratio."""
        self.assertTrue(
            (
                self.zf["zone_deviation_weight"]
                <= self.zf["zone_deviation_count"] + 1e-9
            ).all()
        )
        fit = self.zf["zone_local_fitness"].dropna()
        self.assertTrue(((fit >= 0) & (fit <= 1)).all())
        self.assertGreater(len(fit), 0)
        # weights must vary by zone like the counts do
        self.assertGreater(self.zf.groupby("zone")["zone_deviation_weight"].sum().nunique(), 1)

    def test_token_case_divergence_under_parallelism(self):
        """Guardrail: the Fulfillment zone has an AND-split (pick || print), so
        token-level and case-level numbers must diverge somewhere. If they are
        equal everywhere, the token/case merging logic broke."""
        token_cols = [c for c in self.zf.columns if c.startswith("token_")]
        case_cols = [c for c in self.zf.columns if c.startswith("case_")]
        self.assertTrue(token_cols and case_cols)

        fulfillment = self.zf[self.zf["zone"] == "Fulfillment"]
        pairs = [
            (t, t.replace("token_", "case_", 1))
            for t in token_cols
            if t.replace("token_", "case_", 1) in case_cols
        ]
        self.assertTrue(pairs, "no comparable token_/case_ column pairs found")
        diverges = any(
            not np.allclose(
                pd.to_numeric(fulfillment[t], errors="coerce").fillna(0).to_numpy(dtype=float),
                pd.to_numeric(fulfillment[c], errors="coerce").fillna(0).to_numpy(dtype=float),
            )
            for t, c in pairs
        )
        self.assertTrue(
            diverges,
            "token_* and case_* metrics are identical everywhere in a zone with "
            "parallelism — expected divergence (see zone-metrics-guardrails)",
        )


class TestZoneValidationRejectsInvalid(unittest.TestCase):
    """The demo zone system is valid; deliberately broken variants must fail."""

    @classmethod
    def setUpClass(cls):
        from tools.discover_petri_net import build_fixed_order_petri_net

        cls.net, cls.im, cls.fm = build_fixed_order_petri_net()
        cls.place_names = sorted(p.name for p in cls.net.places)
        with open(os.path.join(DEMO_DIR, "zones.json"), encoding="utf-8") as f:
            cls.zones = json.load(f)

    def _validate(self, zone_inputs):
        from process_model.zone_validation import validate_zones

        return validate_zones(
            zone_inputs=zone_inputs,
            place_names=self.place_names,
            net=self.net,
            require_non_empty=True,
            allow_unassigned_places=True,
            require_connected=True,
        )

    def test_demo_zone_system_is_valid(self):
        result = self._validate(list(self.zones.items()))
        self.assertTrue(result["zone_config_valid"], msg=str(result["errors"]))

    def test_overlapping_zones_rejected(self):
        zones = [list(item) for item in self.zones.items()]
        zones[1][1] = list(zones[1][1]) + [zones[0][1][0]]  # steal a place from zone 0
        result = self._validate([tuple(z) for z in zones])
        self.assertFalse(result["zone_config_valid"])

    def test_disconnected_zone_rejected(self):
        # Customer place + Logistics place share no transition -> disconnected
        result = self._validate(
            [("Broken", ["p_after_A1", "p_after_E4"])]
        )
        self.assertFalse(result["zone_config_valid"])


if __name__ == "__main__":
    unittest.main()
