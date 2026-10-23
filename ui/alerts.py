from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


def plot_alert_zone_heatmap(
    alert_points: pd.DataFrame,
    zone_order: list[str] | None = None,
    title: str = "Alert activity by zone",
):
    if alert_points.empty:
        return None

    df = alert_points.copy()
    required = {"window_start", "zone"}
    if not required.issubset(df.columns):
        return None

    if zone_order is None:
        zone_order = sorted(df["zone"].dropna().astype(str).unique().tolist())

    df = df[df["zone"].isin(zone_order)].copy()
    if df.empty:
        return None

    if "severity" not in df.columns:
        df["severity"] = 1

    if "hover_text" not in df.columns:
        df["hover_text"] = df["zone"].astype(str)

    df["window_start"] = pd.to_datetime(df["window_start"], errors="coerce")
    df = df.dropna(subset=["window_start"]).copy()
    if df.empty:
        return None

    def _merge_hover(series: pd.Series) -> str:
        seen = []
        for value in series.astype(str):
            if value and value not in seen:
                seen.append(value)
        return "<br><br>".join(seen)

    grouped = (
        df.groupby(["zone", "window_start"], as_index=False)
        .agg(
            severity=("severity", "max"),
            hover_text=("hover_text", _merge_hover),
        )
        .copy()
    )

    windows = sorted(grouped["window_start"].dropna().unique().tolist())
    severity_grid = pd.DataFrame(0, index=zone_order, columns=windows, dtype=float)
    hover_grid = pd.DataFrame("", index=zone_order, columns=windows, dtype=object)

    severity_labels = {0: "No alert", 1: "Low", 2: "Medium", 3: "High"}

    for row in grouped.itertuples(index=False):
        sev = int(max(0, min(3, row.severity)))
        severity_grid.at[row.zone, row.window_start] = sev
        hover_grid.at[row.zone, row.window_start] = (
            f"Zone: {row.zone}<br>"
            f"Window: {pd.Timestamp(row.window_start).strftime('%Y-%m-%d %H:%M')}<br>"
            f"Severity: {severity_labels.get(sev, 'Unknown')}<br><br>"
            f"{row.hover_text}"
        )

    fig = go.Figure(
        data=
        [
            go.Heatmap(
                z=severity_grid.values,
                x=windows,
                y=zone_order,
                customdata=hover_grid.values,
                zmin=0,
                zmax=3,
                colorscale=[
                    [0.00, "#f5f5f5"],
                    [0.24, "#f5f5f5"],
                    [0.25, "#f4d35e"],
                    [0.49, "#f4d35e"],
                    [0.50, "#ee964b"],
                    [0.74, "#ee964b"],
                    [0.75, "#d1495b"],
                    [1.00, "#d1495b"],
                ],
                colorbar=dict(
                    title="Severity",
                    tickmode="array",
                    tickvals=[0, 1, 2, 3],
                    ticktext=["None", "Low", "Medium", "High"],
                ),
                hovertemplate="%{customdata}<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        height=max(320, 120 + 55 * len(zone_order)),
        title=title,
        xaxis_title="Time window",
        yaxis_title="Zone",
    )
    fig.update_xaxes(type="date")
    fig.update_yaxes(autorange="reversed")
    return fig


def badge_color_emoji(severity: int) -> str:
    return "🔴" if severity >= 3 else ("🟠" if severity == 2 else "🟡")


def basic_reason_labels(row: pd.Series, open_age_threshold: float, backlog_threshold: float) -> list[str]:
    reasons = []
    if (
        "token_avg_age_open" in row.index
        and pd.notna(row.get("token_avg_age_open"))
        and float(row["token_avg_age_open"]) >= open_age_threshold
    ):
        reasons.append("Open work getting older")

    if (
        "token_present_end" in row.index
        and pd.notna(row.get("token_present_end"))
        and float(row["token_present_end"]) >= backlog_threshold
    ):
        reasons.append("Backlog high")

    return reasons


def basic_short_explanation(row: pd.Series, open_age_threshold: float, backlog_threshold: float) -> str:
    has_age = (
        "token_avg_age_open" in row.index
        and pd.notna(row.get("token_avg_age_open"))
        and float(row["token_avg_age_open"]) >= open_age_threshold
    )
    has_backlog = (
        "token_present_end" in row.index
        and pd.notna(row.get("token_present_end"))
        and float(row["token_present_end"]) >= backlog_threshold
    )

    if has_age and has_backlog:
        return "This zone has both aging unfinished work and high backlog. A possible issue is growing congestion or a developing bottleneck."
    if has_age:
        return "Unfinished work in this zone is getting older. A possible issue is delay or slow clearance."
    if has_backlog:
        return "This zone has a high amount of unfinished token work. A possible issue is that inflow is higher than the zone can currently handle."
    return "This zone triggered an alert."


def advanced_reasons(
    row: pd.Series,
    rules_: list[tuple[str, str, float]],
    metric_labels: dict[str, str],
) -> list[str]:
    out = []
    for metric, op, thr in rules_:
        if metric not in row.index or pd.isna(row.get(metric)):
            continue
        val = float(row[metric])
        matched = (val >= thr) if op == "≥" else (val <= thr)
        if matched:
            out.append(f"**{metric_labels.get(metric, metric)} {op} {thr:g}** (value={val:.2f})")
    return out


def advanced_short_explanation(violated_metrics: list[str]) -> str:
    vm = set(violated_metrics)
    backlog_metrics = {
        "token_present_end",
        "token_avg_present_window",
        "token_netflow",
        "case_present_end",
        "case_active_window",
    }
    duration_metrics = {
        "token_avg_age_open",
        "token_avg_duration_completed",
        "case_avg_duration_completed",
    }
    throughput_metrics = {
        "token_enter",
        "token_exit",
        "case_enter",
        "case_exit",
        "token_completion_ratio",
        "case_completion_ratio",
    }

    if vm & backlog_metrics and vm & duration_metrics:
        return "The zone shows both delay and backlog signals. A possible issue is a developing bottleneck."
    if vm & duration_metrics:
        return "The zone shows a delay-related signal. A possible issue is slower handling or temporary overload."
    if vm & backlog_metrics:
        return "The zone shows backlog-related pressure. A possible issue is accumulation of unfinished work."
    if vm & throughput_metrics:
        return "The zone shows a flow-related rule violation. A possible issue is an unusual inflow, outflow, or completion pattern."
    return "This zone violated at least one configured alert rule."
