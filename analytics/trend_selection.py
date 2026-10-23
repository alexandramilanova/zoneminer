"""Exact zone–metric change analysis for configurable plots.

Legacy list-based endpoints retain their existing behavior. This workflow omits
constant aggregate components and uses adjacent PELT segments for contributions.
It reuses the existing squared-error PELT and strictness-to-penalty search.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.changepoints import (
    _EPS,
    _standardize_series_with_nans,
    collect_changepoint_events,
    pelt_changepoints,
)
from analytics.metrics.groups import list_metric_labels


def analyze_trend_selection(
    zf: pd.DataFrame,
    pairs: list[tuple[str, str]],
    *,
    normalize: bool = False,
    local_enabled: bool = True,
    overall_enabled: bool = False,
    cp_strictness: int = 50,
    min_points: int = 8,
    min_size: int = 3,
) -> dict:
    if len(set(pairs)) != len(pairs):
        raise ValueError("Duplicate zone–metric pairs are not allowed.")
    if not 0 <= cp_strictness <= 100:
        raise ValueError("Change-point strictness must be between 0 and 100.")
    labels = list_metric_labels()
    zone_names = set(zf['zone'].dropna())
    rows, statuses, local_frames, components = [], [], [], []
    for zone, metric in pairs:
        if zone not in zone_names:
            raise ValueError(f"Unknown zone {zone!r}.")
        if metric not in zf.columns or metric not in labels or not pd.api.types.is_numeric_dtype(zf[metric]):
            raise ValueError(f"Unknown or nonnumeric metric {metric!r} for zone {zone!r}.")
        part = zf.loc[zf.zone == zone, ['window_start', metric]].copy()
        part['window_start'] = pd.to_datetime(part.window_start)
        part = part.sort_values('window_start').drop_duplicates('window_start')
        values = pd.to_numeric(part.set_index('window_start')[metric], errors='coerce')
        values = values.where(np.isfinite(values))
        finite = values.dropna()
        status = ('insufficient_observations' if len(finite) < max(min_points, 8, min_size * 2)
                  else 'constant' if float(np.std(finite)) <= _EPS else 'usable')
        display = values.copy()
        if normalize and len(finite):
            # Preserve the existing trend display's sample-SD convention.
            sd = float(finite.std())
            display = (values - finite.mean()) / sd if np.isfinite(sd) and sd > 0 else values * 0
        for timestamp, value in display.items():
            rows.append(dict(zone=zone, metric=metric, metric_label=labels[metric], window_start=timestamp, value=value))
        detected = pd.DataFrame()
        if local_enabled and status == 'usable':
            clean = pd.DataFrame({'zone': zone, 'window_start': values.index, metric: values.values})
            detected = collect_changepoint_events(clean, [zone], [metric], '',
                cp_strictness=cp_strictness, min_size=min_size, min_points=min_points,
                max_per_series=None, metric_display_map=labels)
            if not detected.empty:
                local_frames.append(detected)
        statuses.append(dict(zone=zone, metric=metric, n_observations=int(len(finite)), n_windows=int(len(values)),
            status=status, local_status='disabled' if not local_enabled else status if status != 'usable'
            else 'detected' if not detected.empty else 'no_changes'))
        if status == 'usable':
            standardized = _standardize_series_with_nans(values)
            # Tuple identities prevent collisions when zone names contain '__'.
            standardized.name = (zone, metric)
            components.append(standardized)

    local = pd.concat(local_frames, ignore_index=True) if local_frames else pd.DataFrame()
    wide = pd.concat(components, axis=1).sort_index() if components else pd.DataFrame()
    overall = dict(status='disabled', n_series=len(components), signal=pd.DataFrame(),
        changepoints=pd.DataFrame(), contributions=pd.DataFrame(), contribution_details=[])
    if overall_enabled:
        if len(components) < 2:
            overall['status'] = 'insufficient_components'
        else:
            # Existing algorithm: population-SD standardization, row-wise mean
            # over available components, no interpolation. Expose coverage.
            signal = wide.mean(axis=1, skipna=True).dropna()
            overall['signal'] = pd.DataFrame({'window_start': signal.index, 'value': signal.values,
                'n_components': wide.reindex(signal.index).notna().sum(axis=1).values})
            if len(signal) < max(min_points, 8, min_size * 2):
                overall['status'] = 'insufficient_observations'
            elif float(np.std(signal)) <= _EPS:
                overall['status'] = 'constant'
            else:
                cps = pelt_changepoints(signal, model='l2', min_size=min_size, strictness=cp_strictness, standardize=False)
                overall['status'] = 'detected' if cps else 'no_changes'
                overall['changepoints'] = pd.DataFrame([dict(timestamp=signal.index[cp], cp_index=cp,
                    cp_order=i + 1, selection_label='Selected zone–metric collection', aggregate_method='mean',
                    n_series=len(components)) for i, cp in enumerate(cps)])
                contributions, details = adjacent_segment_contributions(wide.reindex(signal.index), cps, labels)
                overall['contributions'] = contributions
                overall['contribution_details'] = details
    return dict(rows=pd.DataFrame(rows), series=statuses, local_changepoints=local, overall=overall)


def adjacent_segment_contributions(wide: pd.DataFrame, cps: list[int], labels: dict[str, str]) -> tuple[pd.DataFrame, list]:
    """Independent segment boundaries, not fixed-size flanks; no invented zeros."""
    boundaries = [0, *sorted(set(cps)), len(wide)]
    rows, details = [], []
    for i, cp in enumerate(boundaries[1:-1], start=1):
        lo, hi = boundaries[i - 1], boundaries[i + 1]
        jumps, omitted = [], []
        for (zone, metric) in wide.columns:
            before, after = wide.iloc[lo:cp][(zone, metric)].dropna(), wide.iloc[cp:hi][(zone, metric)].dropna()
            if before.empty or after.empty:
                omitted.append(dict(zone=zone, metric=metric, reason='No observations on one side of the boundary'))
                continue
            before_mean, after_mean = float(before.mean()), float(after.mean())
            jumps.append(dict(timestamp=wide.index[cp], selection_label='Selected zone–metric collection', aggregate_method='mean',
                zone=zone, metric_column=metric, metric_label=labels.get(metric, metric), series=f'{zone} · {labels.get(metric, metric)}',
                before_mean=before_mean, after_mean=after_mean, jump_score=abs(after_mean - before_mean),
                before_start=wide.index[lo], before_end=wide.index[cp - 1], after_start=wide.index[cp], after_end=wide.index[hi - 1],
                before_n=int(len(before)), after_n=int(len(after))))
        total = sum(row['jump_score'] for row in jumps)
        details.append(dict(timestamp=wide.index[cp].isoformat(), status='measured' if total > 0 else 'no_measurable_contribution',
            total_jump=total, included_components=len(jumps), omitted_components=omitted))
        if total > 0:
            for row in jumps:
                row['contribution_pct'] = 100 * row['jump_score'] / total
                rows.append(row)
    return pd.DataFrame(rows).sort_values(['timestamp', 'contribution_pct'], ascending=[True, False]).reset_index(drop=True) if rows else pd.DataFrame(), details
