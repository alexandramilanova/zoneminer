"""Build the bundled demo dataset (log + Petri net + zone system) under data/demo/.

The demo dataset is the seeded e-commerce order-fulfillment simulation from
``tools/synthetic_log.py`` paired with the hand-built Petri net from
``tools/discover_petri_net.py`` and a five-zone system over its places.
Everything is deterministic (fixed seed), so this script always reproduces
byte-identical inputs.

Two variants:
    small  -- 14 days x ~30 orders/day; used by the regression baseline and CI.
    full   -- generator defaults (35 days x ~120 orders/day, all drift windows);
              the dataset the live demo ships with.

Usage (from repo root):
    python tools/build_demo_data.py          # writes the small variant
    python tools/build_demo_data.py --full   # additionally writes the full variant
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pm4py.objects.petri_net.exporter import exporter as pnml_exporter

from tools.discover_petri_net import build_fixed_order_petri_net
from tools.synthetic_log import generate_order_log_v5_capacity_backlog

DEMO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "demo")

# Five zones over the places of the fixed order-process Petri net.
# Invariants (see zone_validation.py): pairwise disjoint, each zone connected
# in the place-adjacency graph. p_start / p_end stay unassigned on purpose
# (source/sink), as do p_and_split / p_and_join (legacy isolated places with
# no arcs in the fixed net).
DEMO_ZONES = {
    "Customer Interaction": [
        "p_after_A1",
        "p_after_A2",
        "p_after_A3",
        "p_after_A4A5",
        "p_after_A6",
    ],
    "Payment & Risk": [
        "p_after_B1",
        "p_after_B_method",
        "p_after_B5",
        "p_after_verification",
        "p_paid",
        "p_payment_failed",
    ],
    "Fulfillment": [
        "p_after_C1",
        "p_pick_ready",
        "p_print_ready",
        "p_after_pick",
        "p_after_print",
        "p_after_parallel",
        "p_after_pack",
    ],
    "Quality": [
        "p_qc_entry",
        "p_qc_done",
    ],
    "Logistics": [
        "p_after_E1",
        "p_after_E2",
        "p_after_E3",
        "p_after_E4",
    ],
}

SMALL_PARAMS = dict(n_days=14, base_daily_orders=30, seed=42)

# The showcase scenario: full 35-day horizon so ALL four injected challenges
# occur (the small variant ends before two of them start):
#   days  6-14  payment-risk drift  — fraud reviews, verification loops, failures
#   days 12-18  arrival surge       — 2.2x order volume (overlaps the risk drift)
#   days 16-25  capacity bottleneck — fulfillment capacity drops 40 -> 18/day,
#                                     creating a real, growing backlog
#   days 22-28  quality drift       — QC and rework probabilities spike
# Order rate is scaled down (~45/day, ~1.5k cases) so the browser replay stays
# smooth, with fulfillment capacity scaled to match so the backlog still forms.
SHOWCASE_PARAMS = dict(
    n_days=35,
    base_daily_orders=45,
    fulfill_capacity_base=40,
    fulfill_capacity_drift=18,
    seed=42,
)


def build(full: bool = False) -> list[str]:
    os.makedirs(DEMO_DIR, exist_ok=True)
    written = []

    net, im, fm = build_fixed_order_petri_net()
    pnml_path = os.path.join(DEMO_DIR, "order_process.pnml")
    pnml_exporter.apply(net, im, pnml_path, final_marking=fm)
    written.append(pnml_path)

    zones_path = os.path.join(DEMO_DIR, "zones.json")
    with open(zones_path, "w", encoding="utf-8") as f:
        json.dump(DEMO_ZONES, f, indent=2)
    written.append(zones_path)

    small_df = generate_order_log_v5_capacity_backlog(**SMALL_PARAMS)
    small_path = os.path.join(DEMO_DIR, "demo_log_small.csv")
    small_df.to_csv(small_path, index=False)
    written.append(small_path)

    showcase_df = generate_order_log_v5_capacity_backlog(**SHOWCASE_PARAMS)
    showcase_path = os.path.join(DEMO_DIR, "demo_log_showcase.csv")
    showcase_df.to_csv(showcase_path, index=False)
    written.append(showcase_path)

    if full:
        full_df = generate_order_log_v5_capacity_backlog()  # generator defaults, seed=42
        full_path = os.path.join(DEMO_DIR, "demo_log_full.csv")
        full_df.to_csv(full_path, index=False)
        written.append(full_path)

    return written


if __name__ == "__main__":
    paths = build(full="--full" in sys.argv)
    for p in paths:
        print(f"Wrote {p}")
