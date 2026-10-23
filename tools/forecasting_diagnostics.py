"""Fixed, untuned causal-forecast feasibility diagnostic; not a benchmark claim.

Run from the repository root, for example:
python tools/forecasting_diagnostics.py log.xes --output report.json
Compressed .xes.gz files are accepted by this diagnostic only. The application
upload contract remains .xes/.csv. No source log, descriptive model or baseline
is changed. All structural components are reported, including final places.
"""
import argparse
from collections import Counter
import gzip
import hashlib
from itertools import groupby
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from analytics.forecasting import observed_bounds, prepare_experiment, run_experiment, utc
from backend.calibration import prepare, load, calibration_prefix
from process_model.io import load_any_log
from process_model.prefix import PrefixUnavailable
from process_model.uncertain_prefix import MarkingSetReplay, occupancy_features, OCCUPANCY_METRICS


def structural_zones(net):
    """Partition fixed from calibration topology, without inspecting outcomes."""
    parent = {p.name:p.name for p in net.places}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for transition in net.transitions:
        if transition.label is None:
            places = sorted({a.source.name for a in transition.in_arcs} | {a.target.name for a in transition.out_arcs})
            for place in places[1:]:
                parent[find(place)] = find(places[0])
    groups = {}
    for place in sorted(parent):
        groups.setdefault(find(place), []).append(place)
    return {f'Component {i+1:03}':ps for i,ps in enumerate(sorted(groups.values()))}


def compatibility(log, net, im, end):
    """Audit every observed case; failures are counted, never repaired/dropped.

    Compatibility is a language/marking test, not a claim of unique token paths.
    A case contributes at most one failure, at its first incompatible batch.
    """
    replay = MarkingSetReplay(net, im)
    counts, examples, cases, events, peak = Counter(), [], 0, 0, 1
    # An initial-closure failure is identical for every case. Compute it once;
    # repeatedly enumerating a rejected state space cannot add evidence.
    try:
        initial = replay.closure(replay.initial)
        initial_error = None
    except PrefixUnavailable as exc:
        initial, initial_error = None, str(exc)
    for trace in log:
        observed = [event for event in trace if utc(event['time:timestamp']) < end]
        if not observed:
            continue
        cases += 1
        if cases % 5000 == 0:
            print(f'Compatibility: {cases} observed cases checked; {sum(counts.values())} rejected so far',flush=True)
        try:
            if initial_error:
                raise PrefixUnavailable(initial_error)
            states = initial
            for stamp, batch in groupby(observed, key=lambda event:utc(event['time:timestamp'])):
                labels = Counter(event['concept:name'] for event in batch)
                states = replay.observe(states, tuple(sorted(labels.items())))
                events += sum(labels.values())
                peak = max(peak, len(states))
        except PrefixUnavailable as exc:
            category = 'visible_deviation' if 'visible deviation' in str(exc) else 'unsupported_or_resource_limit'
            counts[category] += 1
            if len(examples) < 10:
                examples.append(dict(case=str(trace.attributes.get('concept:name')), reason=str(exc)))
    return dict(observed_cases=cases, compatible_cases=cases-sum(counts.values()), failed_cases=sum(counts.values()),
                failures_by_category=dict(counts), examples=examples, replayed_events_before_failures=events, peak_markings=peak)


def evaluate(path):
    started = time.perf_counter()
    report = dict(source_name=path.name, source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        protocol='Daily; calendar 20% calibration / 70% development; horizon 1; threshold >=1; history lags 3; DT/RF/HGB; no tuning',
        zone_policy='All silent-linked place components, fixed from calibration topology. Structural diagnostics, not validated business zones. Final-place tokens persist.')
    try:
        with tempfile.TemporaryDirectory() as temporary:
            if path.name.lower().endswith('.xes.gz'):
                expanded = Path(temporary) / 'log.xes'
                with gzip.open(path, 'rb') as source, expanded.open('wb') as target:
                    import shutil
                    shutil.copyfileobj(source, target)
                log = load_any_log(str(expanded))
            else:
                log = load_any_log(str(path))
        report.update(cases=len(log), events=sum(map(len,log)), import_order=log.attributes.get('zone_analytics:import_order'))
        print(f'Imported {report["cases"]} cases / {report["events"]} events',flush=True)
        start,end = observed_bounds(log,'D')
        days = (end-start).days
        cutoff = start + pd.Timedelta(days=max(1,int(days*.2)))
        development = start + pd.Timedelta(days=int(days*.7))
        if not start < cutoff < development < end:
            raise ValueError('History is too short for the fixed calendar partition.')
        report.update(start=str(start), observed_through=str(end), calibration_end=str(cutoff), development_end=str(development))
        graph = prepare(log,cutoff,'D')
        net,im,fm,provenance = load(graph['calibration']['id'])
        report['calibration'] = provenance
        print(f'Frozen calibration: {provenance["observed_cases"]} prefixes / {provenance["observed_events"]} events',flush=True)
        report['model'] = dict(places=len(net.places),transitions=len(net.transitions),silent=sum(t.label is None for t in net.transitions))
        prefix,_ = calibration_prefix(log,cutoff)
        report['calibration_compatibility'] = compatibility(prefix,net,im,cutoff)
        report['full_observed_compatibility'] = compatibility(log,net,im,end)
        zones = structural_zones(net)
        report['zones'] = [dict(name=z,places=ps,contains_initial=any(p.name in ps for p in im),contains_final=any(p.name in ps for p in fm)) for z,ps in zones.items()]
        if report['calibration_compatibility']['failed_cases']:
            raise ValueError('The learned calibration prefixes are not supported by declared replay; no forecasting result is reported.')
        if report['full_observed_compatibility']['failed_cases']:
            raise ValueError('Observed cases are incompatible or exceed replay limits; none are dropped to obtain a forecast.')
        frame = occupancy_features(log,net,im,zones,'D',cutoff,end)
        report['reconstruction'] = frame.attrs['prediction_reconstruction']
        report['targets'] = []
        for zone in zones:
            for metric in OCCUPANCY_METRICS:
                rows = frame[frame.zone == zone]
                item = dict(zone=zone,metric=metric,windows=len(rows),ambiguous_windows=int(rows[metric].isna().sum()))
                report['targets'].append(item)
                if item['ambiguous_windows']:
                    item['status'] = 'rejected: nonidentifiable occupancy'
                    continue
                X,y,available,current = prepare_experiment(frame,[dict(zone=zone,metric=metric)],zone,metric,1.,'>=',1,3,'D')
                dev = (X.index < development) & (available <= development) & y.notna()
                held = (X.index >= development) & (available <= end) & y.notna()
                item.update(development_examples=int(dev.sum()),development_positives=int(y[dev].sum()),heldout_examples=int(held.sum()),heldout_positives=int(y[held].sum()))
                try:
                    result = run_experiment(X,y,available,current,development_end=development,observed_through=end,
                        models=['decision_tree','random_forest','hist_gradient_boosting'],horizon=1,timeframe='D')
                    item.update(status='trained',baselines=result['baselines'],models=[{key:m[key] for key in ('model_key','cv','holdout','forecast')} for m in result['models']])
                except ValueError as exc:
                    item.update(status='rejected',reason=str(exc))
    except (ValueError, OSError) as exc:
        report['error'] = str(exc)
    report['seconds'] = time.perf_counter()-started
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = evaluate(args.log)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False))
    print(json.dumps({key:value for key,value in result.items() if key not in ('targets','zones')},indent=2))
