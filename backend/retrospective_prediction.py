"""Exploratory prediction over saved descriptive reconstruction artifacts."""
import fcntl
import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel,ConfigDict,Field

from analytics.metrics.reference import get_metric_reference
from analytics.metrics.schema import CANONICAL_METRICS
from analytics.retrospective_prediction import DEFAULTS,NOTE,PROTOCOL,evaluate
from backend import store
from backend.forecasting import PredictorPair


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_zone: str = Field(min_length=1)
    target_metric: str = Field(min_length=1)
    threshold: float = Field(allow_inf_nan=False)
    threshold_source: Literal['manual','suggested'] = 'manual'
    operator: str = Field(default='>=',pattern='^(>=|<=)$')
    horizon: int = Field(ge=1,le=30)
    feature_pairs: list[PredictorPair] = Field(min_length=1,max_length=256)
    balance_classes: bool = False


def suggest_threshold(values, operator):
    """Descriptive quantile default, independent of models and evaluation scores."""
    values = pd.to_numeric(values,errors='coerce').replace([np.inf,-np.inf],np.nan).dropna()
    if values.empty:
        return dict(value=None,reason='No defined historical values.',positive_windows=0,negative_windows=0)
    percentile = .75 if operator=='>=' else .25
    value = float(f"{values.quantile(percentile,interpolation='higher'):.6g}")
    unique = np.sort(values.unique())
    if len(unique)==1:
        value = float(unique[0])
    else:
        if operator=='>=':
            value = float(unique[1]) if value<=unique[0] else min(value,float(unique[-1]))
        else:
            value = float(unique[-2]) if value>=unique[-1] else max(value,float(unique[0]))
    positives = int((values>=value if operator=='>=' else values<=value).sum())
    return dict(value=value,percentile=percentile,positive_windows=positives,negative_windows=len(values)-positives,
        reason='Constant metric: no threshold can produce two classes.' if len(unique)==1 else
        'Historical upper quartile; adjusted above the minimum when needed for sparse values.' if operator=='>=' else
        'Historical lower quartile; adjusted below the maximum when needed for sparse values.')


def options(frame):
    metrics = [dict(name=m.name,label=m.label,family=m.family,**get_metric_reference(m.name))
               for m in CANONICAL_METRICS if m.name in frame]
    availability = {}
    for zone,rows in frame.groupby('zone'):
        availability[zone] = {}
        for metric in metrics:
            values = pd.to_numeric(rows[metric['name']],errors='coerce').replace([np.inf,-np.inf],np.nan).dropna()
            availability[zone][metric['name']] = dict(observed=len(values),minimum=float(values.min()) if len(values) else None,
                maximum=float(values.max()) if len(values) else None,distinct_values=int(values.nunique()),
                suggested_thresholds={op:suggest_threshold(values,op) for op in ('>=','<=')})
    return dict(protocol_version=PROTOCOL,zones=sorted(availability),metrics=metrics,availability=availability,
                defaults=DEFAULTS,interpretation=NOTE,windows=int(frame.window_start.nunique()))


def execute(meta,frame,body):
    if body.threshold_source=='suggested':
        if body.target_metric not in frame or body.target_zone not in set(frame.zone):
            raise ValueError('Choose an available target zone and metric.')
        suggestion = suggest_threshold(frame.loc[frame.zone==body.target_zone,body.target_metric],body.operator)
        if suggestion['value'] is None or not np.isclose(body.threshold,suggestion['value'],rtol=1e-12,atol=0):
            raise ValueError('Suggested threshold does not match this target. Reload the setup or enter a custom threshold.')
    implementation = hashlib.sha256(b''.join((Path(__file__).resolve().parents[1]/name).read_bytes() for name in
        ('analytics/retrospective_prediction.py','analytics/forecasting.py','analytics/prediction.py',
         'backend/retrospective_prediction.py','backend/prediction_view.py'))).hexdigest()
    fingerprint = hashlib.sha256(pd.util.hash_pandas_object(frame,index=True).values.tobytes()+json.dumps(list(frame.columns)).encode()).hexdigest()
    specification = dict(analysis_id=meta['id'],protocol=PROTOCOL,implementation_sha256=implementation,
        feature_table_sha256=fingerprint,defaults=DEFAULTS,
        software_versions={name:version(name) for name in ('pandas','numpy','scikit-learn','pm4py','shap')},**body.model_dump())
    specification['threshold_policy'] = ('Historical upper quartile for >=; lower quartile for <=, with sparse-value guard. '
        'Computed from the full reconstructed target series, independently of model scores; exploratory, not a predeclared business limit.'
        if body.threshold_source=='suggested' else 'Analyst-entered threshold; no performance-based threshold search.')
    key = hashlib.sha256(json.dumps(specification,sort_keys=True).encode()).hexdigest()
    directory = Path(store.analysis_dir(meta['id']))/'retrospective_prediction'
    directory.mkdir(exist_ok=True)
    with (directory/(key+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path = directory/(key+'.json')
        if path.exists():
            return dict(json.loads(path.read_text()),cached=True)
        result = evaluate(frame,[p.model_dump() for p in body.feature_pairs],body.target_zone,body.target_metric,
                          body.threshold,body.operator,body.horizon,meta['timeframe'],balance_classes=body.balance_classes)
        conformance = store.load_frame(meta['id'],'conformance')
        audit = dict(source='Existing complete-trace alignment replay; original upload and descriptive artifacts unchanged.',
            timing='Model and silent moves inherit the replay convention: previous reconstructed time + 1 microsecond; subsequent observed times are clamped if necessary. These are inferred times.',
            limitations='Optimal alignments may be nonunique. Model moves insert inferred firings; log-only moves do not fire model transitions. This is not a uniquely observed token history.')
        if conformance is not None:
            audit.update(aligned_cases=len(conformance),**{name:int(conformance[column].sum()) for name,column in
                [('log_only_moves','alignment_log_move_count'),('visible_model_moves','alignment_model_move_count'),
                 ('cases_with_visible_deviation','alignment_has_deviation')] if column in conformance})
        result.update(experiment_id=key,cached=False,specification=specification,reconstruction=audit,
            software_versions=specification['software_versions'])
        temporary=directory/(key+'.tmp')
        temporary.write_text(json.dumps(result,allow_nan=False))
        os.replace(temporary,path)
        return result
