"""Bounded private cache for deterministic views of immutable analysis frames."""
from functools import lru_cache
import hashlib
import inspect
import json
import os
from pathlib import Path
import tempfile

from backend import config, store

_VIEWS = {"get_changepoints", "get_selection_changepoints", "selected_trends",
          "get_dependencies", "get_dependency_pair"}
_MAX_BYTES = 32 * 1024 * 1024
_MAX_ENTRY = 8 * 1024 * 1024
_MAX_FILES = 64


@lru_cache(maxsize=1)
def _implementation():
    digest = hashlib.sha256()
    for folder in ("analytics", "backend", "services", "process_model"):
        for path in sorted((Path(config.REPO_ROOT) / folder).rglob("*.py")):
            digest.update(str(path.relative_to(config.REPO_ROOT)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def location(function, args, kwargs):
    if function.__name__ not in _VIEWS:
        return None
    bound = inspect.signature(function).bind(*args, **kwargs)
    bound.apply_defaults()
    try:
        frame = Path(store.analysis_dir(bound.arguments["analysis_id"])) / "zone_features.parquet"
    except ValueError:
        return None
    if not frame.exists():
        return None
    stat = frame.stat()
    specification = (_implementation(), function.__name__, stat.st_mtime_ns, stat.st_size,
                     {key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
                      for key, value in bound.arguments.items()})
    key = hashlib.sha256(json.dumps(specification, sort_keys=True).encode()).hexdigest()
    return Path(config.data_dir()) / "view-cache" / (key + ".json")


def read(path):
    if path is None:
        return None
    try:
        value = json.loads(path.read_text())
        os.utime(path, None)
        return value
    except (OSError, ValueError):
        return None


def write(path, value):
    if path is None:
        return
    try:
        encoded = json.dumps(value, allow_nan=False).encode()
        if len(encoded) > _MAX_ENTRY:
            return
        path.parent.mkdir(exist_ok=True)
        # Only the server writes these files. Session deletion/expiry removes
        # them with the rest of that workspace; none are shared across visitors.
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(encoded)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        entries = []
        for candidate in path.parent.glob("*.json"):
            try:
                stat = candidate.stat()
                entries.append((stat.st_mtime_ns, candidate, stat.st_size))
            except OSError:
                continue
        total = sum(size for _, _, size in entries)
        count = len(entries)
        for _, candidate, size in sorted(entries):
            if total <= _MAX_BYTES and count <= _MAX_FILES:
                break
            candidate.unlink(missing_ok=True)
            total -= size
            count -= 1
    except (OSError, TypeError, ValueError):
        # A disposable cache must never turn a valid computation into an error.
        return
