from __future__ import annotations

import pandas as pd
import plotly.express as px


TOKEN_METRIC_COLUMNS = {
    "token_enter",
    "token_exit",
    "token_present_end",
    "token_avg_present_window",
    "token_netflow",
    "token_avg_duration_completed",
    "token_avg_age_open",
    "token_completion_ratio",
}

CASE_METRIC_COLUMNS = {
    "case_enter",
    "case_exit",
    "case_active_window",
    "case_present_end",
    "case_avg_duration_completed",
    "case_completion_ratio",
}

CONFORMANCE_METRIC_COLUMNS = {
    "alignment_trace_count",
    "alignment_trace_fitness_mean",
    "alignment_deviation_count",
}


def allowed_metric_columns(family_choice: str) -> set[str]:
    if family_choice in ("Token level", "Token only"):
        return TOKEN_METRIC_COLUMNS
    if family_choice in ("Case level", "Case only"):
        return CASE_METRIC_COLUMNS
    if family_choice == "Conformance only":
        return CONFORMANCE_METRIC_COLUMNS
    return TOKEN_METRIC_COLUMNS | CASE_METRIC_COLUMNS | CONFORMANCE_METRIC_COLUMNS


def default_display_names(family_choice: str) -> list[str]:
    if family_choice in ("Token level", "Token only"):
        return [
            "Token enter",
            "Token exit",
            "Token present at window end",
            "Token average completed duration",
        ]
    if family_choice in ("Case level", "Case only"):
        return [
            "Case enter",
            "Case exit",
            "Case present at window end",
            "Case average completed duration",
        ]
    if family_choice == "Conformance only":
        return [
            "Alignment trace count",
            "Alignment trace fitness mean",
            "Alignment deviation count",
        ]
    return [
        "Token enter",
        "Token exit",
        "Case enter",
        "Case exit",
    ]


def plot_changepoint_contribution_bars(
    contrib_df: pd.DataFrame,
    title: str = "Contribution by series",
):
    if contrib_df is None or contrib_df.empty:
        return None

    df = contrib_df.copy()
    df["delta"] = pd.to_numeric(df["after_mean"], errors="coerce") - pd.to_numeric(df["before_mean"], errors="coerce")
    df["direction"] = df["delta"].apply(lambda x: "Increase" if x >= 0 else "Decrease")
    df["series_label"] = df["zone"].astype(str) + " · " + df["metric_label"].astype(str)
    df = df.sort_values(["contribution_pct", "series_label"], ascending=[True, True])

    fig = px.bar(
        df,
        x="contribution_pct",
        y="series_label",
        orientation="h",
        color="direction",
        color_discrete_map={"Increase": "#d97706", "Decrease": "#2563eb"},
        hover_data={
            "zone": True,
            "metric_label": True,
            "before_mean": ":.3f",
            "after_mean": ":.3f",
            "jump_score": ":.3f",
            "contribution_pct": ":.1f",
            "series_label": False,
        },
        title=title,
    )
    fig.update_layout(
        height=max(320, 90 + 34 * len(df)),
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_title="Contribution (%)",
        yaxis_title="",
        legend_title_text="Direction",
    )
    return fig
