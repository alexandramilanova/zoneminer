"""Discovery options must identify immutable models and preserve old analyses."""
import os
import tempfile
import unittest
from collections import OrderedDict
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import config, store, runner
from backend.main import create_app


def rare_path_log():
    rows = ['case_id,concept:name,time:timestamp']
    for case in range(31):
        activities = ['B', 'C', 'D', 'A'] if case == 30 else ['A', 'B', 'C', 'D']
        for index, activity in enumerate(activities):
            rows.append(f'{case},{activity},2024-01-01T{index + 1:02d}:00:00Z')
    return '\n'.join(rows).encode()


class DiscoveryControlsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.dict(os.environ, {'ZONE_ANALYTICS_DATA_DIR': root}))
        self.stack.enter_context(patch.object(config, 'DATA_DIR', root))
        self.stack.enter_context(patch.object(store, '_con', None))
        self.stack.enter_context(patch.object(runner, '_bundle_cache', OrderedDict()))
        self.client = self.stack.enter_context(TestClient(create_app()))
        self.addCleanup(self.close_connection)

    def close_connection(self):
        if store._con is not None:
            store._con.close()
            store._con = None

    def upload(self, threshold=0):
        response = self.client.post('/api/datasets', files={'log': ('rare.csv', rare_path_log())},
                                    data={'noise_threshold': str(threshold)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']

    def test_filtering_changes_model_without_changing_source_or_old_identity(self):
        original = self.upload()
        before = self.client.get(f'/api/datasets/{original}/model').json()
        self.assertEqual(set(before['activity_labels']), {'A', 'B', 'C', 'D'})
        result = self.client.post(f'/api/datasets/{original}/discover', json={'noise_threshold': .2})
        self.assertEqual(result.status_code, 200, result.text)
        filtered = result.json()['id']
        self.assertNotEqual(original, filtered)
        after = self.client.get(f'/api/datasets/{filtered}/model').json()
        self.assertEqual(after['discovery_noise_threshold'], .2)
        self.assertLess(len(after['places']), len(before['places']))
        self.assertEqual(before['event_count'], after['event_count'])
        self.assertEqual(before['case_count'], after['case_count'])
        self.assertEqual(self.client.get(f'/api/datasets/{original}/model').json(), before)
        runner._bundle_cache.clear()
        self.assertEqual(self.client.get(f'/api/datasets/{filtered}/model').json(), after)
        repeated = self.client.post(f'/api/datasets/{original}/discover', json={'noise_threshold': .2}).json()
        self.assertTrue(repeated['deduplicated'])
        self.assertEqual(repeated['id'], filtered)
        self.assertEqual(self.upload(.2), filtered)
        zero = self.client.post(f'/api/datasets/{filtered}/discover', json={'noise_threshold': 0}).json()
        self.assertEqual(zero['id'], original)

    def test_supplied_models_are_not_rediscovered_and_invalid_thresholds_fail(self):
        response = self.client.post('/api/datasets/showcase/discover', json={'noise_threshold': .2})
        self.assertEqual(response.status_code, 400)
        for threshold in [-.1, 1.1, 'nan']:
            self.assertEqual(self.client.post('/api/datasets', files={'log': ('a.csv', rare_path_log())},
                             data={'noise_threshold': str(threshold)}).status_code, 422)
        self.assertEqual(self.client.post('/api/datasets/missing/discover', json={'noise_threshold': .2}).status_code, 404)
