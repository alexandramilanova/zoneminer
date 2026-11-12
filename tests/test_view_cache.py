import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

from backend import config, isolation, view_cache


class ViewCacheTests(unittest.TestCase):
    def test_private_parameter_and_frame_versions_and_bounded_cache(self):
        def selected_trends(analysis_id, body=None):
            pass
        with tempfile.TemporaryDirectory() as root:
            context = config.WORKSPACE.set(root)
            try:
                folder = Path(root) / "analyses" / "analysis"
                folder.mkdir(parents=True)
                frame = folder / "zone_features.parquet"
                frame.write_bytes(b"first")
                path = view_cache.location(selected_trends, ("analysis",), {})
                view_cache.write(path, {"rows": [42]})
                self.assertEqual(view_cache.read(path), {"rows": [42]})
                self.assertNotEqual(path, view_cache.location(selected_trends, ("analysis", {"metric": "other"}), {}))
                frame.write_bytes(b"changed frame")
                self.assertIsNone(view_cache.read(view_cache.location(selected_trends, ("analysis",), {})))
                other = config.WORKSPACE.set(root + "/other")
                try:
                    self.assertIsNone(view_cache.location(selected_trends, ("analysis",), {}))
                finally:
                    config.WORKSPACE.reset(other)
                path.write_text("incomplete JSON")
                self.assertIsNone(view_cache.read(path))
                with patch.object(view_cache, "_MAX_FILES", 2):
                    for i in range(5):
                        view_cache.write(path.parent / f"{i}.json", {"i": i})
                    self.assertEqual(len(list(path.parent.glob("*.json"))), 2)
            finally:
                config.WORKSPACE.reset(context)

    def test_queued_request_rechecks_completed_cache_before_spawning(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "views" / "cached.json"
            view_cache.write(path, {"rows": [7]})
            with patch.object(isolation.subprocess, "Popen") as child:
                self.assertEqual(isolation.run("unused", "unused", cache_path=path), {"rows": [7]})
                child.assert_not_called()

    def test_queue_retries_capacity_and_respects_expiry_and_optional_wait_cap(self):
        from fastapi import HTTPException
        with tempfile.TemporaryDirectory() as root:
            context = config.WORKSPACE.set(root)
            try:
                slots = Mock()
                slots.acquire.side_effect = [False, False, True]
                with patch.object(isolation, "_slots", slots):
                    self.assertEqual(isolation.run("builtins", "pow", 2, 3), 8)
                    self.assertEqual(slots.acquire.call_count, 3)
                    slots.release.assert_called_once()
                (Path(root) / "session.json").write_text(json.dumps({"expires": time.time() - 1}))
                with self.assertRaises(HTTPException) as caught:
                    isolation.run("builtins", "pow", 2, 3)
                self.assertEqual(caught.exception.status_code, 410)
                (Path(root) / "session.json").unlink()
                with patch.dict("os.environ", {"ZONE_ANALYTICS_COMPUTE_QUEUE_WAIT_SECONDS": "1"}), \
                     patch.object(isolation, "_slots", Mock(acquire=Mock(return_value=False))), \
                     patch.object(isolation.time, "monotonic", side_effect=[0, 2]):
                    with self.assertRaises(HTTPException) as caught:
                        isolation.run("builtins", "pow", 2, 3)
                    self.assertEqual(caught.exception.status_code, 429)
            finally:
                config.WORKSPACE.reset(context)

    def test_local_views_reuse_results_and_invalidate_on_parameters_or_frame_change(self):
        calls = []
        def selected_trends(analysis_id, body=None):
            calls.append(body)
            return {"rows": [len(calls)]}
        with tempfile.TemporaryDirectory() as root, patch.object(config, "DATA_DIR", root), \
                patch.object(config, "data_dir", return_value=root):
            directory = Path(root) / "analyses" / "local"
            directory.mkdir(parents=True)
            frame = directory / "zone_features.parquet"
            frame.write_bytes(b"first")
            wrapped = isolation.endpoint(selected_trends)
            with patch.object(isolation, "run", side_effect=AssertionError("Local cache started a worker")):
                self.assertEqual(wrapped("local"), {"rows": [1]})
                self.assertEqual(wrapped("local"), {"rows": [1]})
                self.assertEqual(wrapped("local", {"metric": "other"}), {"rows": [2]})
                frame.write_bytes(b"different content")
                self.assertEqual(wrapped("local"), {"rows": [3]})
            self.assertEqual(calls, [None, {"metric": "other"}, None])
