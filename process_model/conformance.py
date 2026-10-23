from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd
from process_model.time_index import EventTimeIndex


def _alignment_moves(alignment_dict) -> list:
    return alignment_dict.get("alignment", []) or alignment_dict.get("alignment_moves", [])


def _trace_timestamps(pm4py_trace) -> list[pd.Timestamp]:
    out: list[pd.Timestamp] = []
    try:
        for ev in pm4py_trace:
            if "time:timestamp" in ev:
                out.append(pd.Timestamp(ev["time:timestamp"]))
    except Exception:
        return []
    return out


def _classify_alignment_move(move) -> tuple[str | None, str | None]:
    if not (isinstance(move, (tuple, list)) and len(move) >= 2):
        return None, None
    log_raw, model_raw = move[0], move[1]
    log_move = None if log_raw in (None, ">>") else str(log_raw)
    model_move = None if model_raw in (None, ">>") else str(model_raw)
    return log_move, model_move


def alignment_move_table_from_alignments(log, aligned: Iterable[dict], net) -> pd.DataFrame:
    """One row per timed alignment move: (case_id, ts, move_type, t_name).

    This is the zone-independent basis for *zone-attributed* conformance:
    each move carries the transition it concerns, so it can later be mapped
    to the zones adjacent to that transition (process_model.features).

    Timing mirrors the replay's walk: sync and log moves take the trace
    event's timestamp; visible model moves take the last seen timestamp
    (+1µs), since the model fires without an observed event. Silent (tau)
    moves are excluded — they are not deviations and are excluded from the
    window-level counts as well. For log-only moves ``t_name`` is the model
    transition matching the event's activity label (None if the label does
    not occur in the model — such moves cannot be zone-attributed).
    """
    from process_model.replay import _petri_maps, alignment_transition_name

    _, _, label_to_tname = _petri_maps(net)
    transitions = {t.name: t for t in net.transitions}
    label_counts = {}
    for transition in net.transitions:
        label_counts[transition.label] = label_counts.get(transition.label, 0) + 1
    rows: list[dict] = []
    eps = pd.Timedelta(microseconds=1)

    for trace, alignment_dict in zip(log, aligned):
        case_id = str(trace.attributes.get("concept:name", "0"))
        trace_ts = _trace_timestamps(trace)
        if not trace_ts:
            continue
        j = 0
        last_ts = trace_ts[0]

        for position, move in enumerate(_alignment_moves(alignment_dict)):
            log_move, model_move = _classify_alignment_move(move)
            exact_name = alignment_transition_name(
                alignment_dict, position, move[0], move[1], net, label_to_tname, transitions
            )
            if log_move is not None and model_move is not None:
                ts = trace_ts[j] if j < len(trace_ts) else last_ts
                last_ts = max(ts, last_ts)
                rows.append(
                    {
                        "case_id": case_id,
                        "ts": last_ts,
                        "move_type": "sync",
                        "t_name": exact_name,
                    }
                )
                j += 1
            elif log_move is not None:
                ts = trace_ts[j] if j < len(trace_ts) else last_ts
                last_ts = max(ts, last_ts)
                if label_counts.get(log_move, 0) > 1:
                    raise ValueError(
                        f"Log-only activity {log_move!r} matches multiple transitions; "
                        "zone attribution is ambiguous and requires an explicit attribution policy"
                    )
                tname = label_to_tname.get(str(log_move))
                rows.append(
                    {
                        "case_id": case_id,
                        "ts": last_ts,
                        "move_type": "log",
                        "t_name": str(tname) if tname is not None else None,
                    }
                )
                j += 1
            elif model_move is not None:
                last_ts = last_ts + eps
                tname = exact_name
                rows.append(
                    {
                        "case_id": case_id,
                        "ts": last_ts,
                        "move_type": "model",
                        "t_name": str(tname) if tname is not None else str(model_move),
                    }
                )
            # silent tau moves (both None): skipped

    df = pd.DataFrame(rows, columns=["case_id", "ts", "move_type", "t_name"])
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"])
    return df


