"""Independent scientific fixtures for prediction-only immediate routing."""
import json
import unittest

import pandas as pd
from pm4py.objects.log.obj import EventLog, Trace, Event
from pm4py.objects.petri_net.obj import PetriNet, Marking
from pm4py.objects.petri_net.utils.petri_utils import add_arc_from_to

from analytics.forecasting import causal_features, prepare_experiment, run_experiment
from process_model.prefix import prefix_tokens, prediction_history, PrefixUnavailable


def chain(weight=1):
    net = PetriNet('forced-routing')
    places = {name: PetriNet.Place(name) for name in ('start', 'before', 'middle', 'zone', 'end')}
    transitions = {name: PetriNet.Transition(name, None if name.startswith('tau') else name)
                   for name in ('A', 'tau1', 'tau2', 'B')}
    net.places.update(places.values())
    net.transitions.update(transitions.values())
    for source, target in [('start','A'), ('A','before'), ('before','tau1'), ('tau1','middle'),
                           ('middle','tau2'), ('tau2','zone'), ('zone','B'), ('B','end')]:
        add_arc_from_to(places.get(source, transitions.get(source)), places.get(target, transitions.get(target)), net, weight=weight)
    return net, Marking({places['start']: weight}), places, transitions


def log(events):
    return EventLog([Trace([Event({'concept:name': label, 'time:timestamp': pd.Timestamp(time)})
                           for time, label in events], attributes={'concept:name': 'c'})])


