from __future__ import annotations

from typing import Any, Tuple

import pandas as pd
from pm4py.algo.discovery.inductive import algorithm as inductive_miner
from pm4py.objects.conversion.bpmn import converter as bpmn_converter
from pm4py.objects.conversion.log import converter as log_converter
from pm4py.objects.conversion.process_tree import converter as pt_converter
from pm4py.objects.conversion.wf_net import converter as wf_net_converter
from pm4py.objects.log.importer.xes import importer as xes_importer
from pm4py.objects.log.util import dataframe_utils
from pm4py.objects.petri_net.importer import importer as pnml_importer
from pm4py.objects.petri_net.obj import Marking, PetriNet
from process_model.semantics import validate_petri_net, validate_pnml


def normalize_event_order(log):
    """Stable chronological import policy, shared by CSV and XES.

    Original event values are retained, ties keep file order. This is explicit
    preprocessing, not timestamp repair or proof of business-process validity.
    """
    changed = moved = tied = 0
    for trace in log:
        case = str(trace.attributes.get("concept:name", "<unknown>"))
        timestamps = []
        for event in trace:
            ts = pd.Timestamp(event.get("time:timestamp"))
            if pd.isna(ts):
                raise ValueError(f"Case {case!r}: every event requires a valid timestamp")
            # Compare a single UTC clock; naive recorded times retain the
            # application's documented UTC interpretation.
            timestamps.append(ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC"))
        order = sorted(range(len(trace)), key=lambda i: timestamps[i])
        if order != list(range(len(trace))):
            changed += 1
            moved += sum(i != original for i, original in enumerate(order))
            events = list(trace)
            for i, original in enumerate(order):
                trace[i] = events[original]
        tied += sum(timestamps[a] == timestamps[b] for a, b in zip(order, order[1:]))
    log.attributes["zone_analytics:import_order"] = dict(policy="stable_timestamp_order_v1",
        reordered_cases=changed, moved_events=moved, tied_adjacent_events=tied)
    return log


def load_xes_log(path: str):
    return normalize_event_order(xes_importer.apply(path, parameters={"show_progress_bar": False}))


def load_csv_log(path: str):
    df = pd.read_csv(path)

    if "case_id" not in df.columns or "concept:name" not in df.columns or "time:timestamp" not in df.columns:
        raise ValueError(f"CSV missing required columns. Found: {list(df.columns)}")

    try:
        df["time:timestamp"] = pd.to_datetime(df["time:timestamp"])
    except ValueError:
        # logs whose offsets span a DST change ("mixed timezones") cannot be
        # parsed into one offset — normalize to UTC instead of failing to load
        df["time:timestamp"] = pd.to_datetime(df["time:timestamp"], utc=True)
    df = dataframe_utils.convert_timestamp_columns_in_df(df)
    df = df.rename(columns={"case_id": "case:concept:name"})

    # format_dataframe sorts (and drops missing rows) before conversion, which
    # would hide import-order changes from the shared report. Convert the
    # already canonical columns directly and preserve every source event.
    if df[["case:concept:name", "concept:name"]].isna().any().any():
        raise ValueError("CSV events require nonempty case IDs and activity names")
    for column in ("case:concept:name", "concept:name"):
        df[column] = df[column].astype(str)
    return normalize_event_order(log_converter.apply(df, variant=log_converter.Variants.TO_EVENT_LOG))


def load_any_log(path: str):
    p = path.lower()
    if p.endswith(".xes"):
        return load_xes_log(path)
    if p.endswith(".csv"):
        return load_csv_log(path)
    raise ValueError("Unsupported log format. Upload .xes or .csv")


def load_pnml(path: str) -> Tuple[PetriNet, Marking, Marking]:
    validate_pnml(path)
    net, im, fm = pnml_importer.apply(path, parameters={"auto_guess_final_marking": False})
    validate_petri_net(net, im, fm)
    return net, im, fm


def discover_process_tree_from_log(log, noise_threshold: float = 0.0):
    if not 0 <= noise_threshold <= 1:
        raise ValueError("Discovery noise threshold must be between 0 and 1")
    return inductive_miner.apply(
        log, variant=inductive_miner.Variants.IMf if noise_threshold else inductive_miner.Variants.IM,
        parameters={"noise_threshold": noise_threshold},
    )


def petri_net_from_process_tree(tree) -> tuple[Any, Any, Any]:
    return pt_converter.apply(tree, variant=pt_converter.Variants.TO_PETRI_NET)


def bpmn_from_process_tree(tree):
    return pt_converter.apply(tree, variant=pt_converter.Variants.TO_BPMN)


def bpmn_from_petri_net(net, im, fm):
    """Structural helper only; never replace the accepting net used in analysis.

    PM4Py's direct conversion does not preserve arc/marking multiplicities.
    Refuse those models instead of showing a misleading helper.
    """
    if (any(arc.weight != 1 for arc in net.arcs) or len(im) != 1 or len(fm) != 1
            or any(count != 1 for count in [*im.values(), *fm.values()])):
        raise ValueError("BPMN cannot represent this model's weighted arcs or multiple start/end tokens faithfully.")
    from pm4py.objects.conversion.wf_net.variants import to_bpmn
    return to_bpmn.apply(net, im, fm)


def process_tree_unavailable_reason(error):
    if "multiplicities" in str(error).lower():
        return ("No process tree: weighted arcs or multiple start/end tokens are not supported "
                "by this helper conversion. Zone definition and analysis use the Petri net.")
    if "not a wf-net" in str(error).lower():
        return ("No process tree: this model is not a workflow net with one source, one sink, "
                "and every node on a path between them. Zone definition and analysis use the Petri net.")
    return ("No process tree: this Petri net could not be reduced to the block-structured "
            "sequence, choice, parallel, and loop constructs required by the converter. "
            "Zone definition and analysis use the Petri net.")


def try_process_tree_from_petri_net(net: PetriNet, im: Marking, fm: Marking):
    if (any(arc.weight != 1 for arc in net.arcs) or len(im) != 1 or len(fm) != 1
            or any(count != 1 for count in [*im.values(), *fm.values()])):
        return None, "Unsupported token/arc multiplicities in the process-tree helper"
    try:
        tree = wf_net_converter.apply(net, im, fm, variant=wf_net_converter.Variants.TO_PROCESS_TREE)
        return tree, None
    except Exception as exc:
        return None, str(exc)


def discover_petri_net_from_log(log) -> tuple | tuple[Any, Any, Any]:
    res = discover_process_tree_from_log(log)
    if isinstance(res, tuple) and len(res) == 3:
        return res

    tree = res
    return petri_net_from_process_tree(tree)
