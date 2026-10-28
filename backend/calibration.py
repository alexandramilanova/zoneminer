"""Frozen prediction-only models learned strictly before an explicit cutoff."""
import fcntl
import hashlib
import json
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path

import pandas as pd
from pm4py.objects.log.obj import EventLog, Trace, Event
from pm4py.objects.petri_net.exporter import exporter
from pydantic import BaseModel

from backend import config, store
from backend.zone_requests import ZoneConfiguration
from process_model.io import discover_process_tree_from_log, petri_net_from_process_tree, load_pnml
from process_model.zone_validation import validate_zones

VERSION = 'observed-prefix-calibration-v1'


class CalibrationRequest(BaseModel):
    calibration_end: str


class StudyRequest(ZoneConfiguration):
    calibration_id: str


def _directory(identifier):
    if not re.fullmatch(r'[a-f0-9]{24}', identifier):
        raise ValueError('Invalid prediction calibration identity.')
    return Path(config.data_dir()) / 'prediction_models' / identifier


def calibration_prefix(log, cutoff):
    """No selection by eventual case completion and no future trace attributes."""
    end = pd.to_datetime(cutoff, utc=True)
    prefix = EventLog()
    for trace in log:
        events = []
        for event in trace:
            ts = pd.Timestamp(event.get('time:timestamp'))
            if pd.isna(ts):
                raise ValueError('Every event requires a valid timestamp for calibration.')
            ts = ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')
            if ts < end:
                events.append(Event({'concept:name':event.get('concept:name'),'time:timestamp':ts}))
        if events:
            case = str(trace.attributes.get('concept:name', ''))
            prefix.append(Trace(events, attributes={'concept:name': case}))
    # Trace container order is not an observation. In particular, a source
    # export may order cases by their eventual completion. Canonicalize using
    # only currently observed identities before discovery and fingerprinting.
    prefix = EventLog(sorted(prefix, key=lambda trace:trace.attributes['concept:name']))
    identities = [trace.attributes['concept:name'] for trace in prefix]
    if any(not case for case in identities) or len(set(identities)) != len(identities):
        raise ValueError('Calibration requires unique, nonempty observed case identities.')
    digest = hashlib.sha256()
    for trace in prefix:
        digest.update(json.dumps([trace.attributes['concept:name'],
            [(e['concept:name'], str(e['time:timestamp'])) for e in trace]], separators=(',', ':')).encode())
    return prefix, digest.hexdigest()


def prepare(log, cutoff, timeframe):
    end = pd.to_datetime(cutoff, utc=True)
    if pd.isna(end) or end.floor(timeframe) != end:
        raise ValueError('Calibration end must be a completed-window boundary.')
    prefix, fingerprint = calibration_prefix(log, end)
    events = sum(map(len, prefix))
    if events < 2:
        raise ValueError('Calibration requires at least two observed events before the cutoff.')
    identifier = hashlib.sha256(json.dumps([VERSION, str(end), fingerprint]).encode()).hexdigest()[:24]
    directory = _directory(identifier)
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / 'model.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (directory / 'metadata.json').exists():
            tree = discover_process_tree_from_log(prefix)
            net, im, fm = petri_net_from_process_tree(tree)
            exporter.apply(net, im, str(directory / 'model.tmp.pnml'), final_marking=fm)
            os.replace(directory / 'model.tmp.pnml', directory / 'model.pnml')
            metadata = dict(id=identifier, version=VERSION, calibration_end=str(end), prefix_sha256=fingerprint,
                            observed_cases=len(prefix), observed_events=events,
                            note='Discovered from observed case prefixes only; case completion was not inferred using later events.')
            (directory / 'metadata.tmp').write_text(json.dumps(metadata))
            os.replace(directory / 'metadata.tmp', directory / 'metadata.json')
    return graph(identifier)


def load(identifier):
    directory = _directory(identifier)
    return _load(str(directory))


@lru_cache(maxsize=8)
def _load(directory):
    directory = Path(directory)
    if not (directory / 'metadata.json').exists():
        raise ValueError('Prediction calibration was not found. Prepare a model first.')
    return (*load_pnml(str(directory / 'model.pnml')), json.loads((directory / 'metadata.json').read_text()))


load.cache_clear = _load.cache_clear


def graph(identifier):
    net, im, fm, metadata = load(identifier)
    return dict(calibration=metadata, places=sorted(p.name for p in net.places),
                transitions=[dict(name=t.name, label=t.label) for t in sorted(net.transitions, key=lambda t:t.name)],
                arcs=[dict(source=a.source.name, target=a.target.name, weight=int(a.weight)) for a in net.arcs],
                initial_marking={p.name:int(n) for p,n in im.items()}, final_marking={p.name:int(n) for p,n in fm.items()},
                activity_labels=sorted({t.label for t in net.transitions if t.label is not None}),
                model_source='calibration_prefix_only', model_notice=metadata['note'])


def freeze(dataset_id, timeframe, request):
    net, _, _, metadata = load(request.calibration_id)
    # Bind the shared prefix-model artifact to this dataset only after verifying
    # its prefix digest; clients cannot borrow another log's calibration.
    from backend.runner import get_bundle
    _, fingerprint = calibration_prefix(get_bundle(dataset_id).log, metadata['calibration_end'])
    if fingerprint != metadata['prefix_sha256']:
        raise ValueError('This calibration does not match the observed prefix of this dataset.')
    result = validate_zones(zone_inputs=request.zone_inputs(), place_names=[p.name for p in net.places], net=net,
        require_non_empty=True, allow_unassigned_places=True, require_connected=True)
    if not result['zone_config_valid']:
        raise ValueError('Invalid prediction zones: ' + json.dumps(result['errors']))
    payload = dict(dataset_id=dataset_id, timeframe=timeframe, calibration_id=request.calibration_id,
                   calibration_end=metadata['calibration_end'], zone_places=result['zone_places'])
    identifier = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
    directory = Path(store.dataset_dir(dataset_id)) / 'prediction_studies'
    directory.mkdir(exist_ok=True)
    # Content-addressed, immutable specification. No descriptive analysis is edited.
    with tempfile.NamedTemporaryFile(mode='w',dir=directory,delete=False,suffix='.tmp') as stream:
        json.dump(dict(id=identifier, **payload), stream)
        temporary=stream.name
    os.replace(temporary,directory / (identifier + '.json'))
    return dict(id=identifier, **payload)


def study(dataset_id, identifier):
    if not re.fullmatch(r'[a-f0-9]{24}', identifier):
        raise ValueError('Invalid prediction study identity.')
    path = Path(store.dataset_dir(dataset_id)) / 'prediction_studies' / (identifier + '.json')
    if not path.exists():
        raise ValueError('Prediction study not found for this dataset.')
    return json.loads(path.read_text())
