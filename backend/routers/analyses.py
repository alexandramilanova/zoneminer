"""Analysis endpoints: job creation, progress streaming, and per-view data.

All numbers come from the same ``services``/``analytics`` functions the
Streamlit oracle uses. Dependency results are lagged Pearson correlation —
association, not causation — and conformance metrics are window-level by
design; the field names and docs keep that language on purpose.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import services
from analytics.alerts import (
    BASIC_ALERT_FRIENDLY,
    compute_advanced_alerts,
    compute_basic_alerts,
    get_recent_alerts_window,
    summarize_basic_alerts_per_zone,
)
from analytics.dependencies import select_basic_dependency_rows
from analytics.metrics.catalog import (
    get_basic_dependency_metrics,
    get_metric_explanations,
    get_metric_label_map,
)
from analytics.metrics.reference import get_metric_reference, WINDOW_RULE, REPLAY_RULE
from analytics.metrics.compat import canonical_metric_name
from analytics.metrics.groups import (
    get_default_alert_threshold,
    get_default_prediction_target_metric,
)
from analytics.prediction import (
    build_binary_target_from_metric_threshold,
    get_default_feature_metrics,
    list_numeric_zone_metrics,
    list_supported_models,
    make_wide_feature_table,
    train_compare_models,
)
from backend import config, store, isolation
from backend.isolation import endpoint
from backend.jobs import manager
from backend.runner import get_bundle, run_analysis_job
from backend.zone_requests import ZoneConfiguration
from backend.prediction_view import decision_tree_view
from display_utils import get_duration_unit_label, get_duration_unit_seconds
from process_model.zone_validation import validate_zones

router = APIRouter(prefix="/api", tags=["analyses"])

TIMEFRAME_LABELS = {"h": "Hourly", "D": "Daily", "7D": "Weekly", "30D": "Monthly"}


def _clean_json(obj):
    """Replace NaN/Inf with None recursively so responses are valid JSON."""
    if isinstance(obj, dict):
        return {k: _clean_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_json(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _records(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].astype(str)
        elif pd.api.types.is_timedelta64_dtype(out[col]):
            out[col] = out[col].dt.total_seconds()
    return _clean_json(out.replace({np.nan: None}).to_dict(orient="records"))


def _get_analysis_or_404(analysis_id: str) -> dict:
    meta = store.get_analysis(analysis_id)
    if meta is None:
        raise HTTPException(404, "Analysis not found")
    return meta


def _load_features_or_409(analysis_id: str) -> pd.DataFrame:
    zf = store.load_frame(analysis_id, "zone_features")
    if zf is None:
        raise HTTPException(409, "Analysis has no computed artifacts yet")
    zf["window_start"] = pd.to_datetime(zf["window_start"])
    return zf


# ---------------------------------------------------------------------------
# Analysis creation + job progress
# ---------------------------------------------------------------------------


class AnalysisRequest(ZoneConfiguration):
    timeframe: str = Field("D", pattern="^(h|D|7D|30D)$")
    backend: Optional[str] = None  # 'pm4py' | 'r4pm'; default from config


@router.post("/datasets/{dataset_id}/analyses")
def create_analysis(dataset_id: str, body: AnalysisRequest):
    if store.get_dataset(dataset_id) is None:
        raise HTTPException(404, "Dataset not found")
    backend = (body.backend or config.DEFAULT_ALIGNMENT_BACKEND).lower()
    if backend not in ("pm4py", "r4pm"):
        raise HTTPException(400, f"Unknown alignment backend {backend!r}")

    if config.data_dir() != config.DATA_DIR:
        validation = isolation.run("backend.isolation", "validate_analysis", dataset_id, body)
    else:
        bundle = get_bundle(dataset_id)
        validation = validate_zones(zone_inputs=body.zone_inputs(), place_names=sorted(p.name for p in bundle.net.places),
                                    net=bundle.net, require_non_empty=True, allow_unassigned_places=True,
                                    require_connected=True)
    if not validation["zone_config_valid"]:
        raise HTTPException(422, detail={"errors": validation["errors"]})
    zone_places = validation["zone_places"]

    analysis_id = store.analysis_id_for(dataset_id, zone_places, body.timeframe, backend)
    if store.has_artifacts(analysis_id):
        store.upsert_analysis(analysis_id, dataset_id, zone_places, body.timeframe, backend, "done")
        return {"analysis_id": analysis_id, "job_id": None, "cached": True}

    # status row first — the job thread upserts "running"/"done" and must not
    # be overwritten by a late "queued" write
    job = manager.submit(
        "analysis",
        lambda j: (
            isolation.analysis_job(j, analysis_id, dataset_id, zone_places, body.timeframe, backend)
            if config.data_dir() != config.DATA_DIR
            else run_analysis_job(j, analysis_id, dataset_id, zone_places, body.timeframe, backend)
        ),
        key=analysis_id,
        on_submit=lambda: store.upsert_analysis(analysis_id, dataset_id, zone_places, body.timeframe, backend, "queued"),
    )
    return {"analysis_id": analysis_id, "job_id": job.id, "cached": False}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "error": job.error,
        "result": job.result,
        "events": job.events,
    }


@router.get("/jobs/{job_id}/events")
def stream_job_events(job_id: str):
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return StreamingResponse(
        manager.sse_events(job),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/analyses/{analysis_id}")
@endpoint
def get_analysis(analysis_id: str):
    meta = _get_analysis_or_404(analysis_id)
    meta["has_artifacts"] = store.has_artifacts(analysis_id)
    meta["timeframe_label"] = TIMEFRAME_LABELS.get(meta["timeframe"], meta["timeframe"])
    return meta


# ---------------------------------------------------------------------------
# Feature table + metric catalog
# ---------------------------------------------------------------------------


@router.get("/analyses/{analysis_id}/features")
@endpoint
def get_features(
    analysis_id: str,
    zones: Optional[str] = None,
    metrics: Optional[str] = None,
):
    _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    if zones:
        zf = zf[zf["zone"].isin(zones.split(","))]
    if metrics:
        keep = ["zone", "window_start"] + [
            canonical_metric_name(m) for m in metrics.split(",") if m
        ]
        zf = zf[[c for c in keep if c in zf.columns]]
    return {"rows": _records(zf), "row_count": int(len(zf))}


@router.get("/analyses/{analysis_id}/metrics")
@endpoint
def get_metric_catalog(analysis_id: str):
    meta = _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    tf_label = TIMEFRAME_LABELS.get(meta["timeframe"], "Daily")
    unit_label = get_duration_unit_label(tf_label)
    labels = get_metric_label_map()
    explanations = get_metric_explanations(tf_label, unit_label)
    numeric = list_numeric_zone_metrics(zf)
    return {
        "metrics": [
            {
                **get_metric_reference(m),
                "non_null_count": int(zf[m].notna().sum()),
                "row_count": int(len(zf)),
                "name": m,
                "label": labels.get(m, m),
                "explanation": explanations.get(m),
                "group": (
                    "token" if m.startswith("token_")
                    else "case" if m.startswith("case_")
                    else "conformance" if m.startswith(("alignment_", "zone_"))
                    else "other"
                ),
            }
            for m in numeric
        ],
        "zones": sorted(zf["zone"].dropna().unique().tolist()),
        "windows": sorted(pd.to_datetime(zf["window_start"]).astype(str).unique().tolist()),
        "duration_unit_label": "seconds",
        "legacy_duration_unit_label": unit_label,
        "window_rule": WINDOW_RULE,
        "replay_rule": REPLAY_RULE,
        "timeframe_label": tf_label,
    }


@router.get("/analyses/{analysis_id}/token-intervals")
@endpoint
def get_token_intervals(
    analysis_id: str,
    limit: int = Query(default=50000, ge=1, le=50000),
    offset: int = Query(default=0, ge=0),
):
    """Token-place intervals mapped to zones — the data behind token replay."""
    meta = _get_analysis_or_404(analysis_id)
    result = store.load_frame_page(analysis_id, "token_place", offset, limit)
    if result is None:
        raise HTTPException(409, "Analysis has no computed artifacts yet")
    page, total = result
    place_to_zone = {
        p: zone for zone, places in meta["zone_places"].items() for p in places
    }
    page["zone"] = page["place"].map(place_to_zone)
    return _interval_page(page, total, offset)


def _interval_page(page: pd.DataFrame, total: int, offset: int) -> dict:
    """Offsets refer to the immutable persisted frame's row order."""
    end = offset + len(page)
    return {
        "rows": _records(page), "row_count": int(len(page)),
        "total_count": int(total), "offset": offset,
        "next_offset": int(end) if end < total else None,
    }


