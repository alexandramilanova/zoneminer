"""Backend parity: the r4pm alignment backend must agree with pm4py.

Optimal alignments are not unique, so the two backends may pick different
(equally optimal) alignments — costs must be identical, fitness identical,
and the derived zone-feature table must agree within tolerances. Where a
metric depends on move *ordering* inside parallel branches, small deviations
are legitimate; anything beyond tolerance is a real regression.
"""

import json
import os
import unittest

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_DIR = os.path.join(REPO_ROOT, "data", "demo")


def _load_demo():
    from services import load_model_inputs

    with open(os.path.join(DEMO_DIR, "demo_log_small.csv"), "rb") as f:
        log_bytes = f.read()
    with open(os.path.join(DEMO_DIR, "order_process.pnml"), "rb") as f:
        pnml_bytes = f.read()
    with open(os.path.join(DEMO_DIR, "zones.json"), encoding="utf-8") as f:
        zone_places = json.load(f)
    return load_model_inputs(log_bytes, ".csv", pnml_bytes), zone_places


class TestAlignmentBackendParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import r4pm  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("r4pm not installed")

        from process_model.alignment_backends import compute_alignments

        cls.bundle, cls.zone_places = _load_demo()
        b = cls.bundle
        cls.aligned_pm4py = compute_alignments(b.log, b.net, b.im, b.fm, backend="pm4py")
        cls.aligned_r4pm = compute_alignments(b.log, b.net, b.im, b.fm, backend="r4pm")

    def test_same_trace_count(self):
        self.assertEqual(len(self.aligned_pm4py), len(self.aligned_r4pm))

    def test_costs_identical(self):
        """Both backends use the same cost function; optimal cost is unique
        even when the optimal alignment is not."""
        costs_pm = [int(a["cost"]) for a in self.aligned_pm4py]
        costs_r4 = [int(a["cost"]) for a in self.aligned_r4pm]
        mismatches = [
            (i, cp, cr) for i, (cp, cr) in enumerate(zip(costs_pm, costs_r4)) if cp != cr
        ]
        self.assertEqual(
            mismatches[:10],
            [],
            msg=f"{len(mismatches)} traces with differing optimal cost",
        )

    def test_fitness_close(self):
        # pm4py's best-worst-cost denominator books tau costs slightly
        # differently than a plain empty-trace alignment, shifting fitness by
        # ~1e-5 uniformly. Move classification (deviation counts) is unaffected,
        # so 1e-4 absolute tolerance is the honest bar here.
        fit_pm = np.array([float(a["fitness"]) for a in self.aligned_pm4py])
        fit_r4 = np.array([float(a["fitness"]) for a in self.aligned_r4pm])
        self.assertTrue(
            np.allclose(fit_pm, fit_r4, atol=1e-4),
            msg=f"max fitness diff: {np.abs(fit_pm - fit_r4).max()}",
        )

    def test_zone_features_agree_within_tolerance(self):
        from services import build_zone_analysis
        from process_model.conformance import trace_conformance_table_from_alignments
        from process_model.replay import token_place_table_from_alignments

        b = self.bundle
        results = {}
        for name, aligned in (("pm4py", self.aligned_pm4py), ("r4pm", self.aligned_r4pm)):
            token_place_df = token_place_table_from_alignments(
                b.log, b.net, b.im, b.fm, aligned=aligned
            )
            conf_df = trace_conformance_table_from_alignments(b.log, aligned)
            res = build_zone_analysis(
                token_place_df, conf_df, self.zone_places, "D", fm=b.fm
            )
            results[name] = (
                res["zone_features"]
                .sort_values(["zone", "window_start"])
                .reset_index(drop=True)
            )

        zf_pm, zf_r4 = results["pm4py"], results["r4pm"]
        self.assertEqual(len(zf_pm), len(zf_r4), "row counts differ")
        self.assertEqual(sorted(zf_pm.columns), sorted(zf_r4.columns))

        # Discontinuous order/pattern statistics over stay orderings: one tied
        # pair resolved differently by an equally-optimal alignment moves them
        # by O(1/n) in a small window, so exact or 1%-relative comparison is
        # the wrong bar. These tolerances still catch systematic breakage
        # (reversed comparisons, off-by-one-window shifts), and one window may
        # flip between "no value" (NaN) and a value.
        order_stat_tolerances = {
            "case_fifo_inversion_ratio": dict(rtol=0.0, atol=0.15),
            "case_overtaken_rate": dict(rtol=0.0, atol=0.25),
            "case_overtake_depth_mean": dict(rtol=0.0, atol=0.5),
            # batch detection thresholds on slightly different stay timestamps
            # can move a stay in/out of a batch or split a cluster
            "case_batch_count": dict(rtol=0.0, atol=2.0),
            "case_batch_size_mean": dict(rtol=0.0, atol=3.0),
            "case_batching_ratio": dict(rtol=0.0, atol=0.25),
            "case_batch_wait_overhead_mean": dict(rtol=0.5, atol=3600.0),
            # threshold effect: an open token near 2x the median duration can
            # sit on either side of "aged" between equally-optimal alignments
            "token_aged_open_share": dict(rtol=0.0, atol=0.15),
        }

        numeric_cols = [
            c for c in zf_pm.columns if pd.api.types.is_numeric_dtype(zf_pm[c])
        ]
        failures = []
        for col in numeric_cols:
            a = pd.to_numeric(zf_pm[col], errors="coerce").to_numpy(dtype=float)
            r = pd.to_numeric(zf_r4[col], errors="coerce").to_numpy(dtype=float)
            finite = a[np.isfinite(a)]
            is_integral = finite.size > 0 and np.allclose(finite, np.round(finite))
            if col in order_stat_tolerances:
                both = np.isfinite(a) & np.isfinite(r)
                nan_mismatches = int((np.isfinite(a) != np.isfinite(r)).sum())
                ok = nan_mismatches <= max(1, len(a) // 50) and np.allclose(
                    a[both], r[both], **order_stat_tolerances[col]
                )
            elif is_integral:
                # counts (entries/exits/cases/tokens) must match exactly
                ok = np.allclose(a, r, rtol=0, atol=0, equal_nan=True)
            else:
                # continuous (time-weighted) metrics: equally-optimal alignments
                # can order parallel moves differently -> 1% relative tolerance
                ok = np.allclose(a, r, rtol=0.01, atol=0.005, equal_nan=True)
            if not ok:
                failures.append((col, float(np.nanmax(np.abs(a - r)))))
        self.assertEqual(
            failures,
            [],
            msg="columns differing between backends beyond tolerance "
            f"(col, max abs diff): {failures}",
        )


