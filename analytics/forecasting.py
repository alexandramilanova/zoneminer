"""Causal prefix features and label-availability constrained forecast experiments.

Retrospective analytics/prediction.py remains the Streamlit reference; the API
uses this separate, explicitly restricted prospective protocol.
"""
from types import SimpleNamespace

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.ensemble import HistGradientBoostingClassifier

from analytics.metrics.schema import CANONICAL_METRICS
from analytics.prediction import MODEL_DISPLAY_NAMES, _build_model_pipeline
from process_model.features import build_zone_token_features_from_places
from process_model.prefix import prediction_history, validate_prefix_model, ROUTING_POLICY
from process_model.uncertain_prefix import occupancy_features, needs_marking_sets

PROTOCOL_VERSION = 'causal-calibrated-markings-v3'
EXCLUDED = {
    'token_aged_open_share': 'Uses a whole-timeline reference duration; no prospective calibration policy is defined.',
    'token_stagnation_index': 'Uses a whole-timeline reference duration; no prospective calibration policy is defined.',
    **{name: 'Batch membership and release can be revised by later exits; its label is not finalized at window end.'
       for name in ('case_batch_count', 'case_batch_size_mean', 'case_batching_ratio', 'case_batch_wait_overhead_mean')},
    **{m.name: 'Requires retrospective complete-trace alignment; no prospective conformance definition is supplied.'
       for m in CANONICAL_METRICS if m.family == 'conformance'},
}
SUPPORTED = [m.name for m in CANONICAL_METRICS if m.name not in EXCLUDED]


def utc(value):
    stamp = pd.Timestamp(value)
    if stamp is None or pd.isna(stamp):
        raise ValueError('A valid timestamp is required.')
    return stamp.tz_localize('UTC') if stamp.tzinfo is None else stamp.tz_convert('UTC')


def window_delta(timeframe):
    if timeframe not in ('h', 'D', '7D', '30D'):
        raise ValueError('Forecasting requires fixed h, D, 7D or 30D analysis windows.')
    return pd.Timedelta(timeframe if timeframe != 'h' else '1h') if timeframe != 'D' else pd.Timedelta(days=1)


def observed_bounds(log, timeframe):
    times = [utc(e.get('time:timestamp')) for trace in log for e in trace]
    if not times:
        raise ValueError('No recorded events are available.')
    end = max(times).ceil(timeframe)
    if end == max(times):
        end += window_delta(timeframe)
    return min(times).floor(timeframe), end


def causal_features(log, net, im, zones, timeframe, observed_through, *, observation_start=None, marking_sets=None):
    marking_sets = needs_marking_sets(net) if marking_sets is None else marking_sets
    if not marking_sets:
        validate_prefix_model(net, im)
    end = utc(observed_through)
    delta = window_delta(timeframe)
    if marking_sets and observation_start is not None:
        return occupancy_features(log, net, im, zones, timeframe, utc(observation_start), end)
    # Never derive the feature grid from future cases/events.
    visible_times = [utc(e.get('time:timestamp')) for trace in log for e in trace
                     if utc(e.get('time:timestamp')) < end]
    if not visible_times:
        raise ValueError('No events precede the observation cutoff.')
    start = utc(observation_start) if observation_start is not None else min(visible_times).floor(timeframe)
    if marking_sets:
        return occupancy_features(log, net, im, zones, timeframe, start, end)
    cutoffs = pd.date_range(start + delta, end, freq=timeframe)
    if end.floor(timeframe) != end or not len(cutoffs) or cutoffs[-1] != end:
        raise ValueError('Observation end must be an exact completed-window boundary.')
    if len(cutoffs) > 256 or len(visible_times) * len(cutoffs) * len(zones) > 3_000_000:
        raise ValueError('Exact prefix feature computation exceeds the initial resource limit (256 windows / 3 million event-window-zone combinations). Use a coarser timeframe or smaller independently defined study period.')
    frames = []
    for cutoff in cutoffs:
        tokens, derived = prediction_history(log, net, im, cutoff)
        snapshot = build_zone_token_features_from_places(tokens, zones, timeframe,
                    observation_start=cutoff - delta, observation_end=cutoff)
        frames.append(snapshot[['zone', 'window_start', 'window_end'] + SUPPORTED])
    result = pd.concat(frames, ignore_index=True)
    inferred = derived[derived['inferred'].astype(bool)]
    preview = inferred.head(20).copy()
    for column in ('timestamp', 'available_at'):
        preview[column] = preview[column].astype(str)
    result.attrs['prediction_reconstruction'] = dict(policy=ROUTING_POLICY, cutoff=str(end),
        observed_events=int((~derived['inferred'].astype(bool)).sum()), inferred_silent_events=len(inferred),
        visible_events_inserted=0, visible_events_deleted=0,
        silent_transition_counts={str(k): int(v) for k, v in inferred['transition_id'].value_counts().items()},
        # Pandas' nullable string column represents silent activity labels as
        # NaN. Preserve the model's absent label as JSON null, never NaN.
        inferred_event_preview=preview.astype(object).where(preview.notna(), None).to_dict(orient='records'), preview_limit=20)
    return result


