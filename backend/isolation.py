"""Bounded, killable computation for anonymous HTTP workspaces.

The pickle files below are created by this server, never accepted from clients.
Each child gets a fresh interpreter and exactly one workspace. Local mode keeps
the existing direct execution path.
"""
from __future__ import annotations

import functools
from collections import deque
import inspect
import logging
import os
import json
from pathlib import Path
import pickle
import signal
import subprocess
import sys
import tempfile
import threading
import time

from fastapi import HTTPException

from backend import config

_slots = threading.BoundedSemaphore(config.limit("MAX_PROCESSES", 1))
_DEFAULT_TIMEOUT = object()


def worker_failure(returncode: int, stderr: bytes) -> HTTPException:
    """Classify evidence from a dead child without exposing its stderr/data."""
    message = stderr.lower()
    if any(marker in message for marker in (b"memory allocation", b"memoryerror", b"bad_alloc", b"out of memory", b"cannot allocate memory")):
        budget = config.worker_memory_mb()
        description = f"worker budget: {budget} MB" if budget else "server RAM exhausted"
        return HTTPException(503, f"Analysis exceeded available memory ({description}). The log was uploaded successfully, but this computation needs more RAM. The local version can use your machine's resources.")
    if returncode == -signal.SIGXFSZ:
        return HTTPException(507, "Computation exceeded the temporary file-size limit.")
    return HTTPException(500, "Computation stopped unexpectedly. Please retry; the server could not determine the cause.")


