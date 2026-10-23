from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd
from pm4py.algo.conformance.alignments.petri_net import algorithm as align_algo
from pm4py.objects.petri_net.obj import Marking, PetriNet

from process_model.semantics import validate_petri_net


@dataclass
class FiredEvent:
    case_id: str
    t_name: str
    t_label: Optional[str]
    ts: pd.Timestamp


def _norm_move(x) -> Optional[str]:
    if x is None:
        return None
    if isinstance(x, str):
        return x
    if isinstance(x, (tuple, list)) and len(x) > 0:
        for part in x:
            if part is None:
                continue
            if isinstance(part, str):
                return part
            if hasattr(part, "label") and part.label is not None:
                return str(part.label)
            if hasattr(part, "name"):
                return str(part.name)
        return str(x[0])
    if hasattr(x, "label") and x.label is not None:
        return str(x.label)
    if hasattr(x, "name"):
        return str(x.name)
    return str(x)


def _petri_maps(net: PetriNet):
    """Weighted incidence lists and unambiguous *label* lookup.

    Repeated place names encode multiplicity, preserving the existing adjacency
    interface. Names and labels are separate namespaces: exact identities are
    carried in alignment metadata, never inferred from a potentially colliding
    label/name dictionary. Duplicate labels have no fallback lookup.
    """
    validate_petri_net(net)
    t_in_places = {t.name: [] for t in net.transitions}
    t_out_places = {t.name: [] for t in net.transitions}
    by_label = {}
    for transition in net.transitions:
        if transition.label is not None:
            by_label.setdefault(transition.label, []).append(transition.name)
    label_to_tname = {label: names[0] for label, names in by_label.items() if len(names) == 1}
    for arc in net.arcs:
        if isinstance(arc.source, PetriNet.Place):
            t_in_places[arc.target.name].extend([arc.source.name] * int(arc.weight))
        else:
            t_out_places[arc.source.name].extend([arc.target.name] * int(arc.weight))
    return t_in_places, t_out_places, label_to_tname


def resolve_transition_name(model_move: Optional[str], label_to_tname: dict) -> Optional[str]:
    return label_to_tname.get(model_move) if model_move not in (None, ">>") else None


def alignment_transition_name(alignment, position, log_move, model_move, net, label_to_tname, transitions=None):
    """Resolve exact model identities; reject ambiguous/incomplete metadata.

    Label-only legacy alignments are accepted only for unique visible labels.
    A silent move always requires its exact identity. A log-only move has no
    model transition, even if its activity happens to occur in the model.
    """
    names = alignment.get("transition_names", {})
    taus = alignment.get("tau_names", {})
    name = names.get(position, taus.get(position))
    if model_move == ">>":
        if name is not None or log_move in (None, ">>"):
            raise ValueError(f"Invalid log-only alignment move at position {position}")
        return None
    if name is None:
        if model_move is None:
            raise ValueError(f"Silent alignment move {position} requires an exact transition identity; recompute the alignment")
        name = label_to_tname.get(model_move)
        if name is None:
            raise ValueError(f"Unknown or ambiguous model label {model_move!r} at move {position}; an exact transition identity is required")
    if transitions is None:
        transitions = {transition.name: transition for transition in net.transitions}
    if name not in transitions:
        raise ValueError(f"Unknown transition identity {name!r} at move {position}")
    if transitions[name].label != model_move:
        raise ValueError(f"Transition identity {name!r} does not match model label {model_move!r} at move {position}")
    if log_move not in (None, ">>") and log_move != model_move:
        raise ValueError(f"Synchronous labels disagree at move {position}")
    return name


def build_firing_sequence_from_alignment(pm4py_trace, alignment_dict, label_to_tname, net, im, *, _maps=None, _transitions=None):
    """Replay a complete alignment with strict enabledness and exact identities.

    The historical timing convention is retained: observed moves use event
    timestamps, inserted model/silent moves use last timestamp + 1 microsecond.
    A following observed timestamp is clamped to that inferred clock. Token
    residence times are retrospective estimates, not observed execution times.
    """
    case_id = str(pm4py_trace.attributes.get("concept:name", "0"))
    trace_ts = []
    for event in pm4py_trace:
        timestamp = pd.Timestamp(event.get("time:timestamp"))
        if timestamp is None or pd.isna(timestamp):
            raise ValueError(f"Case {case_id!r}: every event requires a valid timestamp")
        trace_ts.append(timestamp)
    if not trace_ts:
        raise ValueError(f"Case {case_id!r}: empty traces have no timestamp for token-history reconstruction")
    if any(right < left for left, right in zip(trace_ts, trace_ts[1:])):
        raise ValueError(f"Case {case_id!r}: event timestamps must be non-decreasing")
    if not isinstance(alignment_dict, dict) or alignment_dict.get("alignment") is None:
        raise ValueError(f"Case {case_id!r}: no complete alignment was returned")
    t_in_places, t_out_places, _ = _maps if _maps is not None else _petri_maps(net)
    transitions = _transitions if _transitions is not None else {t.name: t for t in net.transitions}
    marking = {place.name: int(count) for place, count in im.items() if count}
    fired = []
    j = 0
    last_ts = trace_ts[0]
    eps = pd.Timedelta(microseconds=1)
    for i, move in enumerate(alignment_dict["alignment"]):
        if not isinstance(move, (tuple, list)) or len(move) != 2:
            raise ValueError(f"Case {case_id!r}: malformed alignment move {i}")
        log_move, model_move = move
        tname = alignment_transition_name(alignment_dict, i, log_move, model_move, net, label_to_tname, transitions)
        if log_move not in (None, ">>"):
            if j >= len(trace_ts):
                raise ValueError(f"Case {case_id!r}: alignment consumes more events than the trace")
            activity = pm4py_trace[j].get("concept:name")
            if activity != log_move:
                raise ValueError(f"Case {case_id!r}: alignment event {log_move!r} does not match trace event {activity!r}")
            last_ts = max(trace_ts[j], last_ts)
            j += 1
        else:
            last_ts += eps
        if tname is None:
            continue
        required = Counter(t_in_places[tname])
        missing = {place: count - marking.get(place, 0) for place, count in required.items() if marking.get(place, 0) < count}
        if missing:
            raise ValueError(f"Case {case_id!r}, move {i}: transition {tname!r} is not enabled; missing tokens {missing}")
        for place, count in required.items():
            marking[place] -= count
        for place in t_out_places[tname]:
            marking[place] = marking.get(place, 0) + 1
        fired.append(FiredEvent(case_id, tname, None if log_move in (None, ">>") else log_move, last_ts))
    if j != len(trace_ts):
        raise ValueError(f"Case {case_id!r}: alignment consumes {j} of {len(trace_ts)} trace events")
    return fired