def prepare_experiment(features, pairs, target_zone, target_metric, threshold, operator, horizon, lags, timeframe):
    if not np.isfinite(threshold):
        raise ValueError('Threshold must be a finite number fixed before evaluation.')
    if horizon < 1 or lags < 0:
        raise ValueError('Horizon must be positive and history lags nonnegative.')
    if operator not in ('>=', '<='):
        raise ValueError('Operator must be >= or <=.')
    if target_metric not in SUPPORTED or any(p['metric'] not in SUPPORTED for p in pairs):
        raise ValueError('A selected metric is not causally supported. See forecasting metric eligibility explanations.')
    if not pairs or len({(p['zone'], p['metric']) for p in pairs}) != len(pairs):
        raise ValueError('Select nonduplicate zone–metric predictor pairs.')
    target = features[features.zone == target_zone].set_index('window_end')[target_metric].sort_index()
    if target.empty:
        raise ValueError('Unknown target zone.')
    index = pd.DatetimeIndex(target.index)
    if len(index) <= horizon:
        raise ValueError('Prediction horizon exceeds the observed history.')
    X = pd.DataFrame(index=index)
    for pair in pairs:
        series = features[features.zone == pair['zone']].set_index('window_end')[pair['metric']]
        if series.empty:
            raise ValueError(f"Unknown predictor zone {pair['zone']!r}.")
        name = f"{pair['zone']}__{pair['metric']}"
        X[name] = series.reindex(index)
        for lag in range(1, lags + 1):
            X[f'{name}__lag{lag}'] = X[name].shift(lag)
    # Structural lag gaps are removed, not imputed. Other undefined metrics
    # remain missing and are handled with training-only median preprocessing.
    X = X.iloc[lags:].replace([np.inf, -np.inf], np.nan)
    current = ((target >= threshold) if operator == '>=' else (target <= threshold)).astype(float)
    current[target.isna()] = np.nan  # undefined duration/ratio is not a negative target
    future = current.shift(-horizon).reindex(X.index)
    availability = pd.Series(index + horizon * window_delta(timeframe), index=index).reindex(X.index)
    return X, future, availability, current.reindex(X.index)


def eligible_training(origins, availability, prediction_origin):
    """Labels must already be observable; own feature origin must be earlier."""
    return (origins < prediction_origin) & (availability <= prediction_origin)


