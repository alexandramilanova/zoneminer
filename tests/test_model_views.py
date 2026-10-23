"""Optional helper views must not reject or silently replace an uploaded model."""
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import datasets
from process_model.io import bpmn_from_petri_net, try_process_tree_from_petri_net, process_tree_unavailable_reason
from services.pipeline import load_model_inputs


class ModelViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.csv = b'case_id,concept:name,time:timestamp\nc1,A,2024-01-01T00:00:00Z\nc1,B,2024-01-01T01:00:00Z\n'
        pnml = next((root / 'data/demo').glob('*.pnml')).read_bytes()
        cls.bundle = load_model_inputs(cls.csv, '.csv', pnml)

    def client(self, bundle):
        app = FastAPI()
        app.include_router(datasets.router)
        mock = patch.object(datasets, 'get_bundle', return_value=bundle)
        mock.start()
        self.addCleanup(mock.stop)
        return TestClient(app)

    def test_non_workflow_showcase_retains_petri_net_and_has_direct_bpmn(self):
        b = self.bundle
        self.assertIsNone(b.process_tree)
        self.assertIsNotNone(b.bpmn_graph)
        self.assertIn('not a workflow net', b.process_tree_notice)
        self.assertIsNone(b.model_notice)
        self.assertEqual(len(b.net.places), 28)
        client = self.client(b)
        model = client.get('/api/datasets/demo/model').json()
        self.assertFalse(model['process_tree_available'])
        self.assertTrue(model['bpmn_available'])
        self.assertIn('Zone definition and analysis', model['process_tree_reason'])
        response = client.get('/api/datasets/demo/bpmn.xml')
        self.assertEqual(response.status_code, 200, response.text)
        xml = ET.fromstring(response.content)
        self.assertTrue(xml.tag.endswith('definitions'))
        task_names = {n.attrib.get('name') for n in xml.iter() if n.tag.endswith('task')}
        self.assertTrue({t.label for t in b.net.transitions if t.label}.issubset(task_names))
        tree = client.get('/api/datasets/demo/process-tree.svg')
        self.assertEqual(tree.status_code, 404)
        self.assertNotIn('PM4Py error', tree.json()['detail'])

    def test_discovery_still_has_both_views(self):
        b = load_model_inputs(self.csv, '.csv', None)
        self.assertIsNotNone(b.process_tree)
        self.assertIsNotNone(b.bpmn_graph)
        client = self.client(b)
        self.assertEqual(client.get('/api/datasets/x/process-tree.svg').status_code, 200)
        self.assertEqual(client.get('/api/datasets/x/bpmn.xml').status_code, 200)

    def test_direct_bpmn_does_not_mutate_net_or_markings(self):
        b = self.bundle
        before = (set(b.net.places), set(b.net.transitions), set(b.net.arcs), dict(b.im), dict(b.fm))
        bpmn_from_petri_net(b.net, b.im, b.fm)
        self.assertEqual(before, (set(b.net.places), set(b.net.transitions), set(b.net.arcs), dict(b.im), dict(b.fm)))

    def test_multiplicities_are_not_silently_lost_in_helpers(self):
        b = load_model_inputs(self.csv, '.csv', None)
        b.im[next(iter(b.im))] = 2
        with self.assertRaisesRegex(ValueError, 'weighted arcs or multiple'):
            bpmn_from_petri_net(b.net, b.im, b.fm)
        tree, error = try_process_tree_from_petri_net(b.net, b.im, b.fm)
        self.assertIsNone(tree)
        self.assertIn('multiple start/end tokens', process_tree_unavailable_reason(error))

    def test_helper_conversion_failure_does_not_break_analysis_inputs(self):
        root = Path(__file__).resolve().parents[1]
        pnml = next((root / 'data/demo').glob('*.pnml')).read_bytes()
        with patch('services.pipeline.bpmn_from_petri_net', side_effect=RuntimeError('internal diagnostic')):
            b = load_model_inputs(self.csv, '.csv', pnml)
        self.assertIsNotNone(b.net)
        self.assertIsNone(b.bpmn_graph)
        self.assertIn('Use the Petri net', b.bpmn_notice)
        self.assertNotIn('internal diagnostic', b.bpmn_notice)
