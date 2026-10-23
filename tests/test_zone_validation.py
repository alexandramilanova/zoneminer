"""Independent zone fixtures and API rejection checks; no analytical baselines."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from pm4py.objects.petri_net.obj import PetriNet
from pm4py.objects.petri_net.utils import petri_utils

from backend.main import create_app
from process_model.zone_validation import validate_zones


def fixture_net():
    net = PetriNet('zone-validation-fixture')
    places = {name: PetriNet.Place(name) for name in ('a', 'b', 'c', 'd')}
    net.places.update(places.values())
    # Two independent connected pairs; {a, c} is disconnected.
    for source, target in [('a', 'b'), ('c', 'd')]:
        transition = PetriNet.Transition(source + target, source + target)
        net.transitions.add(transition)
        petri_utils.add_arc_from_to(places[source], transition, net)
        petri_utils.add_arc_from_to(transition, places[target], net)
    return net


class TestZoneValidation(unittest.TestCase):
    def setUp(self):
        self.net = fixture_net()

    def validate(self, drafts, **kwargs):
        return validate_zones(drafts, ['a', 'b', 'c', 'd'], self.net, **kwargs)

    def test_valid_connected_zone(self):
        self.assertTrue(self.validate([('First', ['a', 'b'])])['zone_config_valid'])

    def test_multiple_valid_zones_and_name_trimming(self):
        result = self.validate([(' First ', ['a', 'b']), ('Second', ['c', 'd'])])
        self.assertTrue(result['zone_config_valid'])
        self.assertEqual(set(result['zone_places']), {'First', 'Second'})

    def test_empty_system_rejected_even_if_empty_contents_allowed(self):
        self.assertFalse(self.validate([], require_non_empty=False)['zone_config_valid'])

    def test_unknown_singleton_is_not_a_connected_valid_zone(self):
        # Even a stale supplied place_names list cannot authorize a place absent
        # from the normative model.
        result = validate_zones([('Ghost zone', ['ghost'])], ['a', 'ghost'], self.net)
        self.assertFalse(result['zone_config_valid'])
        self.assertIn('Ghost zone', ' '.join(result['errors']))
        self.assertIn('ghost', ' '.join(result['errors']))

    def test_unknown_place_in_otherwise_connected_zone(self):
        self.assertFalse(self.validate([('First', ['a', 'b', 'ghost'])])['zone_config_valid'])

    def test_blank_and_duplicate_names(self):
        for drafts in [[(' ', ['a'])], [('Same', ['a']), (' Same ', ['b'])]]:
            with self.subTest(drafts=drafts):
                self.assertFalse(self.validate(drafts)['zone_config_valid'])

    def test_existing_structural_constraints(self):
        for drafts in [[('Empty', [])], [('Broken', ['a', 'c'])],
                       [('First', ['a']), ('Second', ['a'])], [('Repeated', ['a', 'a'])]]:
            with self.subTest(drafts=drafts):
                self.assertFalse(self.validate(drafts)['zone_config_valid'])


class TestZoneValidationApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        bundle = SimpleNamespace(net=fixture_net())
        for target, value in [('backend.routers.datasets.get_bundle', bundle),
                              ('backend.routers.analyses.get_bundle', bundle),
                              ('backend.routers.analyses.store.get_dataset', {'id': 'uploaded'})]:
            p = patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def test_mapping_and_lossless_drafts_both_validate(self):
        for zones in [{'First': ['a', 'b'], 'Second': ['c', 'd']},
                      [{'name': 'First', 'places': ['a', 'b']}, {'name': 'Second', 'places': ['c', 'd']}]]:
            response = self.client.post('/api/datasets/uploaded/zones/validate', json={'zones': zones})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['valid'])

    def test_invalid_configuration_cannot_create_analysis_or_job(self):
        invalid = [{}, [], {'Ghost zone': ['ghost']}, {' ': ['a']},
                   {'Same': ['a'], ' Same ': ['b']},
                   [{'name': 'Same', 'places': ['a']}, {'name': 'Same', 'places': ['b']}],
                   [{'name': ' ', 'places': ['a']}], {'Broken': ['a', 'c']}]
        with patch('backend.routers.analyses.manager.submit') as submit:
            for zones in invalid:
                with self.subTest(zones=zones):
                    checked = self.client.post('/api/datasets/uploaded/zones/validate', json={'zones': zones})
                    self.assertFalse(checked.json()['valid'])
                    response = self.client.post('/api/datasets/uploaded/analyses', json={'zones': zones})
                    self.assertEqual(response.status_code, 422)
                    self.assertTrue(response.json()['detail']['errors'])
            submit.assert_not_called()
