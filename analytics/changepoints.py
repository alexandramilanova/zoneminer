from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import ruptures as rpt


_CHANGEPOINT_EVENT_COLUMNS = [
    "timestamp",
    "zone",
    "metric_column",
    "metric_label",
    "series",
    "cp_index",
    "cp_order",
]

_SELECTION_CHANGEPOINT_EVENT_COLUMNS = [
    "timestamp",
    "selection_label",
    "aggregate_method",
    "n_series",
    "cp_index",
    "cp_order",
]

_SELECTION_CHANGEPOINT_CONTRIBUTION_COLUMNS = [
    "timestamp",
    "selection_label",
    "aggregate_method",
    "zone",
    "metric_column",
    "metric_label",
    "series",
    "before_mean",
    "after_mean",
    "jump_score",
    "contribution_pct",
]

_EPS = 1e-12
_MAX_SEARCH_STEPS = 40
_BINARY_SEARCH_STEPS = 28


def _values_cache_key(values: np.ndarray) -> tuple[float, ...]:
    arr = np.asarray(values, dtype=float)
    # Rounded tuples are stable enough for repeated reruns of the same series.
    return tuple(np.round(arr, 8).tolist())


@lru_cache(maxsize=2048)
def _run_pelt_cached(
    values_key: tuple[float, ...],
    model: str,
    penalty: float,
    min_size: int,
    jump: int,
) -> tuple[int, ...]:
    if len(values_key) < max(8, min_size * 2):
        return ()

    y = np.asarray(values_key, dtype=float).reshape(-1, 1)
    algo = rpt.Pelt(model=model, min_size=min_size, jump=jump).fit(y)
    bkps = algo.predict(pen=float(max(penalty, 0.0)))
    return tuple(int(b) for b in bkps if 0 < b < len(values_key))


def _standardize_array(x: np.ndarray) -> np.ndarray:
    """
    Standardize to zero mean / unit std so strictness behaves similarly
    across metrics with different scales.
    """
    x = np.asarray(x, dtype=float)
    mu = float(np.mean(x))
    sigma = float(np.std(x))

    if sigma <= _EPS:
        return x - mu

    return (x - mu) / sigma


def _run_pelt_on_values(
    values: np.ndarray,
    model: str = "l2",
    penalty: float = 0.0,
    min_size: int = 3,
    jump: int = 1,
) -> list[int]:
    """
    Run PELT on already-clean numeric values.
    """
    return list(
        _run_pelt_cached(
            _values_cache_key(values),
            model,
            float(max(penalty, 0.0)),
            int(min_size),
            int(jump),
        )
    )


def _target_cp_count(max_found: int, strictness: int) -> int:
    """
    strictness=0   -> keep the maximum number of CPs PELT can find
    strictness=100 -> keep 0 CPs
    """
    strictness = int(np.clip(strictness, 0, 100))
    return int(round((100 - strictness) / 100 * max_found))


def _pelt_changepoints_from_strictness(
    values: np.ndarray,
    model: str = "l2",
    strictness: int = 50,
    min_size: int = 3,
    jump: int = 1,
) -> list[int]:
    """
    Convert strictness to changepoints by searching for a penalty that gives
    the desired number of changepoints.

    This is behavior-based, not raw-penalty-based:
    - 0   -> maximum CPs PELT can produce for this series
    - 100 -> no CPs
    """
    # "Maximum" here means what PELT returns at penalty 0 on the standardized series
    cps_at_zero = _run_pelt_on_values(
        values,
        model=model,
        penalty=0.0,
        min_size=min_size,
        jump=jump,
    )
    max_found = len(cps_at_zero)

    if max_found == 0:
        return []

    target = _target_cp_count(max_found, strictness)

    if target >= max_found:
        return cps_at_zero

    if target <= 0:
        # Find a penalty large enough to remove all changepoints
        hi = 1.0
        cps_hi = _run_pelt_on_values(
            values,
            model=model,
            penalty=hi,
            min_size=min_size,
            jump=jump,
        )

        for _ in range(_MAX_SEARCH_STEPS):
            if len(cps_hi) == 0:
                return []
            hi *= 2.0
            cps_hi = _run_pelt_on_values(
                values,
                model=model,
                penalty=hi,
                min_size=min_size,
                jump=jump,
            )

        return cps_hi

    # Find an upper bound where CP count <= target
    lo = 0.0
    hi = 1.0
    cps_hi = _run_pelt_on_values(
        values,
        model=model,
        penalty=hi,
        min_size=min_size,
        jump=jump,
    )

    for _ in range(_MAX_SEARCH_STEPS):
        if len(cps_hi) <= target:
            break
        lo = hi
        hi *= 2.0
        cps_hi = _run_pelt_on_values(
            values,
            model=model,
            penalty=hi,
            min_size=min_size,
            jump=jump,
        )

    best_cps = cps_hi
    best_gap = abs(len(cps_hi) - target)
    best_pen = hi

    # Also compare with zero-penalty result
    gap_zero = abs(len(cps_at_zero) - target)
    if gap_zero < best_gap:
        best_cps = cps_at_zero
        best_gap = gap_zero
        best_pen = 0.0

    # Binary search for a penalty giving a CP count close to target
    for _ in range(_BINARY_SEARCH_STEPS):
        mid = (lo + hi) / 2.0
        cps_mid = _run_pelt_on_values(
            values,
            model=model,
            penalty=mid,
            min_size=min_size,
            jump=jump,
        )
        gap_mid = abs(len(cps_mid) - target)

        if gap_mid < best_gap or (gap_mid == best_gap and mid > best_pen):
            best_cps = cps_mid
            best_gap = gap_mid
            best_pen = mid

        if len(cps_mid) > target:
            lo = mid
        else:
            hi = mid

    return best_cps


