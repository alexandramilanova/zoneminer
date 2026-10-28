import itertools
import unittest

import pandas as pd

from process_model.alignment_order import canonical_alignment
from process_model.replay import token_place_table_from_alignments
from tests.test_replay_semantics import make_net, event_log, exact_alignment


class CanonicalAlignmentTests(unittest.TestCase):
    def test_weighted_independent_interleavings_have_one_valid_timed_history(self):
        net, im, fm = make_net(
            ["p", "q", "pa", "qb", "fa", "fb"],
            [("ta", None), ("tb", None), ("a", "A"), ("b", "B")],
            [("p", "ta", 2), ("ta", "pa", 2), ("pa", "a", 2), ("a", "fa", 1),
             ("q", "tb", 3), ("tb", "qb", 3), ("qb", "b", 3), ("b", "fb", 1)],
            {"p": 2, "q": 3}, {"fa": 1, "fb": 1})
        pairs = {"ta": (">>", None), "tb": (">>", None), "a": ("A", "A"), "b": ("B", "B")}
        expected = None
        for order in itertools.permutations(pairs):
            if not (order.index("ta") < order.index("a") < order.index("b") and order.index("tb") < order.index("b")):
                continue
            original = exact_alignment([pairs[t] for t in order], order)[0]
            original.update(cost=2, fitness=1.)
            canonical = canonical_alignment(original, net)
            self.assertEqual([move[0] for move in canonical["alignment"] if move[0] != ">>"], ["A", "B"])
            self.assertEqual(canonical["cost"], original["cost"])
            self.assertEqual(canonical["fitness"], original["fitness"])
            self.assertEqual(sorted(canonical["transition_names"].values()), sorted(order))
            frame = token_place_table_from_alignments(event_log("A", "B"), net, im, fm, aligned=[canonical])
            frame = frame.sort_values(["place", "produced_ts", "consumed_ts"]).reset_index(drop=True)
            if expected is not None:
                pd.testing.assert_frame_equal(frame, expected, check_exact=True)
            expected = frame

    def test_dependent_invalid_order_is_not_repaired(self):
        net, im, fm = make_net(["s", "m", "f"], [("tau", None), ("a", "A")],
                              [("s", "tau", 1), ("tau", "m", 1), ("m", "a", 1), ("a", "f", 1)],
                              {"s": 1}, {"f": 1})
        invalid = exact_alignment([("A", "A"), (">>", None)], ["a", "tau"])[0]
        canonical = canonical_alignment(invalid, net)
        with self.assertRaisesRegex(ValueError, "not enabled"):
            token_place_table_from_alignments(event_log("A"), net, im, fm, aligned=[canonical])

    def test_inferred_firing_does_not_cross_distinct_timestamp(self):
        net, _, _ = make_net(
            ["s", "m", "f", "q", "r"],
            [("a", "A"), ("b", "B"), ("tau", None)],
            [("s", "a", 1), ("a", "m", 1), ("m", "b", 1),
             ("b", "f", 1), ("q", "tau", 1), ("tau", "r", 1)],
            {"s": 1, "q": 1}, {"f": 1, "r": 1})
        original = exact_alignment([("A", "A"), ("B", "B"), (">>", None)],
                                   ["a", "b", "tau"])[0]
        times = ["2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z"]
        canonical = canonical_alignment(original, net, times)
        self.assertEqual(canonical["transition_names"], original["transition_names"])
        tied = canonical_alignment(original, net, [times[0], times[0]])
        self.assertEqual(list(tied["transition_names"].values()), ["tau", "a", "b"])
