from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier, export_text

from analytics.metrics.compat import canonical_metric_name, canonicalize_metric_names
from analytics.metrics.groups import get_default_ml_metrics


MODEL_DISPLAY_NAMES = {
    "decision_tree": "Decision tree",
    "random_forest": "Random forest",
    "hist_gradient_boosting": "Hist gradient boosting",
}


@dataclass
class MLResult:
    model_key: str
    model_label: str
    horizon: int
    n_rows: int
    positive_rows: int
    positive_rate: float
    mean_f1: float
    mean_precision: float
    mean_recall: float
    confusion_matrix_total: np.ndarray
    tp: int
    fn: int
    fp: int
    tn: int
    target_entropy: float
    root_entropy_df: pd.DataFrame
    feature_importance_df: pd.DataFrame
    cv_predictions: pd.DataFrame
    tree_rules_text: str
    latest_window_start: pd.Timestamp | None
    latest_pred_class: int | None
    latest_pred_prob: float | None
    pipeline: Pipeline
    feature_names: list[str]
    per_fold_metrics: pd.DataFrame


def list_supported_models() -> list[str]:
    return list(MODEL_DISPLAY_NAMES)


def get_model_label(model_key: str) -> str:
    return MODEL_DISPLAY_NAMES.get(model_key, model_key)


def model_supports_tree_details(model_key: str) -> bool:
    return model_key == "decision_tree"

def get_default_feature_metrics(zf: pd.DataFrame) -> list[str]:
    """Return a sensible default metric subset that exists in the dataframe."""
    existing = get_default_ml_metrics(list(zf.columns))
    numeric_only = []
    for col in existing:
        if col in zf.columns and pd.api.types.is_numeric_dtype(zf[col]):
            numeric_only.append(col)
    if numeric_only:
        return numeric_only
    return list_numeric_zone_metrics(zf)


def list_numeric_zone_metrics(zf: pd.DataFrame) -> list[str]:
    excluded = {"window_start", "zone", "window_end"}
    out = []
    for col in zf.columns:
        if col in excluded:
            continue
        if pd.api.types.is_numeric_dtype(zf[col]):
            out.append(col)
    return out


def make_wide_feature_table(
    zf: pd.DataFrame,
    metrics: Sequence[str],
    history_lags: int = 3,
) -> pd.DataFrame:
    """
    Build one row per window_start and one column per zone-metric combination,
    then append lagged copies of those columns.

    Example column names:
      Registration__token_present_end
      Registration__token_present_end__lag1
      Doctor__token_avg_age_open__lag2
    """
    required = {"window_start", "zone"}
    missing = required - set(zf.columns)
    if missing:
        raise ValueError("zf is missing required columns: {}".format(sorted(missing)))

    metrics = canonicalize_metric_names(list(metrics))
    if not metrics:
        raise ValueError("Select at least one feature metric.")

    work = zf.copy()
    work["window_start"] = pd.to_datetime(work["window_start"])
    work = work.sort_values(["window_start", "zone"])

    pieces: list[pd.DataFrame] = []
    for metric in metrics:
        if metric not in work.columns:
            continue

        wide = work.pivot_table(
            index="window_start",
            columns="zone",
            values=metric,
            aggfunc="mean",
        )
        if wide.empty:
            continue

        wide = wide.sort_index()
        wide.columns = ["{}__{}".format(str(zone), metric) for zone in wide.columns]
        pieces.append(wide)

    if not pieces:
        raise ValueError("None of the selected metrics could be converted into a feature table.")

    X0 = pd.concat(pieces, axis=1).sort_index()
    X0 = X0.loc[:, ~X0.columns.duplicated()].copy()

    lag_frames = [X0]
    for lag in range(1, int(history_lags) + 1):
        lagged = X0.shift(lag)
        lagged.columns = ["{}__lag{}".format(c, lag) for c in X0.columns]
        lag_frames.append(lagged)

    X = pd.concat(lag_frames, axis=1).sort_index()
    X.index.name = "window_start"
    return X