if __name__ == "__main__":
    unittest.main()


class AlignmentBatchConfigurationTests(unittest.TestCase):
    def test_configured_batches_keep_optimal_costs_and_valid_replay(self):
        from unittest.mock import patch
        from process_model.alignment_backends import compute_alignments, variant_batch_size
        from process_model.replay import token_place_table_from_alignments
        bundle, _ = _load_demo()
        with patch.dict(os.environ, {'ZONE_ANALYTICS_ALIGNMENT_BATCH_SIZE': '64'}):
            reference = compute_alignments(bundle.log, bundle.net, bundle.im, bundle.fm, backend='r4pm')
        with patch.dict(os.environ, {'ZONE_ANALYTICS_ALIGNMENT_BATCH_SIZE': '1'}):
            bounded = compute_alignments(bundle.log, bundle.net, bundle.im, bundle.fm, backend='r4pm')
        self.assertEqual([x['cost'] for x in reference], [x['cost'] for x in bounded])
        self.assertEqual([x['fitness'] for x in reference], [x['fitness'] for x in bounded])
        self.assertFalse(token_place_table_from_alignments(bundle.log, bundle.net, bundle.im, bundle.fm, aligned=bounded).empty)
        for invalid in ('0', '-1', '1025', 'bad'):
            with patch.dict(os.environ, {'ZONE_ANALYTICS_ALIGNMENT_BATCH_SIZE': invalid}):
                with self.assertRaises(ValueError):
                    variant_batch_size()
