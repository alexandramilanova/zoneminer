"""Backend configuration: storage locations and runtime flags.

All state lives under ``var/`` at the repo root (gitignored), overridable via
ZONE_ANALYTICS_DATA_DIR — the Docker image sets this to a writable path and
pre-bakes the demo dataset's computed artifacts there.
"""

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.environ.get("ZONE_ANALYTICS_DATA_DIR", os.path.join(REPO_ROOT, "var"))
DATASETS_DIR = os.path.join(DATA_DIR, "datasets")
ANALYSES_DIR = os.path.join(DATA_DIR, "analyses")
DB_PATH = os.path.join(DATA_DIR, "store.duckdb")

DEMO_DIR = os.path.join(REPO_ROOT, "data", "demo")
DEMO_DATASET_ID = "demo"
SHOWCASE_DATASET_ID = "showcase"

# Bundled example scenarios (tools/build_examples.py): one folder per
# scenario with log.csv, model.pnml, zones.json, meta.json. The folder name
# is the dataset id.
EXAMPLES_DIR = os.path.join(REPO_ROOT, "data", "examples")

# Default alignment backend for API-triggered analyses. r4pm is the fast path;
# pm4py remains available as the reference implementation (parity gate).
DEFAULT_ALIGNMENT_BACKEND = os.environ.get("ZONE_ANALYTICS_ALIGNMENT_BACKEND", "r4pm")

FRONTEND_DIST = os.path.join(REPO_ROOT, "frontend", "dist")


def ensure_dirs() -> None:
    for d in (DATA_DIR, DATASETS_DIR, ANALYSES_DIR):
        os.makedirs(d, exist_ok=True)
