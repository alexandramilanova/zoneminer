"""In-process background jobs with staged progress and SSE streaming.

One job = one expensive pipeline run (parse -> align -> replay -> features ->
persist). Jobs run on daemon threads; progress events accumulate per job and
are streamed to clients via server-sent events. This is deliberately simple —
a single-process local application does not need a distributed queue.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
import uuid
from contextvars import copy_context
from dataclasses import dataclass, field
from typing import Callable, Optional
from fastapi import HTTPException
from backend import config


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued | running | done | error
    error: Optional[str] = None
    result: Optional[dict] = None
    events: list[dict] = field(default_factory=list)
    cond: threading.Condition = field(default_factory=threading.Condition)
    workspace: str = ""
    finished_at: float | None = None

    def emit(self, stage: str, status: str, detail: str = "") -> None:
        with self.cond:
            if len(self.events) >= config.limit("JOB_EVENTS", 200):
                return
            self.events.append(
                {
                    "stage": stage,
                    "status": status,
                    "detail": detail,
                    "ts": time.time(),
                }
            )
            self.cond.notify_all()

    def finish(self, result: Optional[dict] = None) -> None:
        with self.cond:
            self.status = "done"
            self.finished_at = time.time()
            self.result = result
            self.events.append({"stage": "__done__", "status": "done", "detail": "", "ts": time.time()})
            self.cond.notify_all()

    def fail(self, error: str) -> None:
        with self.cond:
            self.status = "error"
            self.finished_at = time.time()
            self.error = error
            self.events.append({"stage": "__done__", "status": "error", "detail": error, "ts": time.time()})
            self.cond.notify_all()


class JobManager:
    def __init__(self, max_workers=None) -> None:
        self._slots = threading.Semaphore(max_workers or max(1, int(os.environ.get("ZONE_ANALYTICS_MAX_JOBS", "1"))))
        self._active = {}
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, fn: Callable[[Job], Optional[dict]], *, key=None, on_submit=None) -> Job:
        workspace = config.data_dir()
        key = (workspace, key) if key is not None else None
        with self._lock:
            self._prune()
            if key is not None and key in self._active:
                return self._active[key]
            pending = [j for j in self._jobs.values() if j.status in ("queued", "running")]
            if len(pending) >= config.limit("MAX_PENDING_JOBS", 16) or sum(j.workspace == workspace for j in pending) >= config.limit("SESSION_JOBS", 2):
                raise HTTPException(429, "The analysis queue is full. Please try again shortly.", headers={"Retry-After": "5"})
            job = Job(id=uuid.uuid4().hex[:12], kind=kind, workspace=workspace)
            if on_submit:
                on_submit()
            self._jobs[job.id] = job
            if key is not None:
                self._active[key] = job

        def runner() -> None:
            job.emit("queue", "running", "Waiting for a compute slot")
            with self._slots:
                job.status = "running"
                job.emit("queue", "done", "Compute slot acquired")
                try:
                    result = fn(job)
                    job.finish(result)
                except Exception as exc:  # surfaced to the client, never swallowed
                    job.fail(str(exc.detail) if isinstance(exc, HTTPException) else f"{type(exc).__name__}: {exc}")
                    traceback.print_exc()
                finally:
                    if key is not None:
                        with self._lock:
                            self._active.pop(key, None)

        context = copy_context()
        threading.Thread(target=lambda: context.run(runner), daemon=True).start()
        return job

    def _prune(self):
        cutoff = time.time() - config.limit("JOB_TTL_SECONDS", 3600)
        finished = sorted((j for j in self._jobs.values() if j.finished_at is not None), key=lambda j: j.finished_at)
        maximum = config.limit("JOB_HISTORY", 200)
        for index, job in enumerate(finished):
            if job.finished_at < cutoff or index < len(finished) - maximum:
                self._jobs.pop(job.id, None)

    def has_pending(self, workspace):
        with self._lock:
            return any(j.workspace == workspace and j.status in ("queued", "running") for j in self._jobs.values())

    def forget_workspace(self, workspace):
        with self._lock:
            self._jobs = {k: j for k, j in self._jobs.items() if j.workspace != workspace}

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            self._prune()
            job = self._jobs.get(job_id)
            return job if job and job.workspace == config.data_dir() else None

    def sse_events(self, job: Job, poll_timeout: float = 15.0):
        """Generator yielding SSE-formatted progress events until terminal."""
        import json as _json

        idx = 0
        while True:
            with job.cond:
                while idx >= len(job.events) and job.status in ("queued", "running"):
                    job.cond.wait(timeout=poll_timeout)
                    break  # emit keep-alive on timeout
                new_events = job.events[idx:]
                idx = len(job.events)
                status = job.status
            if not new_events:
                if status in ("done", "error"):
                    return
                yield ": keep-alive\n\n"
                continue
            for ev in new_events:
                yield f"data: {_json.dumps(ev)}\n\n"
            if status in ("done", "error"):
                return


manager = JobManager()
