"""Independent small-net semantics tests, followed by backend integration tests.

Expected histories and incidence balances are specified by the fixtures, not
learned from either alignment backend or copied from a regression baseline.
"""

import unittest
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from pm4py.objects.log.obj import Event, EventLog, Trace
from pm4py.objects.petri_net.obj import Marking, PetriNet
from pm4py.objects.petri_net.utils import petri_utils
from pm4py.objects.petri_net.exporter import exporter as pnml_exporter

from process_model.alignment_backends import compute_alignments, _net_to_r4pm
from process_model.conformance import alignment_move_table_from_alignments
from process_model.replay import token_place_table_from_alignments
from process_model.semantics import validate_petri_net
from process_model.io import load_pnml


def make_net(places, transitions, arcs, initial, final):
    net = PetriNet("semantic-fixture")
    ps = {name: PetriNet.Place(name) for name in places}
    ts = {name: PetriNet.Transition(name, label) for name, label in transitions}
    net.places.update(ps.values())
    net.transitions.update(ts.values())
    nodes = ps | ts
    for source, target, weight in arcs:
        petri_utils.add_arc_from_to(nodes[source], nodes[target], net, weight=weight)
    return net, Marking({ps[p]: n for p, n in initial.items()}), Marking({ps[p]: n for p, n in final.items()})


def event_log(*labels):
    return EventLog([Trace([
        Event({"concept:name": label, "time:timestamp": pd.Timestamp("2024-01-01 08:00") + pd.Timedelta(hours=i)})
        for i, label in enumerate(labels)
    ], attributes={"concept:name": "case-1"})])


def exact_alignment(moves, identities):
    return [{"alignment": moves, "transition_names": {i: name for i, name in enumerate(identities) if name is not None}}]


def weighted_net():
    return make_net(["p", "q"], [("a", "A")], [("p", "a", 2), ("a", "q", 3)], {"p": 2}, {"q": 3})


def competing_net():
    return make_net(
        ["s", "bad", "mid", "ready", "f"],
        [("a_wrong", None), ("z_right", None), ("y_second", None), ("a", "A"), ("b", "B")],
        [("s", "a_wrong", 1), ("a_wrong", "bad", 1), ("bad", "b", 1), ("b", "f", 1),
         ("s", "z_right", 1), ("z_right", "mid", 1), ("mid", "y_second", 1),
         ("y_second", "ready", 1), ("ready", "a", 1), ("a", "f", 1)],
        {"s": 1}, {"f": 1},
    )


def concurrent_net():
    return make_net(
        ["s", "left", "right", "done_l", "done_r", "f"],
        [("split", "A"), ("left_work", "B"), ("right_work", "C"), ("join", None)],
        [("s", "split", 1), ("split", "left", 1), ("split", "right", 1),
         ("left", "left_work", 1), ("left_work", "done_l", 1),
         ("right", "right_work", 1), ("right_work", "done_r", 1),
         ("done_l", "join", 1), ("done_r", "join", 1), ("join", "f", 1)],
        {"s": 1}, {"f": 1},
    )


def duplicate_label_net():
    return make_net(["s", "m", "f"], [("first", "A"), ("second", "A")],
                    [("s", "first", 1), ("first", "m", 1), ("m", "second", 1), ("second", "f", 1)],
                    {"s": 1}, {"f": 1})


class ReplayAssertions:
    def assert_incidence_balance(self, net, im, fm, history, firing_names):
        """Check fixture incidence independently, including enabling each step."""
        marking = Counter({p.name: n for p, n in im.items()})
        produced = marking.copy()
        consumed = Counter()
        transitions = {t.name: t for t in net.transitions}
        for name in firing_names:
            transition = transitions[name]
            inputs = Counter()
            outputs = Counter()
            for arc in net.arcs:
                if arc.target is transition:
                    inputs[arc.source.name] += arc.weight
                if arc.source is transition:
                    outputs[arc.target.name] += arc.weight
            for place, count in inputs.items():
                self.assertGreaterEqual(marking[place], count)
                marking[place] -= count
                consumed[place] += count
            for place, count in outputs.items():
                marking[place] += count
                produced[place] += count
        self.assertEqual(+marking, Counter({p.name: n for p, n in fm.items() if n}))
        for place in net.places:
            rows = history[history.place == place.name]
            self.assertEqual(len(rows), produced[place.name])
            self.assertEqual(int(rows.consumed_ts.notna().sum()), consumed[place.name])
            self.assertEqual(int(rows.consumed_ts.isna().sum()), marking[place.name])
        closed = history[history.consumed_ts.notna()]
        self.assertTrue((closed.consumed_ts >= closed.produced_ts).all())


