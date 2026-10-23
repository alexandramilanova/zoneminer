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
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued | running | done | error
    error: Optional[str] = None
    result: Optional[dict] = None
    events: list[dict] = field(default_factory=list)
    cond: threading.Condition = field(default_factory=threading.Condition)

    def emit(self, stage: str, status: str, detail: str = "") -> None:
        with self.cond:
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
            self.result = result
            self.events.append({"stage": "__done__", "status": "done", "detail": "", "ts": time.time()})
            self.cond.notify_all()

    def fail(self, error: str) -> None:
        with self.cond:
            self.status = "error"
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
        with self._lock:
            if key is not None and key in self._active:
                return self._active[key]
            job = Job(id=uuid.uuid4().hex[:12], kind=kind)
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
                    job.fail(f"{type(exc).__name__}: {exc}")
                    traceback.print_exc()
                finally:
                    if key is not None:
                        with self._lock:
                            self._active.pop(key, None)

        threading.Thread(target=runner, daemon=True).start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

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
                yield ": keep-alive\n\n"
                continue
            for ev in new_events:
                yield f"data: {_json.dumps(ev)}\n\n"
            if status in ("done", "error"):
                return


manager = JobManager()