def _zone_stays_frame(analysis_id: str, meta: dict) -> pd.DataFrame:
    """Case-zone stays for an analysis; analyses computed before the stays
    table was persisted are backfilled lazily from token-place intervals."""
    df = store.load_frame(analysis_id, "case_zone_stays")
    if df is None:
        token_place_df = store.load_frame(analysis_id, "token_place")
        if token_place_df is None:
            raise HTTPException(409, "Analysis has no computed artifacts yet")
        from process_model.features import build_case_zone_stays_from_places

        df = build_case_zone_stays_from_places(token_place_df, meta["zone_places"])
        if not df.empty:
            df["duration_s"] = df["duration"].dt.total_seconds()
        else:
            df["duration_s"] = []
        df = df.drop(columns=["duration"])
        store.save_frame(analysis_id, "case_zone_stays", df)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["exit_ts"] = pd.to_datetime(df["exit_ts"])
    return df


@router.get("/analyses/{analysis_id}/zone-stays")
@endpoint
def get_zone_stays(
    analysis_id: str, zones: Optional[str] = None,
    limit: int = Query(default=200000, ge=1, le=200000),
    offset: int = Query(default=0, ge=0),
    case_id: Optional[str] = None,
):
    """Case-zone stays (merged maximal intervals per case and zone) — the data
    behind the flow-pattern views (CFD, fingerprint scatter)."""
    meta = _get_analysis_or_404(analysis_id)
    # Filter persisted Parquet before materialization, especially for one case's
    # journey in the replay. Keep the legacy reconstruction fallback below.
    page = store.load_frame_page(analysis_id, "case_zone_stays", offset, limit,
                                 case_id=case_id, zones=zones.split(",") if zones else None)
    if page is not None:
        frame, total = page
        return _interval_page(frame, total, offset)
    df = _zone_stays_frame(analysis_id, meta)
    if case_id is not None:
        df = df[df["case_id"].astype(str) == case_id]
    if zones:
        df = df[df["zone"].isin(zones.split(","))]
    return _interval_page(df.iloc[offset:offset + limit], len(df), offset)


