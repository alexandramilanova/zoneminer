"""Precompute the demo analysis into the backend store.

Run at Docker build time (and usable locally) so the local demo loads from cached results:
the first visitor hits a cache, not an alignment computation.

Analysis IDs are content-addressed over the *inputs* (dataset, zones,
timeframe, backend), not the code version — so after an upgrade that adds
metrics, a store from an older version still holds a feature table without
the new columns. This script detects that (persisted columns missing a
canonical metric) and recomputes; pass --force to recompute unconditionally.

    python tools/precompute_demo.py [--force]
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics.metrics.schema import CANONICAL_METRICS
from backend import config, store
from backend.main import demo_zone_places, register_demo_dataset
from backend.runner import run_analysis_job


def _artifacts_current(analysis_id: str) -> bool:
    """Present AND carrying every canonical metric column."""
    if not store.has_artifacts(analysis_id):
        return False
    zf = store.load_frame(analysis_id, "zone_features")
    if zf is None:
        return False
    missing = [s.name for s in CANONICAL_METRICS if s.name not in zf.columns]
    if missing:
        print(f"  stale artifacts (missing {len(missing)} newer metric columns) — recomputing")
        return False
    return True


def main(force: bool = False) -> None:
    config.ensure_dirs()
    register_demo_dataset()
    zones = demo_zone_places()
    backend = config.DEFAULT_ALIGNMENT_BACKEND
    for dataset_id in (config.DEMO_DATASET_ID, config.SHOWCASE_DATASET_ID):
        if store.get_dataset(dataset_id) is None:
            print(f"Dataset {dataset_id} not bundled — skipped.")
            continue
        analysis_id = store.analysis_id_for(dataset_id, zones, "D", backend)
        if not force and _artifacts_current(analysis_id):
            print(f"{dataset_id}: analysis {analysis_id} already precomputed.")
            continue
        run_analysis_job(None, analysis_id, dataset_id, zones, "D", backend)
        print(f"{dataset_id}: precomputed analysis {analysis_id} ({backend}) into {config.DATA_DIR}")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
