from __future__ import annotations

from typing import Iterable

import pandas as pd

from analytics.metrics.compat import canonical_metric_name


BASIC_ALERT_FRIENDLY = {
    "token_avg_age_open": "Open work getting older",
    "token_present_end": "Backlog high",
}


def get_recent_alerts_window(alerts: pd.DataFrame, lookback_windows: int) -> pd.DataFrame:
    """
    Keep only the last N distinct window_start values globally.
    """
    if alerts.empty or "window_start" not in alerts.columns:
        return alerts.iloc[0:0].copy()

    recent_starts = sorted(alerts["window_start"].dropna().unique())[-int(lookback_windows):]
    return alerts[alerts["window_start"].isin(recent_starts)].copy()


def compute_basic_alerts(
    alerts_recent: pd.DataFrame,
    open_age_threshold: float = 0.0,
    backlog_threshold: float = 20.0,
) -> pd.DataFrame:
    """
    Basic mode:
    alert if token_avg_age_open >= open_age_threshold
    OR token_present_end >= backlog_threshold

    Assumes token_avg_age_open is stored as numeric duration
    (for example raw seconds).
    """
    if alerts_recent.empty:
        return alerts_recent.iloc[0:0].copy()

    age_cond = pd.Series(False, index=alerts_recent.index)
    backlog_cond = pd.Series(False, index=alerts_recent.index)

    if "token_avg_age_open" in alerts_recent.columns:
        age_cond = pd.to_numeric(alerts_recent["token_avg_age_open"], errors="coerce") >= float(open_age_threshold)

    if "token_present_end" in alerts_recent.columns:
        backlog_cond = pd.to_numeric(alerts_recent["token_present_end"], errors="coerce") >= float(backlog_threshold)

    mask = age_cond.fillna(False) | backlog_cond.fillna(False)
    return alerts_recent[mask].copy()


def get_basic_alert_reasons(
    row: pd.Series,
    friendly: dict[str, str] | None = None,
    open_age_threshold: float = 0.0,
    backlog_threshold: float = 20.0,
) -> list[str]:
    friendly = friendly or BASIC_ALERT_FRIENDLY
    out: list[str] = []

    if (
        "token_avg_age_open" in row.index
        and pd.notna(row.get("token_avg_age_open"))
        and float(row["token_avg_age_open"]) >= float(open_age_threshold)
    ):
        out.append(
            f"{friendly.get('token_avg_age_open', 'token_avg_age_open')} "
            f"(token_avg_age_open={float(row['token_avg_age_open']):.2f})"
        )

    if (
        "token_present_end" in row.index
        and pd.notna(row.get("token_present_end"))
        and float(row["token_present_end"]) >= float(backlog_threshold)
    ):
        out.append(
            f"{friendly.get('token_present_end', 'token_present_end')} "
            f"(token_present_end={float(row['token_present_end']):.1f})"
        )

    return out


def get_basic_alert_severity(
    row: pd.Series,
    open_age_threshold: float = 0.0,
    backlog_threshold: float = 20.0,
) -> int:
    sev = 0

    if (
        "token_avg_age_open" in row.index
        and pd.notna(row.get("token_avg_age_open"))
        and float(row["token_avg_age_open"]) >= float(open_age_threshold)
    ):
        sev += 2

    if (
        "token_present_end" in row.index
        and pd.notna(row.get("token_present_end"))
        and float(row["token_present_end"]) >= float(backlog_threshold)
    ):
        sev += 1

    return sev


def summarize_basic_alerts_per_zone(
    flagged: pd.DataFrame,
    friendly: dict[str, str] | None = None,
    open_age_threshold: float = 0.0,
    backlog_threshold: float = 20.0,
) -> pd.DataFrame:
    """
    Keep only the latest flagged row per zone and attach:
      - reasons
      - severity
      - badge
    """
    if flagged.empty:
        out = flagged.iloc[0:0].copy()
        out["reasons"] = []
        out["severity"] = []
        out["badge"] = []
        return out

    latest = (
        flagged.sort_values("window_start")
        .groupby("zone")
        .tail(1)
        .copy()
    )

    latest["reasons"] = latest.apply(
        lambda row: get_basic_alert_reasons(
            row,
            friendly=friendly,
            open_age_threshold=open_age_threshold,
            backlog_threshold=backlog_threshold,
        ),
        axis=1,
    )

    latest["severity"] = latest.apply(
        lambda row: get_basic_alert_severity(
            row,
            open_age_threshold=open_age_threshold,
            backlog_threshold=backlog_threshold,
        ),
        axis=1,
    )

    latest["badge"] = latest["severity"].map(
        lambda s: "🔴" if s >= 3 else ("🟠" if s == 2 else "🟡")
    )

    latest = latest.sort_values(["severity", "zone"], ascending=[False, True])
    return latest