def run(module: str, name: str, *args, timeout=_DEFAULT_TIMEOUT, progress=None, cache_path=None, **kwargs):
    # Admission is bounded by the HTTP/session and job pools. Once admitted,
    # wait for capacity instead of failing companion views after 30 seconds.
    # Expired/deleted sessions must also leave the queue before spawning a child.
    root = config.data_dir()
    lease = Path(root) / "session.json"
    wait_seconds = config.optional_limit("COMPUTE_QUEUE_WAIT_SECONDS")
    wait_until = time.monotonic() + wait_seconds if wait_seconds is not None else None
    while True:
        if lease.exists() and json.loads(lease.read_text())["expires"] <= time.time():
            raise HTTPException(410, "This temporary session expired or was deleted.")
        if _slots.acquire(timeout=0.25):
            break
        if wait_until is not None and time.monotonic() >= wait_until:
            raise HTTPException(429, "Compute capacity is busy. Please try again shortly.", headers={"Retry-After": "5"})
    try:
        from backend import view_cache
        cached = view_cache.read(cache_path)
        if cached is not None:
            return cached
        root = config.data_dir()
        config.ensure_dirs()
        with tempfile.TemporaryDirectory(prefix="task-", dir=root) as directory:
            request = Path(directory) / "request.bin"
            result = Path(directory) / "result.bin"
            events = Path(directory) / "events.jsonl"
            request.write_bytes(pickle.dumps((module, name, args, kwargs)))
            env = {**os.environ, "ZONE_ANALYTICS_WORKSPACE": root,
                   "ZONE_ANALYTICS_WORKER": "1", "ZONE_ANALYTICS_PROGRESS": str(events),
                   "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                   "RAYON_NUM_THREADS": str(config.limit("NATIVE_THREADS", 1))}
            seconds = config.optional_limit("REQUEST_TIMEOUT_SECONDS") if timeout is _DEFAULT_TIMEOUT else timeout
            lease = Path(root) / "session.json"
            if lease.exists():
                remaining = json.loads(lease.read_text())["expires"] - time.time()
                seconds = min(seconds, remaining) if seconds is not None else remaining
                if seconds <= 0:
                    raise HTTPException(410, "This temporary session has expired.")
            child = subprocess.Popen([sys.executable, "-m", "backend.worker", str(request), str(result)],
                                     env=env, cwd=config.REPO_ROOT, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE, start_new_session=True)
            # Native libraries can abort rather than raise MemoryError. Drain a
            # bounded tail in memory for classification; never log event values,
            # private filesystem paths, or raw native diagnostics.
            diagnostic = deque(maxlen=8)
            def drain_stderr():
                while chunk := child.stderr.read(1024):
                    diagnostic.append(chunk)
            reader = threading.Thread(target=drain_stderr, daemon=True)
            reader.start()
            try:
                deadline = time.monotonic() + seconds if seconds is not None else None
                seen = 0
                next_storage_check = time.monotonic()
                while True:
                    if lease.exists() and json.loads(lease.read_text())["expires"] <= time.time():
                        raise HTTPException(410, "This temporary session expired or was deleted.")
                    if time.monotonic() >= next_storage_check:
                        from backend.sessions import check_storage
                        check_storage()
                        next_storage_check = time.monotonic() + 1
                    if progress and events.exists():
                        lines = events.read_text().splitlines()
                        for line in lines[seen:]:
                            try:
                                event = json.loads(line)
                            except ValueError:
                                break  # last write may still be in progress
                            progress.emit(**event)
                            seen += 1
                    try:
                        child.wait(timeout=min(0.25, max(0, deadline - time.monotonic())) if deadline is not None else 0.25)
                        break
                    except subprocess.TimeoutExpired:
                        if deadline is not None and time.monotonic() >= deadline:
                            raise
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                if lease.exists() and json.loads(lease.read_text())["expires"] <= time.time():
                    raise HTTPException(410, "This temporary session expired or was deleted.")
                raise HTTPException(504, "Computation exceeded the time limit. Try a smaller dataset.")
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                reader.join(timeout=2)
                if not reader.is_alive():
                    child.stderr.close()
            if child.returncode or not result.exists():
                failure = worker_failure(child.returncode, b"".join(diagnostic))
                logging.getLogger(__name__).warning("Isolated computation stopped: operation=%s exit=%s status=%s", name, child.returncode, failure.status_code)
                raise failure
            ok, payload = pickle.loads(result.read_bytes())
            if not ok:
                code, detail = payload
                raise HTTPException(code, detail)
            view_cache.write(cache_path, payload)
            return payload
    finally:
        _slots.release()


def endpoint(function):
    """Run synchronous read/analysis endpoints in a bounded child in anonymous mode."""
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        if config.data_dir() != config.DATA_DIR and not os.environ.get("ZONE_ANALYTICS_WORKER"):
            from backend import view_cache
            path = view_cache.location(function, args, kwargs)
            cached = view_cache.read(path)
            if cached is not None:
                return cached
            return run(function.__module__, function.__name__, *args, cache_path=path, **kwargs)
        return function(*args, **kwargs)
    # FastAPI resolves annotations in the wrapper's module. Resolve postponed
    # annotations against the original endpoint module before wrapping it.
    wrapped.__signature__ = inspect.signature(function, eval_str=True)
    return wrapped


def parse_dataset(dataset_id: str):
    from backend.runner import get_bundle
    bundle = get_bundle(dataset_id)
    cases = len(bundle.log)
    events = sum(map(len, bundle.log))
    case_limit = config.optional_limit("MAX_CASES")
    event_limit = config.optional_limit("MAX_EVENTS")
    node_limit = config.optional_limit("MAX_MODEL_NODES")
    if (case_limit is not None and cases > case_limit) or (event_limit is not None and events > event_limit):
        raise HTTPException(413, "Event log exceeds the case or event limit.")
    if node_limit is not None and len(bundle.net.places) + len(bundle.net.transitions) > node_limit:
        raise HTTPException(413, "Process model exceeds the node limit.")
    return {"cases": cases, "events": events}


def validate_analysis(dataset_id, body):
    from backend.runner import get_bundle
    from process_model.zone_validation import validate_zones
    bundle = get_bundle(dataset_id)
    return validate_zones(zone_inputs=body.zone_inputs(), place_names=sorted(p.name for p in bundle.net.places),
                          net=bundle.net, require_non_empty=True, allow_unassigned_places=True,
                          require_connected=True)


def analyse(analysis_id, dataset_id, zones, timeframe, backend):
    from backend.runner import run_analysis_job
    class Progress:
        count = 0
        def emit(self, stage, status, detail=""):
            if self.count >= 200:
                return
            with open(os.environ["ZONE_ANALYTICS_PROGRESS"], "a") as output:
                output.write(json.dumps(dict(stage=stage, status=status, detail=detail[:1000])) + "\n")
            self.count += 1
    return run_analysis_job(Progress(), analysis_id, dataset_id, zones, timeframe, backend)


def analysis_job(job, analysis_id, dataset_id, zones, timeframe, backend):
    from backend import store
    try:
        return run("backend.isolation", "analyse", analysis_id, dataset_id, zones, timeframe, backend,
                   timeout=config.optional_limit("ANALYSIS_TIMEOUT_SECONDS"), progress=job)
    except Exception:
        store.upsert_analysis(analysis_id, dataset_id, zones, timeframe, backend, "error",
                              "Computation stopped or exceeded a resource limit")
        raise