def pelt_changepoints(
    series: pd.Series,
    model: str = "l2",
    penalty: float = 5.0,
    min_size: int = 3,
    jump: int = 1,
    strictness: int | None = None,
    standardize: bool = True,
) -> list[int]:
    """
    Return changepoint indices for the cleaned series.

    Notes:
    - NaNs are dropped before fitting.
    - Returned indices refer to the cleaned series order.
    - Each returned index is the first sample of the new regime.
    - If `strictness` is provided, it overrides `penalty`.
    - strictness=0   => maximum CPs PELT can find for this series
    - strictness=100 => no CPs
    """
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < max(8, min_size * 2):
        return []

    values = s.to_numpy(dtype=float)

    if standardize:
        values = _standardize_array(values)

    if strictness is not None:
        return _pelt_changepoints_from_strictness(
            values,
            model=model,
            strictness=strictness,
            min_size=min_size,
            jump=jump,
        )

    return _run_pelt_on_values(
        values,
        model=model,
        penalty=penalty,
        min_size=min_size,
        jump=jump,
    )


def _selected_cps(cps: list[int], max_per_series: int | None) -> list[int]:
    """
    Select changepoints to keep.
    - None or <= 0 => keep all
    - positive int => keep only the last N
    """
    if max_per_series is None or max_per_series <= 0:
        return cps
    return cps[-max_per_series:]


def _changepoint_strength(values: np.ndarray, cp_idx: int, flank_points: int = 3) -> float:
    n = len(values)
    if cp_idx <= 0 or cp_idx >= n:
        return 0.0

    lo = max(0, cp_idx - int(flank_points))
    hi = min(n, cp_idx + int(flank_points))
    if lo >= cp_idx or cp_idx >= hi:
        return 0.0

    before = np.asarray(values[lo:cp_idx], dtype=float)
    after = np.asarray(values[cp_idx:hi], dtype=float)
    before = before[np.isfinite(before)]
    after = after[np.isfinite(after)]
    if before.size == 0 or after.size == 0:
        return 0.0
    return float(abs(np.mean(after) - np.mean(before)))


def _select_strongest_cps(
    values: np.ndarray,
    cps: list[int],
    max_cps: int | None,
    flank_points: int = 3,
) -> list[int]:
    if max_cps is None or max_cps <= 0 or len(cps) <= max_cps:
        return sorted(cps)

    ranked = sorted(
        cps,
        key=lambda cp_idx: (_changepoint_strength(values, cp_idx, flank_points), cp_idx),
        reverse=True,
    )
    return sorted(ranked[: int(max_cps)])