def build_binary_target_from_metric_threshold(
    zf: pd.DataFrame,
    target_zone: str,
    target_metric: str,
    threshold: float,
    operator: str = ">=",
) -> pd.Series:
    """
    Create a 0/1 label per window for one target zone using a metric threshold.
    Only windows where the target zone exists are labeled.
    """
    target_metric = canonical_metric_name(target_metric)
    required = {"window_start", "zone", target_metric}
    missing = required - set(zf.columns)
    if missing:
        raise ValueError("zf is missing required columns for target label: {}".format(sorted(missing)))

    zone_df = zf.loc[zf["zone"] == target_zone, ["window_start", target_metric]].copy()
    if zone_df.empty:
        raise ValueError("No rows found for target zone '{}'.".format(target_zone))

    zone_df["window_start"] = pd.to_datetime(zone_df["window_start"])
    zone_df = zone_df.drop_duplicates(subset=["window_start"]).sort_values("window_start")

    if operator == ">=":
        label = (zone_df[target_metric].astype(float) >= float(threshold)).astype(int)
    elif operator == "<=":
        label = (zone_df[target_metric].astype(float) <= float(threshold)).astype(int)
    else:
        raise ValueError("operator must be '>=' or '<='")

    out = pd.Series(label.values, index=zone_df["window_start"], name="target")
    out.index.name = "window_start"
    return out


def build_binary_target_from_flag_table(
    zf: pd.DataFrame,
    flagged_df: pd.DataFrame,
    target_zone: str,
) -> pd.Series:
    """
    Turn a flagged rows table into a 0/1 series for one target zone.
    Windows where the target zone does not exist are excluded instead of forced to 0.
    """
    required_zf = {"window_start", "zone"}
    required_flagged = {"window_start", "zone"}
    if not required_zf.issubset(zf.columns):
        raise ValueError("zf must contain 'window_start' and 'zone'.")
    if flagged_df is None or flagged_df.empty:
        flagged_df = pd.DataFrame(columns=["window_start", "zone"])
    if not required_flagged.issubset(flagged_df.columns):
        raise ValueError("flagged_df must contain 'window_start' and 'zone'.")

    target_windows = (
        zf.loc[zf["zone"] == target_zone, ["window_start"]]
        .drop_duplicates()
        .copy()
    )
    if target_windows.empty:
        raise ValueError("No rows found for target zone '{}'.".format(target_zone))

    target_windows["window_start"] = pd.to_datetime(target_windows["window_start"])
    target_windows = target_windows.sort_values("window_start")

    flagged_zone = (
        flagged_df.loc[flagged_df["zone"] == target_zone, ["window_start"]]
        .drop_duplicates()
        .copy()
    )
    if not flagged_zone.empty:
        flagged_zone["window_start"] = pd.to_datetime(flagged_zone["window_start"])
        flagged_zone["target"] = 1

    merged = target_windows.merge(flagged_zone, on="window_start", how="left")
    merged["target"] = merged["target"].fillna(0).astype(int)

    out = pd.Series(merged["target"].values, index=merged["window_start"], name="target")
    out.index.name = "window_start"
    return out