class IndependentReplaySemanticsTests(ReplayAssertions, unittest.TestCase):
    def test_weighted_input_and_output_have_exact_token_histories(self):
        net, im, fm = weighted_net()
        history = token_place_table_from_alignments(event_log("A"), net, im, fm,
            aligned=exact_alignment([("A", "A")], ["a"]))
        self.assertEqual(history.place.tolist(), ["p", "p", "q", "q", "q"])
        self.assertEqual(history.loc[history.place == "p", "consumed_ts"].tolist(), [pd.Timestamp("2024-01-01 08:00")] * 2)
        self.assertTrue(history.loc[history.place == "q", "consumed_ts"].isna().all())
        self.assert_incidence_balance(net, im, fm, history, ["a"])

    def test_exact_silent_chain_selects_correct_competing_branch(self):
        net, im, fm = competing_net()
        history = token_place_table_from_alignments(event_log("A"), net, im, fm,
            aligned=exact_alignment([(">>", None), (">>", None), ("A", "A")], ["z_right", "y_second", "a"]))
        self.assertEqual(history.place.tolist(), ["s", "mid", "ready", "f"])
        self.assertNotIn("bad", history.place.tolist())
        self.assertEqual(history.loc[history.place == "mid", "time_spent"].iloc[0], pd.Timedelta(microseconds=1))
        self.assert_incidence_balance(net, im, fm, history, ["z_right", "y_second", "a"])

    def test_split_join_concurrency_preserves_both_branches(self):
        net, im, fm = concurrent_net()
        history = token_place_table_from_alignments(event_log("A", "B", "C"), net, im, fm,
            aligned=exact_alignment([("A", "A"), ("B", "B"), ("C", "C"), (">>", None)],
                                    ["split", "left_work", "right_work", "join"]))
        left = history[history.place == "left"].iloc[0]
        right = history[history.place == "right"].iloc[0]
        self.assertEqual(left.time_spent, pd.Timedelta(hours=1))
        self.assertEqual(right.time_spent, pd.Timedelta(hours=2))
        self.assertEqual(left.produced_ts, right.produced_ts)
        self.assert_incidence_balance(net, im, fm, history, ["split", "left_work", "right_work", "join"])

    def test_duplicate_labels_resolve_by_identity_in_replay_and_conformance(self):
        net, im, fm = duplicate_label_net()
        log = event_log("A", "A")
        aligned = exact_alignment([("A", "A"), ("A", "A")], ["first", "second"])
        history = token_place_table_from_alignments(log, net, im, fm, aligned=aligned)
        self.assertEqual(history.place.tolist(), ["s", "m", "f"])
        moves = alignment_move_table_from_alignments(log, aligned, net)
        self.assertEqual(moves.t_name.tolist(), ["first", "second"])
        self.assert_incidence_balance(net, im, fm, history, ["first", "second"])

    def test_transition_name_and_activity_label_are_separate_namespaces(self):
        net, im, fm = make_net(["s", "m", "f"], [("A", "B"), ("other", "A")],
            [("s", "A", 1), ("A", "m", 1), ("m", "other", 1), ("other", "f", 1)], {"s": 1}, {"f": 1})
        history = token_place_table_from_alignments(event_log("B", "A"), net, im, fm,
            aligned=exact_alignment([("B", "B"), ("A", "A")], ["A", "other"]))
        self.assert_incidence_balance(net, im, fm, history, ["A", "other"])

    def test_insufficient_tokens_raise_instead_of_producing_phantom_tokens(self):
        net, im, fm = weighted_net()
        im[next(iter(im))] = 1
        with self.assertRaisesRegex(ValueError, "not enabled.*missing tokens"):
            token_place_table_from_alignments(event_log("A"), net, im, fm,
                aligned=exact_alignment([("A", "A")], ["a"]))

    def test_second_firing_cannot_reuse_consumed_tokens(self):
        net, im, fm = weighted_net()
        with self.assertRaisesRegex(ValueError, "not enabled"):
            token_place_table_from_alignments(event_log("A", "A"), net, im, fm,
                aligned=exact_alignment([("A", "A"), ("A", "A")], ["a", "a"]))

    def test_final_marking_must_match_place_and_multiplicity(self):
        for final in ({"q": 2}, {"q": 3, "p": 1}, {"p": 2}):
            with self.subTest(final=final):
                net, im, fm = weighted_net()
                places = {p.name: p for p in net.places}
                fm = Marking({places[p]: n for p, n in final.items()})
                with self.assertRaisesRegex(ValueError, "final marking.*does not match"):
                    token_place_table_from_alignments(event_log("A"), net, im, fm,
                        aligned=exact_alignment([("A", "A")], ["a"]))

    def test_multiple_final_places_and_unconsumed_initial_token(self):
        net, im, fm = make_net(["p", "q", "r"], [("a", "A")],
            [("p", "a", 1), ("a", "q", 1), ("a", "r", 2)], {"p": 2}, {"p": 1, "q": 1, "r": 2})
        history = token_place_table_from_alignments(event_log("A"), net, im, fm,
            aligned=exact_alignment([("A", "A")], ["a"]))
        self.assert_incidence_balance(net, im, fm, history, ["a"])

    def test_log_only_moves_do_not_fire_and_identity_alignment_keeps_initial_tokens(self):
        net, im, _ = weighted_net()
        history = token_place_table_from_alignments(event_log("noise"), net, im, im,
            aligned=exact_alignment([("noise", ">>")], [None]))
        self.assertEqual(history.place.tolist(), ["p", "p"])
        self.assert_incidence_balance(net, im, im, history, [])

    def test_ambiguous_log_only_zone_attribution_is_rejected(self):
        net, im, fm = duplicate_label_net()
        log = event_log("A", "A", "A")
        aligned = exact_alignment([("A", "A"), ("A", ">>"), ("A", "A")], ["first", None, "second"])
        token_place_table_from_alignments(log, net, im, fm, aligned=aligned)
        with self.assertRaisesRegex(ValueError, "zone attribution is ambiguous"):
            alignment_move_table_from_alignments(log, aligned, net)

    def test_unknown_mismatched_and_ambiguous_identities_are_rejected(self):
        net, im, fm = competing_net()
        for name in ("missing", "b"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "identity"):
                token_place_table_from_alignments(event_log("A"), net, im, fm,
                    aligned=exact_alignment([("A", "A")], [name]))
        with self.assertRaisesRegex(ValueError, "Silent.*exact transition identity"):
            token_place_table_from_alignments(event_log("A"), net, im, fm,
                aligned=[{"alignment": [(">>", None), (">>", None), ("A", "A")]}])
        net, im, fm = duplicate_label_net()
        with self.assertRaisesRegex(ValueError, "ambiguous model label"):
            token_place_table_from_alignments(event_log("A", "A"), net, im, fm,
                aligned=[{"alignment": [("A", "A"), ("A", "A")]}])

    def test_missing_alignments_and_events_raise(self):
        net, im, fm = weighted_net()
        for aligned in ([], [None], [{"alignment": []}], [{"alignment": [("A",)]}]):
            with self.subTest(aligned=aligned), self.assertRaises(ValueError):
                token_place_table_from_alignments(event_log("A"), net, im, fm, aligned=aligned)
        with self.assertRaisesRegex(ValueError, "empty traces"):
            token_place_table_from_alignments(event_log(), net, im, fm, aligned=[{"alignment": []}])
        log = event_log("A")
        del log[0][0]["time:timestamp"]
        with self.assertRaisesRegex(ValueError, "timestamp"):
            token_place_table_from_alignments(log, net, im, fm, aligned=exact_alignment([("A", "A")], ["a"]))

    def test_unsupported_arcs_and_invalid_counts_are_rejected(self):
        for weight in (0, -1, 1.5, True):
            net, im, fm = weighted_net()
            next(iter(net.arcs)).weight = weight
            with self.subTest(weight=weight), self.assertRaisesRegex(ValueError, "weights must be positive integers"):
                validate_petri_net(net, im, fm)
        for kind in ("reset", "inhibitor"):
            net, im, fm = weighted_net()
            next(iter(net.arcs)).properties["arctype"] = kind
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "reset/inhibitor"):
                compute_alignments(event_log("A"), net, im, fm, backend="r4pm")
        net, im, fm = weighted_net()
        im[next(iter(im))] = -1
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            validate_petri_net(net, im, fm)

    def test_duplicate_node_names_are_rejected(self):
        net, im, fm = weighted_net()
        net.places.add(PetriNet.Place("p"))
        with self.assertRaisesRegex(ValueError, "Duplicate place identities"):
            validate_petri_net(net, im, fm)

    def test_parallel_arc_objects_are_rejected(self):
        net, im, fm = weighted_net()
        arc = next(a for a in net.arcs if isinstance(a.source, PetriNet.Place))
        petri_utils.add_arc_from_to(arc.source, arc.target, net)
        with self.assertRaisesRegex(ValueError, "Parallel arcs"):
            validate_petri_net(net, im, fm)

    def test_model_moves_retain_identity_and_inferred_time(self):
        net, im, fm = duplicate_label_net()
        aligned = exact_alignment([("A", "A"), (">>", "A")], ["first", "second"])
        history = token_place_table_from_alignments(event_log("A"), net, im, fm, aligned=aligned)
        self.assert_incidence_balance(net, im, fm, history, ["first", "second"])
        self.assertEqual(history[history.place == "m"].iloc[0].time_spent, pd.Timedelta(microseconds=1))
        moves = alignment_move_table_from_alignments(event_log("A"), aligned, net)
        self.assertEqual(moves.t_name.tolist(), ["first", "second"])
        self.assertEqual(moves.move_type.tolist(), ["sync", "model"])

    def test_consumption_timestamp_precision_is_not_reduced(self):
        net, im, fm = make_net(["s", "m"], [("a", "A"), ("b", "B")],
            [("s", "a", 1), ("a", "m", 1), ("m", "b", 1)], {"s": 1}, {})
        log = event_log("A", "B")
        end = log[0][0]["time:timestamp"] + pd.Timedelta(nanoseconds=123)
        log[0][1]["time:timestamp"] = end
        history = token_place_table_from_alignments(log, net, im, fm,
            aligned=exact_alignment([("A", "A"), ("B", "B")], ["a", "b"]))
        self.assertEqual(history[history.place == "m"].iloc[0].consumed_ts, end)
        self.assertEqual(history[history.place == "m"].iloc[0].time_spent, pd.Timedelta(nanoseconds=123))


