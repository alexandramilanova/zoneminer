"""Build the bundled example scenarios under data/examples/.

Each scenario is a small, seeded, deterministic event log + hand-built Petri
net + zone system + metadata, designed so ONE family of the tool's analyses
shows textbook behavior:

    express-lane    priority customers overtake in the Processing queue
                    -> FIFO/overtaking metrics, fingerprint scatter,
                       performance spectrum, calibratable queue model
    batch-dispatch  parcels leave the loading dock in two daily truck runs
                    -> batching metrics, CFD staircase, batch fingerprint
                       rows, "degenerate" queue-model verdict
    review-rework   rejected documents loop Review -> Revision -> Drafting
                    -> Review again, plus log/model-move noise
                    -> REVISIT metrics (zero on the order-process demos by
                       construction!), zone-attributed conformance, local
                       fitness, a cyclic handover graph
    capacity-cliff  a mid-line assembly slowdown builds a backlog that
                    starves everything downstream, then recovers and drains
                    -> bottleneck states, flow-map halos, drift scores,
                       period comparison, alert hints, mid-drift open-case
                       outlook

Every generator uses a fixed seed and a fixed base date, so the script always
reproduces byte-identical files.

Usage (from repo root):
    python tools/build_examples.py
"""

from __future__ import annotations

import heapq
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from pm4py.objects.petri_net.exporter import exporter as pnml_exporter
from pm4py.objects.petri_net.obj import Marking, PetriNet
from pm4py.objects.petri_net.utils import petri_utils

EXAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "examples"
)
BASE = datetime(2025, 3, 3, 0, 0, 0)  # a Monday

