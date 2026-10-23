"""Analyses over the zone-feature table (change points, dependencies).

Bodies moved verbatim from the Streamlit app's cached functions. All results
are plain DataFrames; the *dependency* analyses compute time-lagged Pearson
correlation — association, not causation (see zone-metrics-guardrails).
No Streamlit imports are allowed in this module.
"""

from typing import Optional

import pandas as pd
from analytics.trend_selection import analyze_trend_selection
from analytics.changepoints import (
    collect_changepoint_events,
    collect_selection_changepoint_contributions,
    collect_selection_changepoints,
)
from analytics.dependencies import (
    compute_propagation_table,
    compute_propagation_table_from_frames,
    prepare_dependency_metric_frames,
)
from analytics.metrics.compat import canonical_metric_name


def selected_trend_analysis(zf: pd.DataFrame, pairs: list[tuple[str, str]], **settings) -> dict:
    return analyze_trend_selection(zf, pairs, **settings)


def changepoint_events(
    zf: pd.DataFrame,
    zones: list[str],
    metrics: list[str],
    cp_strictness: int,
    min_size: int,
    min_points: int,
    max_per_series: Optional[int],
    jump: int,
    metric_display_map: dict[str, str],
) -> pd.DataFrame:
    return collect_changepoint_events(
        zf=zf,
        zones=zones,
        metrics=metrics,
        timeframe_label="",
        cp_strictness=cp_strictness,
        min_size=min_size,
        min_points=min_points,
        max_per_series=max_per_series,
        jump=jump,
        metric_display_map=metric_display_map,
    )


def selection_changepoints(
    zf: pd.DataFrame,
    zones: list[str],
    metrics: list[str],
    cp_strictness: int,
    min_size: int,
    min_points: int,
    jump: int,
    aggregate_method: str,
    selection_label: str,
    max_selection_cps: Optional[int],
    flank_points: int,
) -> pd.DataFrame:
    return collect_selection_changepoints(
        zf=zf,
        zones=zones,
        metrics=metrics,
        cp_strictness=cp_strictness,
        min_size=min_size,
        min_points=min_points,
        jump=jump,
        aggregate_method=aggregate_method,
        selection_label=selection_label,
        max_selection_cps=max_selection_cps,
        flank_points=flank_points,
    )


def selection_changepoint_contributions(
    zf: pd.DataFrame,
    zones: list[str],
    metrics: list[str],
    selection_cp_events: pd.DataFrame,
    min_points: int,
    metric_display_map: dict[str, str],
    selection_label: str,
    aggregate_method: str,
    flank_points: int,
) -> pd.DataFrame:
    return collect_selection_changepoint_contributions(
        zf=zf,
        zones=zones,
        metrics=metrics,
        selection_cp_events=selection_cp_events,
        min_points=min_points,
        metric_display_map=metric_display_map,
        selection_label=selection_label,
        aggregate_method=aggregate_method,
        flank_points=flank_points,
    )


def dependency_table(
    zf: pd.DataFrame,
    src_metric: str,
    tgt_metric: str,
    max_lag: int,
    min_lag: int,
    min_points: int,
    correlate_changes: bool,
) -> pd.DataFrame:
    return compute_propagation_table(
        zf=zf,
        src_metric=src_metric,
        tgt_metric=tgt_metric,
        max_lag=max_lag,
        min_lag=min_lag,
        min_points=min_points,
        correlate_changes=correlate_changes,
    )


def basic_dependency_matrix(
    zf: pd.DataFrame,
    metric_options: list[str],
    max_lag: int,
    min_lag: int,
    min_points: int,
    correlate_changes: bool,
) -> pd.DataFrame:
    """All-pairs lagged-correlation table over the given metrics."""
    frames = prepare_dependency_metric_frames(zf, list(metric_options))
    rows = []

    for src_metric in metric_options:
        for tgt_metric in metric_options:
            if tgt_metric == src_metric:
                continue

            dep = compute_propagation_table_from_frames(
                metric_frames=frames,
                src_metric=src_metric,
                tgt_metric=tgt_metric,
                max_lag=max_lag,
                min_lag=min_lag,
                min_points=min_points,
                correlate_changes=correlate_changes,
            )

            if dep is None or dep.empty:
                continue

            dep = dep.copy()
            dep["src_metric"] = canonical_metric_name(src_metric)
            dep["tgt_metric"] = canonical_metric_name(tgt_metric)
            rows.append(dep)

    if not rows:
        return pd.DataFrame()

    return pd.concat(rows, ignore_index=True)
