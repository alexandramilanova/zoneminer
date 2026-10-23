"""Independent import/index oracles and cache/job integration tests.

No expected analytical baseline is rewritten by these scalability changes.
"""
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import numpy as np
import pandas as pd
from pm4py.objects.log.obj import Event, EventLog, Trace

from process_model.io import load_csv_log, load_xes_log, normalize_event_order
from process_model.time_index import EventTimeIndex, IntervalTimeIndex


class ImportOrderTests(unittest.TestCase):
    def test_xes_and_csv_use_stable_chronological_order(self):
        xes = '''<?xml version="1.0"?><log><trace><string key="concept:name" value="c"/>
        <event><string key="concept:name" value="late"/><date key="time:timestamp" value="2024-01-02T00:00:00Z"/></event>
        <event><string key="concept:name" value="first"/><date key="time:timestamp" value="2024-01-01T00:00:00Z"/></event>
        <event><string key="concept:name" value="tie"/><date key="time:timestamp" value="2024-01-01T00:00:00Z"/></event>
        </trace></log>'''
        csv = 'case_id,concept:name,time:timestamp\nc,late,2024-01-02T00:00:00Z\nc,first,2024-01-01T00:00:00Z\nc,tie,2024-01-01T00:00:00Z\n'
        with tempfile.TemporaryDirectory() as directory:
            for suffix, data, loader in [('xes', xes, load_xes_log), ('csv', csv, load_csv_log)]:
                path = os.path.join(directory, 'log.' + suffix)
                with open(path, 'w') as stream:
                    stream.write(data)
                log = loader(path)
                self.assertEqual([event['concept:name'] for event in log[0]], ['first', 'tie', 'late'])
                self.assertEqual(log[0].attributes['concept:name'], 'c')
                self.assertEqual(log.attributes['zone_analytics:import_order']['reordered_cases'], 1)
                self.assertEqual(log.attributes['zone_analytics:import_order']['tied_adjacent_events'], 1)

    def test_values_and_attributes_are_preserved(self):
        late = Event({'time:timestamp': pd.Timestamp('2024-01-02', tz='UTC'), 'custom': 2})
        early = Event({'time:timestamp': pd.Timestamp('2024-01-01', tz='UTC'), 'custom': 1})
        trace = Trace([late, early], attributes={'concept:name': 'c', 'other': 'value'})
        log = normalize_event_order(EventLog([trace]))
        self.assertIs(log[0][0], early)
        self.assertIs(log[0][1], late)
        self.assertEqual(trace.attributes['other'], 'value')
        self.assertEqual(late['time:timestamp'], pd.Timestamp('2024-01-02', tz='UTC'))
        report = log.attributes['zone_analytics:import_order']
        self.assertEqual((report['reordered_cases'], report['moved_events']), (1, 2))

    def test_missing_timestamp_is_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, 'every event requires a valid timestamp'):
            normalize_event_order(EventLog([Trace([Event({})], attributes={'concept:name': 'bad'})]))