MIN = timedelta(minutes=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


# ---------------------------------------------------------------------------
# net construction helpers
# ---------------------------------------------------------------------------


def _chain_net(name: str, activities: list[str], extra=None):
    """Sequential net p_start -[A1]-> p_after_A1 -[A2]-> ... -> p_end.

    ``extra`` optionally adds transitions: list of (t_name, label, in_place,
    out_place) referring to place names created here.
    """
    net = PetriNet(name)
    places = {}

    def place(pname: str) -> PetriNet.Place:
        p = PetriNet.Place(pname)
        net.places.add(p)
        places[pname] = p
        return p

    def trans(tname: str, label: str) -> PetriNet.Transition:
        t = PetriNet.Transition(tname, label)
        net.transitions.add(t)
        return t

    prev = place("p_start")
    for act in activities:
        t = trans(f"t_{act}", act)
        petri_utils.add_arc_from_to(prev, t, net)
        nxt = place(f"p_after_{act}")
        petri_utils.add_arc_from_to(t, nxt, net)
        prev = nxt
    # rename the last place to p_end for readability
    prev.name = "p_end"
    places["p_end"] = places.pop(f"p_after_{activities[-1]}")

    for tname, label, in_place, out_place in extra or []:
        t = trans(tname, label)
        if in_place not in places:
            place(in_place)
        if out_place not in places:
            place(out_place)
        petri_utils.add_arc_from_to(places[in_place], t, net)
        petri_utils.add_arc_from_to(t, places[out_place], net)

    im = Marking({places["p_start"]: 1})
    fm = Marking({places["p_end"]: 1})
    return net, im, fm


def _sec(t: datetime) -> float:
    """Seconds since BASE — all queue arithmetic uses this instead of epoch
    timestamps, so results are identical regardless of the host timezone's
    DST transitions inside the simulated window."""
    return (t - BASE).total_seconds()


def _dt(seconds: float) -> datetime:
    return BASE + timedelta(seconds=float(seconds))


def _fifo_servers(jobs: list[tuple[datetime, float]], c: int) -> list[datetime]:
    """FCFS c-server queue: jobs = (ready_time, service_seconds) sorted by
    ready time; returns completion times in job order."""
    free: list[float] = [0.0] * c
    heapq.heapify(free)
    out = []
    for ready, service in jobs:
        f = heapq.heappop(free)
        start = max(_sec(ready), f)
        end = start + service
        heapq.heappush(free, end)
        out.append(_dt(end))
    return out


def _write(example_id: str, df: pd.DataFrame, net, im, fm, zones: dict, meta: dict):
    out = os.path.join(EXAMPLES_DIR, example_id)
    os.makedirs(out, exist_ok=True)
    df = df.sort_values(["case_id", "time:timestamp"]).reset_index(drop=True)
    df["time:timestamp"] = df["time:timestamp"].map(lambda d: d.strftime("%Y-%m-%d %H:%M:%S"))
    df.to_csv(os.path.join(out, "log.csv"), index=False)
    pnml_exporter.apply(net, im, os.path.join(out, "model.pnml"), final_marking=fm)
    with open(os.path.join(out, "zones.json"), "w", encoding="utf-8") as f:
        json.dump(zones, f, indent=2)
    with open(os.path.join(out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    # self-check: the zone system must be valid on this net
    from process_model.zone_validation import validate_zones

    result = validate_zones(
        zone_inputs=list(zones.items()),
        place_names=sorted(p.name for p in net.places),
        net=net,
        require_non_empty=True,
        allow_unassigned_places=True,
        require_connected=True,
    )
    assert result["zone_config_valid"], f"{example_id}: invalid zones: {result['errors']}"
    print(
        f"{example_id}: {df['case_id'].nunique()} cases, {len(df)} events, "
        f"{len(zones)} zones -> {out}"
    )


# ---------------------------------------------------------------------------
# scenario 1: express-lane (overtaking)
# ---------------------------------------------------------------------------


def build_express_lane():
    rng = np.random.RandomState(11)
    rows = []
    jobs = []  # (classify_done, is_express, case_id)
    cid = 0
    for day in range(15):
        if (BASE + day * DAY).weekday() >= 5:
            continue  # weekends off
        n = 46 + rng.randint(-4, 5)
        starts = np.sort(rng.uniform(8 * 3600, 18 * 3600, n))
        for s in starts:
            cid += 1
            case = f"E{cid:04d}"
            t = BASE + day * DAY + timedelta(seconds=float(s))
            rows.append((case, "Register_Order", t))
            t = t + timedelta(minutes=float(rng.uniform(2, 10)))
            rows.append((case, "Classify_Order", t))
            jobs.append((t, bool(rng.rand() < 0.25), case))

    # 2-server priority queue: whenever a server frees, express jobs already
    # waiting are served before standard ones (each class FIFO internally)
    jobs.sort(key=lambda j: j[0])
    free = [0.0, 0.0]
    heapq.heapify(free)
    waiting_express: list[tuple[float, int]] = []
    waiting_standard: list[tuple[float, int]] = []
    next_job = 0
    done = 0
    service_of = {}
    while done < len(jobs):
        f = heapq.heappop(free)
        # admit everything that became ready before the server freed
        while next_job < len(jobs) and _sec(jobs[next_job][0]) <= f:
            r, express, _ = jobs[next_job]
            (waiting_express if express else waiting_standard).append((_sec(r), next_job))
            next_job += 1
        if waiting_express:
            ready, idx = waiting_express.pop(0)
        elif waiting_standard:
            ready, idx = waiting_standard.pop(0)
        elif next_job < len(jobs):
            # idle server: jump to the next arrival
            ready = _sec(jobs[next_job][0])
            idx = next_job
            next_job += 1
        else:
            break
        start = max(f, ready)
        service = float(rng.uniform(60, 150) * 60)
        end = start + service
        heapq.heappush(free, end)
        service_of[idx] = end
        done += 1

    for idx, (_, express, case) in enumerate(jobs):
        t_done = _dt(service_of[idx])
        rows.append((case, "Process_Order", t_done))
        rows.append(
            (case, "Ship_Order", t_done + timedelta(minutes=float(rng.uniform(20, 60))))
        )

    df = pd.DataFrame(rows, columns=["case_id", "concept:name", "time:timestamp"])
    net, im, fm = _chain_net(
        "express_lane", ["Register_Order", "Classify_Order", "Process_Order", "Ship_Order"]
    )
    zones = {
        "Intake": ["p_after_Register_Order"],
        "Processing": ["p_after_Classify_Order"],
        "Shipping": ["p_after_Process_Order"],
    }
    meta = {
        "title": "Express lane: priority overtaking",
        "description": (
            "A quarter of the orders are express and jump the two-server Processing "
            "queue. Averages look healthy — the reordering is the story."
        ),
        "highlights": [
            "FIFO inversion & overtaking metrics (Processing)",
            "Fingerprint scatter: crossing dots below the envelope",
            "Performance spectrum: crossing lines",
            "Queue-model lens calibrates; what-if applies",
        ],
        "timeframe": "D",
    }
    _write("express-lane", df, net, im, fm, zones, meta)


# ---------------------------------------------------------------------------
# scenario 2: batch-dispatch (batching)
# ---------------------------------------------------------------------------


def build_batch_dispatch():
    rng = np.random.RandomState(23)
    rows = []
    pack_jobs = []
    cid = 0
    for day in range(12):
        n = 52 + rng.randint(-5, 6)
        starts = np.sort(rng.uniform(7 * 3600, 16.5 * 3600, n))
        for s in starts:
            cid += 1
            case = f"B{cid:04d}"
            t = BASE + day * DAY + timedelta(seconds=float(s))
            rows.append((case, "Receive_Parcel", t))
            pack_jobs.append((t, float(rng.uniform(15, 45) * 60), case))

    pack_jobs.sort(key=lambda j: j[0])
    pack_done = _fifo_servers([(r, s) for r, s, _ in pack_jobs], c=4)

    for (ready, _, case), packed in zip(pack_jobs, pack_done):
        rows.append((case, "Pack_Parcel", packed))
        # truck runs at 11:00 and 17:00: the parcel leaves the dock on the
        # first departure after packing (next morning if packed after 17:00)
        dep = packed.replace(minute=0, second=0, microsecond=0)
        if packed.hour < 11:
            dep = dep.replace(hour=11)
        elif packed.hour < 17:
            dep = dep.replace(hour=17)
        else:
            dep = (dep + DAY).replace(hour=11)
        load = dep + timedelta(seconds=float(rng.uniform(0, 240)))
        rows.append((case, "Load_Truck", load))
        rows.append(
            (case, "Deliver_Parcel", load + timedelta(minutes=float(rng.uniform(90, 240))))
        )

    df = pd.DataFrame(rows, columns=["case_id", "concept:name", "time:timestamp"])
    net, im, fm = _chain_net(
        "batch_dispatch", ["Receive_Parcel", "Pack_Parcel", "Load_Truck", "Deliver_Parcel"]
    )
    zones = {
        "Packing": ["p_after_Receive_Parcel"],
        "Loading dock": ["p_after_Pack_Parcel"],
        "Delivery": ["p_after_Load_Truck"],
    }
    meta = {
        "title": "Batch dispatch: two truck runs a day",
        "description": (
            "Parcels are packed continuously but leave the loading dock only at "
            "11:00 and 17:00 — synchronized waiting made visible."
        ),
        "highlights": [
            "Batching metrics: ~2 batches/day on the dock",
            "CFD staircase; fingerprint scatter rows",
            "Batch wait overhead vs. cheap clusters",
            "Queue-model verdict: degenerate (by design)",
        ],
        "timeframe": "D",
    }
    _write("batch-dispatch", df, net, im, fm, zones, meta)


# ---------------------------------------------------------------------------
# scenario 3: review-rework (revisits + zone conformance)
# ---------------------------------------------------------------------------


def build_review_rework():
    rng = np.random.RandomState(37)
    rows = []
    cid = 0
    for day in range(14):
        n = 28 + rng.randint(-4, 5)
        starts = np.sort(rng.uniform(8 * 3600, 17 * 3600, n))
        for s in starts:
            cid += 1
            case = f"R{cid:04d}"
            t = BASE + day * DAY + timedelta(seconds=float(s))
            rows.append((case, "Draft_Document", t))
            skip_submit_once = rng.rand() < 0.07  # missing event -> model move
            rounds = 0
            while True:
                rounds += 1
                t = t + timedelta(hours=float(rng.uniform(1, 4)))
                if not (skip_submit_once and rounds == 1):
                    rows.append((case, "Submit_For_Review", t))
                t = t + timedelta(hours=float(rng.uniform(2, 8)))
                approve_p = 0.62 if rounds == 1 else 0.8
                if rng.rand() < approve_p or rounds >= 3:
                    rows.append((case, "Approve_Document", t))
                    if rng.rand() < 0.10:  # stray duplicate -> log move
                        rows.append(
                            (case, "Approve_Document", t + timedelta(minutes=float(rng.uniform(5, 20))))
                        )
                    rows.append(
                        (case, "Publish_Document", t + timedelta(hours=float(rng.uniform(1, 3))))
                    )
                    break
                rows.append((case, "Reject_Document", t))
                t = t + timedelta(hours=float(rng.uniform(4, 24)))
                rows.append((case, "Revise_Document", t))

    df = pd.DataFrame(rows, columns=["case_id", "concept:name", "time:timestamp"])
    net, im, fm = _chain_net(
        "review_rework",
        ["Draft_Document", "Submit_For_Review", "Approve_Document", "Publish_Document"],
        extra=[
            ("t_Reject", "Reject_Document", "p_after_Submit_For_Review", "p_revising"),
            ("t_Revise", "Revise_Document", "p_revising", "p_after_Draft_Document"),
        ],
    )
    zones = {
        "Drafting": ["p_after_Draft_Document"],
        "Review": ["p_after_Submit_For_Review"],
        "Revision": ["p_revising"],
        "Publishing": ["p_after_Approve_Document"],
    }
    meta = {
        "title": "Review & rework: documents loop back",
        "description": (
            "Rejected documents leave Review, get revised, and re-enter Drafting and "
            "Review — real revisits, plus noisy events the model cannot replay."
        ),
        "highlights": [
            "Revisit & rework metrics (non-zero!)",
            "Zone-attributed log/model moves & local fitness",
            "Cyclic handover Sankey",
            "Case journey: watch a document loop",
        ],
        "timeframe": "D",
    }
    _write("review-rework", df, net, im, fm, zones, meta)


# ---------------------------------------------------------------------------
# scenario 4: capacity-cliff (bottleneck chain, open cases at the end)
# ---------------------------------------------------------------------------


def build_capacity_cliff():
    rng = np.random.RandomState(53)
    rows = []
    prep_jobs = []
    cid = 0
    for day in range(21):
        n = 38 + rng.randint(-4, 5)
        starts = np.sort(rng.uniform(8 * 3600, 17 * 3600, n))
        for s in starts:
            cid += 1
            case = f"C{cid:04d}"
            t = BASE + day * DAY + timedelta(seconds=float(s))
            rows.append((case, "Intake_Order", t))
            prep_jobs.append((t, float(rng.uniform(20, 40) * 60), case))

    prep_jobs.sort(key=lambda j: j[0])
    prep_done = _fifo_servers([(r, s) for r, s, _ in prep_jobs], c=4)

    # Assembly: 3 stations; during days 8-13 the crew slows down ~3.5x (the
    # cliff), building a real backlog in front of Assembly
    cliff_lo = _sec(BASE + 8 * DAY)
    cliff_hi = _sec(BASE + 14 * DAY)
    asm_jobs = sorted(zip(prep_done, [j[2] for j in prep_jobs]), key=lambda x: x[0])
    free = [0.0] * 3
    heapq.heapify(free)
    asm_done = {}
    for ready, case in asm_jobs:
        f = heapq.heappop(free)
        start = max(f, _sec(ready))
        slow = cliff_lo <= start < cliff_hi
        service = float(rng.uniform(60, 100) * 60) * (3.5 if slow else 1.0)
        end = start + service
        heapq.heappush(free, end)
        asm_done[case] = _dt(end)

    insp_jobs = sorted(
        ((asm_done[j[2]], float(rng.uniform(20, 45) * 60), j[2]) for j in prep_jobs),
        key=lambda x: x[0],
    )
    insp_done = _fifo_servers([(r, s) for r, s, _ in insp_jobs], c=2)

    prep_done_of = {j[2]: d for j, d in zip(prep_jobs, prep_done)}
    insp_done_of = {j[2]: d for j, d in zip(insp_jobs, insp_done)}
    for _, _, case in prep_jobs:
        rows.append((case, "Prepare_Order", prep_done_of[case]))
        rows.append((case, "Assemble_Order", asm_done[case]))
        rows.append((case, "Inspect_Order", insp_done_of[case]))
        rows.append(
            (case, "Dispatch_Order", insp_done_of[case] + timedelta(minutes=float(rng.uniform(10, 30))))
        )

    df = pd.DataFrame(rows, columns=["case_id", "concept:name", "time:timestamp"])
    # note: truncating the log would NOT leave open tokens — alignment always
    # completes a trace to the final marking with model moves. Open cases are
    # visible at any mid-drift moment instead (the outlook's moment slider).
    cutoff = BASE + 24 * DAY
    df = df[df["time:timestamp"] < cutoff]

    net, im, fm = _chain_net(
        "capacity_cliff",
        ["Intake_Order", "Prepare_Order", "Assemble_Order", "Inspect_Order", "Dispatch_Order"],
    )
    zones = {
        "Preparation": ["p_after_Intake_Order"],
        "Assembly": ["p_after_Prepare_Order"],
        "Inspection": ["p_after_Assemble_Order"],
        "Dispatch": ["p_after_Inspect_Order"],
    }
    meta = {
        "title": "Capacity cliff: a bottleneck is born and drains",
        "description": (
            "Assembly slows to a crawl for six days: backlog piles up in front of it, "
            "downstream zones starve, then the line recovers and drains."
        ),
        "highlights": [
            "Bottleneck states: queueing, then starving downstream",
            "Zone flow map halos & drift scores",
            "Compare two periods (before vs. during)",
            "Open-case outlook mid-drift (moment slider)",
        ],
        "timeframe": "D",
    }
    _write("capacity-cliff", df, net, im, fm, zones, meta)


def main() -> None:
    os.makedirs(EXAMPLES_DIR, exist_ok=True)
    build_express_lane()
    build_batch_dispatch()
    build_review_rework()
    build_capacity_cliff()


if __name__ == "__main__":
    main()
