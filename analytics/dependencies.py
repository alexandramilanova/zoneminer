import pandas as pd
import numpy as np

from analytics.metrics.compat import canonical_metric_name


def prepare_dependency_metric_frames(
    zf: pd.DataFrame,
    metrics: list[str],
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    if zf.empty or "window_start" not in zf.columns or "zone" not in zf.columns:
        return frames

    for metric in metrics:
        canonical = canonical_metric_name(metric)
        if canonical not in zf.columns:
            continue
        frames[canonical] = (
            zf.pivot_table(
                index="window_start",
                columns="zone",
                values=canonical,
                aggfunc="mean",
            )
            .sort_index()
        )

    return frames


def lagged_best_corr(
    x: pd.Series,
    y: pd.Series,
    max_lag: int,
    min_lag: int = 0,
    min_points: int = 8,
    correlate_changes: bool = False,
):
    best_corr = np.nan
    best_lag = None
    best_n = 0

    x = pd.to_numeric(x, errors="coerce")
    y = pd.to_numeric(y, errors="coerce")

    if correlate_changes:
        x = x.diff()
        y = y.diff()

    max_lag = max(int(max_lag), 0)
    min_lag = max(int(min_lag), 0)
    if min_lag > max_lag:
        min_lag = max_lag

    for lag in range(min_lag, max_lag + 1):
        yy = y.shift(-lag)
        df = pd.concat(
            [x.rename("x"), yy.rename("y")],
            axis=1
        ).dropna()

        if len(df) < min_points:
            continue
        if df["x"].nunique() <= 1 or df["y"].nunique() <= 1:
            continue

        c = df["x"].corr(df["y"])
        if pd.isna(c):
            continue

        if (
            best_lag is None
            or abs(c) > abs(best_corr)
            or (np.isclose(abs(c), abs(best_corr)) and lag < best_lag)
        ):
            best_corr = float(c)
            best_lag = int(lag)
            best_n = int(len(df))

    return best_corr, best_lag, best_n


def compute_propagation_table_from_frames(
    metric_frames: dict[str, pd.DataFrame],
    src_metric: str,
    tgt_metric: str,
    max_lag: int,
    min_lag: int = 0,
    min_points: int = 8,
    correlate_changes: bool = False,
):
    src_metric = canonical_metric_name(src_metric)
    tgt_metric = canonical_metric_name(tgt_metric)

    src = metric_frames.get(src_metric)
    tgt = metric_frames.get(tgt_metric)
    if src is None or tgt is None or src.empty or tgt.empty:
        return pd.DataFrame(columns=[
            "from_zone",
            "to_zone",
            "src_metric",
            "tgt_metric",
            "best_corr",
            "best_lag_windows",
            "overlap_points",
        ])

    idx = src.index.intersection(tgt.index)
    src, tgt = src.loc[idx], tgt.loc[idx]

    rows = []
    zones = list(src.columns.intersection(tgt.columns))

    for a in zones:
        for b in zones:
            if a == b:
                continue

            c, lag, n = lagged_best_corr(
                src[a],
                tgt[b],
                max_lag=max_lag,
                min_lag=min_lag,
                min_points=min_points,
                correlate_changes=correlate_changes,
            )

            rows.append({
                "from_zone": a,
                "to_zone": b,
                "src_metric": src_metric,
                "tgt_metric": tgt_metric,
                "best_corr": c,
                "best_lag_windows": lag,
                "overlap_points": n,
            })

    if not rows:
        return pd.DataFrame(columns=[
            "from_zone",
            "to_zone",
            "src_metric",
            "tgt_metric",
            "best_corr",
            "best_lag_windows",
            "overlap_points",
        ])

    out = pd.DataFrame(rows)
    return out.sort_values(
        "best_corr",
        key=lambda s: s.abs(),
        ascending=False,
        na_position="last",
    )


def compute_propagation_table(
    zf: pd.DataFrame,
    src_metric: str,
    tgt_metric: str,
    max_lag: int,
    min_lag: int = 0,
    min_points: int = 8,
    correlate_changes: bool = False,
):
    metric_frames = prepare_dependency_metric_frames(
        zf,
        [src_metric, tgt_metric],
    )
    return compute_propagation_table_from_frames(
        metric_frames=metric_frames,
        src_metric=src_metric,
        tgt_metric=tgt_metric,
        max_lag=max_lag,
        min_lag=min_lag,
        min_points=min_points,
        correlate_changes=correlate_changes,
    )


def select_basic_dependency_rows(
    dep_all: pd.DataFrame,
    priority_threshold: float = 0.9,
    fallback_threshold: float = 0.7,
    fallback_top_n: int = 10,
) -> pd.DataFrame:
    if dep_all is None or dep_all.empty:
        return pd.DataFrame()

    out = dep_all.copy()
    out = out.dropna(subset=["best_corr", "best_lag_windows"]).copy()
    if out.empty:
        return out

    out = out[out["from_zone"] != out["to_zone"]].copy()
    out = out[out["best_lag_windows"].astype(int) >= 1].copy()
    out = out[out["best_corr"].abs() >= float(fallback_threshold)].copy()
    if out.empty:
        return out

    out = out.sort_values("best_corr", key=lambda s: s.abs(), ascending=False)
    out = out.drop_duplicates(
        subset=["src_metric", "tgt_metric", "from_zone", "to_zone"],
        keep="first",
    )

    priority = out[out["best_corr"].abs() >= float(priority_threshold)].copy()
    if len(priority) >= int(fallback_top_n):
        return priority.reset_index(drop=True)

    return out.head(int(fallback_top_n)).reset_index(drop=True)