def make_supervised_dataset(
    X: pd.DataFrame,
    y_current: pd.Series,
    horizon: int,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Shift labels backward so features at time t predict the label at time t+horizon.
    """
    if horizon < 1:
        raise ValueError("horizon must be at least 1.")

    X2 = X.copy()
    X2.index = pd.to_datetime(X2.index)
    X2 = X2.sort_index()

    y2 = y_current.copy()
    y2.index = pd.to_datetime(y2.index)
    y2 = y2.sort_index()

    common_index = X2.index.intersection(y2.index)
    X2 = X2.loc[common_index].sort_index()
    y2 = y2.loc[common_index].sort_index()

    y_future = y2.shift(-int(horizon))
    mask = y_future.notna()

    X_final = X2.loc[mask].copy()
    y_final = y_future.loc[mask].astype(int).copy()
    y_final.name = "target_future"

    return X_final, y_final

def _binary_entropy_from_counts(n_neg: int, n_pos: int) -> float:
    total = int(n_neg) + int(n_pos)
    if total == 0:
        return 0.0

    p_neg = float(n_neg) / float(total)
    p_pos = float(n_pos) / float(total)

    out = 0.0
    if p_neg > 0:
        out -= p_neg * np.log2(p_neg)
    if p_pos > 0:
        out -= p_pos * np.log2(p_pos)
    return float(out)


def _binary_entropy_from_series(y: pd.Series) -> float:
    y = pd.Series(y).astype(int)
    n_neg = int((y == 0).sum())
    n_pos = int((y == 1).sum())
    return _binary_entropy_from_counts(n_neg, n_pos)


def _best_numeric_entropy_split(x: pd.Series, y: pd.Series) -> dict | None:
    """
    For one numeric descriptive feature, derive candidate thresholds from points
    where the target changes, then choose the threshold with the highest information gain.
    """
    df = pd.DataFrame(
        {
            "x": pd.to_numeric(x, errors="coerce"),
            "y": pd.Series(y).astype(int),
        }
    ).dropna()

    if df.empty or len(df) < 2:
        return None
    if df["y"].nunique() < 2:
        return None
    if df["x"].nunique() < 2:
        return None

    df = df.sort_values(["x", "y"]).reset_index(drop=True)

    thresholds = []
    for i in range(len(df) - 1):
        x_left = float(df.loc[i, "x"])
        x_right = float(df.loc[i + 1, "x"])
        y_left = int(df.loc[i, "y"])
        y_right = int(df.loc[i + 1, "y"])

        if y_left != y_right and x_left != x_right:
            thresholds.append((x_left + x_right) / 2.0)

    thresholds = sorted(set(thresholds))
    if not thresholds:
        return None

    parent_entropy = _binary_entropy_from_series(df["y"])
    best = None

    for thr in thresholds:
        left = df.loc[df["x"] <= thr, "y"]
        right = df.loc[df["x"] > thr, "y"]

        if left.empty or right.empty:
            continue

        left_neg = int((left == 0).sum())
        left_pos = int((left == 1).sum())
        right_neg = int((right == 0).sum())
        right_pos = int((right == 1).sum())

        left_entropy = _binary_entropy_from_counts(left_neg, left_pos)
        right_entropy = _binary_entropy_from_counts(right_neg, right_pos)

        weighted_entropy = (
            float(len(left)) / float(len(df)) * left_entropy
            + float(len(right)) / float(len(df)) * right_entropy
        )
        information_gain = parent_entropy - weighted_entropy

        row = {
            "threshold": float(thr),
            "left_neg": left_neg,
            "left_pos": left_pos,
            "right_neg": right_neg,
            "right_pos": right_pos,
            "left_entropy": float(left_entropy),
            "right_entropy": float(right_entropy),
            "weighted_entropy": float(weighted_entropy),
            "information_gain": float(information_gain),
        }

        if best is None or row["information_gain"] > best["information_gain"]:
            best = row

    return best


def build_root_entropy_table(X: pd.DataFrame, y: pd.Series) -> tuple[float, pd.DataFrame]:
    """
    Build a class-style table for the first split:
    - entropy(target)
    - best threshold per descriptive feature
    - partial entropies
    - weighted entropy
    - information gain
    """
    if X.empty or y.empty:
        return 0.0, pd.DataFrame()

    imputer = SimpleImputer(strategy="median")
    X_imp = pd.DataFrame(
        imputer.fit_transform(X),
        index=X.index,
        columns=X.columns,
    )

    parent_entropy = _binary_entropy_from_series(y)

    rows = []
    for feature in X_imp.columns:
        best = _best_numeric_entropy_split(X_imp[feature], y)
        if best is None:
            continue

        rows.append(
            {
                "feature": feature,
                "threshold": best["threshold"],
                "left_neg": best["left_neg"],
                "left_pos": best["left_pos"],
                "right_neg": best["right_neg"],
                "right_pos": best["right_pos"],
                "left_entropy": best["left_entropy"],
                "right_entropy": best["right_entropy"],
                "weighted_entropy": best["weighted_entropy"],
                "information_gain": best["information_gain"],
            }
        )

    if not rows:
        return parent_entropy, pd.DataFrame()

    out = pd.DataFrame(rows).sort_values(
        ["information_gain", "weighted_entropy", "feature"],
        ascending=[False, True, True],
    ).reset_index(drop=True)

    return float(parent_entropy), out


def _safe_n_splits(n_rows: int, requested_n_splits: int) -> int:
    return max(2, min(int(requested_n_splits), max(2, n_rows - 1)))


def _build_model_pipeline(
    model_key: str,
    *,
    max_depth: int,
    min_samples_leaf: int,
    random_state: int,
) -> Pipeline:
    if model_key == "decision_tree":
        model = DecisionTreeClassifier(
            criterion="entropy",
            max_depth=int(max_depth),
            min_samples_leaf=int(min_samples_leaf),
            random_state=int(random_state),
        )
    elif model_key == "random_forest":
        model = RandomForestClassifier(
            n_estimators=200,
            criterion="entropy",
            max_depth=int(max_depth),
            min_samples_leaf=int(min_samples_leaf),
            n_jobs=1,
            random_state=int(random_state),
        )
    elif model_key == "hist_gradient_boosting":
        model = HistGradientBoostingClassifier(
            max_depth=int(max_depth),
            min_samples_leaf=int(min_samples_leaf),
            random_state=int(random_state),
        )
    else:
        raise ValueError("Unsupported model_key '{}'.".format(model_key))

    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("model", model),
        ]
    )


def train_evaluate_timeseries_model(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    model_key: str,
    horizon: int,
    max_depth: int = 3,
    min_samples_leaf: int = 5,
    n_splits: int = 5,
    random_state: int = 42,
) -> MLResult:
    """
    Time-series CV for one early-warning model.
    Fits a final model on all available rows after CV.
    """
    X_train, y_train = make_supervised_dataset(X, y, horizon=horizon)
    if X_train.empty or y_train.empty:
        raise ValueError("No supervised rows remain after horizon shifting.")

    if y_train.nunique() < 2:
        raise ValueError(
            "Target has only one class after horizon shifting. Choose a different zone, threshold, or horizon."
        )

    usable_splits = _safe_n_splits(len(X_train), n_splits)
    if len(X_train) <= usable_splits:
        usable_splits = max(2, len(X_train) - 1)
    if usable_splits < 2:
        raise ValueError("Not enough rows for time-series cross-validation.")

    cv = TimeSeriesSplit(n_splits=usable_splits)

    pipeline = _build_model_pipeline(
        model_key,
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
        random_state=random_state,
    )

    fold_metrics = []
    pred_rows = []
    cm_total = np.zeros((2, 2), dtype=int)

    for fold_id, (train_idx, test_idx) in enumerate(cv.split(X_train), start=1):
        X_tr = X_train.iloc[train_idx]
        y_tr = y_train.iloc[train_idx]
        X_te = X_train.iloc[test_idx]
        y_te = y_train.iloc[test_idx]

        if y_tr.nunique() < 2:
            continue

        pipeline.fit(X_tr, y_tr)
        y_pred = pipeline.predict(X_te)

        if hasattr(pipeline.named_steps["model"], "predict_proba"):
            y_score = pipeline.predict_proba(X_te)[:, 1]
        else:
            y_score = np.full(shape=len(X_te), fill_value=np.nan)

        cm = confusion_matrix(y_te, y_pred, labels=[0, 1])
        cm_total += cm

        fold_metrics.append(
            {
                "fold": fold_id,
                "n_test": int(len(y_te)),
                "positives_test": int(y_te.sum()),
                "f1": float(f1_score(y_te, y_pred, zero_division=0)),
                "precision": float(precision_score(y_te, y_pred, zero_division=0)),
                "recall": float(recall_score(y_te, y_pred, zero_division=0)),
            }
        )

        pred_rows.append(
            pd.DataFrame(
                {
                    "window_start": X_te.index,
                    "y_true": y_te.values,
                    "y_pred": y_pred,
                    "y_score": y_score,
                    "fold": fold_id,
                }
            )
        )

    if not fold_metrics:
        raise ValueError(
            "No valid folds could be trained. This usually means the positive class is too rare in the earlier training windows."
        )

    per_fold_metrics = pd.DataFrame(fold_metrics)
    cv_predictions = pd.concat(pred_rows, ignore_index=True).sort_values("window_start")

    pipeline.fit(X_train, y_train)

    feature_names = list(X_train.columns)
    model = pipeline.named_steps["model"]

    importances = getattr(model, "feature_importances_", np.zeros(len(feature_names)))
    feature_importance_df = (
        pd.DataFrame({"feature": feature_names, "importance": importances})
        .sort_values("importance", ascending=False)
        .reset_index(drop=True)
    )

    tree_rules_text = export_text(model, feature_names=feature_names) if model_supports_tree_details(model_key) else ""

    latest_window_start = None
    latest_pred_class = None
    latest_pred_prob = None
    if len(X_train) > 0:
        latest_window_start = pd.to_datetime(X_train.index[-1])
        latest_X = X_train.tail(1)
        latest_pred_class = int(pipeline.predict(latest_X)[0])
        if hasattr(model, "predict_proba"):
            latest_pred_prob = float(pipeline.predict_proba(latest_X)[0, 1])

    target_entropy = 0.0
    root_entropy_df = pd.DataFrame()
    if model_supports_tree_details(model_key):
        target_entropy, root_entropy_df = build_root_entropy_table(X_train, y_train)

    tn = int(cm_total[0, 0])
    fp = int(cm_total[0, 1])
    fn = int(cm_total[1, 0])
    tp = int(cm_total[1, 1])

    return MLResult(
        model_key=model_key,
        model_label=get_model_label(model_key),
        horizon=int(horizon),
        n_rows=int(len(X_train)),
        positive_rows=int(y_train.sum()),
        positive_rate=float(y_train.mean()),
        mean_f1=float(per_fold_metrics["f1"].mean()),
        mean_precision=float(per_fold_metrics["precision"].mean()),
        mean_recall=float(per_fold_metrics["recall"].mean()),
        confusion_matrix_total=cm_total,
        tp=tp,
        fn=fn,
        fp=fp,
        tn=tn,
        target_entropy=float(target_entropy),
        root_entropy_df=root_entropy_df,
        feature_importance_df=feature_importance_df,
        cv_predictions=cv_predictions,
        tree_rules_text=tree_rules_text,
        latest_window_start=latest_window_start,
        latest_pred_class=latest_pred_class,
        latest_pred_prob=latest_pred_prob,
        pipeline=pipeline,
        feature_names=feature_names,
        per_fold_metrics=per_fold_metrics,
    )


def train_evaluate_tree_timeseries(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    horizon: int,
    max_depth: int = 3,
    min_samples_leaf: int = 5,
    n_splits: int = 5,
    random_state: int = 42,
) -> MLResult:
    return train_evaluate_timeseries_model(
        X,
        y,
        model_key="decision_tree",
        horizon=horizon,
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
        n_splits=n_splits,
        random_state=random_state,
    )


def scan_horizons(
    X: pd.DataFrame,
    y: pd.Series,
    horizons: Iterable[int],
    *,
    model_key: str = "decision_tree",
    max_depth: int = 3,
    min_samples_leaf: int = 5,
    n_splits: int = 5,
    random_state: int = 42,
) -> tuple[pd.DataFrame, int | None]:
    """
    Train one tree per horizon and return a summary table plus the best horizon by mean F1.
    """
    rows = []
    best_h = None
    best_f1 = -np.inf

    for h in horizons:
        try:
            res = train_evaluate_timeseries_model(
                X,
                y,
                model_key=model_key,
                horizon=int(h),
                max_depth=max_depth,
                min_samples_leaf=min_samples_leaf,
                n_splits=n_splits,
                random_state=random_state,
            )
            rows.append(
                {
                    "model": get_model_label(model_key),
                    "model_key": model_key,
                    "horizon": int(h),
                    "mean_f1": res.mean_f1,
                    "mean_precision": res.mean_precision,
                    "mean_recall": res.mean_recall,
                    "n_rows": res.n_rows,
                    "positive_rows": res.positive_rows,
                    "positive_rate": res.positive_rate,
                    "status": "ok",
                }
            )
            if res.mean_f1 > best_f1:
                best_f1 = res.mean_f1
                best_h = int(h)
        except Exception as exc:
            rows.append(
                {
                    "model": get_model_label(model_key),
                    "model_key": model_key,
                    "horizon": int(h),
                    "mean_f1": np.nan,
                    "mean_precision": np.nan,
                    "mean_recall": np.nan,
                    "n_rows": np.nan,
                    "positive_rows": np.nan,
                    "positive_rate": np.nan,
                    "status": str(exc),
                }
            )

    summary = pd.DataFrame(rows).sort_values("horizon").reset_index(drop=True)
    return summary, best_h


def train_compare_models(
    X: pd.DataFrame,
    y: pd.Series,
    model_keys: Sequence[str],
    *,
    search_best_horizon: bool,
    fixed_horizon: int,
    max_horizon: int,
    max_depth: int = 3,
    min_samples_leaf: int = 5,
    n_splits: int = 5,
    random_state: int = 42,
) -> tuple[dict[str, MLResult], dict[str, pd.DataFrame | None], pd.DataFrame]:
    results: dict[str, MLResult] = {}
    horizon_scans: dict[str, pd.DataFrame | None] = {}
    comparison_rows: list[dict] = []

    for model_key in model_keys:
        horizon_scan_df = None
        selected_horizon = int(fixed_horizon)

        if search_best_horizon:
            horizon_scan_df, best_horizon = scan_horizons(
                X,
                y,
                horizons=range(1, int(max_horizon) + 1),
                model_key=model_key,
                max_depth=max_depth,
                min_samples_leaf=min_samples_leaf,
                n_splits=n_splits,
                random_state=random_state,
            )
            if best_horizon is None:
                status = (
                    str(horizon_scan_df.loc[horizon_scan_df["status"] != "ok", "status"].iloc[0])
                    if horizon_scan_df is not None and not horizon_scan_df.empty and (horizon_scan_df["status"] != "ok").any()
                    else "No valid horizon found."
                )
                comparison_rows.append(
                    {
                        "model": get_model_label(model_key),
                        "model_key": model_key,
                        "selected_horizon": np.nan,
                        "mean_f1": np.nan,
                        "mean_precision": np.nan,
                        "mean_recall": np.nan,
                        "n_rows": np.nan,
                        "positive_rows": np.nan,
                        "positive_rate": np.nan,
                        "status": status,
                    }
                )
                horizon_scans[model_key] = horizon_scan_df
                continue
            selected_horizon = int(best_horizon)

        result = train_evaluate_timeseries_model(
            X,
            y,
            model_key=model_key,
            horizon=selected_horizon,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            n_splits=n_splits,
            random_state=random_state,
        )
        results[model_key] = result
        horizon_scans[model_key] = horizon_scan_df
        comparison_rows.append(
            {
                "model": result.model_label,
                "model_key": model_key,
                "selected_horizon": result.horizon,
                "mean_f1": result.mean_f1,
                "mean_precision": result.mean_precision,
                "mean_recall": result.mean_recall,
                "n_rows": result.n_rows,
                "positive_rows": result.positive_rows,
                "positive_rate": result.positive_rate,
                "status": "ok",
            }
        )

    comparison_df = pd.DataFrame(comparison_rows)
    if not comparison_df.empty:
        comparison_df = comparison_df.sort_values(
            ["mean_f1", "mean_precision", "model"],
            ascending=[False, False, True],
            na_position="last",
        ).reset_index(drop=True)
    return results, horizon_scans, comparison_df
