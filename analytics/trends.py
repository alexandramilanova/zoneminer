# trend_analysis.py
from __future__ import annotations

import pandas as pd

from analytics.metrics.compat import canonicalize_metric_names
from analytics.metrics.groups import is_duration_metric


def filter_trend_source(
    zf: pd.DataFrame,
    zones: list[str],
    metrics: list[str],
) -> pd.DataFrame:
    """
    Filter the source dataframe for one chart and keep only required columns.
    """
    metrics = canonicalize_metric_names(list(metrics))
    if zf.empty or not zones or not metrics:
        cols = [c for c in ["window_start", "zone"] + list(metrics) if c in zf.columns]
        return zf.iloc[0:0][cols].copy() if cols else zf.iloc[0:0].copy()

    cols = [c for c in ["window_start", "zone"] + list(metrics) if c in zf.columns]
    return (
        zf[zf["zone"].isin(zones)][cols]
        .sort_values(["window_start", "zone"])
        .copy()
    )


def melt_trend_df(dfp: pd.DataFrame) -> pd.DataFrame:
    """
    Wide -> long for plotting.
    """
    if dfp.empty:
        return pd.DataFrame(columns=["window_start", "zone", "metric", "value"])

    metric_cols = [c for c in dfp.columns if c not in ["window_start", "zone"]]
    return dfp.melt(
        id_vars=["window_start", "zone"],
        value_vars=metric_cols,
        var_name="metric",
        value_name="value",
    )


def convert_duration_metrics_for_display(
    long_df: pd.DataFrame,
    mode: str,
    duration_display_fn,
) -> pd.DataFrame:
    """
    Convert canonical duration metrics from raw seconds into the selected display unit.
    """
    if long_df.empty or duration_display_fn is None:
        return long_df

    out = long_df.copy()
    mask_duration = out["metric"].map(is_duration_metric)
    if mask_duration.any():
        out.loc[mask_duration, "value"] = duration_display_fn(out.loc[mask_duration, "value"])
    return out


def normalize_trend_long_df(long_df: pd.DataFrame) -> pd.DataFrame:
    """
    Min-max normalize per (zone, metric), while preserving all columns.
    """
    if long_df.empty:
        return long_df

    out = long_df.copy()
    out["value"] = pd.to_numeric(out["value"], errors="coerce")

    grouped_values = out.groupby(
        ["zone", "metric"],
        dropna=False,
    )["value"]

    group_min = grouped_values.transform("min")
    group_max = grouped_values.transform("max")

    denominator = group_max - group_min

    # Avoid division by zero for constant series
    denominator = denominator.mask(denominator == 0, 1.0)

    out["value"] = (out["value"] - group_min) / denominator

    return out

def add_trend_series_labels(
    long_df: pd.DataFrame,
    reverse_catalog: dict[str, str],
) -> pd.DataFrame:
    """
    Add friendly metric labels and combined legend series labels.
    """
    if long_df.empty:
        out = long_df.copy()
        out["metric_label"] = []
        out["series"] = []
        return out

    out = long_df.copy()
    out["metric_label"] = out["metric"].map(reverse_catalog).fillna(out["metric"])
    out["series"] = out["zone"].astype(str) + " · " + out["metric_label"].astype(str)
    return out


def prepare_trend_long_df(
    zf: pd.DataFrame,
    zones: list[str],
    metrics: list[str],
    mode: str,
    reverse_catalog: dict[str, str],
    normalize: bool = False,
    atz_display_fn=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Main helper for chart prep.

    Returns:
      - zfi: filtered wide dataframe for this chart
      - long_df: long dataframe ready for plotly
    """
    zfi = filter_trend_source(zf, zones, metrics)
    long_df = melt_trend_df(zfi)

    if atz_display_fn is not None:
        long_df = convert_duration_metrics_for_display(long_df, mode, atz_display_fn)

    if normalize:
        long_df = normalize_trend_long_df(long_df)

    long_df = add_trend_series_labels(long_df, reverse_catalog)
    return zfi, long_df
