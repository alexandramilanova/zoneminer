"""Switchable alignment computation backends: pm4py (reference) and r4pm (fast).

Both backends return the same shape: one dict per trace, in log order, with

    {"alignment": [(log_label | ">>", model_label | ">>" | None), ...],
     "cost": int, "fitness": float}

plus ``transition_names`` mapping every model/synchronous move position to
its exact transition name (including silent moves). Label pairs are kept for
conformance compatibility; replay never guesses silent-transition identities.
Both adapters preserve ordinary arc weights and explicit initial/final markings.

The r4pm backend mirrors pm4py's standard cost function (sync 0, tau 1,
log/model move 10000) and pm4py's fitness formula
``1 - cost / (empty_trace_cost + n_events * move_cost)`` so costs and fitness
values are directly comparable. Optimal alignments are not unique, so small
differences in move *order* (e.g. within parallel branches) are legitimate;
the parity gate compares the resulting feature tables with tolerances rather
than expecting identical alignments.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from functools import lru_cache
from typing import Optional

from pm4py.objects.petri_net.obj import Marking, PetriNet

from process_model.replay import compute_alignments as _compute_alignments_pm4py
from process_model.semantics import validate_petri_net

# pm4py standard alignment costs (utils.align_utils: STD_*)
SYNC_COST = 0
TAU_COST = 1
MOVE_COST = 10000

DEFAULT_BACKEND = "pm4py"
_BACKEND_ENV_VAR = "ZONE_ANALYTICS_ALIGNMENT_BACKEND"
# Bound response size and retain progress between native parallel calls.
_VARIANT_BATCH_SIZE = 64


def resolve_backend(backend: Optional[str] = None) -> str:
    resolved = (backend or os.environ.get(_BACKEND_ENV_VAR) or DEFAULT_BACKEND).lower()
    if resolved not in ("pm4py", "r4pm"):
        raise ValueError(f"Unknown alignment backend: {resolved!r} (use 'pm4py' or 'r4pm')")
    return resolved


def compute_alignments(log, net: PetriNet, im: Marking, fm: Marking, backend: Optional[str] = None, progress=None):
    resolved = resolve_backend(backend)
    if resolved == "r4pm":
        return compute_alignments_r4pm(log, net, im, fm, progress=progress)
    return _compute_alignments_pm4py(log, net, im, fm)


# ---------------------------------------------------------------------------
# r4pm backend
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _align_binding_ids():
    import r4pm

    bindings = {b["name"]: b["id"] for b in r4pm.list_bindings()}
    return bindings["align_variants"], bindings["align_empty_trace"]


def _cost_options() -> dict:
    return {
        "cost_fn": {
            "sync_move_cost": SYNC_COST,
            "silent_move_cost": TAU_COST,
            "model_move_cost": MOVE_COST,
            "log_move_cost": MOVE_COST,
        }
    }


def _trace_labels(trace) -> tuple[str, ...]:
    return tuple(str(ev["concept:name"]) for ev in trace if "concept:name" in ev)


def _net_to_r4pm(net: PetriNet, im: Marking, fm: Marking):
    """Convert a pm4py net to r4pm's JSON shape with *our own* UUIDs, so every
    r4pm transition id maps back to the pm4py transition name — including
    silent transitions, whose identity r4pm reports exactly per move."""
    import uuid

    validate_petri_net(net, im, fm)
    if im is None or fm is None:
        raise ValueError("Replay requires explicit initial and final markings")
    # Random UUIDs and set iteration changed which equally optimal silent path
    # native search chose, making inferred microsecond timings vary on reload.
    # Stable structural IDs preserve original names in the reverse mapping.
    places = sorted(net.places, key=lambda p: p.name)
    place_uuid = {p.name: str(uuid.uuid5(uuid.NAMESPACE_URL, "zoneminer/place/" + p.name)) for p in places}

    def structure(t):
        return json.dumps([t.label,
                           sorted((a.source.name, int(a.weight)) for a in t.in_arcs),
                           sorted((a.target.name, int(a.weight)) for a in t.out_arcs)])

    transitions = sorted(net.transitions, key=lambda t: (structure(t), t.name))
    occurrences = Counter()
    trans_uuid = {}
    for transition in transitions:
        key = structure(transition)
        ordinal = occurrences[key]
        occurrences[key] += 1
        trans_uuid[transition.name] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"zoneminer/transition/{key}/{ordinal}"))
    name_by_uuid = {u: name for name, u in trans_uuid.items()}
    label_by_uuid = {trans_uuid[t.name]: t.label for t in net.transitions}

    arcs = []
    for arc in net.arcs:
        if isinstance(arc.source, PetriNet.Place):
            nodes = [place_uuid[arc.source.name], trans_uuid[arc.target.name]]
            arc_type = "PlaceTransition"
        else:
            nodes = [trans_uuid[arc.source.name], place_uuid[arc.target.name]]
            arc_type = "TransitionPlace"
        arcs.append({"from_to": {"type": arc_type, "nodes": nodes}, "weight": int(arc.weight)})
    arcs.sort(key=lambda arc: json.dumps(arc, sort_keys=True))

    r_net = {
        "places": {u: {"id": u} for u in place_uuid.values()},
        "transitions": {
            u: {"id": u, "label": label_by_uuid[u]} for u in trans_uuid.values()
        },
        "arcs": arcs,
        "initial_marking": {place_uuid[p.name]: int(c) for p, c in sorted(im.items(), key=lambda item: item[0].name) if c},
        "final_markings": [{place_uuid[p.name]: int(c) for p, c in sorted(fm.items(), key=lambda item: item[0].name) if c}],
    }
    return r_net, name_by_uuid, label_by_uuid


def compute_alignments_r4pm(log, net: PetriNet, im: Marking, fm: Marking, progress=None):
    """Alignments via the rust4pm engine, adapted to pm4py's output shape.

    Aligns unique variants in native parallel batches, then fans the results
    out to all traces of each variant in the original log order.
    """
    import r4pm

    r_net, name_by_uuid, label_by_uuid = _net_to_r4pm(net, im, fm)

    trace_labels = [_trace_labels(trace) for trace in log]
    frequencies = Counter(trace_labels)
    total_variants = len(frequencies)
    if progress:
        progress(0, total_variants)
    if not trace_labels:
        return []

    align_variants_id, align_empty_id = _align_binding_ids()
    options = _cost_options()

    empty_raw = r4pm.call_binding(
        align_empty_id, json.dumps({"net": r_net, "options": options})
    )
    empty_cost = int(_loads(empty_raw)["cost"])

    variant_cache: dict[tuple[str, ...], dict] = {}
    variants = list(frequencies)
    for start in range(0, total_variants, _VARIANT_BATCH_SIZE):
        batch = {labels: frequencies[labels] for labels in variants[start:start + _VARIANT_BATCH_SIZE]}
        rows = _align_variant_batch(r4pm, align_variants_id, r_net, batch, options)
        if not isinstance(rows, list):
            raise ValueError("Rust4PM did not return a variant alignment list")
        completed = {}
        for row in rows:
            labels = tuple(row["activities"])
            if labels not in batch or labels in completed or row["frequency"] != batch[labels]:
                raise ValueError("Rust4PM returned unexpected or duplicate alignment variants")
            result = row["result"]
            if "Err" in result:
                raise ValueError(f"Rust4PM alignment failed for a {len(labels)}-event variant: {result['Err']}")
            completed[labels] = _adapt_alignment(
                result.get("Ok"), labels, label_by_uuid, name_by_uuid, empty_cost
            )
        if completed.keys() != batch.keys():
            raise ValueError("Rust4PM returned incomplete variant alignments")
        variant_cache.update(completed)
        if progress:
            progress(len(variant_cache), total_variants)
    from process_model.alignment_order import canonical_alignment
    return [canonical_alignment(variant_cache[labels], net, [event["time:timestamp"] for event in trace])
            for labels, trace in zip(trace_labels, log)]


def _align_variant_batch(r4pm, binding_id, r_net, frequencies, options):
    """Import a compact activity-only projection; always release its registry entry.

    Rust4PM 0.6.0.post1 accepts projections through its file-backed registry.
    Encoding labels directly preserves our missing-label and string conventions
    without serializing timestamps or importing the full event log a second time.
    """
    activities = list(dict.fromkeys(label for labels in frequencies for label in labels))
    indices = {label: index for index, label in enumerate(activities)}
    projection = {
        "activities": activities,
        "act_to_index": indices,
        "traces": [
            [[indices[label] for label in labels], count]
            for labels, count in sorted(frequencies.items(), key=lambda item: -item[1])
        ],
    }
    with tempfile.TemporaryDirectory(prefix="zone-alignment-") as directory:
        path = os.path.join(directory, "projection.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(projection, handle)
        projection_id = r4pm.import_item("EventLogActivityProjection", path)
        try:
            return _loads(r4pm.call_binding(
                binding_id,
                json.dumps({"net": r_net, "projection": projection_id, "options": options}),
            ))
        finally:
            r4pm.remove_item(projection_id)


def _loads(raw):
    return json.loads(raw) if isinstance(raw, str) else raw


def _adapt_alignment(
    result: dict,
    trace_labels: tuple[str, ...],
    label_by_uuid: dict,
    name_by_uuid: dict,
    empty_cost: int,
) -> dict:
    """Retain exact Rust4PM transition identities for every model move."""
    alignment = []
    transition_names = {}
    tau_names = {}
    if not isinstance(result, dict) or "moves" not in result:
        raise ValueError("Rust4PM did not return a complete alignment")
    for move in result["moves"]:
        if "SyncMove" in move or "ModelMove" in move:
            kind = "SyncMove" if "SyncMove" in move else "ModelMove"
            payload = move[kind]
            uuid_ = payload["transition"]
            if uuid_ not in name_by_uuid:
                raise ValueError(f"Rust4PM returned an unknown transition identity {uuid_!r}")
            label = label_by_uuid[uuid_]
            transition_names[len(alignment)] = name_by_uuid[uuid_]
            if kind == "SyncMove":
                observed = trace_labels[payload["trace_event_index"]]
                if observed != label:
                    raise ValueError("Rust4PM synchronous move does not match the observed activity")
                alignment.append((observed, label))
            else:
                if label is None:
                    tau_names[len(alignment)] = name_by_uuid[uuid_]
                alignment.append((">>", label))
        elif "LogMove" in move:
            label = trace_labels[move["LogMove"]["trace_event_index"]]
            alignment.append((label, ">>"))
        else:
            raise ValueError(f"Unsupported Rust4PM alignment move: {move!r}")

    cost = int(result.get("cost", 0))
    # pm4py's fitness integer-divides tau costs out of numerator and
    # denominator (utils.align_utils) — mirror it exactly so both backends
    # report identical fitness for identical alignments.
    best_worst = empty_cost + MOVE_COST * len(trace_labels)
    fitness = (
        1.0 - (cost // MOVE_COST) / (best_worst // MOVE_COST)
        if best_worst // MOVE_COST > 0
        else 1.0
    )
    return {"alignment": alignment, "cost": cost, "fitness": fitness, "tau_names": tau_names, "transition_names": transition_names}