def trace_conformance_table_from_alignments(log, aligned: Iterable[dict]) -> pd.DataFrame:
    rows = []

    for trace, alignment_dict in zip(log, aligned):
        case_id = str(trace.attributes.get("concept:name", "0"))
        trace_ts = _trace_timestamps(trace)
        trace_start = trace_ts[0] if trace_ts else pd.NaT
        trace_end = trace_ts[-1] if trace_ts else pd.NaT

        sync_move_count = 0
        log_move_count = 0
        model_move_count = 0

        for move in _alignment_moves(alignment_dict):
            log_move, model_move = _classify_alignment_move(move)
            if log_move is not None and model_move is not None:
                sync_move_count += 1
            elif log_move is not None:
                log_move_count += 1
            elif model_move is not None:
                model_move_count += 1

        deviation_count = log_move_count + model_move_count
        rows.append(
            {
                "case_id": case_id,
                "trace_start": trace_start,
                "trace_end": trace_end,
                "trace_event_count": len(trace_ts),
                "alignment_trace_fitness": float(alignment_dict.get("fitness")) if alignment_dict.get("fitness") is not None else np.nan,
                "alignment_trace_cost": float(alignment_dict.get("cost")) if alignment_dict.get("cost") is not None else np.nan,
                "alignment_sync_move_count": sync_move_count,
                "alignment_log_move_count": log_move_count,
                "alignment_model_move_count": model_move_count,
                "alignment_deviation_count": deviation_count,
                "alignment_has_deviation": int(deviation_count > 0),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    out["trace_start"] = pd.to_datetime(out["trace_start"])
    out["trace_end"] = pd.to_datetime(out["trace_end"])
    return out


def add_window_conformance_features(
    zone_feat: pd.DataFrame,
    trace_conformance_df: pd.DataFrame | None,
) -> pd.DataFrame:
    if zone_feat.empty or trace_conformance_df is None:
        return zone_feat

    trace_conformance_df = trace_conformance_df.copy()
    if trace_conformance_df.empty or "trace_end" not in trace_conformance_df.columns:
        return zone_feat

    trace_conformance_df["trace_end"] = pd.to_datetime(trace_conformance_df["trace_end"])
    if trace_conformance_df["trace_end"].isna().all():
        return zone_feat

    window_rows = []
    windows = (
        zone_feat[["window_start", "window_end"]]
        .drop_duplicates()
        .sort_values(["window_start", "window_end"])
    )

    trace_index = EventTimeIndex(trace_conformance_df["trace_end"])
    for row in windows.itertuples(index=False):
        w0 = pd.to_datetime(row.window_start)
        w1 = pd.to_datetime(row.window_end)
        in_window = trace_conformance_df.iloc[trace_index.between(w0, w1)]

        trace_count = int(len(in_window))
        window_rows.append(
            {
                "window_start": w0,
                "window_end": w1,
                "alignment_trace_count": trace_count,
                "alignment_trace_fitness_mean": float(in_window["alignment_trace_fitness"].mean()) if trace_count else np.nan,
                "alignment_trace_cost_mean": float(in_window["alignment_trace_cost"].mean()) if trace_count else np.nan,
                "alignment_sync_move_count": int(in_window["alignment_sync_move_count"].sum()) if trace_count else 0,
                "alignment_log_move_count": int(in_window["alignment_log_move_count"].sum()) if trace_count else 0,
                "alignment_model_move_count": int(in_window["alignment_model_move_count"].sum()) if trace_count else 0,
                "alignment_deviation_count": int(in_window["alignment_deviation_count"].sum()) if trace_count else 0,
                "alignment_trace_deviation_rate": float(in_window["alignment_has_deviation"].mean()) if trace_count else 0.0,
            }
        )

    conformance_window_df = pd.DataFrame(window_rows)
    if conformance_window_df.empty:
        return zone_feat

    merged = zone_feat.merge(conformance_window_df, on=["window_start", "window_end"], how="left")
    for count_col in [
        "alignment_trace_count",
        "alignment_sync_move_count",
        "alignment_log_move_count",
        "alignment_model_move_count",
        "alignment_deviation_count",
        "alignment_trace_deviation_rate",
    ]:
        if count_col in merged.columns:
            merged[count_col] = merged[count_col].fillna(0)
    return merged