def build_advanced_rules_caption(
    rules: Iterable[tuple[str, str, float]],
    combine_mode: str,
) -> str:
    joiner = " OR " if combine_mode == "ANY" else " AND "
    normalized = [(canonical_metric_name(m), op, thr) for m, op, thr in rules]
    return "Active rules: " + joiner.join([f"{m} {op} {thr:g}" for m, op, thr in normalized])


def compute_advanced_alerts(
    alerts_recent: pd.DataFrame,
    rules: list[tuple[str, str, float]],
    combine_mode: str = "ANY",
) -> pd.DataFrame:
    """
    rules = [(metric, op, threshold)], where op in {'≥', '≤'}
    combine_mode in {'ANY', 'ALL'}
    """
    if alerts_recent.empty or not rules:
        return alerts_recent.iloc[0:0].copy()

    mask = (
        pd.Series(False, index=alerts_recent.index)
        if combine_mode == "ANY"
        else pd.Series(True, index=alerts_recent.index)
    )

    for metric, op, thr in rules:
        metric = canonical_metric_name(metric)
        if metric not in alerts_recent.columns:
            if combine_mode != "ANY":
                # ALL-mode: an unevaluable rule can never be satisfied — the
                # conjunction must fail rather than silently weaken.
                mask &= False
            continue

        s = pd.to_numeric(alerts_recent[metric], errors="coerce")
        cond = (s >= thr) if op == "≥" else (s <= thr)
        cond = cond.fillna(False)

        mask = (mask | cond) if combine_mode == "ANY" else (mask & cond)

    return alerts_recent[mask].copy()


def prepare_basic_alert_history(
    flagged: pd.DataFrame,
    include_duration_display: bool = False,
    duration_display_fn=None,
) -> pd.DataFrame:
    """
    Prepare the compact Basic-mode history table.
    """
    if flagged.empty:
        return flagged.iloc[0:0].copy()

    hist = flagged.sort_values(["window_start", "zone"]).copy()

    if (
        include_duration_display
        and duration_display_fn is not None
        and "token_avg_age_open" in hist.columns
    ):
        hist["token_avg_age_open_display"] = duration_display_fn(hist["token_avg_age_open"])
        cols = [
            c for c in
            [
                "window_start",
                "zone",
                "token_present_end",
                "token_netflow",
                "case_present_end",
                "token_avg_age_open_display",
            ]
            if c in hist.columns
        ]
    else:
        cols = [
            c for c in
            [
                "window_start",
                "zone",
                "token_present_end",
                "token_netflow",
                "case_present_end",
                "token_avg_age_open",
            ]
            if c in hist.columns
        ]

    return hist[cols].tail(200)


def prepare_advanced_alert_history(
    flagged: pd.DataFrame,
    rules: list[tuple[str, str, float]],
) -> pd.DataFrame:
    """
    Prepare the Advanced-mode history table.
    """
    if flagged.empty:
        return flagged.iloc[0:0].copy()

    base_cols = ["window_start", "zone"]
    rule_cols = [m for (m, _, _) in rules if m in flagged.columns]
    extra_cols = [
        c for c in [
            "token_present_end",
            "token_avg_present_window",
            "token_netflow",
            "token_avg_duration_completed",
            "token_avg_age_open",
            "case_active_window",
            "case_present_end",
            "case_avg_duration_completed",
        ]
        if c in flagged.columns
    ]

    cols: list[str] = []
    for c in base_cols + rule_cols + extra_cols:
        if c in flagged.columns and c not in cols:
            cols.append(c)

    return flagged.sort_values(["window_start", "zone"])[cols].tail(200)
