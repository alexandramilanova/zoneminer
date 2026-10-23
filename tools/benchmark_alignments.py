"""Compare cold serial and native-batch Rust4PM alignment on the same net.

Run from the repository root: python tools/benchmark_alignments.py
Optionally supply --log path/to/log.xes and --pnml path/to/model.pnml.
Input loading and discovery are excluded from alignment timings. No persisted
analysis cache is read or written. Identical transition UUIDs are used for both
paths. Costs and fitness must match; equally optimal paths may differ. Replay
validates both histories, and the report records whether they match exactly.
"""

import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import r4pm

from process_model import alignment_backends as backends
from process_model.replay import token_place_table_from_alignments
from process_model.io import (
    discover_process_tree_from_log,
    load_any_log,
    load_csv_log,
    load_pnml,
    petri_net_from_process_tree,
)


def serial_alignments(bundle, converted):
    net, names, labels_by_id = converted
    ids = {entry["name"]: entry["id"] for entry in r4pm.list_bindings()}
    options = backends._cost_options()
    empty = json.loads(r4pm.call_binding(ids["align_empty_trace"], json.dumps({"net": net, "options": options})))
    cache = {}
    results = []
    for trace in bundle.log:
        labels = backends._trace_labels(trace)
        if labels not in cache:
            raw = r4pm.call_binding(ids["align_trace"], json.dumps({"net": net, "trace": list(labels), "options": options}))
            cache[labels] = backends._adapt_alignment(json.loads(raw), labels, labels_by_id, names, empty["cost"])
        results.append(cache[labels])
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=Path("data/demo/demo_log_showcase.csv"))
    parser.add_argument("--pnml", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    pnml = args.pnml
    if pnml is None and args.log == Path("data/demo/demo_log_showcase.csv"):
        pnml = Path("data/demo/order_process.pnml")
    log = load_csv_log(str(args.log)) if args.log.suffix == ".csv" else load_any_log(str(args.log))
    net, im, fm = load_pnml(str(pnml)) if pnml else petri_net_from_process_tree(discover_process_tree_from_log(log))
    bundle = SimpleNamespace(log=log, net=net, im=im, fm=fm)
    print(json.dumps({"prepared_cases": len(log), "variants": len({backends._trace_labels(trace) for trace in log})}), flush=True)
    converted = backends._net_to_r4pm(bundle.net, bundle.im, bundle.fm)
    timings = {"serial": [], "batch": []}
    aligned = {}
    with patch.object(backends, "_net_to_r4pm", return_value=converted):
        for repeat in range(args.repeats):
            # Alternate order to reduce warm-up/order bias.
            for method in (("serial", "batch") if repeat % 2 == 0 else ("batch", "serial")):
                start = time.perf_counter()
                aligned[method] = serial_alignments(bundle, converted) if method == "serial" else backends.compute_alignments_r4pm(bundle.log, bundle.net, bundle.im, bundle.fm)
                timings[method].append(time.perf_counter() - start)
                print(json.dumps({"method": method, "round": repeat + 1, "seconds": timings[method][-1]}), flush=True)
            if len(aligned["serial"]) != len(aligned["batch"]):
                raise AssertionError("Serial and batch case counts differ")
            for serial, batch in zip(aligned["serial"], aligned["batch"]):
                if (serial["cost"], serial["fitness"]) != (batch["cost"], batch["fitness"]):
                    raise AssertionError("Serial and batch alignment costs or fitness differ")
    tables = {method: token_place_table_from_alignments(bundle.log, bundle.net, bundle.im, bundle.fm, aligned=result) for method, result in aligned.items()}
    try:
        pd.testing.assert_frame_equal(tables["serial"], tables["batch"])
        exact_replay = True
    except AssertionError:
        exact_replay = False
    medians = {method: statistics.median(values) for method, values in timings.items()}
    print(json.dumps({
        "cases": len(bundle.log),
        "variants": len({backends._trace_labels(trace) for trace in bundle.log}),
        "intervals": len(tables["batch"]),
        "median_seconds": medians,
        "speedup": medians["serial"] / medians["batch"],
        "equal_costs_and_fitness": True,
        "different_optimal_case_alignments": sum(s != b for s, b in zip(aligned["serial"], aligned["batch"])),
        "both_replays_valid": True,
        "exact_replay_equality": exact_replay,
    }, indent=2))


if __name__ == "__main__":
    main()
