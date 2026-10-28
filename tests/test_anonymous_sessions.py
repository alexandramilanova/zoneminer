"""Privacy boundaries and lifecycle using real independent browser cookies."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import config, store
from backend.main import create_app

CSV = b"case_id,concept:name,time:timestamp\nc,A,2024-01-01T00:00:00Z\nc,B,2024-01-02T00:00:00Z\n"


class AnonymousSessionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(config, "DATA_DIR", self.tmp.name), patch.object(config, "MODE", "anonymous"),
                        patch.dict(os.environ, {"ZONE_ANALYTICS_COOKIE_SECURE": "0"})]
        for p in self.patches:
            p.start()
        self.app = create_app()
        self.a = TestClient(self.app)
        self.b = TestClient(self.app)

    def tearDown(self):
        self.a.close()
        self.b.close()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_private_upload_and_analysis_cannot_be_read_by_another_visitor(self):
        uploaded = self.a.post("/api/datasets", files={"log": ("private.csv", CSV)})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        identifier = uploaded.json()["id"]
        self.assertEqual(self.a.get(f"/api/datasets/{identifier}").status_code, 200)
        self.assertEqual(self.b.get(f"/api/datasets/{identifier}").status_code, 404)
        self.assertNotIn(identifier, [row["id"] for row in self.b.get("/api/datasets").json()])
        # Same input bytes do not reveal that another visitor uploaded them.
        again = self.b.post("/api/datasets", files={"log": ("private.csv", CSV)})
        self.assertEqual(again.status_code, 200, again.text)
        self.assertFalse(again.json().get("deduplicated", False))
        token = self.a.cookies.get("zoneminer_session")
        root = self.app.state.sessions.leases[token].root
        context = config.WORKSPACE.set(root)
        try:
            store.upsert_analysis("private-result", identifier, {}, "D", "r4pm", "done")
            store.save_frame("private-result", "secret", __import__("pandas").DataFrame({"secret": [42]}))
        finally:
            config.WORKSPACE.reset(context)
        self.assertEqual(self.a.get("/api/analyses/private-result").status_code, 200)
        self.assertEqual(self.b.get("/api/analyses/private-result").status_code, 404)
        self.assertEqual(self.b.get("/api/analyses/private-result/metrics").status_code, 404)

    def test_expiry_deletes_files_and_restart_recovers_expiry(self):
        response = self.a.get("/api/session")
        self.assertEqual(response.json()["mode"], "anonymous")
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=Strict", response.headers["set-cookie"])
        token = self.a.cookies.get("zoneminer_session")
        lease = self.app.state.sessions.leases[token]
        root = Path(lease.root)
        (root / "private.txt").write_text("private")
        from backend.sessions import Sessions
        restored = Sessions()
        self.assertEqual(restored.leases[token].expires, lease.expires)
        lease.expires = time.time() - 1
        self.assertEqual(self.a.get("/api/session").status_code, 410)
        self.app.state.sessions.cleanup()
        self.assertFalse(root.exists())
        self.assertNotIn(token, self.app.state.sessions.leases)

    def test_cross_origin_and_actual_body_limits(self):
        self.assertEqual(self.a.post("/api/datasets", headers={"Origin": "https://other.example"}, files={"log": ("a.csv", CSV)}).status_code, 403)
        with patch.dict(os.environ, {"ZONE_ANALYTICS_REQUEST_MB": "1"}):
            # Streaming without Content-Length exercises actual byte counting.
            response = self.a.post("/api/datasets", content=iter([b"x" * (700 * 1024)] * 2),
                                   headers={"Content-Type": "multipart/form-data; boundary=test"})
            self.assertEqual(response.status_code, 413, response.text)

    def test_explicit_delete_and_capacity(self):
        self.a.get("/api/session")
        token = self.a.cookies.get("zoneminer_session")
        root = Path(self.app.state.sessions.leases[token].root)
        with patch.dict(os.environ, {"ZONE_ANALYTICS_MAX_SESSIONS": "1"}):
            self.assertEqual(self.b.get("/api/session").status_code, 503)
        self.assertEqual(self.a.delete("/api/session").status_code, 200)
        self.app.state.sessions.cleanup()
        self.assertFalse(root.exists())
        self.assertEqual(self.a.get("/api/session").status_code, 200)

    def test_xml_entities_are_rejected(self):
        response = self.a.post("/api/datasets", files={"log": ("bad.xes", b'<!DOCTYPE log [<!ENTITY x SYSTEM "file:///etc/passwd">]><log/>')})
        self.assertEqual(response.status_code, 400, response.text)

    def test_csv_above_old_50_mib_boundary_is_accepted_without_a_policy_cap(self):
        # Blank CSV lines increase file bytes without increasing the scientific
        # workload. This independently exercises transport/storage size handling.
        large = CSV + b"\n" * (51 * 1024 * 1024)
        response = self.a.post("/api/datasets", files={"log": ("large.csv", large)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(self.a.get("/api/session").json()["upload_mb"])
        with patch.dict(os.environ, {"ZONE_ANALYTICS_UPLOAD_MB": "1"}):
            response = self.a.post("/api/datasets", files={"log": ("large.csv", large)})
            self.assertEqual(response.status_code, 413, response.text)

    def test_real_analysis_and_job_progress_are_session_scoped(self):
        uploaded = self.a.post("/api/datasets", files={"log": ("small.csv", CSV)})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        identifier = uploaded.json()["id"]
        graph = self.a.get(f"/api/datasets/{identifier}/model").json()
        internal = next(p for p in graph["places"] if p not in graph["initial_marking"] and p not in graph["final_marking"])
        response = self.a.post(f"/api/datasets/{identifier}/analyses", json={"zones": {"Work": [internal]}, "timeframe": "D"})
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["job_id"]
        self.assertEqual(self.b.get(f"/api/jobs/{job_id}").status_code, 404)
        self.assertEqual(self.b.get(f"/api/jobs/{job_id}/events").status_code, 404)
        deadline = time.time() + 60
        while time.time() < deadline:
            job = self.a.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"done", "error"}:
                break
            time.sleep(0.2)
        self.assertEqual(job["status"], "done", job)
        result = self.a.get(f'/api/analyses/{response.json()["analysis_id"]}/features')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertGreater(result.json()["row_count"], 0)


class TimestampConversionTests(unittest.TestCase):
    def test_utc_nanosecond_precision_and_missing_values(self):
        import pandas as pd
        from process_model.features import _utc_nanoseconds
        series = pd.Series(pd.to_datetime(["2024-03-31T03:00:00.123456789+02:00", None], utc=True))
        result = _utc_nanoseconds(series)
        self.assertEqual(result[0], pd.Timestamp("2024-03-31T01:00:00.123456789Z").value)
        self.assertEqual(result[1], pd.NaT.value)


class ResourceBoundaryTests(unittest.TestCase):
    def test_input_count_caps_are_optional_and_explicit_caps_still_work(self):
        from types import SimpleNamespace
        from backend.isolation import parse_dataset
        from fastapi import HTTPException
        bundle = SimpleNamespace(log=[range(100001)], net=SimpleNamespace(places=range(2001), transitions=[]))
        with patch("backend.runner.get_bundle", return_value=bundle):
            self.assertEqual(parse_dataset("large")["events"], 100001)
            with patch.dict(os.environ, {"ZONE_ANALYTICS_MAX_EVENTS": "100000"}):
                with self.assertRaises(HTTPException) as caught:
                    parse_dataset("large")
                self.assertEqual(caught.exception.status_code, 413)

    def test_memory_budget_uses_container_capacity_and_can_be_overridden(self):
        env = {key: value for key, value in os.environ.items() if key not in {"ZONE_ANALYTICS_WORKER_MEMORY_MB", "ZONE_ANALYTICS_MAX_PROCESSES"}}
        env["ZONE_ANALYTICS_MAX_PROCESSES"] = "1"
        with patch.dict(os.environ, env, clear=True), patch("os.sysconf", side_effect=lambda key: 4096 if key == "SC_PAGE_SIZE" else 16 * 1024 ** 3 // 4096), patch("pathlib.Path.read_text", return_value=str(8 * 1024 ** 3)):
            self.assertEqual(config.worker_memory_mb(), 6144)
            with patch.dict(os.environ, {"ZONE_ANALYTICS_WORKER_MEMORY_MB": "4096"}):
                self.assertEqual(config.worker_memory_mb(), 4096)
            with patch.dict(os.environ, {"ZONE_ANALYTICS_WORKER_MEMORY_MB": "0"}):
                self.assertIsNone(config.worker_memory_mb())

    def test_analysis_can_omit_request_time_cap_but_still_expires_with_session(self):
        import json
        from backend.isolation import run
        from fastapi import HTTPException
        with tempfile.TemporaryDirectory() as tmp:
            context = config.WORKSPACE.set(tmp)
            try:
                with patch.dict(os.environ, {"ZONE_ANALYTICS_REQUEST_TIMEOUT_SECONDS": "1"}):
                    self.assertIsNone(run("time", "sleep", 1.1, timeout=None))
                (Path(tmp) / "session.json").write_text(json.dumps({"expires": time.time() + 0.1}))
                with self.assertRaises(HTTPException) as caught:
                    run("time", "sleep", 10, timeout=None)
                self.assertEqual(caught.exception.status_code, 410)
            finally:
                config.WORKSPACE.reset(context)

    def test_native_allocation_failure_is_distinct_from_an_unexplained_crash(self):
        import signal
        from backend.isolation import worker_failure
        memory = worker_failure(-signal.SIGABRT, b"memory allocation of 1048576 bytes failed")
        self.assertEqual(memory.status_code, 503)
        self.assertIn("memory", memory.detail)
        crash = worker_failure(-signal.SIGSEGV, b"private diagnostic content")
        self.assertEqual(crash.status_code, 500)
        self.assertNotIn("memory", crash.detail)
        self.assertNotIn("private diagnostic", crash.detail)

    def test_timeout_terminates_worker_and_releases_capacity(self):
        from backend.isolation import run
        from fastapi import HTTPException
        with tempfile.TemporaryDirectory() as tmp:
            context = config.WORKSPACE.set(tmp)
            try:
                started = time.monotonic()
                with self.assertRaises(HTTPException) as caught:
                    run("time", "sleep", 10, timeout=0.1)
                self.assertEqual(caught.exception.status_code, 504)
                self.assertLess(time.monotonic() - started, 5)
                self.assertEqual(run("builtins", "pow", 2, 10), 1024)
                with patch.dict(os.environ, {"RAYON_NUM_THREADS": "64", "ZONE_ANALYTICS_NATIVE_THREADS": "1"}):
                    self.assertEqual(run("os", "getenv", "RAYON_NUM_THREADS"), "1")
                self.assertEqual(list(Path(tmp).glob("task-*")), [])
            finally:
                config.WORKSPACE.reset(context)

    def test_queue_capacity_ownership_and_bounded_history(self):
        import threading
        from fastapi import HTTPException
        from backend.jobs import JobManager
        release = threading.Event()
        manager = JobManager(max_workers=1)
        context = config.WORKSPACE.set("visitor-a")
        try:
            with patch.dict(os.environ, {"ZONE_ANALYTICS_MAX_PENDING_JOBS": "1", "ZONE_ANALYTICS_JOB_EVENTS": "3"}):
                job = manager.submit("test", lambda j: release.wait(5), key="one")
                self.assertIs(manager.submit("test", lambda j: None, key="one"), job)
                with self.assertRaises(HTTPException) as caught:
                    manager.submit("test", lambda j: None, key="two")
                self.assertEqual(caught.exception.status_code, 429)
                for _ in range(10):
                    job.emit("test", "running")
                self.assertLessEqual(len(job.events), 3)
                other = config.WORKSPACE.set("visitor-b")
                try:
                    self.assertIsNone(manager.get(job.id))
                finally:
                    config.WORKSPACE.reset(other)
                release.set()
                deadline = time.time() + 5
                while job.status in {"queued", "running"} and time.time() < deadline:
                    time.sleep(0.01)
                self.assertEqual(job.status, "done")
                self.assertTrue(any("__done__" in event for event in manager.sse_events(job)))
                job.finished_at = 0
                self.assertIsNone(manager.get(job.id))
        finally:
            release.set()
            config.WORKSPACE.reset(context)