class WindowIndexTests(unittest.TestCase):
    def test_fast_fifo_statistics_match_independent_pair_definition(self):
        from process_model.features import _order_inversion_stats
        rng = np.random.default_rng(7)
        for n in (0, 1, 2, 30, 300, 4001):
            entries = rng.integers(0, 100, n)
            exits = entries + rng.integers(0, 100, n)
            actual = _order_inversion_stats(entries, exits)
            if n < 2:
                self.assertTrue(all(np.isnan(value) for value in actual))
                continue
            if n > 4000:
                selected = np.argsort(entries, kind='stable')[np.linspace(0, n - 1, 4000).astype(int)]
                entries, exits = entries[selected], exits[selected]
            pairs = (entries[:, None] < entries[None, :]) & (exits[:, None] > exits[None, :])
            depth = pairs.sum(axis=0)
            expected = (float(pairs.sum()) / (len(entries) * (len(entries) - 1) // 2),
                        float(pairs.any(axis=1).mean()),
                        float(depth[depth > 0].mean()) if (depth > 0).any() else np.nan)
            np.testing.assert_equal(actual, expected)

    def test_random_intervals_match_independent_direct_integral(self):
        rng = np.random.default_rng(42)
        origin = pd.Timestamp('2024-01-01', tz='UTC')
        starts = pd.Series([origin + pd.Timedelta(seconds=int(n)) for n in rng.integers(0, 100, 200)])
        ends = pd.Series([start + pd.Timedelta(seconds=int(n)) for start, n in zip(starts, rng.integers(0, 50, 200))])
        ends.iloc[::7] = pd.NaT
        index = IntervalTimeIndex(starts, ends)
        for left in range(0, 160, 10):
            w0, w1 = origin + pd.Timedelta(seconds=left), origin + pd.Timedelta(seconds=left + 10)
            expected_present = [i for i, (s, e) in enumerate(zip(starts, ends)) if s < w1 and (pd.isna(e) or e >= w1)]
            expected_area = sum(max(0.0, (min(e, w1) - max(s, w0)).total_seconds())
                                if pd.notna(e) else max(0.0, (w1 - max(s, w0)).total_seconds())
                                for s, e in zip(starts, ends))
            self.assertEqual(index.present_before(w1), expected_present)
            self.assertAlmostEqual(index.occupied_seconds(w0, w1), expected_area)
            self.assertEqual(index.starts.between(w0, w1).tolist(), np.flatnonzero((starts >= w0) & (starts < w1)).tolist())

    def test_boundaries_zero_duration_and_missing_end(self):
        starts = pd.to_datetime(['2024-01-01', '2024-01-02', '2024-01-02'])
        ends = pd.to_datetime(['2024-01-02', '2024-01-02', None])
        index = IntervalTimeIndex(starts, ends)
        self.assertEqual(index.present_before('2024-01-02'), [0])
        self.assertEqual(index.present_before('2024-01-03'), [2])
        self.assertEqual(index.occupied_seconds('2024-01-02', '2024-01-03'), 86400)
        self.assertEqual(EventTimeIndex(ends).between('2024-01-02', '2024-01-03').tolist(), [0, 1])

    def test_large_area_does_not_overflow_epoch_nanosecond_sums(self):
        starts = pd.to_datetime(['2024-01-01'] * 1000)
        ends = pd.to_datetime([None] * 1000)
        index = IntervalTimeIndex(starts, ends)
        self.assertEqual(index.occupied_seconds('2024-01-01', '2025-01-01'), 1000 * 366 * 86400)


class ReplayCacheTests(unittest.TestCase):
    def test_persistent_reuse_backend_isolation_and_partial_recovery(self):
        from backend import replay_cache, store
        tokens = pd.DataFrame({'produced_ts': pd.to_datetime(['2024-01-01']), 'consumed_ts': pd.to_datetime(['2024-01-02'])})
        calls = []
        def compute():
            calls.append(True)
            return tokens.copy(), pd.DataFrame({'cost': [0]}), pd.DataFrame({'move_type': ['sync']})
        with tempfile.TemporaryDirectory() as directory, patch.object(store, 'analysis_dir', side_effect=lambda key: os.path.join(directory, key)):
            first = replay_cache.get_replay_tables('d', 'r4pm', compute)
            events = []
            second = replay_cache.get_replay_tables('d', 'r4pm', compute, progress=lambda *event: events.append(event))
            pd.testing.assert_frame_equal(first[0], second[0].drop(columns=['time_spent']), check_dtype=False)
            self.assertEqual(len(calls), 1)
            self.assertEqual([event[0] for event in events], ['align', 'replay', 'conformance'])
            replay_cache.get_replay_tables('d', 'pm4py', compute)
            self.assertEqual(len(calls), 2)
            # An incomplete cache must be recomputed, never accepted as a hit.
            for root, dirs, files in os.walk(directory):
                if 'alignment_moves.parquet' in files:
                    os.unlink(os.path.join(root, 'alignment_moves.parquet'))
            replay_cache.get_replay_tables('d', 'r4pm', compute)
            self.assertEqual(len(calls), 3)

    def test_concurrent_replay_requests_compute_once(self):
        from backend import replay_cache, store
        calls = []
        def compute():
            calls.append(True)
            return (pd.DataFrame({'produced_ts': pd.to_datetime(['2024-01-01']), 'consumed_ts': pd.to_datetime([None])}),
                    pd.DataFrame({'cost': [0]}), pd.DataFrame({'move_type': ['sync']}))
        with tempfile.TemporaryDirectory() as directory, patch.object(store, 'analysis_dir', side_effect=lambda key: os.path.join(directory, key)):
            with ThreadPoolExecutor(max_workers=3) as pool:
                results = list(pool.map(lambda _: replay_cache.get_replay_tables('same', 'r4pm', compute), range(3)))
            self.assertEqual(len(calls), 1)
            self.assertEqual([len(result[0]) for result in results], [1, 1, 1])


class ModelIdentityTests(unittest.TestCase):
    def test_discovered_identities_survive_eviction_and_remain_discovered(self):
        from backend import runner, store
        csv = b'case_id,concept:name,time:timestamp\nc,A,2024-01-01T00:00:00Z\nc,B,2024-01-02T00:00:00Z\n'
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'log.csv')
            with open(path, 'wb') as stream:
                stream.write(csv)
            with patch.object(store, 'dataset_file_paths', return_value=(path, None)), patch.object(store, 'dataset_dir', return_value=directory):
                first = runner.get_bundle('identity-test')
                runner._bundle_cache.pop('identity-test')
                second = runner.get_bundle('identity-test')
                self.assertEqual({p.name for p in first.net.places}, {p.name for p in second.net.places})
                self.assertEqual({t.name for t in first.net.transitions}, {t.name for t in second.net.transitions})
                self.assertEqual(second.model_source, 'discovered_from_log')
                self.assertEqual(dict((p.name, n) for p, n in first.fm.items()), dict((p.name, n) for p, n in second.fm.items()))
                runner._bundle_cache.pop('identity-test')


class JobQueueTests(unittest.TestCase):
    def test_duplicate_requests_share_job_and_queued_jobs_are_bounded(self):
        from backend.jobs import JobManager
        manager = JobManager(max_workers=1)
        started, release, second_started = threading.Event(), threading.Event(), threading.Event()
        submitted = []
        def work(job):
            started.set()
            if not release.wait(5):
                raise RuntimeError('test timed out')
        first = manager.submit('analysis', work, key='one', on_submit=lambda: submitted.append(1))
        self.assertTrue(started.wait(5))
        same = manager.submit('analysis', work, key='one', on_submit=lambda: submitted.append(2))
        second = manager.submit('analysis', lambda job: second_started.set(), key='two')
        try:
            self.assertIs(first, same)
            self.assertEqual(submitted, [1])
            self.assertEqual(second.status, 'queued')
            self.assertFalse(second_started.is_set())
        finally:
            release.set()
        self.assertTrue(second_started.wait(5))
        list(manager.sse_events(second, poll_timeout=0.1))
        self.assertEqual(first.status, 'done')
        self.assertEqual(second.status, 'done')
