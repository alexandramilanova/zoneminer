"""Record the regression baseline from the small demo dataset.

Runs the full pipeline (load -> align -> replay -> zone features) through the
service layer on ``data/demo/demo_log_small.csv`` + ``order_process.pnml`` +
``zones.json`` and stores reference outputs under ``tests/baseline/``:

    zone_features_baseline.csv  -- the full zone-feature table
    baseline_summary.json       -- coarse invariant numbers (row/case counts,
                                   per-zone token/case totals, fitness mean)

``tests/test_regression_baseline.py`` recomputes the same pipeline and compares
against these files. Re-run this script ONLY when a change to computed values is
intended and reviewed — never to make a red test green (see the
reproduce-experiments skill: silently refreshing the baseline hides regressions).

Usage (from repo root):
    python tools/record_baseline.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import run_demo_pipeline

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_DIR = os.path.join(REPO_ROOT, "data", "demo")
BASELINE_DIR = os.path.join(REPO_ROOT, "tests", "baseline")


def compute_summary(res: dict) -> dict:
    zf = res["zone_features"]
    token_place_df = res["token_place_df"]
    conf = res["trace_conformance_df"]

    per_zone = {}
    for zone, grp in zf.groupby("zone"):
        per_zone[str(zone)] = {
            "rows": int(len(grp)),
            "token_entries_total": float(grp.get("token_entries", 0).sum()) if "token_entries" in grp else None,
            "case_entries_total": float(grp.get("case_entries", 0).sum()) if "case_entries" in grp else None,
        }

    return {
        "zone_feature_rows": int(len(zf)),
        "zone_feature_columns": sorted(zf.columns.tolist()),
        "zones": sorted(zf["zone"].dropna().unique().tolist()),
        "token_place_rows": int(len(token_place_df)),
        "conformance_trace_count": int(len(conf)),
        "fitness_mean": float(conf["alignment_trace_fitness"].mean())
        if "alignment_trace_fitness" in conf.columns
        else None,
        "deviating_trace_count": int(conf["alignment_has_deviation"].sum())
        if "alignment_has_deviation" in conf.columns
        else None,
        "per_zone": per_zone,
    }


def main():
    with open(os.path.join(DEMO_DIR, "zones.json"), encoding="utf-8") as f:
        zone_places = json.load(f)

    res = run_demo_pipeline(
        log_path=os.path.join(DEMO_DIR, "demo_log_small.csv"),
        pnml_path=os.path.join(DEMO_DIR, "order_process.pnml"),
        zone_places=zone_places,
        timeframe="D",
    )

    os.makedirs(BASELINE_DIR, exist_ok=True)

    zf = res["zone_features"].sort_values(["zone", "window_start"]).reset_index(drop=True)
    zf.to_csv(os.path.join(BASELINE_DIR, "zone_features_baseline.csv"), index=False)

    summary = compute_summary(res)
    with open(os.path.join(BASELINE_DIR, "baseline_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"Baseline written to {BASELINE_DIR}")
    print(f"  zone-feature rows: {summary['zone_feature_rows']}")
    print(f"  zones: {summary['zones']}")
    print(f"  aligned traces: {summary['conformance_trace_count']}")
    print(f"  fitness mean: {summary['fitness_mean']}")


if __name__ == "__main__":
    main()