class AlignmentBackendSemanticIntegrationTests(ReplayAssertions, unittest.TestCase):
    """Only methods below belong to integration; reuse the balance assertion."""

    def test_engines_preserve_weighted_arcs_chains_parallelism_and_duplicate_labels(self):
        fixtures = [
            (weighted_net, ("A",), ["a"]),
            (competing_net, ("A",), ["z_right", "y_second", "a"]),
            (concurrent_net, ("A", "B", "C"), ["split", "left_work", "right_work", "join"]),
            (duplicate_label_net, ("A", "A"), ["first", "second"]),
        ]
        for fixture, labels, expected_names in fixtures:
            net, im, fm = fixture()
            log = event_log(*labels)
            histories = {}
            costs = []
            for backend in ("pm4py", "r4pm"):
                with self.subTest(fixture=fixture.__name__, backend=backend):
                    aligned = compute_alignments(log, net, im, fm, backend=backend)
                    self.assertEqual(list(aligned[0]["transition_names"].values()), expected_names)
                    history = token_place_table_from_alignments(log, net, im, fm, aligned=aligned)
                    self.assert_incidence_balance(net, im, fm, history, expected_names)
                    histories[backend] = history.sort_values(["place", "produced_ts", "consumed_ts"]).reset_index(drop=True)
                    costs.append(aligned[0]["cost"])
            self.assertEqual(costs[0], costs[1])
            pd.testing.assert_frame_equal(histories["pm4py"], histories["r4pm"])

    def test_both_engines_support_multiple_and_empty_final_markings(self):
        for arcs, final in (
            ([("p", "a", 1), ("a", "q", 1), ("a", "r", 2)], {"p": 1, "q": 1, "r": 2}),
            ([("p", "a", 2)], {}),
        ):
            net, im, fm = make_net(["p", "q", "r"], [("a", "A")], arcs, {"p": 2}, final)
            for backend in ("pm4py", "r4pm"):
                with self.subTest(final=final, backend=backend):
                    aligned = compute_alignments(event_log("A"), net, im, fm, backend=backend)
                    history = token_place_table_from_alignments(event_log("A"), net, im, fm, aligned=aligned)
                    self.assert_incidence_balance(net, im, fm, history, ["a"])

    def test_rust_conversion_preserves_arc_weights(self):
        net, im, fm = weighted_net()
        converted, _, _ = _net_to_r4pm(net, im, fm)
        self.assertEqual(sorted(arc["weight"] for arc in converted["arcs"]), [2, 3])

    def test_zero_marking_entries_mean_no_tokens_in_both_engines(self):
        net, im, fm = weighted_net()
        places = {p.name: p for p in net.places}
        im[places["q"]] = 0
        fm[places["p"]] = 0
        for backend in ("pm4py", "r4pm"):
            with self.subTest(backend=backend):
                aligned = compute_alignments(event_log("A"), net, im, fm, backend=backend)
                history = token_place_table_from_alignments(event_log("A"), net, im, fm, aligned=aligned)
                self.assert_incidence_balance(net, im, fm, history, ["a"])

    def test_utc_weighted_replay_integrates_with_all_open_case_zone_stays(self):
        from services import compute_alignment_tables, build_zone_analysis
        net, im, fm = weighted_net()
        log = event_log("A")
        log[0][0]["time:timestamp"] = log[0][0]["time:timestamp"].tz_localize("UTC")
        for backend in ("pm4py", "r4pm"):
            with self.subTest(backend=backend):
                tokens, conf, moves = compute_alignment_tables(log, net, im, fm, backend=backend)
                result = build_zone_analysis(tokens, conf, {"Z": ["p", "q"]}, "D", net=net, fm=fm, alignment_moves_df=moves)
                features = result["zone_features"]
                self.assertEqual(features.iloc[-1]["token_present_end"], 3)
                self.assertEqual(features.iloc[-1]["case_present_end"], 1)
                self.assertEqual(features["token_enter"].sum(), 5)
                self.assertEqual(features["token_exit"].sum(), 2)

    def test_utc_log_only_history_retains_all_open_token_timezone(self):
        net, im, fm = weighted_net()
        log = event_log("noise")
        log[0][0]["time:timestamp"] = log[0][0]["time:timestamp"].tz_localize("UTC")
        history = token_place_table_from_alignments(log, net, im, im,
            aligned=exact_alignment([("noise", ">>")], [None]))
        self.assertEqual(history.produced_ts.dtype, history.consumed_ts.dtype)
        self.assertTrue(history.consumed_ts.isna().all())


class ModelImportAndCacheIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "model.pnml"
        net, im, fm = weighted_net()
        pnml_exporter.apply(net, im, str(self.path), final_marking=fm)

    def test_weighted_pnml_roundtrip_preserves_markings(self):
        net, im, fm = load_pnml(str(self.path))
        self.assertEqual(sorted(a.weight for a in net.arcs), [2, 3])
        self.assertEqual({p.name: n for p, n in im.items()}, {"p": 2})
        self.assertEqual({p.name: n for p, n in fm.items()}, {"q": 3})

    def test_model_graph_retains_arc_weights(self):
        from backend.routers.datasets import get_model_graph
        net, im, fm = weighted_net()
        bundle = SimpleNamespace(net=net, im=im, fm=fm, log=[], process_tree=None,
                                 model_source="uploaded_petri_net", model_notice=None)
        with patch("backend.routers.datasets.get_bundle", return_value=bundle):
            graph = get_model_graph("weighted")
        self.assertEqual(sorted(arc["weight"] for arc in graph["arcs"]), [2, 3])

    def test_missing_and_multiple_final_markings_are_rejected(self):
        tree = ET.parse(self.path)
        net = tree.getroot().find("net")
        finals = net.find("finalmarkings")
        marking = finals.find("marking")
        finals.append(ET.fromstring(ET.tostring(marking)))
        tree.write(self.path)
        with self.assertRaisesRegex(ValueError, "exactly one final marking"):
            load_pnml(str(self.path))
        net.remove(finals)
        tree.write(self.path)
        with self.assertRaisesRegex(ValueError, "exactly one final marking"):
            load_pnml(str(self.path))

    def test_hierarchical_and_semantic_extensions_are_rejected(self):
        original = self.path.read_text()
        for extension in ("page", "variables", "declaration", "delay", "referencePlace", "arctype"):
            self.path.write_text(original)
            tree = ET.parse(self.path)
            ET.SubElement(tree.getroot().find("net"), extension)
            tree.write(self.path)
            with self.subTest(extension=extension), self.assertRaisesRegex(ValueError, "not supported|Unsupported"):
                load_pnml(str(self.path))

    def test_bad_arc_references_are_rejected_before_import_can_drop_them(self):
        tree = ET.parse(self.path)
        tree.getroot().find("net/page/arc").set("target", "missing")
        tree.write(self.path)
        with self.assertRaisesRegex(ValueError, "arcs must connect existing"):
            load_pnml(str(self.path))

    def test_old_replay_artifacts_cannot_be_a_cache_hit(self):
        from backend.store import analysis_id_for
        zones = {"Z": ["p"]}
        old_payload = json.dumps(["dataset", zones, "D", "r4pm"], sort_keys=True)
        old_id = hashlib.sha256(old_payload.encode()).hexdigest()[:16]
        self.assertNotEqual(analysis_id_for("dataset", zones, "D", "r4pm"), old_id)
        self.assertEqual(analysis_id_for("dataset", zones, "D", "r4pm"), analysis_id_for("dataset", zones, "D", "r4pm"))


if __name__ == "__main__":
    unittest.main()
