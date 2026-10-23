"""Independent prefix ambiguity, temporal calibration and API-contract tests."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
from pm4py.objects.petri_net.obj import PetriNet, Marking
from pm4py.objects.petri_net.utils.petri_utils import add_arc_from_to
from pm4py.objects.log.obj import EventLog, Trace, Event

from backend import calibration
from analytics.forecasting import prepare_experiment, run_experiment
from process_model.uncertain_prefix import MarkingSetReplay, occupancy_features
from process_model.prefix import PrefixUnavailable


def optional():
    net = PetriNet('optional')
    places = {n:PetriNet.Place(n) for n in ('start','waiting','submitted','end')}
    transitions = {n:PetriNet.Transition(n,None if n=='skip' else n) for n in ('Create','Submit','Finish','skip')}
    net.places.update(places.values());net.transitions.update(transitions.values())
    for source,target in [('start','Create'),('Create','waiting'),('waiting','Submit'),('Submit','submitted'),
                          ('waiting','skip'),('skip','submitted'),('submitted','Finish'),('Finish','end')]:
        add_arc_from_to(places.get(source,transitions.get(source)),places.get(target,transitions.get(target)),net)
    return net,Marking({places['start']:1}),places,transitions


def log(events,case='one'):
    return EventLog([Trace([Event({'concept:name':label,'time:timestamp':pd.Timestamp(time)}) for time,label in events],
                           attributes={'concept:name':case,'future_outcome':'must not enter calibration'})])


class AlternativeMarkingTests(unittest.TestCase):
    def test_duplicate_visible_labels_preserve_both_transition_identities(self):
        net = PetriNet('duplicate labels')
        p = {name:PetriNet.Place(name) for name in ('start','left','right')}
        net.places.update(p.values())
        for name,target in [('left transition','left'),('right transition','right')]:
            transition = PetriNet.Transition(name,'A')
            net.transitions.add(transition)
            add_arc_from_to(p['start'],transition,net)
            add_arc_from_to(transition,p[target],net)
        frame = occupancy_features(log([('2024-01-01T12:00Z','A')]),net,Marking({p['start']:1}),
            {'Either':['left','right'],'Left':['left']},'D','2024-01-01','2024-01-02')
        self.assertEqual(frame[frame.zone=='Either'].token_present_end.tolist(),[1])
        self.assertTrue(frame[frame.zone=='Left'].token_present_end.isna().all())
        self.assertEqual(frame.attrs['prediction_reconstruction']['peak_markings'],2)

    def test_future_changes_leave_all_three_marking_profile_predictions_identical(self):
        net,im,_,_=optional()
        source = EventLog()
        start = pd.Timestamp('2024-01-01T00:00Z')
        for day in range(32):
            for case in range(1 if day%4<2 else 4):
                at = start + pd.Timedelta(days=day,hours=12)
                source.append(log([(at,'Create'),(at+pd.Timedelta(hours=18),'Finish')],f'{day}-{case}')[0])
        # Even an invalid unavailable label cannot invalidate an earlier
        # forecast through iterator lookahead.
        changed = EventLog(list(source)+list(log([('2024-03-01T12:00Z',None)],'future')))
        outputs = []
        for events in (source,changed):
            frame = occupancy_features(events,net,im,{'Z':['waiting','submitted']},'D',start,start+pd.Timedelta(days=32))
            X,y,available,current = prepare_experiment(frame,[dict(zone='Z',metric='case_present_end')],
                'Z','token_present_end',3.,'>=',1,0,'D')
            result = run_experiment(X,y,available,current,development_end=start+pd.Timedelta(days=22),
                observed_through=start+pd.Timedelta(days=32),models=['decision_tree','random_forest','hist_gradient_boosting'],horizon=1,timeframe='D')
            outputs.append((frame,[dict(model=m['model_key'],forecast=m['forecast'],holdout=m['holdout']) for m in result['models']]))
        pd.testing.assert_frame_equal(outputs[0][0],outputs[1][0])
        self.assertEqual(outputs[0][1],outputs[1][1])

    def test_weighted_concurrent_tokens_have_independently_known_counts(self):
        net = PetriNet('weighted concurrent')
        p = {name:PetriNet.Place(name) for name in ('start','left','right','end')}
        net.places.update(p.values())
        t = {name:PetriNet.Transition(name,name) for name in ('Split','Left','Right')}
        net.transitions.update(t.values())
        for source,target,weight in [('start','Split',2),('Split','left',2),('Split','right',1),
                                      ('left','Left',2),('Left','end',2),('right','Right',1),('Right','end',1)]:
            add_arc_from_to(p.get(source,t.get(source)),p.get(target,t.get(target)),net,weight=weight)
        source = log([('2024-01-01T12:00Z','Split'),('2024-01-02T12:00Z','Right'),('2024-01-02T12:00Z','Left')])
        frame = occupancy_features(source,net,Marking({p['start']:2}),{'Work':['left','right'],'End':['end']},
                                   'D','2024-01-01','2024-01-03')
        self.assertEqual(frame[frame.zone=='Work'].token_present_end.tolist(),[3,0])
        self.assertEqual(frame[frame.zone=='Work'].case_present_end.tolist(),[1,0])
        self.assertEqual(frame[frame.zone=='End'].token_present_end.tolist(),[0,3])
        self.assertEqual(frame[frame.zone=='End'].case_present_end.tolist(),[0,1])
        # An initial marking with only one token cannot enable weight-two Split.
        with self.assertRaisesRegex(PrefixUnavailable,'visible deviation'):
            occupancy_features(source,net,Marking({p['start']:1}),{'Work':['left','right']},
                               'D','2024-01-01','2024-01-03')

    def test_disabled_silent_competitor_must_not_be_lost_before_later_observation(self):
        net=PetriNet('pending');p={n:PetriNet.Place(n) for n in ('p','seed','q','r','done')}
        net.places.update(p.values())
        t={n:PetriNet.Transition(n,None if n.startswith('tau') else n) for n in ('A','B','tauSkip','tauJoin')}
        net.transitions.update(t.values())
        for a,b in [('seed','A'),('A','q'),('p','tauSkip'),('tauSkip','done'),('p','tauJoin'),('q','tauJoin'),('tauJoin','r'),('r','B'),('B','done')]:
            add_arc_from_to(p.get(a,t.get(a)),p.get(b,t.get(b)),net)
        im=Marking({p['p']:1,p['seed']:1})
        source=log([('2024-01-01T12:00Z','A'),('2024-01-02T12:00Z','B')])
        f=occupancy_features(source,net,im,{'Z':list(p)},'D','2024-01-01','2024-01-03')
        self.assertEqual(f.case_present_end.tolist(),[1,1])
        self.assertTrue(np.isnan(f.token_present_end.iloc[0]))

    def test_optional_route_keeps_both_possibilities_and_only_invariant_zone_counts(self):
        net,im,_,_=optional()
        source=log([('2024-01-01T12:00Z','Create'),('2024-01-02T12:00Z','Submit'),('2024-01-03T12:00Z','Finish')])
        f=occupancy_features(source,net,im,{'Together':['waiting','submitted'],'Waiting':['waiting']},'D','2024-01-01','2024-01-04')
        merged=f[f.zone=='Together'];waiting=f[f.zone=='Waiting']
        self.assertEqual(merged.token_present_end.tolist(),[1,1,0])
        self.assertEqual(merged.case_present_end.tolist(),[1,1,0])
        self.assertTrue(np.isnan(waiting.token_present_end.iloc[0]))
        self.assertEqual(waiting.token_present_end_lower.tolist(),[0,0,0])
        self.assertEqual(waiting.token_present_end_upper.tolist(),[1,0,0])
        self.assertEqual(f.attrs['prediction_reconstruction']['peak_markings'],2)
        self.assertIsNone(f.attrs['prediction_reconstruction']['inferred_silent_events'])

    def test_future_evidence_never_rewrites_earlier_ambiguous_snapshot(self):
        net,im,_,_=optional()
        a=log([('2024-01-01T12:00Z','Create'),('2024-01-03T12:00Z','Submit')])
        b=log([('2024-01-01T12:00Z','Create'),('2024-01-03T12:00Z','Finish')])
        kwargs=dict(net=net,im=im,zones={'Z':['waiting','submitted']},timeframe='D',start='2024-01-01',end='2024-01-03')
        pd.testing.assert_frame_equal(occupancy_features(a,**kwargs),occupancy_features(b,**kwargs))

    def test_simultaneous_events_use_all_compatible_orders_and_boundary_is_excluded(self):
        net,im,_,_=optional()
        source=log([('2024-01-02T00:00Z','Submit'),('2024-01-02T00:00Z','Create')])
        f=occupancy_features(source,net,im,{'Z':['waiting','submitted']},'D','2024-01-01','2024-01-03')
        self.assertEqual(f.token_present_end.tolist(),[0,1])
        self.assertEqual(f.attrs['prediction_reconstruction']['tied_timestamp_batches'],1)

    def test_incompatible_visible_event_does_not_get_dropped(self):
        net,im,_,_=optional()
        with self.assertRaisesRegex(PrefixUnavailable,'visible deviation') as error:
            occupancy_features(log([('2024-01-01T12:00Z','Unknown')]),net,im,{'Z':['waiting']},'D','2024-01-01','2024-01-02')
        self.assertEqual(error.exception.diagnostics['case'],'one')

    def test_silent_cycle_and_resource_limit_do_not_choose_one_path(self):
        net,im,places,transitions=optional()
        # A silent self-loop has infinitely many immediate histories.
        loop=PetriNet.Transition('loop',None);net.transitions.add(loop)
        add_arc_from_to(places['submitted'],loop,net);add_arc_from_to(loop,places['submitted'],net)
        replay=MarkingSetReplay(net,im)
        states=replay.closure(tuple(1 if p.name=='waiting' else 0 for p in replay.places))
        self.assertEqual(len(states),2) # stuttering cycle changes no occupancy
        closed=PetriNet('closed');p=PetriNet.Place('p');t=PetriNet.Transition('tau',None)
        closed.places.add(p);closed.transitions.add(t);add_arc_from_to(p,t,closed);add_arc_from_to(t,p,closed)
        with self.assertRaisesRegex(PrefixUnavailable,'cycle'):
            MarkingSetReplay(closed,Marking({p:1})).closure((1,))
        net,im,_,_=optional(); replay=MarkingSetReplay(net,im)
        with patch('process_model.uncertain_prefix.MAX_STATES',1):
            with self.assertRaisesRegex(PrefixUnavailable,'possible markings'):
                replay.closure(tuple(1 if p.name=='waiting' else 0 for p in replay.places))


class CalibrationTests(unittest.TestCase):
    def test_future_events_and_completion_do_not_change_calibration_artifact(self):
        a=log([('2024-01-01T12:00Z','Create'),('2024-01-02T12:00Z','Submit'),('2024-02-01T12:00Z','Finish')])
        b=log([('2024-01-01T12:00Z','Create'),('2024-01-02T12:00Z','Submit'),('2024-03-01T12:00Z','Unseen')])
        b.append(log([('2024-03-01T12:00Z','New')],case='future')[0])
        a.append(log([('2024-01-02T10:00Z','Create')],case='other')[0])
        b=EventLog(list(log([('2024-01-02T10:00Z','Create')],case='other'))+list(b))
        with tempfile.TemporaryDirectory() as tmp,patch('backend.calibration.config.DATA_DIR',tmp):
            calibration.load.cache_clear()
            first=calibration.prepare(a,'2024-01-03','D'); second=calibration.prepare(b,'2024-01-03','D')
            self.assertEqual(first,second)
            self.assertEqual(first['calibration']['observed_events'],3)
            prefix,_=calibration.calibration_prefix(a,'2024-01-03')
            self.assertEqual(dict(prefix[0].attributes),{'concept:name':'one'})
            self.assertEqual(len(prefix[0]),2) # unfinished case retained
            calibration.load.cache_clear()

    def test_study_zones_are_validated_and_other_dataset_prefix_cannot_be_borrowed(self):
        source=log([('2024-01-01T12:00Z','Create'),('2024-01-02T12:00Z','Finish')])
        with tempfile.TemporaryDirectory() as tmp,patch('backend.calibration.config.DATA_DIR',tmp), \
             patch('backend.calibration.store.dataset_dir',return_value=tmp), \
             patch('backend.runner.get_bundle',return_value=SimpleNamespace(log=source)):
            calibration.load.cache_clear()
            graph=calibration.prepare(source,'2024-01-03','D');identifier=graph['calibration']['id']
            for zones in ({}, {'Z':['nonexistent']}, [{'name':'same','places':[graph['places'][0]]},{'name':'same','places':[graph['places'][1]]}]):
                with self.assertRaisesRegex(ValueError,'Invalid prediction zones'):
                    calibration.freeze('d','D',calibration.StudyRequest(calibration_id=identifier,zones=zones))
            good=calibration.freeze('d','D',calibration.StudyRequest(calibration_id=identifier,zones={'Z':[graph['places'][0]]}))
            self.assertEqual(calibration.study('d',good['id']),good)
            with patch('backend.runner.get_bundle',return_value=SimpleNamespace(log=log([('2024-01-01T12:00Z','Different')]))):
                with self.assertRaisesRegex(ValueError,'does not match'):
                    calibration.freeze('different','D',calibration.StudyRequest(calibration_id=identifier,zones={'Z':[graph['places'][0]]}))
            calibration.load.cache_clear()
