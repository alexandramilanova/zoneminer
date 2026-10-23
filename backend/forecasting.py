"""Prospective experiment API and persistent protection against holdout reuse."""
import fcntl
import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from types import SimpleNamespace

import pandas as pd
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from analytics.forecasting import (EXCLUDED, PROTOCOL_VERSION, SUPPORTED, causal_features,
    observed_bounds, prepare_experiment, run_experiment, utc, window_delta)
from analytics.metrics.reference import get_metric_reference
from analytics.metrics.schema import CANONICAL_METRICS
from backend import store
from backend.runner import get_bundle
from process_model.prefix import validate_prefix_model
from process_model.semantics import validate_petri_net
from process_model.uncertain_prefix import needs_marking_sets, OCCUPANCY_METRICS
from backend import calibration


class PredictorPair(BaseModel):
    model_config = ConfigDict(extra='forbid')
    zone: str = Field(min_length=1)
    metric: str = Field(min_length=1)


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_zone: str = Field(min_length=1)
    target_metric: str = Field(min_length=1)
    threshold: float = Field(allow_inf_nan=False)
    operator: Literal['>=', '<='] = '>='
    horizon: int = Field(ge=1, le=30)
    development_end: str
    observed_through: str
    protocol_acknowledged: Literal[True]
    feature_pairs: list[PredictorPair] = Field(min_length=1, max_length=50)
    history_lags: int = Field(default=3, ge=0, le=10)
    models: list[str] = Field(default_factory=lambda: ['decision_tree', 'random_forest', 'hist_gradient_boosting'], min_length=1)
    study_id: str | None = None


def context(meta, study_id=None):
    bundle = get_bundle(meta['dataset_id'])
    if not study_id:
        return meta, bundle, None
    spec = calibration.study(meta['dataset_id'], study_id)
    if spec['timeframe'] != meta['timeframe']:
        raise ValueError('Prediction study timeframe differs from this analysis; prepare a study for the selected timeframe.')
    net, im, fm, provenance = calibration.load(spec['calibration_id'])
    return dict(meta, zone_places=spec['zone_places']), SimpleNamespace(log=bundle.log, net=net, im=im, fm=fm,
        model_source='calibration_prefix_only'), dict(spec, provenance=provenance)


def options(meta, study_id=None):
    meta, bundle, spec = context(meta, study_id)
    reasons = []
    requires_calibration = bundle.model_source == 'discovered_from_log'
    if requires_calibration:
        reasons.append('This descriptive model was discovered from the full log. Prepare a separate prediction model from an earlier calibration period below; then define and freeze its own zones.')
    marking_sets = spec is not None or needs_marking_sets(bundle.net)
    try:
        if marking_sets:
            validate_petri_net(bundle.net, bundle.im)
        else:
            validate_prefix_model(bundle.net, bundle.im)
    except ValueError as exc:
        reasons.append(str(exc))
    start, end = observed_bounds(bundle.log, meta['timeframe'])
    if spec:
        start = utc(spec['calibration_end'])
    windows = pd.date_range(start + window_delta(meta['timeframe']), end, freq=meta['timeframe'])
    if len(windows) < 2:
        reasons.append('Insufficient completed analysis windows in the recorded event history.')
    eligible_metrics = OCCUPANCY_METRICS if marking_sets else SUPPORTED
    return dict(protocol_version=PROTOCOL_VERSION, eligible=not reasons, reasons=reasons,
        calibration_required=requires_calibration, study=spec,
        forecast_profile='marking_set_occupancy' if marking_sets else 'forced_routing_history',
        zones=sorted(meta['zone_places']), window_ends=[str(w) for w in windows],
        metrics=[dict(name=m.name, label=m.label, **get_metric_reference(m.name),
                      forecast_supported=m.name in eligible_metrics, forecast_reason=(None if m.name in eligible_metrics else
                        EXCLUDED.get(m.name, 'Alternative histories can share a marking but disagree on flow, duration or age. This profile supports only identifiable end-of-window occupancy.'))) for m in CANONICAL_METRICS],
        assumptions=['Events are available at recorded timestamps; ingestion delays are unsupported.',
            'Cases become observable at their first event; initial tokens are instantiated then.',
            'Models and zones are fixed before the experiment. Calibrated models use only events before calibration end; full-log descriptive model/zones are not reused.',
            'Prediction-only forced silent routing is instantaneous at the triggering observed-event timestamp. Initial routing uses the first case observation; these timestamps are assumptions, not measurements.',
            'Competing routing keeps pending and immediately routed alternatives, including competitors not yet enabled. Only occupancy shared by every possible marking is usable. No route probabilities are assumed. Resource bounds and closed divergent silent regions fail explicitly.',
            'Simultaneous observed activities are replayed in every model-compatible order in the marking-set profile. Visible deviations are rejected; events are never inserted or deleted. Descriptive replay is unchanged.',
            'Within-place token matching follows the existing FIFO reconstruction convention.',
            'Data coverage through the selected observation boundary is asserted by the analyst; logging gaps are not inferred. The last selectable boundary is the end of the final event bin, not proof of complete coverage.'])


