"""Native batches retain exact identities, case order, and all-or-error results."""

import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from pm4py.objects.log.obj import EventLog

from process_model import alignment_backends as backends
from process_model.replay import token_place_table_from_alignments
from tests.test_alignment_backends import _load_demo


class TestBatchRegistryCleanup(unittest.TestCase):
    def test_projection_is_removed_when_native_search_raises(self):
        imported_paths = []

        def import_item(kind, path):
            self.assertEqual(kind, "EventLogActivityProjection")
            imported_paths.append(path)
            projection = json.loads(Path(path).read_text())
            self.assertEqual(projection["activities"], ["A", "B"])
            self.assertEqual(projection["traces"], [[[0, 1], 3], [[], 1]])
            return "projection-id"

        engine = SimpleNamespace(
            import_item=import_item,
            call_binding=Mock(side_effect=RuntimeError("search failed")),
            remove_item=Mock(),
        )
        with self.assertRaisesRegex(RuntimeError, "search failed"):
            backends._align_variant_batch(engine, "batch", {}, {("A", "B"): 3, (): 1}, {})
        engine.remove_item.assert_called_once_with("projection-id")
        self.assertFalse(Path(imported_paths[0]).exists())


class TestNativeAlignmentBatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import r4pm
        except ImportError:
            raise unittest.SkipTest("r4pm not installed")
        cls.engine = r4pm
        cls.bundle, _ = _load_demo()
        variants = {}
        for trace in cls.bundle.log:
            variants.setdefault(backends._trace_labels(trace), trace)
            if len(variants) == 5:
                break
        traces = list(variants.values())
        cls.log = EventLog([traces[0], traces[4], traces[1], traces[0], traces[3], traces[2], traces[4]])

    def align(self, progress=None):
        b = self.bundle
        return backends.compute_alignments_r4pm(self.log, b.net, b.im, b.fm, progress)

    def test_multibatch_matches_serial_alignments_and_replay_in_case_order(self):
        b = self.bundle
        converted = backends._net_to_r4pm(b.net, b.im, b.fm)
        r_net, names, labels_by_id = converted
        bindings = {entry["name"]: entry["id"] for entry in self.engine.list_bindings()}
        options = backends._cost_options()
        empty = json.loads(self.engine.call_binding(bindings["align_empty_trace"], json.dumps({"net": r_net, "options": options})))
        serial = []
        for trace in self.log:
            labels = backends._trace_labels(trace)
            result = json.loads(self.engine.call_binding(bindings["align_trace"], json.dumps({"net": r_net, "trace": labels, "options": options})))
            serial.append(backends._adapt_alignment(result, labels, labels_by_id, names, empty["cost"]))

        progress = Mock()
        native_batch = backends._align_variant_batch

        def reversed_rows(*args):
            # Consumers must not rely on native variant order.
            return list(reversed(native_batch(*args)))

        with patch.object(backends, "_net_to_r4pm", return_value=converted), patch.object(backends, "_VARIANT_BATCH_SIZE", 2), patch.object(backends, "_align_variant_batch", side_effect=reversed_rows):
            batched = self.align(progress)
        self.assertEqual(batched, serial)
        self.assertEqual([call.args for call in progress.call_args_list], [(0, 5), (2, 5), (4, 5), (5, 5)])
        pd.testing.assert_frame_equal(
            token_place_table_from_alignments(self.log, b.net, b.im, b.fm, aligned=batched),
            token_place_table_from_alignments(self.log, b.net, b.im, b.fm, aligned=serial),
        )

    def test_missing_duplicate_unknown_and_wrong_frequency_variants_are_rejected(self):
        native_batch = backends._align_variant_batch
        mutations = {
            "missing": lambda rows: rows[:-1],
            "duplicate": lambda rows: rows + [rows[0]],
            "unknown": lambda rows: [dict(rows[0], activities=["unknown"])] + rows[1:],
            "frequency": lambda rows: [dict(rows[0], frequency=999)] + rows[1:],
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), patch.object(backends, "_align_variant_batch", side_effect=lambda *args: mutate(native_batch(*args))):
                with self.assertRaisesRegex(ValueError, "incomplete|unexpected|duplicate"):
                    self.align()

    def test_per_variant_search_error_is_not_silently_skipped(self):
        row = {"activities": list(backends._trace_labels(self.log[0])), "frequency": 2, "result": {"Err": {"SearchError": "LimitReached"}}}
        with patch.object(backends, "_align_variant_batch", return_value=[row]):
            with self.assertRaisesRegex(ValueError, "LimitReached"):
                self.align()

    def test_empty_log_does_not_import_a_projection(self):
        b = self.bundle
        with patch.object(backends, "_align_variant_batch") as batch:
            self.assertEqual(backends.compute_alignments_r4pm([], b.net, b.im, b.fm), [])
            batch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