def compute_alignments(log, net: PetriNet, im: Marking, fm: Marking):
    """Keep pm4py's exact transition names alongside its legacy label pairs."""
    validate_petri_net(net, im, fm)
    if im is None or fm is None:
        raise ValueError("Replay requires explicit initial and final markings")
    im = Marking({place: int(count) for place, count in im.items() if count})
    fm = Marking({place: int(count) for place, count in fm.items() if count})
    parameters = {"ret_tuple_as_trans_desc": True}
    variant = align_algo.DEFAULT_VARIANT
    if any(arc.weight != 1 for arc in net.arcs) or sum(im.values()) != 1 or sum(fm.values()) != 1:
        # The default synchronous-product path can reject valid weighted /
        # multi-token markings. Exact Dijkstra over (trace position, marking)
        # uses ordinary weighted semantics and the same alignment cost function.
        variant = align_algo.Variants.VERSION_DIJKSTRA_SEMANTICS
    raw = align_algo.apply_log(log, net, im, fm, parameters=parameters, variant=variant)
    results = []
    for alignment in raw:
        if alignment is None or alignment.get("alignment") is None:
            raise ValueError("pm4py could not find a complete alignment to the specified final marking")
        labels = []
        names = {}
        taus = {}
        for position, (identities, pair) in enumerate(alignment["alignment"]):
            labels.append(tuple(pair))
            if identities[1] != ">>":
                names[position] = identities[1]
                if pair[1] is None:
                    taus[position] = identities[1]
        results.append({**alignment, "alignment": labels, "transition_names": names, "tau_names": taus})
    return results


def token_place_table_from_alignments(
    log,
    net: PetriNet,
    im: Marking,
    fm: Marking,
    aligned=None,
) -> pd.DataFrame:
    """One interval per produced token; only exact complete replays are accepted.

    Tokens in the verified final marking remain unconsumed (NaT), as required
    by P/T semantics. FIFO matching of indistinguishable tokens within a place
    and the existing inferred timestamp convention are retained.
    """
    validate_petri_net(net, im, fm)
    if im is None or fm is None:
        raise ValueError("Replay requires explicit initial and final markings")
    maps = _petri_maps(net)
    t_in_places, t_out_places, label_to_tname = maps
    transitions = {t.name: t for t in net.transitions}
    aligned = compute_alignments(log, net, im, fm) if aligned is None else aligned

    if len(aligned) != len(log):
        raise ValueError("Alignment count does not match trace count")
    rows = []
    for trace, al in zip(log, aligned):
        case_id = str(trace.attributes.get("concept:name", "0"))
        fired = build_firing_sequence_from_alignment(trace, al, label_to_tname, net, im, _maps=maps, _transitions=transitions)

        open_tokens: Dict[str, deque[pd.Timestamp]] = {}

        def consume(place_name: str, ts: pd.Timestamp, case_id: str):
            if not open_tokens.get(place_name):
                raise ValueError(f"Case {case_id!r}: no token available in place {place_name!r}")
            p_ts = open_tokens[place_name].popleft()
            rows.append(
                {
                    "case_id": case_id,
                    "place": place_name,
                    "produced_ts": p_ts,
                    "consumed_ts": ts,
                    "time_spent": (ts - p_ts),
                }
            )

        first_ts = fired[0].ts if fired else pd.to_datetime(trace[0]["time:timestamp"])
        for p_obj, cnt in im.items():
            for _ in range(int(cnt)):
                open_tokens.setdefault(p_obj.name, deque()).append(first_ts)

        for fired_evt in fired:
            tname = fired_evt.t_name
            ts = fired_evt.ts

            for p_in in t_in_places.get(tname, []):
                consume(p_in, ts, case_id)

            for p_out in t_out_places.get(tname, []):
                open_tokens.setdefault(p_out, deque()).append(ts)

        actual_final = {place: len(tokens) for place, tokens in open_tokens.items() if tokens}
        expected_final = {place.name: int(count) for place, count in fm.items() if count}
        if actual_final != expected_final:
            raise ValueError(f"Case {case_id!r}: replay final marking {actual_final} does not match expected {expected_final}")

        for p, ts_list in open_tokens.items():
            for p_ts in ts_list:
                rows.append(
                    {
                        "case_id": case_id,
                        "place": p,
                        "produced_ts": p_ts,
                        "consumed_ts": pd.NaT,
                        "time_spent": pd.NaT,
                    }
                )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["produced_ts"] = pd.to_datetime(df["produced_ts"])
    df["consumed_ts"] = pd.to_datetime(df["consumed_ts"])
    if df["consumed_ts"].isna().all():
        df["consumed_ts"] = pd.Series(pd.NaT, index=df.index, dtype=df["produced_ts"].dtype)
    return df