def scores(y, pred):
    y, pred = np.asarray(y, dtype=int), np.asarray(pred, dtype=int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return dict(n_rows=len(y), positive_rows=int(y.sum()), positive_rate=float(y.mean()),
                f1=float(f1_score(y, pred, zero_division=0)),
                precision=float(precision_score(y, pred, zero_division=0)),
                recall=float(recall_score(y, pred, zero_division=0)),
                confusion=dict(tn=int(tn), fp=int(fp), fn=int(fn), tp=int(tp)))


def pipeline(key):
    model = _build_model_pipeline(key, max_depth=3, min_samples_leaf=5, random_state=42)
    model.named_steps['imputer'].set_params(keep_empty_features=True)
    return model


def explain_shap(fitted, X):
    """Training-only background and explanation sample; explain raw class-1 output."""
    try:
        import shap
        values = fitted.named_steps['imputer'].transform(X)
        # Deterministic spread over training, no held-out examples in background.
        background = values[np.linspace(0, len(values) - 1, min(64, len(values)), dtype=int)]
        sample = values[np.linspace(0, len(values) - 1, min(64, len(values)), dtype=int)]
        model = fitted.named_steps['model']
        method = 'Tree SHAP'
        try:
            explainer = shap.TreeExplainer(model, data=background,
                                         feature_perturbation='interventional', model_output='raw')
            explanation = explainer(sample, check_additivity=True)
        except Exception:
            if not isinstance(model, HistGradientBoostingClassifier):
                raise
            # Explain the estimator itself when its SHAP tree conversion fails.
            # One deterministic permutation estimates allocation; local accuracy
            # is checked independently against the actual decision function.
            method = 'Permutation SHAP (approximate feature allocation)'
            class ExactBackground(shap.maskers.Independent):
                def invariants(self, x):
                    # np.isclose can merge small distinct occupancies across a
                    # fitted split. Only identical imputed inputs are invariant.
                    return self.data == x
            explanation = shap.PermutationExplainer(model.decision_function, ExactBackground(background), seed=42)(
                sample, max_evals=2 * sample.shape[1] + 1)
        effects = np.asarray(explanation.values)
        base = np.asarray(explanation.base_values)
        if effects.ndim == 3:
            effects, base = effects[:, :, 1], base[:, 1]
        expected = (model.decision_function(sample) if isinstance(model, HistGradientBoostingClassifier)
                    else model.predict_proba(sample)[:, 1])
        if not np.allclose(base.reshape(-1) + effects.sum(axis=1), expected, rtol=1e-5, atol=1e-6):
            raise ValueError('SHAP effects do not reconstruct the fitted model output.')
        names = list(X.columns)
        order = np.argsort(-np.abs(effects).mean(axis=0))[:12]
        rows = [dict(feature=names[j], mean_abs_shap=float(np.abs(effects[:, j]).mean()),
                     values=effects[:, j].tolist(), feature_values=sample[:, j].tolist()) for j in order]
        return dict(status='available', method=method, scope='final model; training examples only',
                    scale='class-1 probability' if hasattr(fitted.named_steps['model'], 'feature_importances_') else 'class-1 log-odds',
                    n_background=len(background), n_explained=len(sample), rows=rows,
                    base_values=base.reshape(-1).tolist())
    except Exception as exc:
        # SHAP is an optional explanation, never fabricated as zero importance.
        return dict(status='unavailable', reason=str(exc), rows=[])


def run_experiment(X, y, availability, current, *, development_end, observed_through, models, horizon, timeframe):
    cutoff, end = utc(development_end), utc(observed_through)
    if cutoff >= end or cutoff not in X.index or end != X.index[-1]:
        raise ValueError('Choose a development cutoff on the feature grid strictly before observation end.')
    if not models or len(set(models)) != len(models) or any(k not in MODEL_DISPLAY_NAMES for k in models):
        raise ValueError('Select supported, nonduplicate classifiers.')
    dev = eligible_training(X.index, availability, cutoff) & y.notna()
    hold = (X.index >= cutoff) & (availability <= end) & y.notna()
    if int(dev.sum()) < 8 or int(hold.sum()) < 2:
        raise ValueError('Insufficient label-eligible history: at least 8 development and 2 held-out examples are required. Reduce the horizon or provide more history; no cutoff is chosen automatically.')
    if y[dev].nunique() < 2:
        raise ValueError('Development target has only one class. No binary models can be compared.')
    if X.iloc[-1].notna().sum() == 0:
        raise ValueError('The latest feature row contains no observable predictor values; no future forecast is issued.')
    if X.loc[dev].notna().sum().sum() == 0:
        raise ValueError('No predictor observations are available in development training.')
    entirely_missing = X.columns[X.loc[dev].notna().sum() == 0].tolist()
    if entirely_missing:
        raise ValueError('Predictors with no development observations must be deselected: ' + ', '.join(entirely_missing))
    D, Y = X.loc[dev], y.loc[dev].astype(int)
    plans = []
    for fold, (train, validation) in enumerate(TimeSeriesSplit(n_splits=min(5, len(D) - 1)).split(D), 1):
        origin = D.index[validation[0]]
        train = train[np.asarray(availability.loc[D.index[train]] <= origin)]
        reason = 'single_class_training' if len(train) and Y.iloc[train].nunique() < 2 else 'no_observable_training_labels' if not len(train) else None
        plans.append((train, validation, dict(fold=fold, prediction_origin=str(origin),
                    train_origins=[str(t) for t in D.index[train]],
                    train_label_available=[str(t) for t in availability.loc[D.index[train]]],
                    n_train=len(train), n_test=len(validation), status=reason or 'valid')))
    valid = [p for p in plans if p[2]['status'] == 'valid']
    if not valid:
        raise ValueError('No valid temporal folds remain after label-availability purging and two-class checks.')
    output, fitted_final = [], {}
    for key in models:
        folds = []
        for train, validation, meta in valid:
            fitted = pipeline(key).fit(D.iloc[train], Y.iloc[train])
            folds.append(dict(**meta, **scores(Y.iloc[validation], fitted.predict(D.iloc[validation]))))
        development_model = pipeline(key).fit(D, Y)
        held = scores(y.loc[hold], development_model.predict(X.loc[hold]))
        # Final forecast refit: labels observable by the actual fitting origin only.
        final = eligible_training(X.index, availability, end) & y.notna()
        final_model = pipeline(key).fit(X.loc[final], y.loc[final].astype(int))
        fitted_final[key] = (final_model, X.loc[final])
        pred = int(final_model.predict(X.tail(1))[0])
        probability = float(final_model.predict_proba(X.tail(1))[0, list(final_model.named_steps['model'].classes_).index(1)])
        importance = getattr(final_model.named_steps['model'], 'feature_importances_', None)
        output.append(dict(model_key=key, model_label=MODEL_DISPLAY_NAMES[key], horizon=horizon,
            cv=dict(f1=float(np.mean([f['f1'] for f in folds])), precision=float(np.mean([f['precision'] for f in folds])),
                    recall=float(np.mean([f['recall'] for f in folds])), valid_folds=len(folds),
                    folds=[dict(meta, **next(({k: v for k, v in f.items() if k not in meta} for f in folds if f['fold'] == meta['fold']), {})) for _, _, meta in plans]),
            holdout=held, n_training_rows=int(final.sum()), positive_training_rows=int(y.loc[final].sum()),
            feature_importance=sorted([dict(feature=n, importance=float(v)) for n, v in zip(X.columns, importance)], key=lambda r: -r['importance']) if importance is not None else [],
            forecast=dict(origin=str(end), target_start=str(end + (horizon - 1) * window_delta(timeframe)),
                          target_end=str(end + horizon * window_delta(timeframe)), predicted_class=pred,
                          probability=probability, probability_calibrated=False,
                          feature_origin=str(X.index[-1]), latest_training_origin=str(X.index[final][-1]),
                          latest_training_label_available=str(availability.loc[final].max()))))
    selected = max(output, key=lambda m: m['cv']['f1'])['model_key']
    # Selection is completed before any held-out score is used.
    majority = int(Y.mean() > .5)
    persist = hold & current.notna()
    baselines = [dict(model='Majority class (development)', **scores(y.loc[hold], np.full(int(hold.sum()), majority)))]
    if persist.any():
        baselines.append(dict(model='Persistence (last observed condition)', **scores(y.loc[persist], current.loc[persist])))
    else:
        baselines.append(dict(model='Persistence', status='unavailable: current target undefined for all held-out origins'))
    from backend.prediction_view import decision_tree_view
    for row in output:
        fitted, training = fitted_final[row['model_key']]
        row['decision_tree'] = decision_tree_view(SimpleNamespace(model_key=row['model_key'], pipeline=fitted, feature_names=list(X.columns)))
        row['shap'] = explain_shap(fitted, training) if row['model_key'] != 'decision_tree' else dict(status='not_applicable', rows=[])
    evidence_warning = 'Limited held-out evidence: fewer than 20 windows or fewer than 5 examples of either class. Treat performance as exploratory.' if int(hold.sum()) < 20 or int(y.loc[hold].sum()) < 5 or int((1-y.loc[hold]).sum()) < 5 else None
    return dict(evidence_warning=evidence_warning, protocol_version=PROTOCOL_VERSION, selected_model=selected, selection_basis='development purged CV mean F1; never held-out scores',
                development_end=str(cutoff), observed_through=str(end), models=output, baselines=baselines,
                holdout_origins=[str(t) for t in X.index[hold]],
                holdout_warning='Held-out period contains only one class; discrimination cannot be established.' if y.loc[hold].nunique() < 2 else None)