def collect_changepoint_events(
    zf: pd.DataFrame,
    zones: Iterable[str],
    metrics: Iterable[str],
    timeframe_label: str,
    cp_strictness: int = 50,
    min_size: int = 3,
    min_points: int = 10,
    max_per_series: int | None = None,
    jump: int = 1,
    metric_display_map: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """
    Compute changepoint events per (zone, metric).

    strictness:
    - 0   => maximum CPs PELT can find for that series
    - 100 => no CPs
    """
    rows: list[dict] = []

    for z in zones:
        zt = zf[zf["zone"] == z].sort_values("window_start").copy()

        for mcol in metrics:
            if mcol not in zt.columns:
                continue

            s = pd.to_numeric(zt[mcol], errors="coerce")
            s_clean = s.dropna()

            if len(s_clean) < min_points:
                continue

            cps = pelt_changepoints(
                s_clean,
                model="l2",
                min_size=min_size,
                jump=jump,
                strictness=cp_strictness,
                standardize=True,
            )
            cps = _selected_cps(cps, max_per_series)

            if not cps:
                continue

            metric_label = metric_display_map.get(mcol, mcol) if metric_display_map else mcol
            series_label = f"{z} · {metric_label}"

            for order_i, cp_idx in enumerate(cps, start=1):
                if 0 <= cp_idx < len(s_clean):
                    ts = zt.loc[s_clean.index[cp_idx], "window_start"]
                    rows.append(
                        {
                            "timestamp": pd.to_datetime(ts),
                            "zone": z,
                            "metric_column": mcol,
                            "metric_label": metric_label,
                            "series": series_label,
                            "cp_index": int(cp_idx),
                            "cp_order": int(order_i),
                        }
                    )

    if not rows:
        return pd.DataFrame(columns=_CHANGEPOINT_EVENT_COLUMNS)

    out = pd.DataFrame(rows, columns=_CHANGEPOINT_EVENT_COLUMNS)
    out = out.sort_values(["series", "cp_index"]).reset_index(drop=True)
    return out


def _standardize_series_with_nans(s: pd.Series) -> pd.Series:
    """
    Standardize one numeric pandas Series while preserving NaN positions.
    """
    x = pd.to_numeric(s, errors="coerce")
    mask = x.notna()

    out = pd.Series(np.nan, index=s.index, dtype=float)
    if mask.sum() == 0:
        return out

    out.loc[mask] = _standardize_array(x.loc[mask].to_numpy(dtype=float))
    return out


def _build_selection_summary_series(
    zf: pd.DataFrame,
    zones: Sequence[str],
    metrics: Sequence[str],
    min_points: int = 10,
    aggregate_method: str = "mean",
) -> tuple[pd.Series, int]:
    """
    Build one normalized aggregate series for the currently selected
    zones + metrics.

    Steps:
    - collect each selected (zone, metric) line
    - standardize each line individually
    - align them on window_start
    - aggregate row-wise by mean or median

    Returns:
    - aggregated summary series indexed by window_start
    - number of contributing lines
    """
    pieces: list[pd.Series] = []

    for z in zones:
        zt = zf[zf["zone"] == z].sort_values("window_start").copy()
        if zt.empty:
            continue

        zt["window_start"] = pd.to_datetime(zt["window_start"])

        for mcol in metrics:
            if mcol not in zt.columns:
                continue

            s = (
                zt[["window_start", mcol]]
                .drop_duplicates(subset=["window_start"])
                .set_index("window_start")[mcol]
            )
            s = pd.to_numeric(s, errors="coerce")

            if s.dropna().shape[0] < min_points:
                continue

            s_std = _standardize_series_with_nans(s)
            s_std.name = f"{z}__{mcol}"
            pieces.append(s_std)

    if len(pieces) < 2:
        return pd.Series(dtype=float), 0

    wide = pd.concat(pieces, axis=1).sort_index()

    if aggregate_method == "median":
        agg = wide.median(axis=1, skipna=True)
    else:
        agg = wide.mean(axis=1, skipna=True)

    agg = pd.to_numeric(agg, errors="coerce").dropna()
    return agg, len(pieces)


def _build_selection_component_frame(
    zf: pd.DataFrame,
    zones: Sequence[str],
    metrics: Sequence[str],
    min_points: int = 10,
) -> pd.DataFrame:
    pieces: list[pd.Series] = []

    for z in zones:
        zt = zf[zf["zone"] == z].sort_values("window_start").copy()
        if zt.empty:
            continue

        zt["window_start"] = pd.to_datetime(zt["window_start"])

        for mcol in metrics:
            if mcol not in zt.columns:
                continue

            s = (
                zt[["window_start", mcol]]
                .drop_duplicates(subset=["window_start"])
                .set_index("window_start")[mcol]
            )
            s = pd.to_numeric(s, errors="coerce")

            if s.dropna().shape[0] < min_points:
                continue

            s_std = _standardize_series_with_nans(s)
            s_std.name = f"{z}__{mcol}"
            pieces.append(s_std)

    if not pieces:
        return pd.DataFrame()

    return pd.concat(pieces, axis=1).sort_index()


def collect_selection_changepoints(
    zf: pd.DataFrame,
    zones: Sequence[str],
    metrics: Sequence[str],
    cp_strictness: int = 50,
    min_size: int = 3,
    min_points: int = 10,
    jump: int = 1,
    aggregate_method: str = "mean",
    selection_label: str = "Current selection",
    max_selection_cps: int | None = None,
    flank_points: int = 3,
) -> pd.DataFrame:
    """
    Compute changepoints for the current user selection as a whole.

    The selected lines are:
    - individually standardized
    - aligned by timestamp
    - aggregated into one summary signal
    - then PELT is run on that summary signal

    Returns one row per overall changepoint.
    """
    summary_s, n_series = _build_selection_summary_series(
        zf=zf,
        zones=list(zones),
        metrics=list(metrics),
        min_points=min_points,
        aggregate_method=aggregate_method,
    )

    if summary_s.empty or n_series < 2 or len(summary_s) < min_points:
        return pd.DataFrame(columns=_SELECTION_CHANGEPOINT_EVENT_COLUMNS)

    cps = pelt_changepoints(
        summary_s,
        model="l2",
        min_size=min_size,
        jump=jump,
        strictness=cp_strictness,
        standardize=False,  # already standardized per selected line
    )
    cps = _select_strongest_cps(
        summary_s.to_numpy(dtype=float),
        cps,
        max_selection_cps,
        flank_points=flank_points,
    )

    if not cps:
        return pd.DataFrame(columns=_SELECTION_CHANGEPOINT_EVENT_COLUMNS)

    rows: list[dict] = []
    for order_i, cp_idx in enumerate(cps, start=1):
        if 0 <= cp_idx < len(summary_s):
            rows.append(
                {
                    "timestamp": pd.to_datetime(summary_s.index[cp_idx]),
                    "selection_label": selection_label,
                    "aggregate_method": aggregate_method,
                    "n_series": int(n_series),
                    "cp_index": int(cp_idx),
                    "cp_order": int(order_i),
                }
            )

    if not rows:
        return pd.DataFrame(columns=_SELECTION_CHANGEPOINT_EVENT_COLUMNS)

    out = pd.DataFrame(rows, columns=_SELECTION_CHANGEPOINT_EVENT_COLUMNS)
    out = out.sort_values(["cp_index"]).reset_index(drop=True)
    return out


def collect_selection_changepoint_contributions(
    zf: pd.DataFrame,
    zones: Sequence[str],
    metrics: Sequence[str],
    selection_cp_events: pd.DataFrame,
    *,
    min_points: int = 10,
    metric_display_map: Mapping[str, str] | None = None,
    selection_label: str = "Current selection",
    aggregate_method: str = "mean",
    flank_points: int = 3,
) -> pd.DataFrame:
    if selection_cp_events is None or selection_cp_events.empty:
        return pd.DataFrame(columns=_SELECTION_CHANGEPOINT_CONTRIBUTION_COLUMNS)

    wide = _build_selection_component_frame(
        zf=zf,
        zones=list(zones),
        metrics=list(metrics),
        min_points=min_points,
    )
    if wide.empty:
        return pd.DataFrame(columns=_SELECTION_CHANGEPOINT_CONTRIBUTION_COLUMNS)

    rows: list[dict] = []
    n = len(wide)

    for cp_row in selection_cp_events.itertuples(index=False):
        # cp_index is positional in the dropna'd aggregate series; `wide` keeps
        # all windows, so locate the change point by its timestamp instead —
        # otherwise flanks shift when leading windows are all-NaN.
        ts = pd.to_datetime(cp_row.timestamp)
        loc = wide.index.get_indexer([ts])
        cp_idx = int(loc[0]) if loc[0] != -1 else int(wide.index.searchsorted(ts))
        if cp_idx <= 0 or cp_idx >= n:
            continue

        lo = max(0, cp_idx - int(flank_points))
        hi = min(n, cp_idx + int(flank_points))
        if lo >= cp_idx or cp_idx >= hi:
            continue

        jump_rows: list[dict] = []
        for col in wide.columns:
            before = pd.to_numeric(wide.iloc[lo:cp_idx][col], errors="coerce").dropna()
            after = pd.to_numeric(wide.iloc[cp_idx:hi][col], errors="coerce").dropna()
            if before.empty or after.empty:
                continue

            zone, metric_column = col.split("__", 1)
            metric_label = metric_display_map.get(metric_column, metric_column) if metric_display_map else metric_column
            before_mean = float(before.mean())
            after_mean = float(after.mean())
            jump_score = abs(after_mean - before_mean)

            jump_rows.append(
                {
                    "timestamp": pd.to_datetime(cp_row.timestamp),
                    "selection_label": selection_label,
                    "aggregate_method": aggregate_method,
                    "zone": zone,
                    "metric_column": metric_column,
                    "metric_label": metric_label,
                    "series": f"{zone} · {metric_label}",
                    "before_mean": before_mean,
                    "after_mean": after_mean,
                    "jump_score": jump_score,
                }
            )

        if not jump_rows:
            continue

        total_jump = sum(row["jump_score"] for row in jump_rows)
        total_jump = total_jump if total_jump > 0 else 1.0
        for row in jump_rows:
            row["contribution_pct"] = 100.0 * row["jump_score"] / total_jump
            rows.append(row)

    if not rows:
        return pd.DataFrame(columns=_SELECTION_CHANGEPOINT_CONTRIBUTION_COLUMNS)

    out = pd.DataFrame(rows, columns=_SELECTION_CHANGEPOINT_CONTRIBUTION_COLUMNS)
    out = out.sort_values(["timestamp", "contribution_pct", "series"], ascending=[True, False, True]).reset_index(drop=True)
    return out
