"""Retrospective classification of complete-trace reconstructed zone series.

Temporal folds and label purging do not make the upstream reconstruction causal.
These are exploratory retrospective experiments, never operational evidence.
"""
from types import SimpleNamespace

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

from analytics.forecasting import explain_shap, pipeline, scores, utc, window_delta
from analytics.metrics.schema import CANONICAL_METRICS
from analytics.prediction import MODEL_DISPLAY_NAMES

PROTOCOL = 'retrospective-v3'
DEFAULTS = dict(history_lags=3, cv_folds=5, max_depth=3, min_samples_leaf=5, random_seed=42)
NOTE = ('Exploratory retrospective experiment on complete-trace alignment features. '
        'Reconstruction, model discovery and some metric yardsticks can use later events. '
        'Temporal evaluation does not establish causally available inputs or validated live forecasting. '
        'Repeated feature/threshold choices make these scores exploratory; no untouched test score is claimed.')


def prepare(features, pairs, zone, metric, threshold, operator, horizon, timeframe):
    allowed = {m.name for m in CANONICAL_METRICS}
    if metric not in allowed or any(p['metric'] not in allowed for p in pairs):
        raise ValueError('Choose a documented metric from this analysis.')
    if not np.isfinite(threshold) or operator not in ('>=','<=') or horizon < 1:
        raise ValueError('Use a finite threshold, >= or <=, and a positive fixed horizon.')
    if not pairs or len({(p['zone'],p['metric']) for p in pairs}) != len(pairs):
        raise ValueError('Select nonduplicate predictor zone–metric pairs.')
    frame = features.copy()
    frame['window_start'] = pd.to_datetime(frame.window_start,utc=True)
    if frame.duplicated(['zone','window_start']).any():
        raise ValueError('Zone series contain duplicate windows; no averaging is assumed.')
    delta = window_delta(timeframe)
    starts = pd.date_range(frame.window_start.min(),frame.window_start.max(),freq=timeframe)
    if not frame.window_start.isin(starts).all():
        raise ValueError('Zone windows do not follow one regular analysis grid.')
    index = starts + delta
    def series(z,m):
        if m not in frame or z not in set(frame.zone):
            raise ValueError(f'Unavailable zone or metric: {z} / {m}.')
        values = pd.to_numeric(frame[frame.zone==z].set_index('window_start')[m],errors='coerce').reindex(starts)
        return pd.Series(values.to_numpy(),index=index).replace([np.inf,-np.inf],np.nan)
    target = series(zone,metric)
    current = (target >= threshold if operator=='>=' else target <= threshold).astype(float).where(target.notna())
    X = pd.DataFrame(index=index)
    for pair in pairs:
        name = pair['zone']+'__'+pair['metric']
        X[name] = series(pair['zone'],pair['metric'])
        for lag in range(1,DEFAULTS['history_lags']+1):
            X[f'{name}__lag{lag}'] = X[name].shift(lag)
    X = X.iloc[DEFAULTS['history_lags']:]
    if len(X) <= horizon:
        raise ValueError('Too few windows for three history lags and this horizon. Use a longer history or a justified coarser experiment.')
    y = current.shift(-horizon).reindex(X.index)
    available = pd.Series(index+horizon*delta,index=index).reindex(X.index)
    return X,y,available,current.reindex(X.index)


def fit_model(key, X, y, balance_classes):
    """Weights depend only on this training partition, never its evaluation labels."""
    fitted = pipeline(key)
    kwargs = {}
    if balance_classes:
        counts = y.value_counts()
        kwargs['model__sample_weight'] = y.map(len(y) / (len(counts) * counts)).to_numpy()
    return fitted.fit(X, y, **kwargs)