class ImmediateRoutingTests(unittest.TestCase):
    def test_initial_routing_records_exact_identity_provenance_and_availability(self):
        net, _, places, _ = chain()
        first = PetriNet.Place('initial'); route = PetriNet.Transition('tau_initial',None)
        net.places.add(first); net.transitions.add(route)
        add_arc_from_to(first,route,net); add_arc_from_to(route,places['start'],net)
        _, events = prediction_history(log([('2024-01-01T12:00Z','A')]), net, Marking({first:1}), '2024-01-02T00:00Z')
        self.assertEqual(events.transition_id.tolist(), ['tau_initial','A','tau1','tau2'])
        self.assertEqual(events.inferred.tolist(), [True,False,True,True])
        self.assertTrue((events.timestamp == pd.Timestamp('2024-01-01T12:00Z')).all())
        self.assertTrue((events.available_at == events.timestamp).all())
        self.assertEqual(events.source.tolist(), ['immediate_silent_routing','observed_event','immediate_silent_routing','immediate_silent_routing'])

    def test_concurrent_split_and_join_waits_for_all_inputs(self):
        net = PetriNet('split-join')
        places = {n: PetriNet.Place(n) for n in ('start','fork','left','right','ldone','rdone','end')}
        transitions = {n: PetriNet.Transition(n,None if n.startswith('tau') else n) for n in ('Start','L','R','tauSplit','tauJoin')}
        net.places.update(places.values()); net.transitions.update(transitions.values())
        for source, target in [('start','Start'),('Start','fork'),('fork','tauSplit'),('tauSplit','left'),('tauSplit','right'),
                               ('left','L'),('L','ldone'),('right','R'),('R','rdone'),('ldone','tauJoin'),('rdone','tauJoin'),('tauJoin','end')]:
            add_arc_from_to(places.get(source,transitions.get(source)),places.get(target,transitions.get(target)),net)
        source = log([('2024-01-01T09:00Z','Start'),('2024-01-01T09:30Z','L'),('2024-01-01T10:30Z','R')])
        im = Marking({places['start']:1})
        early, early_events = prediction_history(source,net,im,'2024-01-01T10:00Z')
        self.assertFalse((early_events.transition_id == 'tauJoin').any())
        self.assertEqual(set(early.loc[early.consumed_ts.isna(),'place']), {'right','ldone'})
        late, late_events = prediction_history(source,net,im,'2024-01-01T11:00Z')
        self.assertEqual(set(late.loc[late.consumed_ts.isna(),'place']), {'end'})
        self.assertEqual(late_events.iloc[-1].transition_id, 'tauJoin')
        self.assertEqual(late_events.iloc[-1].timestamp, pd.Timestamp('2024-01-01T10:30Z'))
        f = causal_features(source,net,im,{'Z':['left','right','ldone','rdone']},'h','2024-01-01T11:00Z')
        self.assertEqual(f.token_present_end.tolist(), [2,0])
        self.assertEqual(f.case_present_end.tolist(), [1,0])
        self.assertEqual(f.token_avg_present_window.tolist(), [2,1])

    def test_weighted_chain_routes_at_observation_time_and_does_not_finish_case(self):
        net, im, _, _ = chain(2)
        source = log([('2024-01-01T12:00Z', 'A'), ('2024-01-03T12:00Z', 'B')])
        tokens = prefix_tokens(source, net, im, '2024-01-02T00:00Z')
        for place in ('before', 'middle'):
            rows = tokens[tokens.place == place]
            self.assertEqual(len(rows), 2)
            self.assertTrue((rows.produced_ts == pd.Timestamp('2024-01-01T12:00Z')).all())
            self.assertTrue((rows.produced_ts == rows.consumed_ts).all())
        self.assertEqual(len(tokens[(tokens.place == 'zone') & tokens.consumed_ts.isna()]), 2)
        self.assertFalse((tokens.place == 'end').any())
        self.assertEqual([e['concept:name'] for e in source[0]], ['A', 'B'])
        features = causal_features(source, net, im, {'Z':['zone']}, 'D', '2024-01-04T00:00Z')
        self.assertEqual(features.token_present_end.tolist(), [2, 2, 0])
        self.assertEqual(features.token_netflow.cumsum().tolist(), [2, 2, 0])
        self.assertEqual(features.case_present_end.tolist(), [1, 1, 0])
        self.assertEqual(features.token_avg_duration_completed.iloc[-1], 48 * 3600)
        audit = features.attrs['prediction_reconstruction']
        json.dumps(audit, allow_nan=False)
        self.assertTrue(all(event['activity'] is None for event in audit['inferred_event_preview']))

    def test_future_changes_do_not_change_routed_history_or_features(self):
        net, im, _, _ = chain()
        first = log([('2024-01-01T12:00Z','A'), ('2024-01-03T12:00Z','B')])
        second = log([('2024-01-01T12:00Z','A'), ('2024-02-01T12:00Z','unexpected')])
        pd.testing.assert_frame_equal(prefix_tokens(first, net, im, '2024-01-03T00:00Z'),
                                      prefix_tokens(second, net, im, '2024-01-03T00:00Z'))
        kwargs = dict(net=net, im=im, zones={'Z':['before','middle','zone']}, timeframe='D', observed_through='2024-01-03T00:00Z')
        pd.testing.assert_frame_equal(causal_features(first, **kwargs), causal_features(second, **kwargs))

    def test_boundary_does_not_fire_observed_or_inferred_events_early(self):
        net, im, _, _ = chain()
        source = log([('2024-01-02T00:00Z','A')])
        self.assertTrue(prefix_tokens(source, net, im, '2024-01-02T00:00Z').empty)
        rows = prefix_tokens(source, net, im, '2024-01-03T00:00Z')
        self.assertEqual(len(rows[rows.place == 'zone']), 1)
        self.assertEqual(rows[rows.place == 'zone'].produced_ts.iloc[0], pd.Timestamp('2024-01-02T00:00Z'))

    def test_silent_visible_choice_is_not_resolved_using_future_event(self):
        net, im, places, _ = chain()
        qc = PetriNet.Transition('QC','QC'); net.transitions.add(qc)
        add_arc_from_to(places['before'], qc, net)
        add_arc_from_to(qc, places['end'], net)
        for future in ('QC','B'):
            with self.assertRaisesRegex(PrefixUnavailable, 'competing.*QC'):
                prefix_tokens(log([('2024-01-01T12:00Z','A'),('2024-01-03T12:00Z',future)]), net, im, '2024-01-02T00:00Z')

    def test_silent_choice_and_infinite_silent_loop_are_rejected(self):
        net, im, places, _ = chain()
        alternative = PetriNet.Transition('tauAlternative', None); net.transitions.add(alternative)
        add_arc_from_to(places['before'], alternative, net)
        add_arc_from_to(alternative, places['end'], net)
        with self.assertRaisesRegex(PrefixUnavailable, 'competing'):
            prefix_tokens(log([('2024-01-01T12:00Z','A')]), net, im, '2024-01-02T00:00Z')
        loop = PetriNet('loop'); p = PetriNet.Place('p'); t = PetriNet.Transition('loop_tau', None)
        loop.places.add(p); loop.transitions.add(t)
        add_arc_from_to(p,t,loop); add_arc_from_to(t,p,loop)
        with self.assertRaisesRegex(PrefixUnavailable, 'nonterminating'):
            prefix_tokens(log([('2024-01-01T12:00Z','X')]), loop, Marking({p:1}), '2024-01-02T00:00Z')

    def test_visible_deviations_are_not_inserted_or_deleted(self):
        net, im, _, _ = chain()
        for events in [[('2024-01-01T12:00Z','B')], [('2024-01-01T12:00Z','A'),('2024-01-01T13:00Z','extra')]]:
            source = log(events)
            with self.assertRaisesRegex(PrefixUnavailable, 'visible deviation.*no repair'):
                prefix_tokens(source, net, im, '2024-01-02T00:00Z')
            self.assertEqual(len(source[0]), len(events))

    def test_potentially_disabled_competitor_is_explicitly_outside_profile(self):
        net, im, places, _ = chain()
        never = PetriNet.Place('not_yet_observed'); net.places.add(never)
        competitor = PetriNet.Transition('conditional_QC','QC'); net.transitions.add(competitor)
        add_arc_from_to(places['before'],competitor,net); add_arc_from_to(never,competitor,net)
        with self.assertRaisesRegex(PrefixUnavailable, 'competing transitions conditional_QC'):
            prefix_tokens(log([('2024-01-01T12:00Z','A')]),net,im,'2024-01-02T00:00Z')

    def test_prediction_routing_does_not_change_descriptive_replay(self):
        from services import compute_alignment_tables
        net, im, places, _ = chain()
        source = log([('2024-01-01T12:00Z','A'),('2024-01-01T13:00Z','B')])
        before = compute_alignment_tables(source,net,im,Marking({places['end']:1}),backend='pm4py')
        tokens, _ = prediction_history(source,net,im,'2024-01-02T00:00Z')
        after = compute_alignment_tables(source,net,im,Marking({places['end']:1}),backend='pm4py')
        for original,current in zip(before,after):
            pd.testing.assert_frame_equal(original,current,check_exact=True)
        self.assertEqual(tokens.loc[tokens.place == 'zone','produced_ts'].iloc[0],pd.Timestamp('2024-01-01T12:00Z'))
        self.assertEqual(before[0].loc[before[0].place == 'zone','produced_ts'].iloc[0],pd.Timestamp('2024-01-01T12:00:00.000002Z'))

    def test_all_three_forecasts_are_identical_when_only_future_events_change(self):
        net, im, _, _ = chain()
        original, changed = EventLog(), EventLog()
        for day in range(50):
            for n in range(1 if day % 8 < 4 else 4):
                at = pd.Timestamp('2024-01-01T06:00Z') + pd.Timedelta(days=day,minutes=n)
                events = [(at.isoformat(),'A'),((at+pd.Timedelta(hours=30)).isoformat(),'B')]
                trace = log(events)[0]; trace.attributes['concept:name'] = f'{day}-{n}'; original.append(trace)
                revised = [(ts, label if pd.Timestamp(ts) < pd.Timestamp('2024-02-20T00:00Z') else 'future_changed') for ts,label in events]
                trace = log(revised)[0]; trace.attributes['concept:name'] = f'{day}-{n}'; changed.append(trace)
        outputs = []
        for source in (original,changed):
            f = causal_features(source,net,im,{'Z':['zone']},'D','2024-02-20T00:00Z')
            self.assertEqual(f.attrs['prediction_reconstruction']['observed_events'] + f.attrs['prediction_reconstruction']['inferred_silent_events'],
                             len(prediction_history(source,net,im,'2024-02-20T00:00Z')[1]))
            X,y,a,c = prepare_experiment(f,[dict(zone='Z',metric='token_present_end')],'Z','token_present_end',3.,'>=',2,2,'D')
            outputs.append(run_experiment(X,y,a,c,development_end='2024-02-05T00:00Z',observed_through='2024-02-20T00:00Z',
                models=['decision_tree','random_forest','hist_gradient_boosting'],horizon=2,timeframe='D'))
        self.assertEqual(outputs[0],outputs[1])
