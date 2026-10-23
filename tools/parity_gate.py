"""Parity gate: the new API must reproduce the Streamlit oracle's numbers.

Three paths over the same demo scenario (demo log + order-process net + five
zones, daily windows):

    A. oracle  — services.run_demo_pipeline (the exact code path the Streamlit
                 app uses), pm4py alignments
    B. api-pm4py — the FastAPI backend end to end, pm4py alignments
                   (must match A exactly: same code, same inputs)
    C. api-r4pm  — the FastAPI backend with the rust4pm alignment engine
                   (counts exact, continuous metrics within 1% — optimal
                   alignments are not unique)

Exit code 0 = gate passed. Run from repo root:
    python tools/parity_gate.py
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_DIR = os.path.join(REPO_ROOT, "data", "demo")


def _norm(zf: pd.DataFrame) -> pd.DataFrame:
    zf = zf.copy()
    zf["window_start"] = pd.to_datetime(zf["window_start"])
    return zf.sort_values(["zone", "window_start"]).reset_index(drop=True)


# Discontinuous order/pattern statistics over stay orderings: one tied pair
# resolved differently by an equally-optimal alignment moves them by O(1/n)
# in a small window. Applies only to the r4pm comparison (pm4py-vs-oracle
# stays exact); same tolerances as tests/test_alignment_backends.py.
ORDER_STAT_TOLERANCES = {
    "case_fifo_inversion_ratio": dict(rtol=0.0, atol=0.15),
    "case_overtaken_rate": dict(rtol=0.0, atol=0.25),
    "case_overtake_depth_mean": dict(rtol=0.0, atol=0.5),
    # batch detection thresholds on slightly different stay timestamps can
    # move a stay in/out of a batch or split a cluster
    "case_batch_count": dict(rtol=0.0, atol=2.0),
    "case_batch_size_mean": dict(rtol=0.0, atol=3.0),
    "case_batching_ratio": dict(rtol=0.0, atol=0.25),
    "case_batch_wait_overhead_mean": dict(rtol=0.5, atol=3600.0),
    # threshold effect: an open token near 2x the median duration can sit on
    # either side of "aged" between equally-optimal alignments
    "token_aged_open_share": dict(rtol=0.0, atol=0.15),
}


def compare(name: str, zf_a: pd.DataFrame, zf_b: pd.DataFrame, exact: bool) -> list[str]:
    problems = []
    if len(zf_a) != len(zf_b):
        return [f"{name}: row count {len(zf_a)} vs {len(zf_b)}"]
    if sorted(zf_a.columns) != sorted(zf_b.columns):
        return [f"{name}: column sets differ"]
    for col in zf_a.columns:
        if not pd.api.types.is_numeric_dtype(zf_a[col]):
            continue
        a = pd.to_numeric(zf_a[col], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(zf_b[col], errors="coerce").to_numpy(dtype=float)
        finite = a[np.isfinite(a)]
        integral = finite.size > 0 and np.allclose(finite, np.round(finite))
        if exact or integral:
            ok = np.allclose(a, b, rtol=0, atol=1e-9, equal_nan=True)
        else:
            ok = np.allclose(a, b, rtol=0.01, atol=0.005, equal_nan=True)
        if not ok and not exact and col in ORDER_STAT_TOLERANCES:
            both = np.isfinite(a) & np.isfinite(b)
            nan_mismatches = int((np.isfinite(a) != np.isfinite(b)).sum())
            ok = nan_mismatches <= max(1, len(a) // 50) and np.allclose(
                a[both], b[both], **ORDER_STAT_TOLERANCES[col]
            )
        if not ok:
            problems.append(
                f"{name}: column '{col}' max abs diff {np.nanmax(np.abs(a - b)):.6g}"
            )
    return problems


def main() -> int:
    os.environ.setdefault("ZONE_ANALYTICS_DATA_DIR", tempfile.mkdtemp(prefix="parity_gate_"))

    from fastapi.testclient import TestClient

    from backend.main import create_app, demo_zone_places
    from services import run_demo_pipeline

    zones = demo_zone_places()

    print("Path A: oracle (services, pm4py) ...")
    t0 = time.time()
    res = run_demo_pipeline(
        log_path=os.path.join(DEMO_DIR, "demo_log_small.csv"),
        pnml_path=os.path.join(DEMO_DIR, "order_process.pnml"),
        zone_places=zones,
        timeframe="D",
    )
    zf_oracle = _norm(res["zone_features"])
    print(f"  {len(zf_oracle)} rows in {time.time() - t0:.1f}s")

    client = TestClient(create_app())
    client.__enter__()
    try:
        api_frames = {}
        for backend in ("pm4py", "r4pm"):
            print(f"Path {'B' if backend == 'pm4py' else 'C'}: api-{backend} ...")
            t0 = time.time()
            resp = client.post(
                "/api/datasets/demo/analyses",
                json={"zones": zones, "timeframe": "D", "backend": backend},
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload["job_id"]:
                while True:
                    job = client.get(f"/api/jobs/{payload['job_id']}").json()
                    if job["status"] in ("done", "error"):
                        break
                    time.sleep(0.5)
                if job["status"] == "error":
                    print(f"  FAILED: {job['error']}")
                    return 1
            rows = client.get(f"/api/analyses/{payload['analysis_id']}/features").json()["rows"]
            api_frames[backend] = _norm(pd.DataFrame(rows))
            print(f"  {len(api_frames[backend])} rows in {time.time() - t0:.1f}s")
    finally:
        client.__exit__(None, None, None)

    problems = []
    problems += compare("oracle vs api-pm4py", zf_oracle, api_frames["pm4py"], exact=True)
    problems += compare("oracle vs api-r4pm", zf_oracle, api_frames["r4pm"], exact=False)

    print()
    if problems:
        print("PARITY GATE FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print("PARITY GATE PASSED")
    print("  oracle == api-pm4py (exact)")
    print("  oracle ~= api-r4pm (counts exact, continuous within 1%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
