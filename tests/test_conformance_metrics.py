import unittest

import pandas as pd

from process_model.conformance import (
    add_window_conformance_features,
    trace_conformance_table_from_alignments,
)


class FakeTrace(list):
    def __init__(self, case_id: str, events: list[dict]):
        super().__init__(events)
        self.attributes = {"concept:name": case_id}


class ConformanceMetricTests(unittest.TestCase):
    def test_trace_conformance_table_counts_sync_and_deviation_moves(self):
        log = [
            FakeTrace(
                "c1",
                [
                    {"time:timestamp": pd.Timestamp("2024-01-01 08:00:00")},
                    {"time:timestamp": pd.Timestamp("2024-01-01 09:00:00")},
                ],
            )
        ]
        aligned = [
            {
                "fitness": 0.75,
                "cost": 2.0,
                "alignment": [("A", "A"), ("B", ">>"), (">>", "C")],
            }
        ]

        out = trace_conformance_table_from_alignments(log, aligned)

        self.assertEqual(len(out), 1)
        self.assertEqual(int(out.loc[0, "alignment_sync_move_count"]), 1)
        self.assertEqual(int(out.loc[0, "alignment_log_move_count"]), 1)
        self.assertEqual(int(out.loc[0, "alignment_model_move_count"]), 1)
        self.assertEqual(int(out.loc[0, "alignment_deviation_count"]), 2)
        self.assertEqual(int(out.loc[0, "alignment_has_deviation"]), 1)
        self.assertAlmostEqual(float(out.loc[0, "alignment_trace_fitness"]), 0.75)

    def test_window_conformance_features_merge_into_zone_features(self):
        zone_feat = pd.DataFrame(
            {
                "zone": ["Zone A", "Zone A"],
                "window_start": pd.to_datetime(["2024-01-01", "2024-01-02"]),
                "window_end": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                "token_enter": [2, 1],
            }
        )
        trace_conformance_df = pd.DataFrame(
            {
                "case_id": ["c1", "c2"],
                "trace_start": pd.to_datetime(["2024-01-01 08:00:00", "2024-01-02 07:00:00"]),
                "trace_end": pd.to_datetime(["2024-01-01 10:00:00", "2024-01-02 11:00:00"]),
                "alignment_trace_fitness": [0.9, 0.5],
                "alignment_trace_cost": [0.0, 3.0],
                "alignment_sync_move_count": [4, 2],
                "alignment_log_move_count": [0, 1],
                "alignment_model_move_count": [0, 2],
                "alignment_deviation_count": [0, 3],
                "alignment_has_deviation": [0, 1],
            }
        )

        merged = add_window_conformance_features(zone_feat, trace_conformance_df)

        self.assertIn("alignment_trace_fitness_mean", merged.columns)
        self.assertIn("alignment_deviation_count", merged.columns)
        first = merged.loc[merged["window_start"] == pd.Timestamp("2024-01-01")].iloc[0]
        second = merged.loc[merged["window_start"] == pd.Timestamp("2024-01-02")].iloc[0]
        self.assertAlmostEqual(float(first["alignment_trace_fitness_mean"]), 0.9)
        self.assertEqual(int(first["alignment_deviation_count"]), 0)
        self.assertAlmostEqual(float(second["alignment_trace_fitness_mean"]), 0.5)
        self.assertEqual(int(second["alignment_deviation_count"]), 3)
        self.assertAlmostEqual(float(second["alignment_trace_deviation_rate"]), 1.0)


if __name__ == "__main__":
    unittest.main()
