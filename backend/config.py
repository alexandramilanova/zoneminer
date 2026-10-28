"""Backend configuration: storage locations and runtime flags.

All state lives under ``var/`` at the repo root (gitignored), overridable via
ZONE_ANALYTICS_DATA_DIR — the Docker image sets this to a writable path and
pre-bakes the demo dataset's computed artifacts there.
"""

import os
from contextvars import ContextVar

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

# Local installations retain their workspace. Anonymous mode is an explicit
# runtime choice; it never exposes the local store to HTTP clients.
MODE = os.environ.get("ZONE_ANALYTICS_MODE", "local")
if MODE not in {"local", "anonymous"}:
    raise ValueError("ZONE_ANALYTICS_MODE must be local or anonymous")
WORKSPACE: ContextVar[str | None] = ContextVar("workspace", default=None)


def data_dir() -> str:
    return WORKSPACE.get() or os.environ.get("ZONE_ANALYTICS_WORKSPACE") or DATA_DIR


def limit(name: str, default: int) -> int:
    value = int(os.environ.get("ZONE_ANALYTICS_" + name, str(default)))
    if value <= 0:
        raise ValueError(f"ZONE_ANALYTICS_{name} must be positive")
    return value


def optional_limit(name: str, default: int = 0) -> int | None:
    """Zero means no application policy cap; physical resources still apply."""
    value = int(os.environ.get("ZONE_ANALYTICS_" + name, str(default)))
    if value < 0:
        raise ValueError(f"ZONE_ANALYTICS_{name} must be nonnegative")
    return value or None


def worker_memory_mb() -> int | None:
    """Share the detected container RAM budget, reserving 25% for the API/OS.

    An explicit positive WORKER_MEMORY_MB overrides this; zero disables the
    per-child allocation limit. Local mode does not use isolated workers.
    """
    if "ZONE_ANALYTICS_WORKER_MEMORY_MB" in os.environ:
        return optional_limit("WORKER_MEMORY_MB")
    from pathlib import Path
    capacities = []
    try:
        capacities.append(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (ValueError, OSError):
        pass
    for filename in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            capacity = int(Path(filename).read_text().strip())
            if 0 < capacity < 2 ** 60:
                capacities.append(capacity)
        except (OSError, ValueError):
            pass
    if not capacities:
        return None
    return max(1, int(min(capacities) * .75 / limit("MAX_PROCESSES", 1) / (1024 * 1024)))


def ensure_dirs() -> None:
    root = data_dir()
    for d in (root, os.path.join(root, "datasets"), os.path.join(root, "analyses")):
        os.makedirs(d, exist_ok=True)
