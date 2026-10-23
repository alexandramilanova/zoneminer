import unittest

import pandas as pd
from pm4py.objects.petri_net.obj import PetriNet
from pm4py.objects.petri_net.utils import petri_utils

from analytics.dependencies import (
    compute_propagation_table,
    compute_propagation_table_from_frames,
    prepare_dependency_metric_frames,
    select_basic_dependency_rows,
)
from process_model.features import (
    _batch_flags,
    _order_inversion_stats,
    build_case_zone_stays_from_places,
    build_zone_token_features_from_places,
)
from process_model.zone_suggestions import (
    readable_activity_labels,
    suggested_places_from_activity_labels,
)
from process_model.zone_validation import validate_zones


class DomainLogicTests(unittest.TestCase):
    def setUp(self):
        self.token_place_df = pd.DataFrame(
            {
                "case_id": ["c1", "c1", "c1", "c2"],
                "place": ["p1", "p2", "p1", "p1"],
                "produced_ts": pd.to_datetime(
                    [
                        "2024-01-01 00:00:00",
                        "2024-01-01 12:00:00",
                        "2024-01-02 00:00:00",
                        "2024-01-01 06:00:00",
                    ]
                ),
                "consumed_ts": pd.to_datetime(
                    [
                        "2024-01-01 12:00:00",
                        "2024-01-02 00:00:00",
                        None,
                        "2024-01-01 18:00:00",
                    ]
                ),
                "time_spent": pd.to_timedelta([43200, 43200, None, 43200], unit="s"),
            }
        )
        self.zone_places = {"Zone A": ["p1", "p2"]}

    def test_zone_validation_catches_duplicate_places(self):
        result = validate_zones(
            zone_inputs=[
                ("Zone A", ["p1", "p2"]),
                ("Zone B", ["p2"]),
            ],
            place_names=["p1", "p2", "p3"],
            net=None,
            require_non_empty=True,
            allow_unassigned_places=True,
            require_connected=False,
        )
        self.assertFalse(result["zone_config_valid"])
        self.assertIn("p2", result["duplicate_places"])

    def test_zone_validation_reports_unassigned_places(self):
        result = validate_zones(
            zone_inputs=[
                ("Zone A", ["p1"]),
                ("Zone B", ["p2"]),
            ],
            place_names=["p1", "p2", "p3"],
            net=None,
            require_non_empty=True,
            allow_unassigned_places=True,
            require_connected=False,
        )
        self.assertTrue(result["zone_config_valid"])
        self.assertIn("p3", result["unassigned_places"])
        self.assertTrue(result["warnings"])

    def test_dependency_frames_match_single_pair_computation(self):
        windows = pd.date_range("2024-01-01", periods=10, freq="D")
        zf = pd.DataFrame(
            {
                "window_start": list(windows) * 2,
                "zone": ["A"] * len(windows) + ["B"] * len(windows),
                "token_enter": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] + [2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
                "case_enter": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19] + [8, 9, 10, 11, 12, 13, 14, 15, 16, 17],
            }
        )

        direct = compute_propagation_table(
            zf=zf,
            src_metric="token_enter",
            tgt_metric="case_enter",
            max_lag=2,
            min_lag=0,
            min_points=5,
            correlate_changes=False,
        )
        frames = prepare_dependency_metric_frames(zf, ["token_enter", "case_enter"])
        from_frames = compute_propagation_table_from_frames(
            metric_frames=frames,
            src_metric="token_enter",
            tgt_metric="case_enter",
            max_lag=2,
            min_lag=0,
            min_points=5,
            correlate_changes=False,
        )

        pd.testing.assert_frame_equal(
            direct.reset_index(drop=True),
            from_frames.reset_index(drop=True),
        )

    def test_basic_dependency_selection_keeps_all_very_strong_rows(self):
        dep_all = pd.DataFrame(
            {
                "from_zone": ["A", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J"],
                "to_zone": ["B", "C", "C", "D", "E", "F", "G", "H", "I", "J", "K"],
                "src_metric": ["token_enter"] * 11,
                "tgt_metric": ["case_enter"] * 11,
                "best_corr": [0.95, 0.94, 0.93, 0.92, 0.91, -0.96, -0.95, 0.97, 0.91, 0.94, 0.92],
                "best_lag_windows": [1] * 11,
                "overlap_points": [12] * 11,
            }
        )

        selected = select_basic_dependency_rows(dep_all)
        self.assertEqual(len(selected), 11)
        self.assertTrue((selected["best_corr"].abs() >= 0.9).all())

    def test_basic_dependency_selection_falls_back_to_top_ten_above_point_seven(self):
        dep_all = pd.DataFrame(
            {
                "from_zone": [f"Z{i}" for i in range(12)],
                "to_zone": [f"Y{i}" for i in range(12)],
                "src_metric": ["token_enter"] * 12,
                "tgt_metric": ["case_enter"] * 12,
                "best_corr": [0.95, 0.91, 0.89, 0.88, 0.87, 0.86, 0.85, 0.84, 0.83, 0.82, 0.79, 0.69],
                "best_lag_windows": [1] * 12,
                "overlap_points": [12] * 12,
            }
        )

        selected = select_basic_dependency_rows(dep_all)
        self.assertEqual(len(selected), 10)
        self.assertTrue((selected["best_corr"].abs() >= 0.7).all())
        self.assertNotIn(0.69, selected["best_corr"].tolist())

    def test_readable_activity_labels_fall_back_to_petri_labels(self):
        net = PetriNet("n")
        t_a = PetriNet.Transition("t_a", "A")
        t_b = PetriNet.Transition("t_b", "B")
        t_tau = PetriNet.Transition("t_tau", None)
        net.transitions.update({t_a, t_b, t_tau})

        labels = readable_activity_labels(None, net)
        self.assertEqual(labels, ["A", "B"])

    def test_suggested_places_from_activity_labels_uses_adjacent_places(self):
        net = PetriNet("n")
        p0 = PetriNet.Place("p0")
        p1 = PetriNet.Place("p1")
        p2 = PetriNet.Place("p2")
        p3 = PetriNet.Place("p3")
        t_a = PetriNet.Transition("t_a", "A")
        t_b = PetriNet.Transition("t_b", "B")

        net.places.update({p0, p1, p2, p3})
        net.transitions.update({t_a, t_b})

        petri_utils.add_arc_from_to(p0, t_a, net)
        petri_utils.add_arc_from_to(t_a, p1, net)
        petri_utils.add_arc_from_to(p1, t_b, net)
        petri_utils.add_arc_from_to(t_b, p2, net)
        petri_utils.add_arc_from_to(t_b, p3, net)

        suggested = suggested_places_from_activity_labels(net, ["B"])
        self.assertEqual(suggested, ["p1", "p2", "p3"])

    def test_suggested_places_from_activity_labels_include_internal_connecting_places(self):
        net = PetriNet("n")
        p0 = PetriNet.Place("p0")
        p1 = PetriNet.Place("p1")
        p2 = PetriNet.Place("p2")
        p3 = PetriNet.Place("p3")
        p4 = PetriNet.Place("p4")
        t_a = PetriNet.Transition("t_a", "A")
        t_tau = PetriNet.Transition("t_tau", None)
        t_b = PetriNet.Transition("t_b", "B")

        net.places.update({p0, p1, p2, p3, p4})
        net.transitions.update({t_a, t_tau, t_b})

        petri_utils.add_arc_from_to(p0, t_a, net)
        petri_utils.add_arc_from_to(t_a, p1, net)
        petri_utils.add_arc_from_to(p1, t_tau, net)
        petri_utils.add_arc_from_to(t_tau, p2, net)
        petri_utils.add_arc_from_to(p2, t_b, net)
        petri_utils.add_arc_from_to(t_b, p3, net)
        petri_utils.add_arc_from_to(t_b, p4, net)

        suggested = suggested_places_from_activity_labels(net, ["A", "B"])
        self.assertIn("p1", suggested)
        self.assertIn("p2", suggested)
        self.assertLess(suggested.index("p1"), suggested.index("p3"))
        self.assertLess(suggested.index("p2"), suggested.index("p4"))

    def test_case_zone_stays_merge_touching_intervals(self):
        stays = build_case_zone_stays_from_places(self.token_place_df, self.zone_places)
        c1 = stays[stays["case_id"] == "c1"]
        self.assertEqual(len(c1), 1)
        self.assertEqual(c1.iloc[0]["zone"], "Zone A")
        self.assertTrue(pd.isna(c1.iloc[0]["exit_ts"]))

    def test_zone_feature_generation_builds_canonical_metrics(self):
        features = build_zone_token_features_from_places(
            self.token_place_df,
            self.zone_places,
            timeframe="D",
        )
        self.assertFalse(features.empty)
        self.assertIn("token_enter", features.columns)
        self.assertIn("token_avg_age_open", features.columns)
        self.assertIn("case_present_end", features.columns)


class OrderInversionStatsTests(unittest.TestCase):
    """FIFO/overtaking statistics (EXTENSIONS A1): hand-checked small cases."""

    @staticmethod
    def _stats(entries, exits):
        import numpy as np

        return _order_inversion_stats(
            np.asarray(entries, dtype="int64"), np.asarray(exits, dtype="int64")
        )

    def test_perfect_fifo(self):
        inv, rate, depth = self._stats([1, 2, 3], [4, 5, 6])
        self.assertEqual(inv, 0.0)
        self.assertEqual(rate, 0.0)
        self.assertTrue(pd.isna(depth))

    def test_single_overtake(self):
        # B enters after A but leaves before A; C is untouched
        inv, rate, depth = self._stats([1, 2, 3], [4, 3, 5])
        self.assertAlmostEqual(inv, 1 / 3)  # 1 inverted pair of 3
        self.assertAlmostEqual(rate, 1 / 3)  # only A was overtaken
        self.assertEqual(depth, 1.0)  # B passed exactly one case

    def test_fully_reversed(self):
        inv, rate, depth = self._stats([1, 2, 3], [6, 5, 4])
        self.assertEqual(inv, 1.0)
        self.assertAlmostEqual(rate, 2 / 3)  # last one is never overtaken
        self.assertAlmostEqual(depth, 1.5)  # B passed 1, C passed 2

    def test_ties_are_order_preserving(self):
        inv, rate, depth = self._stats([1, 1, 2], [3, 3, 3])
        self.assertEqual(inv, 0.0)
        self.assertEqual(rate, 0.0)
        self.assertTrue(pd.isna(depth))

    def test_degenerate_sizes(self):
        inv, rate, depth = self._stats([], [])
        self.assertTrue(pd.isna(inv) and pd.isna(rate) and pd.isna(depth))
        inv, rate, depth = self._stats([1], [2])
        self.assertTrue(pd.isna(inv) and pd.isna(rate) and pd.isna(depth))


class RevisitMetricsTests(unittest.TestCase):
    """Revisit/rework metrics (EXTENSIONS A5) on a hand-built scenario."""

    def test_revisit_counts_ratio_and_gap(self):
        token_place_df = pd.DataFrame(
            {
                "case_id": ["c1", "c1", "c2"],
                "place": ["p1", "p1", "p1"],
                "produced_ts": pd.to_datetime(
                    ["2024-01-01 00:00", "2024-01-01 12:00", "2024-01-01 01:00"]
                ),
                "consumed_ts": pd.to_datetime(
                    ["2024-01-01 06:00", "2024-01-01 18:00", "2024-01-01 02:00"]
                ),
            }
        )
        zf = build_zone_token_features_from_places(token_place_df, {"Z": ["p1"]}, timeframe="D")
        row = zf[zf["window_start"] == pd.Timestamp("2024-01-01")].iloc[0]
        # three stays start on Jan 1; c1's second stay (6h after leaving) is a revisit
        self.assertEqual(row["case_revisit_enter"], 1)
        self.assertAlmostEqual(row["case_rework_ratio"], 1 / 3)
        self.assertAlmostEqual(row["case_revisit_gap_mean"], 6 * 3600.0)

    def test_no_revisits_is_zero_not_nan(self):
        token_place_df = pd.DataFrame(
            {
                "case_id": ["c1", "c2"],
                "place": ["p1", "p1"],
                "produced_ts": pd.to_datetime(["2024-01-01 00:00", "2024-01-01 01:00"]),
                "consumed_ts": pd.to_datetime(["2024-01-01 06:00", "2024-01-01 02:00"]),
            }
        )
        zf = build_zone_token_features_from_places(token_place_df, {"Z": ["p1"]}, timeframe="D")
        row = zf[zf["window_start"] == pd.Timestamp("2024-01-01")].iloc[0]
        self.assertEqual(row["case_revisit_enter"], 0)
        self.assertEqual(row["case_rework_ratio"], 0.0)
        self.assertTrue(pd.isna(row["case_revisit_gap_mean"]))


class BatchFlagsTests(unittest.TestCase):
    """Batching-on-exit detection (EXTENSIONS A2): hand-checked small cases.

    Times in minutes for readability; converted to ns on call.
    """

    MIN = 60 * 1_000_000_000  # one minute in ns

    def _flags(self, entries_min, exits_min, eps_gap_min=15, **kw):
        import numpy as np

        entries = np.asarray(entries_min, dtype="int64") * self.MIN
        exits = np.asarray(exits_min, dtype="int64") * self.MIN
        order = np.argsort(exits, kind="stable")
        return _batch_flags(entries[order], exits[order], eps_gap_min * self.MIN, **kw)

    def test_synchronized_release_is_a_batch(self):
        # four cases enter hours apart, all leave within three minutes
        bf = self._flags([0, 60, 120, 180], [300, 301, 302, 303])
        self.assertTrue(bf["batched"].all())
        self.assertEqual(list(bf["batch_size"]), [4])
        # the last enterer (entry 180, exit 303, sojourn 123) is the quickest
        # member; the first arrival's overhead is its sojourn minus that:
        # (300 - 0) - 123 = 177 minutes
        self.assertEqual(bf["wait_overhead_s"].max(), 177 * 60.0)
        self.assertEqual(bf["wait_overhead_s"].min(), 0.0)

    def test_steady_flow_is_not_a_batch(self):
        # exits chain within the gap, but entries are equally spread (no
        # synchronized waiting) -> compression test rejects the cluster
        bf = self._flags([0, 10, 20, 30], [60, 70, 80, 90])
        self.assertFalse(bf["batched"].any())
        self.assertEqual(len(bf["batch_size"]), 0)

    def test_too_small_cluster_is_not_a_batch(self):
        bf = self._flags([0, 60], [300, 301])
        self.assertFalse(bf["batched"].any())

    def test_gap_splits_clusters(self):
        # two synchronized releases an hour apart -> two batches of three
        bf = self._flags(
            [0, 20, 40, 200, 220, 240],
            [300, 301, 302, 400, 401, 402],
        )
        self.assertEqual(list(bf["batch_size"]), [3, 3])
        self.assertTrue(bf["batched"].all())


class WhatIfSimulationTests(unittest.TestCase):
    """C2 what-if: the FCFS c-server simulator on hand-checked scenarios."""

    def test_single_server_queue_builds(self):
        import numpy as np

        from analytics.whatif import simulate_queue

        # three arrivals at t=0,10,20 with service 100 each, one server:
        # waits are 0, 90, 180
        waits, finishes = simulate_queue(
            np.array([0.0, 10.0, 20.0]), np.array([100.0, 100.0, 100.0]), 1
        )
        self.assertEqual(list(waits), [0.0, 90.0, 180.0])
        self.assertEqual(list(finishes), [100.0, 200.0, 300.0])

    def test_enough_servers_means_no_wait(self):
        import numpy as np

        from analytics.whatif import simulate_queue

        waits, _ = simulate_queue(
            np.array([0.0, 10.0, 20.0]), np.array([100.0, 100.0, 100.0]), 3
        )
        self.assertEqual(list(waits), [0.0, 0.0, 0.0])

    def test_occupancy_curve(self):
        import numpy as np

        from analytics.whatif import occupancy_curve

        occ = occupancy_curve(
            np.array([0.0, 5.0]), np.array([10.0, 20.0]), np.array([1.0, 7.0, 15.0, 25.0])
        )
        self.assertEqual(list(occ), [1, 2, 1, 0])


if __name__ == "__main__":
    unittest.main()