def evaluate(features,pairs,zone,metric,threshold,operator,horizon,timeframe,balance_classes=False):
    X,y,available,current = prepare(features,pairs,zone,metric,threshold,operator,horizon,timeframe)
    observed = y.notna()
    D,Y = X.loc[observed],y.loc[observed].astype(int)
    if len(D) < 8:
        raise ValueError(f'Only {len(D)} labeled windows remain; at least eight are required after history lags, horizon and missing targets.')
    if Y.nunique() < 2:
        raise ValueError(f'Target has one class: {int(Y.sum())} positive and {int((1-Y).sum())} negative labeled windows. A binary comparison is unavailable. Choose a substantively meaningful condition; no threshold is changed automatically.')
    missing = D.columns[D.notna().sum()==0].tolist()
    if missing:
        raise ValueError('Predictors have no labeled-history observations: '+', '.join(missing))
    plans = []
    for number,(train,test) in enumerate(TimeSeriesSplit(n_splits=min(DEFAULTS['cv_folds'],len(D)-1)).split(D),1):
        origin = D.index[test[0]]
        train = train[np.asarray(available.loc[D.index[train]] <= origin)]
        status = 'valid' if len(train) and Y.iloc[train].nunique()==2 else 'single-class training' if len(train) else 'no label-eligible training rows'
        plans.append((train,test,dict(fold=number,status=status,n_train=len(train),n_test=len(test),
            training_positive_windows=int(Y.iloc[train].sum()),training_negative_windows=int((1-Y.iloc[train]).sum()),
            evaluation_positive_windows=int(Y.iloc[test].sum()),evaluation_negative_windows=int((1-Y.iloc[test]).sum()),
            first_evaluation_origin=str(origin),latest_training_label_available=str(available.loc[D.index[train]].max()) if len(train) else None)))
    valid = [p for p in plans if p[2]['status']=='valid']
    if not valid:
        raise ValueError('No valid temporal folds remain after label purging and two-class checks. No performance is reported.')
    models, baseline_rows = [], []
    for key,label in MODEL_DISPLAY_NAMES.items():
        folds,predictions,majority_truth,majority_pred,persist_truth,persist_pred = [],[],[],[],[],[]
        for train,test,meta in valid:
            fitted = fit_model(key,D.iloc[train],Y.iloc[train],balance_classes)
            pred = fitted.predict(D.iloc[test])
            truth = Y.iloc[test]
            folds.append(dict(**meta,**scores(truth,pred)))
            predictions.extend(dict(origin=str(origin),actual=int(actual),predicted=int(guess)) for origin,actual,guess in zip(truth.index,truth,pred))
            majority_truth.extend(truth.tolist());majority_pred.extend([int(Y.iloc[train].mean()>.5)]*len(test))
            now = current.reindex(truth.index)
            persist_truth.extend(truth[now.notna()].tolist());persist_pred.extend(now.dropna().astype(int).tolist())
        final = fit_model(key,D,Y,balance_classes)
        importance = getattr(final.named_steps['model'],'feature_importances_',None)
        estimate = dict(status='unavailable',reason='Latest reconstructed window has no predictor values.')
        if X.iloc[-1].notna().any():
            guess = int(final.predict(X.tail(1))[0])
            probability = float(final.predict_proba(X.tail(1))[0,list(final.named_steps['model'].classes_).index(1)])
            estimate = dict(status='available',origin=str(X.index[-1]),target_start=str(X.index[-1]+(horizon-1)*window_delta(timeframe)),
                target_end=str(X.index[-1]+horizon*window_delta(timeframe)),predicted_class=guess,probability=probability,
                latest_training_origin=str(D.index[-1]),latest_training_label_available=str(available.loc[D.index].max()))
        from backend.prediction_view import decision_tree_view
        pooled = scores([p['actual'] for p in predictions],[p['predicted'] for p in predictions])
        diagnostic = (f"All {pooled['positive_rows']} positive evaluation windows were missed "
            f"({pooled['confusion']['fp']} false alarms)."
            if pooled['confusion']['tp']==0 and pooled['positive_rows'] else
            'No positive conditions occurred in evaluated windows; positive-class F1 is not informative.'
            if not pooled['positive_rows'] else None)
        models.append(dict(model_key=key,model_label=label,diagnostic=diagnostic,mean_f1=float(np.mean([f['f1'] for f in folds])),
            mean_precision=float(np.mean([f['precision'] for f in folds])),mean_recall=float(np.mean([f['recall'] for f in folds])),
            valid_folds=len(valid),evaluation=pooled,
            folds=[next((f for f in folds if f['fold']==m['fold']),m) for _,_,m in plans],predictions=predictions,
            estimate=estimate,feature_importance=[dict(feature=n,importance=float(v)) for n,v in zip(X.columns,importance) if v>=.005] if importance is not None else [],
            decision_tree=decision_tree_view(SimpleNamespace(model_key=key,pipeline=final,feature_names=list(X.columns))),
            shap=explain_shap(final,D) if key!='decision_tree' else dict(status='not_applicable',rows=[])))
        if not baseline_rows:
            baseline_rows=[dict(model='Training-majority baseline',**scores(majority_truth,majority_pred))]
            baseline_rows.append(dict(model='Persistence: current reconstructed condition',**scores(persist_truth,persist_pred)) if persist_truth else dict(model='Persistence',status='unavailable: current condition missing'))
    persistence = next((b for b in baseline_rows if b['model'].startswith('Persistence')),None)
    comparable = persistence and persistence.get('n_rows')==models[0]['evaluation']['n_rows']
    baseline_note = ('No classifier exceeded persistence on pooled F1 in this exploratory comparison.'
        if comparable and max(m['evaluation']['f1'] for m in models)<=persistence['f1'] else
        'At least one classifier exceeded persistence on pooled F1 in this exploratory comparison; this does not establish live forecasting accuracy.'
        if comparable else 'Persistence has different or unavailable evaluation support. Check row counts before comparing scores.')
    return dict(protocol_version=PROTOCOL,interpretation=NOTE,defaults=DEFAULTS,baseline_note=baseline_note,target=dict(zone=zone,metric=metric,threshold=threshold,operator=operator),
        horizon=horizon,timeframe=timeframe,balance_classes=balance_classes,feature_pairs=pairs,training_windows=len(D),positive_windows=int(Y.sum()),negative_windows=int((1-Y).sum()),
        positive_rate=float(Y.mean()),models=models,baselines=baseline_rows,
        warning='Limited class support: fewer than five labeled examples of either class. Interpret results cautiously.' if min(Y.sum(),(1-Y).sum())<5 else None)