@router.get("/analyses/{analysis_id}/queueing")
@endpoint
def get_queueing_profile(analysis_id: str, scatter_limit: int = 1500):
    """Queueing-theoretic zone profile from case-zone stays.

    Per zone: arrival/departure rates, sojourn stats, time-averaged WIP,
    a Little's-law consistency ratio (L / (lambda x W) — approximately 1 under
    stationarity; sustained deviation indicates ramp-up/ramp-down phases,
    non-stationarity, or leaking tokens, so it doubles as a data-quality
    diagnostic), burstiness (coefficients of variation), and a
    load-dependence coefficient: the Pearson correlation between a stay's
    sojourn and the number of stays already active when it entered
    (association, not causation). The scatter sample behind that coefficient
    is returned for plotting (deterministically decimated).
    """
    meta = _get_analysis_or_404(analysis_id)
    stays = _zone_stays_frame(analysis_id, meta)
    zones_out = []
    for zone in sorted(meta["zone_places"].keys()):
        g = stays[stays["zone"] == zone]
        if g.empty:
            continue
        entries = g["entry_ts"].sort_values().to_numpy(dtype="datetime64[ns]")
        completed = g[g["exit_ts"].notna()]
        t0 = g["entry_ts"].min()
        t1 = max(
            completed["exit_ts"].max() if not completed.empty else t0,
            g["entry_ts"].max(),
        )
        span_s = max((t1 - t0).total_seconds(), 1.0)
        span_days = span_s / 86400.0

        durations = completed["duration_s"].dropna().to_numpy(dtype=float)
        w_mean = float(durations.mean()) if durations.size else None
        w_p50 = float(np.percentile(durations, 50)) if durations.size else None

        # time-averaged WIP: stay-time inside [t0, t1] per unit time
        clip_start = g["entry_ts"].clip(lower=t0)
        clip_end = g["exit_ts"].fillna(t1).clip(upper=t1)
        stay_time = (clip_end - clip_start).dt.total_seconds().clip(lower=0).sum()
        l_avg = float(stay_time / span_s)

        mu_per_day = float(len(completed) / span_days)

        # Little's-law consistency L ~ lambda x W, measured on a TRIMMED
        # observation window (middle 80% of the timeline) so stays can cross
        # its boundaries — measured over the full span the three quantities
        # satisfy the identity trivially. L = time-averaged WIP inside the
        # window; lambda = arrivals inside it; W = mean sojourn of those
        # arrivals (open stays count in L but can't contribute a sojourn,
        # which is exactly how leakage/aging shows up as ratio > 1).
        littles_ratio = None
        obs0 = t0 + pd.Timedelta(seconds=0.1 * span_s)
        obs1 = t1 - pd.Timedelta(seconds=0.1 * span_s)
        obs_span_s = (obs1 - obs0).total_seconds()
        if obs_span_s > 0:
            in_obs = (g["entry_ts"] >= obs0) & (g["entry_ts"] < obs1)
            arrivals = g[in_obs]
            arr_dur = arrivals["duration_s"].dropna().to_numpy(dtype=float)
            obs_start = g["entry_ts"].clip(lower=obs0)
            obs_end = g["exit_ts"].fillna(obs1).clip(upper=obs1)
            l_obs = float(
                (obs_end - obs_start).dt.total_seconds().clip(lower=0).sum() / obs_span_s
            )
            lam_obs = len(arrivals) / obs_span_s
            if arr_dur.size and lam_obs > 0 and arr_dur.mean() > 0:
                littles_ratio = float(l_obs / (lam_obs * float(arr_dur.mean())))

        inter = np.diff(entries).astype("timedelta64[s]").astype(float)
        cv_arrival = (
            float(inter.std() / inter.mean()) if inter.size >= 2 and inter.mean() > 0 else None
        )
        cv_sojourn = (
            float(durations.std() / durations.mean())
            if durations.size >= 2 and durations.mean() > 0
            else None
        )

        # occupancy at entry: stays entered strictly before minus stays
        # already gone (open stays never leave, so they simply never subtract)
        exits_sorted = np.sort(completed["exit_ts"].to_numpy(dtype="datetime64[ns]"))
        occ_all = np.searchsorted(entries, g["entry_ts"].to_numpy(dtype="datetime64[ns]"), side="left") - np.searchsorted(
            exits_sorted, g["entry_ts"].to_numpy(dtype="datetime64[ns]"), side="right"
        )
        comp_mask = g["exit_ts"].notna().to_numpy()
        occ = occ_all[comp_mask].astype(float)
        soj = g["duration_s"].to_numpy(dtype=float)[comp_mask]
        load_r = None
        if occ.size >= 8 and occ.std() > 0 and np.nanstd(soj) > 0:
            load_r = float(np.corrcoef(occ, soj)[0, 1])

        # Queue-model lens (experimental): an aggregated-server
        # G/G/1 approximation with mined parameters. Service time = median
        # sojourn of LOW-LOAD arrivals (occupancy at entry <= its p25 — what a
        # case experiences when nothing queues ahead of it); effective service
        # rate = p90 of daily departures (peak sustained throughput);
        # Kingman's formula then predicts the stationary mean wait. Gaps
        # between prediction and measurement are informative, not failures:
        # the model describes stationary behavior, so regime shifts (drift,
        # capacity collapse) show up exactly as large deviations.
        queue_model = None
        if occ.size >= 20 and durations.size >= 20:
            low_load = soj[occ <= np.percentile(occ, 25)]
            tau = float(np.median(low_load)) if low_load.size >= 5 else float(np.median(soj))
            daily_exits = (
                completed.groupby(completed["exit_ts"].dt.floor("D")).size().to_numpy(dtype=float)
            )
            mu_per_s = float(np.percentile(daily_exits, 90)) / 86400.0 if daily_exits.size else 0.0
            lam_per_s_est = len(g) / span_s
            rho = lam_per_s_est / mu_per_s if mu_per_s > 0 else None
            # the model's arrival CV winsorizes gaps at their p90 — otherwise
            # off-hours idle periods dominate the burstiness estimate and
            # Kingman wildly overpredicts for zones that drain instantly
            cv_a_model = None
            if inter.size >= 2:
                gaps_w = np.minimum(inter, np.percentile(inter, 90))
                if gaps_w.mean() > 0:
                    cv_a_model = float(gaps_w.std() / gaps_w.mean())
            kingman_wait = None
            if rho is not None and 0 < rho < 1 and cv_a_model is not None and cv_sojourn is not None:
                kingman_wait = float(
                    (rho / (1 - rho)) * ((cv_a_model**2 + cv_sojourn**2) / 2) * (1 / mu_per_s)
                )
            mean_soj = float(np.mean(soj))
            measured_wait = max(0.0, mean_soj - tau)
            if tau >= mean_soj:
                fit = "degenerate"  # low-load arrivals aren't faster (e.g. batching)
            elif rho is not None and rho >= 1:
                fit = "overloaded"
            elif kingman_wait is not None and measured_wait > max(3 * kingman_wait, 4 * tau):
                fit = "regime-shift"  # stationary model can't explain the waits
            else:
                fit = "plausible"
            queue_model = {
                "service_time_s": tau,
                "service_rate_per_day": mu_per_s * 86400.0,
                "utilization": rho,
                "kingman_wait_s": kingman_wait,
                "measured_wait_s": measured_wait,
                "fit": fit,
            }

        step = max(1, occ.size // int(scatter_limit))
        zones_out.append(
            {
                "zone": zone,
                "stay_count": int(len(g)),
                "completed_count": int(len(completed)),
                "arrival_rate_per_day": float(len(g) / span_days),
                "departure_rate_per_day": mu_per_day,
                "sojourn_mean_s": w_mean,
                "sojourn_p50_s": w_p50,
                "wip_time_avg": l_avg,
                "littles_ratio": littles_ratio,
                "cv_interarrival": cv_arrival,
                "cv_sojourn": cv_sojourn,
                "load_dependence_r": load_r,
                "queue_model": queue_model,
                "scatter": {
                    "occupancy_at_entry": occ[::step].tolist(),
                    "sojourn_s": soj[::step].tolist(),
                },
            }
        )
    return _clean_json(
        {
            "note": (
                "Little's ratio ~ 1 indicates stationary, non-leaking flow; the "
                "load-dependence coefficient is a Pearson correlation — "
                "association, not causation."
            ),
            "zones": zones_out,
        }
    )


def _handover_records(stays: pd.DataFrame) -> pd.DataFrame:
    """One row per inter-zone handover: (src, tgt, exit_ts, delay_s).

    For every completed stay, the case's *flow successor* is its first stay
    (any zone) entering at or after the exit — parallel branches overlapping
    in time therefore never produce a false handover. Same-zone successors
    are revisits (covered by the case_revisit_* metrics) and excluded.
    """
    records: list[tuple[str, str, pd.Timestamp, float]] = []
    for _, g in stays.groupby("case_id", sort=False):
        g = g.sort_values("entry_ts")
        entries = g["entry_ts"].to_numpy(dtype="datetime64[ns]")
        zones_arr = g["zone"].to_numpy()
        exits = g["exit_ts"].to_numpy(dtype="datetime64[ns]")
        n = len(g)
        for i in range(n):
            if pd.isna(exits[i]):
                continue
            j = int(np.searchsorted(entries, exits[i], side="left"))
            if j == i:  # zero-duration corner case: skip the stay itself
                j += 1
            if j >= n:
                continue
            delay_s = float((entries[j] - exits[i]) / np.timedelta64(1, "s"))
            records.append((str(zones_arr[i]), str(zones_arr[j]), pd.Timestamp(exits[i]), delay_s))
    df = pd.DataFrame(records, columns=["src", "tgt", "exit_ts", "delay_s"])
    return df[df["src"] != df["tgt"]]


def _aggregate_handovers(pairs_df: pd.DataFrame) -> list[dict]:
    agg = (
        pairs_df.groupby(["src", "tgt"])["delay_s"]
     .agg(count="size", median_delay_s="median", mean_delay_s="mean")
     .reset_index()
     .sort_values("count", ascending=False)
    )
    return _records(agg)


@router.get("/analyses/{analysis_id}/handovers")
@endpoint
def get_handovers(analysis_id: str, periods: int = 0):
    """Inter-zone handover structure from case-zone stays.

    Returned per zone pair: volume and handover-delay stats. The handover
    delay is waiting *between* zones — time in no zone at all, e.g. a queue
    at the boundary that neither zone's sojourn accounts for.

    With ``periods`` = N > 0, the timeline is additionally split into N equal
    spans (by handover timestamp) and each span's pair aggregation is
    returned too — the data behind the flow view's time slider, so scrubbing
    animates structural change without refetching.
    """
    meta = _get_analysis_or_404(analysis_id)
    stays = _zone_stays_frame(analysis_id, meta)
    pairs_df = _handover_records(stays) if not stays.empty else pd.DataFrame()
    if pairs_df.empty:
        return {"pairs": [], "handover_count": 0, "periods": []}
    out_periods = []
    n = max(0, int(periods))
    if n > 1:
        t0 = pairs_df["exit_ts"].min()
        t1 = pairs_df["exit_ts"].max()
        edges = pd.date_range(t0, t1, periods=n + 1)
        for i in range(n):
            lo, hi = edges[i], edges[i + 1]
            mask = (pairs_df["exit_ts"] >= lo) & (
                (pairs_df["exit_ts"] < hi) if i < n - 1 else (pairs_df["exit_ts"] <= hi)
            )
            out_periods.append(
                {
                    "start": str(lo),
                    "end": str(hi),
                    "pairs": _aggregate_handovers(pairs_df[mask]) if mask.any() else [],
                }
            )
    return _clean_json(
        {
            "pairs": _aggregate_handovers(pairs_df),
            "handover_count": int(len(pairs_df)),
            "periods": out_periods,
        }
    )


@router.get("/analyses/{analysis_id}/case-estimates")
@endpoint
def get_case_estimates(analysis_id: str, at: Optional[str] = None, limit: int = 200):
    """Remaining-time outlook for cases open at time ``at`` (descriptive variant).

    For each stay open at ``at`` (default: end of the log), the remaining
    time in its zone is estimated by **conditional survival** on the zone's
    own history *up to that moment*: among completed stays that ended before
    ``at``, take those longer than the open stay's current age and report the
    quantiles of (duration − age). No trained model, and no future data —
    stays completing after ``at`` never inform the estimate. When the log
    does know how an open stay actually ended, the true remaining time is
    returned alongside purely for validation display. Inter-case context
    (queue mining, Senderovich et al.) is the natural next step; this
    estimator is the honest baseline for it.
    """
    meta = _get_analysis_or_404(analysis_id)
    stays = _zone_stays_frame(analysis_id, meta)
    if stays.empty:
        return {"at": at, "zones": [], "cases": []}
    t = pd.Timestamp(at) if at else stays["entry_ts"].max()
    tz = stays["entry_ts"].dt.tz
    if t.tzinfo is None and tz is not None:
        t = t.tz_localize(tz)

    open_mask = (stays["entry_ts"] <= t) & (stays["exit_ts"].isna() | (stays["exit_ts"] > t))
    open_stays = stays[open_mask].copy()
    hist = stays[stays["exit_ts"].notna() & (stays["exit_ts"] <= t)]
    hist_by_zone = {
        z: np.sort(g["duration_s"].dropna().to_numpy(dtype=float))
        for z, g in hist.groupby("zone")
    }

    cases = []
    zone_rows: dict[str, dict] = {}
    for _, r in open_stays.iterrows():
        zone = str(r["zone"])
        age = float((t - r["entry_ts"]).total_seconds())
        durs = hist_by_zone.get(zone, np.array([]))
        tail = durs[durs > age]
        est = None
        if tail.size >= 5:
            est = {
                "p25": float(np.percentile(tail, 25) - age),
                "p50": float(np.percentile(tail, 50) - age),
                "p75": float(np.percentile(tail, 75) - age),
            }
        actual = (
            float((r["exit_ts"] - t).total_seconds()) if pd.notna(r["exit_ts"]) else None
        )
        cases.append(
            {
                "case_id": str(r["case_id"]),
                "zone": zone,
                "age_s": age,
                "est_remaining_p50_s": est["p50"] if est else None,
                "est_remaining_p25_s": est["p25"] if est else None,
                "est_remaining_p75_s": est["p75"] if est else None,
                "support_n": int(tail.size),
                "actual_remaining_s": actual,
            }
        )
        zr = zone_rows.setdefault(zone, {"zone": zone, "open_cases": 0, "ages": [], "ests": []})
        zr["open_cases"] += 1
        zr["ages"].append(age)
        if est:
            zr["ests"].append(est["p50"])
    cases.sort(key=lambda c: -c["age_s"])
    zones_out = [
        {
            "zone": z["zone"],
            "open_cases": z["open_cases"],
            "median_age_s": float(np.median(z["ages"])) if z["ages"] else None,
            "median_est_remaining_s": float(np.median(z["ests"])) if z["ests"] else None,
        }
        for z in sorted(zone_rows.values(), key=lambda x: -x["open_cases"])
    ]
    return _clean_json(
        {
            "note": (
                "Conditional-survival estimate from each zone's history up to the "
                "chosen moment — descriptive, not a trained model; actual values are "
                "shown only for validation."
            ),
            "at": str(t),
            "zones": zones_out,
            "cases": cases[: int(limit)],
        }
    )


@router.get("/analyses/{analysis_id}/whatif")
@endpoint
def get_whatif(analysis_id: str, zone: str, capacity_multiplier: float = 1.0):
    """What-if capacity analysis (experimental): the zone's
    actual arrivals and mined service demands replayed through a c-server
    queue, with c calibrated to reproduce the measured mean wait and then
    scaled by ``capacity_multiplier``. Arrivals are held fixed — upstream
    would react in reality — so this builds intuition, not guarantees; the
    baseline-vs-measured occupancy overlay is the validity check."""
    from analytics.whatif import whatif_capacity

    meta = _get_analysis_or_404(analysis_id)
    stays = _zone_stays_frame(analysis_id, meta)
    if zone not in set(stays["zone"].unique()):
        raise HTTPException(422, f"Unknown zone {zone!r}")
    mult = min(max(float(capacity_multiplier), 0.25), 4.0)
    result = whatif_capacity(stays, zone, capacity_multiplier=mult)
    if result is None:
        raise HTTPException(422, "Too few completed stays in this zone for a what-if run")
    result["note"] = (
        "Counterfactual with fixed arrivals and mined service demands — an "
        "approximation for intuition, not a guarantee; check how well the "
        "baseline tracks the measured occupancy before trusting the what-if."
    )
    return _clean_json(result)


def _transitive(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    """Transitive closure of a small digraph (zones), cycle-safe."""
    out: dict[str, set[str]] = {}
    for start in graph:
        seen: set[str] = set()
        stack = list(graph.get(start, ()))
        while stack:
            v = stack.pop()
            if v in seen:
                continue
            seen.add(v)
            stack.extend(graph.get(v, ()))
        out[start] = seen - {start}
    return out


@router.get("/analyses/{analysis_id}/bottlenecks")
@endpoint
def get_bottleneck_states(analysis_id: str):
    """Dynamic bottleneck-state suggestions per zone and window (in the spirit of Toosinezhad et al., ICPM 2020: bottlenecks are dynamic
    and propagate).

    Heuristic classification from the zone-feature table plus the handover
    graph — *suggestions with hedged semantics, not ground truth*:

    - ``queueing``: the zone's own backlog is building (positive netflow with
      above-median occupancy) and no downstream congestion explains it — the
      zone looks like the constraint itself.
    - ``blocked``: backlog building while some *immediate downstream* zone is
      simultaneously congested (occupancy above its own p75 and rising) — the
      congestion may be inherited, not caused here.
    - ``starving``: the zone runs dry (arrivals and occupancy below its own
      p25) while some *upstream* zone (transitively) is congested — flow is
      being held back before it reaches this zone.
    - ``flowing``: none of the above.

    Thresholds are per-zone quantiles over the zone's own history, so a
    naturally busy zone is not permanently "congested".
    """
    _get_analysis_or_404(analysis_id)
    meta = store.get_analysis(analysis_id)
    zf = _load_features_or_409(analysis_id)
    stays = _zone_stays_frame(analysis_id, meta)
    pairs = _handover_records(stays) if not stays.empty else pd.DataFrame()

    down: dict[str, set[str]] = {}
    up: dict[str, set[str]] = {}
    if not pairs.empty:
        vol = pairs.groupby(["src", "tgt"]).size()
        # ignore rare pairs (< 2% of handovers): noise edges make everything
        # look adjacent to everything
        floor = max(1, int(0.02 * len(pairs)))
        for (src, tgt), n in vol.items():
            if n >= floor:
                down.setdefault(src, set()).add(tgt)
                up.setdefault(tgt, set()).add(src)
    up_trans = _transitive(up)

    zones = sorted(zf["zone"].dropna().unique().tolist())
    piv_occ = zf.pivot_table(index="window_start", columns="zone", values="token_present_end")
    piv_net = zf.pivot_table(index="window_start", columns="zone", values="token_netflow")
    piv_ent = zf.pivot_table(index="window_start", columns="zone", values="token_enter")
    q = {
        z: {
            "occ_med": float(piv_occ[z].quantile(0.5)),
            "occ_hi": float(piv_occ[z].quantile(0.75)),
            "occ_lo": float(piv_occ[z].quantile(0.25)),
            "ent_lo": float(piv_ent[z].quantile(0.25)),
        }
        for z in zones
    }

    windows = [str(w) for w in piv_occ.index]
    out_zones = []
    for z in zones:
        states = []
        for w in piv_occ.index:
            occ = float(piv_occ.at[w, z]) if pd.notna(piv_occ.at[w, z]) else 0.0
            net = float(piv_net.at[w, z]) if pd.notna(piv_net.at[w, z]) else 0.0
            ent = float(piv_ent.at[w, z]) if pd.notna(piv_ent.at[w, z]) else 0.0
            growing = net > 0 and occ >= q[z]["occ_med"] and occ > 0
            # congestion requires strictly positive occupancy: a zone whose
            # p75 is 0 must not count as congested while sitting empty
            downstream_congested = any(
                pd.notna(piv_occ.at[w, d])
                and float(piv_occ.at[w, d]) > 0
                and float(piv_occ.at[w, d]) >= q[d]["occ_hi"]
                and float(piv_net.at[w, d] if pd.notna(piv_net.at[w, d]) else 0) > 0
                for d in down.get(z, ())
                if d in q
            )
            upstream_congested = any(
                pd.notna(piv_occ.at[w, u])
                and float(piv_occ.at[w, u]) > 0
                and float(piv_occ.at[w, u]) >= q[u]["occ_hi"]
                for u in up_trans.get(z, ())
                if u in q
            )
            if growing and downstream_congested:
                state = "blocked"
            elif growing:
                state = "queueing"
            elif ent <= q[z]["ent_lo"] and occ <= q[z]["occ_lo"] and upstream_congested:
                state = "starving"
            else:
                state = "flowing"
            states.append(state)
        counts = {s: states.count(s) for s in ("flowing", "queueing", "blocked", "starving")}
        out_zones.append({"zone": z, "states": states, "counts": counts})
    return _clean_json(
        {
            "note": (
                "Heuristic state suggestions from per-zone quantile thresholds and "
                "the handover graph — indications to investigate, not ground truth."
            ),
            "windows": windows,
            "zones": out_zones,
            "edges": [
                {"src": s, "tgt": t} for s, ts in sorted(down.items()) for t in sorted(ts)
            ],
        }
    )


# ---------------------------------------------------------------------------
# Analysis views: overview/alerts, trends, changepoints, dependencies, prediction
# ---------------------------------------------------------------------------


@router.get("/analyses/{analysis_id}/overview")
@endpoint
def get_overview(analysis_id: str):
    meta = _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    latest_ts = zf["window_start"].max()
    latest = zf[zf["window_start"] == latest_ts]
    conf_cols = [c for c in zf.columns if c.startswith("alignment_")]
    conformance = (
        {c: (None if latest[c].dropna().empty else float(latest[c].dropna().iloc[0])) for c in conf_cols}
        if not latest.empty
        else {}
    )
    per_zone = []
    for zone, grp in latest.groupby("zone"):
        row = grp.iloc[0]
        per_zone.append(
            {
                "zone": str(zone),
                "token_present_end": float(row.get("token_present_end", 0) or 0),
                "case_present_end": float(row.get("case_present_end", 0) or 0),
                "token_avg_age_open": float(row["token_avg_age_open"])
                if "token_avg_age_open" in row and pd.notna(row["token_avg_age_open"])
                else None,
            }
        )
    return _clean_json(
        {
            "zones": sorted(zf["zone"].dropna().unique().tolist()),
            "window_count": int(zf["window_start"].nunique()),
            "latest_window": str(latest_ts),
            "latest_window_end": str(pd.Timestamp(latest_ts) + pd.tseries.frequencies.to_offset(meta["timeframe"])) if pd.notna(latest_ts) else None,
            "window_conformance": conformance,
            "per_zone_latest": per_zone,
        }
    )


@router.get("/analyses/{analysis_id}/alerts")
@endpoint
def get_alerts(
    analysis_id: str,
    lookback_windows: int = 7,
    open_age_threshold: Optional[float] = None,
    backlog_threshold: float = 20.0,
):
    meta = _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    tf_label = TIMEFRAME_LABELS.get(meta["timeframe"], "Daily")
    if open_age_threshold is None:
        open_age_threshold = get_default_alert_threshold(
            "token_avg_age_open", get_duration_unit_seconds(tf_label)
        )
    recent = get_recent_alerts_window(zf, lookback_windows)
    flagged = compute_basic_alerts(
        recent,
        open_age_threshold=float(open_age_threshold),
        backlog_threshold=float(backlog_threshold),
    )
    summary = summarize_basic_alerts_per_zone(
        flagged,
        friendly=BASIC_ALERT_FRIENDLY,
        open_age_threshold=float(open_age_threshold),
        backlog_threshold=float(backlog_threshold),
    )
    return {
        "thresholds": {
            "open_age_threshold": float(open_age_threshold),
            "backlog_threshold": float(backlog_threshold),
            "lookback_windows": int(lookback_windows),
        },
        "period": {
            "window_start": str(recent["window_start"].min()) if not recent.empty else None,
            "window_end": str(pd.Timestamp(recent["window_start"].max()) + pd.tseries.frequencies.to_offset(meta["timeframe"])) if not recent.empty else None,
            "window_count": int(recent["window_start"].nunique()),
        },
        "flagged_rows": _records(flagged),
        "per_zone_summary": _records(summary),
    }


def _bh_fdr(pvals: np.ndarray) -> np.ndarray:
    """Benjamini–Hochberg adjusted p-values (q-values)."""
    n = pvals.size
    order = np.argsort(pvals)
    ranked = pvals[order] * n / (np.arange(n) + 1)
    # enforce monotonicity from the largest rank down
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.clip(ranked, 0, 1)
    return out


@router.get("/analyses/{analysis_id}/compare")
@endpoint
def compare_periods(
    analysis_id: str,
    start_a: str,
    end_a: str,
    start_b: str,
    end_b: str,
    min_windows: int = 3,
):
    """Compare two time slices per zone and metric ("process
    cubes lite": slicing event data into comparable cells, van der Aalst).

    For every zone × metric: window-mean in each slice, absolute and relative
    delta, and Welch's t-test with **Benjamini–Hochberg FDR control across
    all comparisons** (many zone×metric cells are tested at once — without
    correction, some would look "significant" by chance alone). Significance
    here means "the window means differ beyond window-to-window noise", not
    that the change is practically important, and never why it happened.
    """
    from scipy import stats

    _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    ws = zf["window_start"]

    def _slice(lo: str, hi: str) -> pd.DataFrame:
        lo_ts, hi_ts = pd.Timestamp(lo), pd.Timestamp(hi)
        if lo_ts.tzinfo is None and ws.dt.tz is not None:
            lo_ts, hi_ts = lo_ts.tz_localize(ws.dt.tz), hi_ts.tz_localize(ws.dt.tz)
        return zf[(ws >= lo_ts) & (ws <= hi_ts)]

    a, b = _slice(start_a, end_a), _slice(start_b, end_b)
    if a.empty or b.empty:
        raise HTTPException(422, "One of the slices contains no windows")

    metrics = [
        c
        for c in zf.columns
        if c not in ("zone", "window_start", "window_end")
        and not c.startswith("alignment_")
        and pd.api.types.is_numeric_dtype(zf[c])
    ]
    labels = get_metric_label_map()
    rows = []
    for zone in sorted(zf["zone"].dropna().unique()):
        ga, gb = a[a["zone"] == zone], b[b["zone"] == zone]
        for m in metrics:
            va = ga[m].dropna().to_numpy(dtype=float)
            vb = gb[m].dropna().to_numpy(dtype=float)
            if len(va) < int(min_windows) or len(vb) < int(min_windows):
                continue
            mean_a, mean_b = float(va.mean()), float(vb.mean())
            delta = mean_b - mean_a
            rel = delta / abs(mean_a) if mean_a != 0 else (np.inf if delta > 0 else (-np.inf if delta < 0 else 0.0))
            if va.std() == 0 and vb.std() == 0:
                p = 1.0 if mean_a == mean_b else 0.0
            else:
                p = float(stats.ttest_ind(va, vb, equal_var=False).pvalue)
            rows.append(
                {
                    "zone": zone,
                    "metric": m,
                    "metric_label": labels.get(m, m),
                    "mean_a": mean_a,
                    "mean_b": mean_b,
                    "delta": delta,
                    "rel_delta": None if not np.isfinite(rel) else float(rel),
                    "n_a": int(len(va)),
                    "n_b": int(len(vb)),
                    "p_value": p,
                }
            )
    if rows:
        q = _bh_fdr(np.array([r["p_value"] for r in rows]))
        for r, qi in zip(rows, q):
            r["q_value"] = float(qi)
            r["significant"] = bool(qi < 0.05)
        rows.sort(key=lambda r: (r["q_value"], -abs(r["rel_delta"] or 0)))
    return _clean_json(
        {
            "note": (
                "Welch's t-test on window means with Benjamini–Hochberg FDR control "
                "across all zone×metric comparisons. Significant = beyond window "
                "noise; says nothing about importance or cause."
            ),
            "slice_a": {"start": start_a, "end": end_a},
            "slice_b": {"start": start_b, "end": end_b},
            "rows": rows,
        }
    )


@router.get("/analyses/{analysis_id}/trends/ci")
@endpoint
def get_trend_ci(analysis_id: str, confidence: float = 0.95):
    """Per-window confidence intervals for the completed-stay duration mean
 : window means are computed from few stays, so the trend
    line alone overstates certainty. Returns, per zone and window, the mean
    duration of case-zone stays completing in the window with a t-based CI
    (NaN when fewer than 2 stays complete). Buckets use the same half-open
    [window_start, next window) grid as the feature table."""
    from scipy import stats

    meta = _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    stays = _zone_stays_frame(analysis_id, meta)
    completed = stays[stays["exit_ts"].notna()]
    ws = sorted(pd.to_datetime(zf["window_start"]).unique())
    if not ws or completed.empty:
        return {"metric": "case_avg_duration_completed", "rows": []}
    step = pd.tseries.frequencies.to_offset(meta["timeframe"])
    edges = pd.DatetimeIndex(list(ws) + [ws[-1] + step])
    conf = min(max(float(confidence), 0.5), 0.999)

    rows = []
    for zone, g in completed.groupby("zone"):
        idx = edges.searchsorted(g["exit_ts"], side="right") - 1
        g = g.assign(_w=idx)
        g = g[(g["_w"] >= 0) & (g["_w"] < len(ws))]
        for wi, gw in g.groupby("_w"):
            vals = gw["duration_s"].dropna().to_numpy(dtype=float)
            if vals.size == 0:
                continue
            mean = float(vals.mean())
            if vals.size >= 2 and vals.std(ddof=1) > 0:
                half = float(
                    stats.t.ppf(0.5 + conf / 2, vals.size - 1)
                    * vals.std(ddof=1)
                    / np.sqrt(vals.size)
                )
                lo, hi = mean - half, mean + half
            else:
                lo = hi = None
            rows.append(
                {
                    "zone": str(zone),
                    "window_start": str(ws[int(wi)]),
                    "mean_s": mean,
                    "lo_s": lo,
                    "hi_s": hi,
                    "n": int(vals.size),
                }
            )
    rows.sort(key=lambda r: (r["zone"], r["window_start"]))
    return _clean_json(
        {
            "note": (
                f"{int(conf * 100)}% t-based confidence intervals on per-window mean "
                "completed-stay durations — window means come from small samples."
            ),
            "metric": "case_avg_duration_completed",
            "rows": rows,
        }
    )


@router.get("/analyses/{analysis_id}/drift")
@endpoint
def get_drift_scores(analysis_id: str, half_window: int = 5):
    """Per-zone multivariate drift scores: energy distance
    between the trailing and leading half-window feature distributions —
    descriptive change intensity, not causal attribution."""
    from analytics.drift import zone_drift_scores

    _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    drift = zone_drift_scores(zf, half_window=int(half_window))
    return {
        "note": (
            "Energy distance between each zone's feature distributions before/after "
            "the window — how much behavior changed, not why."
        ),
        "half_window": int(half_window),
        "rows": _records(drift),
    }


class ZoneMetricPair(BaseModel):
    zone: str = Field(min_length=1)
    metric: str = Field(min_length=1)


class TrendSelectionRequest(BaseModel):
    pairs: list[ZoneMetricPair]
    normalize: bool = False
    local_enabled: bool = True
    overall_enabled: bool = False
    cp_strictness: int = Field(50, ge=0, le=100)


@router.post("/analyses/{analysis_id}/trends/selection")
@endpoint
def selected_trends(analysis_id: str, body: TrendSelectionRequest):
    """Exact pairs; aggregate signals/contributions. Legacy GET routes unchanged."""
    _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    try:
        result = services.selected_trend_analysis(zf, [(p.zone, p.metric) for p in body.pairs],
            normalize=body.normalize, local_enabled=body.local_enabled,
            overall_enabled=body.overall_enabled, cp_strictness=body.cp_strictness)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    overall = result["overall"]
    return {
        "rows": _records(result["rows"]),
        "series": result["series"],
        "local_changepoints": _records(result["local_changepoints"]),
        "overall": {**overall, **{key: _records(overall[key]) for key in ("signal", "changepoints", "contributions")}},
        "protocol": {"local_cost": "l2", "aggregate_method": "mean", "min_points": 8,
            "min_size": 3, "display_sd_ddof": 1, "aggregate_sd_ddof": 0,
            "missing_policy": "Mean of available standardized components; no interpolation",
            "contribution_context": "adjacent_detected_segments"},
    }


@router.get("/analyses/{analysis_id}/trends")
@endpoint
def get_trends(
    analysis_id: str,
    zones: Optional[str] = None,
    metrics: Optional[str] = None,
    normalize: bool = False,
):
    _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    zone_list = zones.split(",") if zones else sorted(zf["zone"].dropna().unique().tolist())
    metric_list = (
        [canonical_metric_name(m) for m in metrics.split(",")]
        if metrics
        else [m for m in ("token_present_end", "token_avg_age_open") if m in zf.columns]
    )
    long = zf[zf["zone"].isin(zone_list)][["zone", "window_start"] + [m for m in metric_list if m in zf.columns]]
    long = long.melt(id_vars=["zone", "window_start"], var_name="metric", value_name="value")
    labels = get_metric_label_map()
    long["metric_label"] = long["metric"].map(lambda m: labels.get(m, m))
    if normalize and not long.empty:
        long["value"] = long.groupby(["zone", "metric"])["value"].transform(
            lambda s: (s - s.mean()) / s.std() if s.std() not in (0, None) and not np.isnan(s.std()) else s * 0
        )
    return {"rows": _records(long.sort_values(["metric", "zone", "window_start"]))}


@router.get("/analyses/{analysis_id}/changepoints")
@endpoint
def get_changepoints(
    analysis_id: str,
    zones: Optional[str] = None,
    metrics: Optional[str] = None,
    cp_strictness: int = 50,  # 0..100 (PELT penalty percentile) — Streamlit default
    min_size: int = 3,
    min_points: int = 8,
    max_per_series: int = 3,
    jump: int = 1,
):
    _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    zone_list = zones.split(",") if zones else sorted(zf["zone"].dropna().unique().tolist())
    metric_list = (
        [canonical_metric_name(m) for m in metrics.split(",")]
        if metrics
        else [m for m in ("token_present_end", "token_avg_age_open", "token_netflow") if m in zf.columns]
    )
    labels = get_metric_label_map()
    events = services.changepoint_events(
        zf=zf,
        zones=zone_list,
        metrics=metric_list,
        cp_strictness=int(cp_strictness),
        min_size=int(min_size),
        min_points=int(min_points),
        max_per_series=int(max_per_series),
        jump=int(jump),
        metric_display_map={m: labels.get(m, m) for m in metric_list},
    )
    return {"rows": _records(events)}


def _attach_dependency_significance(dep: pd.DataFrame, n_lags: int) -> pd.DataFrame:
    """Statistical guardrail  for the dependency scan.

    ``best_corr`` is the max-|r| over ``n_lags`` scanned lags, so its plain
    p-value is optimistic — apply a Bonferroni factor for the lag selection,
    then Benjamini–Hochberg FDR across *all scanned pairs* (many zone×metric
    pairs are tested at once; without correction some look "significant" by
    chance alone). ``significant`` means "association beyond noise at FDR
    5%" — still association, never causation.
    """
    from scipy import stats

    dep = dep.copy()
    r = pd.to_numeric(dep["best_corr"], errors="coerce")
    n = pd.to_numeric(dep["overlap_points"], errors="coerce")
    p = pd.Series(np.nan, index=dep.index, dtype=float)
    valid = r.notna() & n.notna() & (n > 2) & (r.abs() < 1)
    t = r[valid].abs() * np.sqrt((n[valid] - 2) / (1 - r[valid] ** 2))
    p.loc[valid] = 2 * stats.t.sf(t, df=n[valid] - 2)
    p.loc[r.notna() & (r.abs() >= 1) & (n > 2)] = 0.0
    p = (p * max(1, int(n_lags))).clip(upper=1.0)
    dep["p_value"] = p
    q = np.full(len(dep), np.nan)
    finite = p.notna().to_numpy()
    if finite.any():
        q[finite] = _bh_fdr(p.to_numpy()[finite])
    dep["q_value"] = q
    dep["significant"] = pd.Series(q, index=dep.index) < 0.05
    return dep


_dependencies_cache: dict[tuple, dict] = {}


@router.get("/analyses/{analysis_id}/dependencies")
@endpoint
def get_dependencies(
    analysis_id: str,
    max_lag: int = 3,
    min_lag: int = 0,
    min_points: int = 8,
    correlate_changes: bool = False,
    top_n: int = 15,
):
    """Lagged cross-zone correlation (association, not causation).

    Window-level conformance metrics (alignment_*) are excluded: they are
    identical for every zone by design, so cross-zone correlations against
    them are artifacts, not findings. Results are cached per parameter set —
    the all-pairs computation takes ~20s on larger datasets.
    """
    key = (analysis_id, max_lag, min_lag, min_points, correlate_changes, top_n)
    cached = _dependencies_cache.get(key)
    if cached is not None:
        return cached

    _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    metric_options = [
        m for m in get_basic_dependency_metrics(list(zf.columns))
        if not m.startswith("alignment_")
    ]
    dep = services.basic_dependency_matrix(
        zf=zf,
        metric_options=metric_options,
        max_lag=int(max_lag),
        min_lag=int(min_lag),
        min_points=int(min_points),
        correlate_changes=bool(correlate_changes),
    )
    if not dep.empty:
        dep = _attach_dependency_significance(dep, n_lags=int(max_lag) - int(min_lag) + 1)
    top = (
        select_basic_dependency_rows(dep, fallback_top_n=int(top_n)) if not dep.empty else dep
    )
    result = {
        "note": "Values are time-lagged Pearson correlations — association, not causation. "
        "Window-level conformance metrics are excluded from cross-zone pairing. "
        "Significance is FDR-controlled across the whole scan (with a lag-selection "
        "penalty) — 'beyond noise', not 'important'.",
        "metric_options": metric_options,
        "rows": _records(top),
        "row_count_all": int(len(dep)),
    }
    if len(_dependencies_cache) >= 32:  # bounded: drop the oldest entry
        _dependencies_cache.pop(next(iter(_dependencies_cache)))
    _dependencies_cache[key] = result
    return result


@router.get("/analyses/{analysis_id}/alerts/hints")
@endpoint
def get_alert_hints(
    analysis_id: str,
    zone: str,
    metric: str = "token_present_end",
    max_lag: int = 3,
):
    """Likely-contributor hints for an alerted zone.

    Ranks the alerted zone's *upstream* zones (transitively, via the handover
    graph) by (a) the strongest lagged Pearson correlation between their flow
    metrics and the alerted metric at lags 1..max_lag, and (b) how much their
    own behavior recently drifted (A9 scores). Association plus recency, not
    causation — a shortlist of where to look first, and the wording keeps the
    dependency-language guardrail everywhere.
    """
    from analytics.dependencies import lagged_best_corr
    from analytics.drift import zone_drift_scores

    meta = _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    if zone not in set(zf["zone"].dropna().unique()):
        raise HTTPException(422, f"Unknown zone {zone!r}")
    metric = canonical_metric_name(metric)
    if metric not in zf.columns:
        raise HTTPException(422, f"Unknown metric {metric!r}")

    stays = _zone_stays_frame(analysis_id, meta)
    pairs = _handover_records(stays) if not stays.empty else pd.DataFrame()
    up: dict[str, set[str]] = {}
    if not pairs.empty:
        floor = max(1, int(0.02 * len(pairs)))
        vol = pairs.groupby(["src", "tgt"]).size()
        for (src, tgt), n in vol.items():
            if n >= floor:
                up.setdefault(tgt, set()).add(src)
    upstream = sorted(_transitive(up).get(zone, set()))
    if not upstream:
        return {"zone": zone, "metric": metric, "hints": [], "note": "No upstream zones."}

    piv = zf.pivot_table(index="window_start", columns="zone", values=metric)
    y = piv[zone] if zone in piv.columns else pd.Series(dtype=float)
    src_metrics = list(dict.fromkeys([metric, "token_netflow", "token_enter"]))
    drift = zone_drift_scores(zf)
    recent_cut = sorted(zf["window_start"].unique())[-10:]

    hints = []
    for u in upstream:
        best = {"corr": np.nan, "lag": None, "src_metric": None}
        for sm in src_metrics:
            if sm not in zf.columns:
                continue
            pu = zf[zf["zone"] == u].set_index("window_start")[sm]
            corr, lag, n = lagged_best_corr(pu, y, max_lag=int(max_lag), min_lag=1)
            if pd.notna(corr) and (pd.isna(best["corr"]) or abs(corr) > abs(best["corr"])):
                best = {"corr": float(corr), "lag": int(lag), "src_metric": sm}
        du = drift[(drift["zone"] == u) & (drift["window_start"].isin(recent_cut))][
            "drift_score"
        ].dropna()
        hints.append(
            {
                "zone": u,
                "src_metric": best["src_metric"],
                "best_corr": None if pd.isna(best["corr"]) else best["corr"],
                "lag": best["lag"],
                "recent_drift_max": float(du.max()) if not du.empty else None,
            }
        )
    hints.sort(key=lambda h: -(abs(h["best_corr"]) if h["best_corr"] is not None else 0))
    return _clean_json(
        {
            "note": (
                "Upstream zones ranked by lagged correlation with the alerted metric, "
                "with recent drift as context — association, not causation; a "
                "shortlist of where to look first."
            ),
            "zone": zone,
            "metric": metric,
            "hints": hints,
        }
    )


class AdvancedAlertRule(BaseModel):
    metric: str
    op: str = Field(">=", pattern="^(>=|<=)$")
    threshold: float


class AdvancedAlertsRequest(BaseModel):
    rules: list[AdvancedAlertRule]
    combine_mode: str = Field("ANY", pattern="^(ANY|ALL)$")
    lookback_windows: int = 7


@router.post("/analyses/{analysis_id}/alerts/advanced")
@endpoint
def get_advanced_alerts(analysis_id: str, body: AdvancedAlertsRequest):
    """Custom alert rules combined with ANY/ALL semantics (advanced mode)."""
    _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    recent = get_recent_alerts_window(zf, int(body.lookback_windows))
    op_map = {">=": "≥", "<=": "≤"}
    flagged = compute_advanced_alerts(
        recent,
        rules=[(r.metric, op_map[r.op], float(r.threshold)) for r in body.rules],
        combine_mode=body.combine_mode,
    )
    keep = ["zone", "window_start"] + sorted(
        {canonical_metric_name(r.metric) for r in body.rules} & set(flagged.columns)
    )
    return {"flagged_rows": _records(flagged[keep] if not flagged.empty else flagged)}


@router.get("/analyses/{analysis_id}/changepoints/selection")
@endpoint
def get_selection_changepoints(
    analysis_id: str,
    zones: Optional[str] = None,
    metrics: Optional[str] = None,
    cp_strictness: int = 50,
    min_size: int = 3,
    min_points: int = 8,
    jump: int = 1,
    aggregate_method: str = "mean",
    max_selection_cps: int = 3,
    flank_points: int = 3,
):
    if aggregate_method not in ("mean", "median"):
        raise HTTPException(422, "aggregate_method must be 'mean' or 'median'")
    """Aggregate change points over a selection of zones/metrics, plus
    per-series contribution scores (composition of a shift, not causation)."""
    _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    zone_list = zones.split(",") if zones else sorted(zf["zone"].dropna().unique().tolist())
    metric_list = (
        [canonical_metric_name(m) for m in metrics.split(",")]
        if metrics
        else [m for m in ("token_present_end", "token_avg_age_open", "token_netflow") if m in zf.columns]
    )
    labels = get_metric_label_map()
    selection_label = "Selection"
    cps = services.selection_changepoints(
        zf=zf,
        zones=zone_list,
        metrics=metric_list,
        cp_strictness=int(cp_strictness),
        min_size=int(min_size),
        min_points=int(min_points),
        jump=int(jump),
        aggregate_method=aggregate_method,
        selection_label=selection_label,
        max_selection_cps=int(max_selection_cps),
        flank_points=int(flank_points),
    )
    contributions = (
        services.selection_changepoint_contributions(
            zf=zf,
            zones=zone_list,
            metrics=metric_list,
            selection_cp_events=cps,
            min_points=int(min_points),
            metric_display_map={m: labels.get(m, m) for m in metric_list},
            selection_label=selection_label,
            aggregate_method=aggregate_method,
            flank_points=int(flank_points),
        )
        if not cps.empty
        else cps.iloc[0:0]
    )
    return {"changepoints": _records(cps), "contributions": _records(contributions)}


@router.get("/analyses/{analysis_id}/dependencies/pair")
@endpoint
def get_dependency_pair(
    analysis_id: str,
    src_metric: str,
    tgt_metric: str,
    max_lag: int = 3,
    min_lag: int = 0,
    min_points: int = 8,
    correlate_changes: bool = False,
):
    """Full zone-pair lagged-correlation table for one metric pair (advanced)."""
    _get_analysis_or_404(analysis_id)
    zf = _load_features_or_409(analysis_id)
    dep = services.dependency_table(
        zf=zf,
        src_metric=canonical_metric_name(src_metric),
        tgt_metric=canonical_metric_name(tgt_metric),
        max_lag=int(max_lag),
        min_lag=int(min_lag),
        min_points=int(min_points),
        correlate_changes=bool(correlate_changes),
    )
    if dep is not None and not dep.empty:
        dep = _attach_dependency_significance(dep, n_lags=int(max_lag) - int(min_lag) + 1)
    return {
        "note": "Time-lagged Pearson correlation — association, not causation. "
        "Significance is FDR-controlled within this table.",
        "rows": _records(dep if dep is not None else pd.DataFrame()),
    }


@router.get("/analyses/{analysis_id}/diagnostics")
@endpoint
def get_diagnostics(analysis_id: str):
    """Leak/open-token diagnostics per zone (and per place when available)."""
    _get_analysis_or_404(analysis_id)
    zone_diag = store.load_frame(analysis_id, "zone_leak_diag")
    place_diag = store.load_frame(analysis_id, "place_leak_diag")
    if zone_diag is None:
        raise HTTPException(409, "Analysis has no computed artifacts yet")
    return {
        "zone_diagnostics": _records(zone_diag),
        "place_diagnostics": _records(place_diag) if place_diag is not None else [],
    }


# Forecasting has a separate causal prefix path; descriptive artifacts are never
# treated as causally available inputs.
from backend.forecasting import PredictionRequest, execute as execute_forecast, options as forecast_options
from backend import calibration as prediction_calibration
from backend import retrospective_prediction


@router.get("/analyses/{analysis_id}/prediction/retrospective/options")
@endpoint
def retrospective_prediction_options(analysis_id: str):
    _get_analysis_or_404(analysis_id)
    return _clean_json(retrospective_prediction.options(_load_features_or_409(analysis_id)))


@router.post("/analyses/{analysis_id}/prediction/retrospective")
@endpoint
def run_retrospective_prediction(analysis_id: str, body: retrospective_prediction.Request):
    meta = _get_analysis_or_404(analysis_id)
    try:
        return _clean_json(retrospective_prediction.execute(meta,_load_features_or_409(analysis_id),body))
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@router.get("/analyses/{analysis_id}/prediction/options")
@endpoint
def get_prediction_options(analysis_id: str, study_id: str | None = None):
    meta = _get_analysis_or_404(analysis_id)
    try:
        return _clean_json(forecast_options(meta, study_id))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/analyses/{analysis_id}/prediction")
@endpoint
def run_prediction(analysis_id: str, body: PredictionRequest):
    meta = _get_analysis_or_404(analysis_id)
    return _clean_json(execute_forecast(meta, body))


@router.post("/analyses/{analysis_id}/prediction/calibrate")
@endpoint
def calibrate_prediction(analysis_id: str, body: prediction_calibration.CalibrationRequest):
    meta = _get_analysis_or_404(analysis_id)
    try:
        bundle = get_bundle(meta['dataset_id'])
        from analytics.forecasting import utc, observed_bounds
        if utc(body.calibration_end) >= observed_bounds(bundle.log, meta['timeframe'])[1]:
            raise ValueError('Calibration end must precede the observation end; later data is required for the experiment.')
        return _clean_json(prediction_calibration.prepare(bundle.log, body.calibration_end, meta['timeframe']))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/analyses/{analysis_id}/prediction/studies")
@endpoint
def freeze_prediction_study(analysis_id: str, body: prediction_calibration.StudyRequest):
    meta = _get_analysis_or_404(analysis_id)
    try:
        return _clean_json(prediction_calibration.freeze(meta['dataset_id'], meta['timeframe'], body))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