def execute(meta, body):
    try:
        config = options(meta, body.study_id) if body.study_id else options(meta)
        meta, bundle, study = context(meta, body.study_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not config['eligible']:
        raise HTTPException(422, 'Forecasting unavailable: ' + ' '.join(config['reasons']))
    zones = meta['zone_places']
    pairs = [p.model_dump() for p in body.feature_pairs]
    if body.target_zone not in zones or any(p['zone'] not in zones for p in pairs):
        raise HTTPException(422, 'Select target and predictor zones from this analysis.')
    allowed = {m['name'] for m in config.get('metrics', []) if m['forecast_supported']} if 'metrics' in config else set(SUPPORTED)
    if body.target_metric not in allowed or any(p['metric'] not in allowed for p in pairs):
        raise HTTPException(422, 'Unsupported forecasting metric: use the metric eligibility explanations; descriptive metrics are unchanged.')
    try:
        end, cutoff = utc(body.observed_through), utc(body.development_end)
        if str(end) not in config['window_ends'] or str(cutoff) not in config['window_ends'] or cutoff >= end:
            raise ValueError('Choose valid completed-window boundaries with development end before observation end.')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    root = Path(__file__).resolve().parents[1]
    implementation = hashlib.sha256(b''.join((root / name).read_bytes() for name in (
        'analytics/forecasting.py', 'analytics/prediction.py', 'process_model/prefix.py',
        'process_model/features.py', 'process_model/uncertain_prefix.py', 'backend/calibration.py',
        'backend/forecasting.py', 'backend/prediction_view.py'))).hexdigest()
    specification = dict(protocol=PROTOCOL_VERSION, implementation_sha256=implementation,
        software_versions={name: version(name) for name in ('numpy', 'pandas', 'scikit-learn', 'pm4py', 'shap')},
        analysis_id=meta['id'], calibration=study, **body.model_dump())
    key = hashlib.sha256(json.dumps(specification, sort_keys=True).encode()).hexdigest()
    directory = os.path.join(store.dataset_dir(meta['dataset_id']), 'forecast_experiments')
    os.makedirs(directory, exist_ok=True)
    # Cross-process lock: one successful evaluation reserves its held-out period.
    # Identical requests return the recorded result, not another test evaluation.
    with open(os.path.join(directory, 'ledger.lock'), 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger_path = os.path.join(directory, 'ledger.json')
        if os.path.exists(ledger_path):
            with open(ledger_path) as stream:
                ledger = json.load(stream)
        else:
            ledger = []
        for prior in ledger:
            if prior['key'] == key:
                with open(os.path.join(directory, key + '.json')) as stream:
                    return dict(json.load(stream), cached=True)
            if max(cutoff, utc(prior['start'])) < min(end, utc(prior['end'])):
                raise HTTPException(409, 'This held-out period has already been evaluated under another configuration. Reusing it for threshold, feature, model or horizon selection would invalidate an untouched-test claim. Use a genuinely later, nonoverlapping evaluation period.')
        try:
            kwargs = dict(observation_start=study['calibration_end'], marking_sets=True) if study else {}
            frame = causal_features(bundle.log, bundle.net, bundle.im, zones, meta['timeframe'], end, **kwargs)
            if config.get('forecast_profile') == 'marking_set_occupancy':
                for pair in pairs + [dict(zone=body.target_zone, metric=body.target_metric)]:
                    rows = frame[frame.zone == pair['zone']]
                    unknown = rows[rows[pair['metric']].isna()]
                    if not unknown.empty:
                        first = unknown.iloc[0]
                        raise ValueError(f"{pair['zone']} / {pair['metric']} is not identifiable in {len(unknown)} windows; "
                            f"first at {first.window_end}: bounds {first[pair['metric']+'_lower']}–{first[pair['metric']+'_upper']}. "
                            'No ambiguous occupancy is imputed or discarded. Define a zone whose occupancy is invariant across the alternatives.')
            X, y, availability, current = prepare_experiment(frame, pairs, body.target_zone, body.target_metric,
                    body.threshold, body.operator, body.horizon, body.history_lags, meta['timeframe'])
            result = run_experiment(X, y, availability, current, development_end=cutoff, observed_through=end,
                    models=body.models, horizon=body.horizon, timeframe=meta['timeframe'])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        later_events = any(utc(e.get('time:timestamp')) >= end for trace in bundle.log for e in trace)
        result['forecast_context'] = ('Historical-cutoff forecast: later events exist in the uploaded log but were excluded from this experiment.' if later_events else
            'Forecast beyond the declared observation end; the uploaded log contains no events from the forecast period.')
        result.update(target=dict(zone=body.target_zone, metric=body.target_metric, operator=body.operator, threshold=body.threshold),
                      feature_pairs=pairs, specification=specification, experiment_id=key, cached=False,
                      assumptions=config['assumptions'],
                      reconstruction=frame.attrs.get('prediction_reconstruction'),
                      evaluation_note='The app prevents reuse of recorded forecast holdouts, but cannot verify earlier external inspection of the data or model/zone provenance. Scores are conditional on the declared protocol.')
        path = os.path.join(directory, key + '.json')
        with open(path + '.tmp', 'w') as stream:
            json.dump(result, stream, allow_nan=False)
        os.replace(path + '.tmp', path)
        ledger.append(dict(key=key, start=str(cutoff), end=str(end)))
        with open(ledger_path + '.tmp', 'w') as stream:
            json.dump(ledger, stream)
        os.replace(ledger_path + '.tmp', ledger_path)
        return result
