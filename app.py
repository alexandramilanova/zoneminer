# app.py

import os
import textwrap
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import streamlit as st
from pm4py.visualization.bpmn import visualizer as bpmn_visualizer
from pm4py.visualization.process_tree import visualizer as process_tree_visualizer
from sklearn.tree import plot_tree

from analytics.alerts import (
    BASIC_ALERT_FRIENDLY,
    get_recent_alerts_window,
    compute_basic_alerts,
    summarize_basic_alerts_per_zone,
    compute_advanced_alerts,
    get_basic_alert_severity,
)
from analytics.dependencies import select_basic_dependency_rows
from analytics.metrics.catalog import (
    get_metric_explanations,
    get_catalog_for_mode,
    get_dependency_metric_names,
    get_basic_dependency_metrics,
    get_all_dependency_metrics,
)
from analytics.metrics.compat import canonical_metric_name, canonicalize_metric_names
from analytics.metrics.groups import (
    get_default_alert_metrics,
    get_default_alert_threshold,
    get_default_dependency_pair,
    get_default_prediction_target_metric,
    get_metric_label,
)
from analytics.prediction import (
    get_default_feature_metrics,
    get_model_label,
    list_numeric_zone_metrics,
    list_supported_models,
    make_wide_feature_table,
    make_supervised_dataset,
    model_supports_tree_details,
    build_binary_target_from_metric_threshold,
    train_compare_models,
)
from analytics.prediction_explain import (
    build_global_shap_beeswarm_figure,
    shap_is_available,
    supports_shap_explanations,
)
from analytics.trends import prepare_trend_long_df
from display_utils import (
    get_duration_unit_seconds,
    get_duration_unit_label,
)
from petri_viz import build_petri_graphviz_with_place_labels, show_graphviz_interactive
from process_model.zone_validation import validate_zones
from process_model.zone_suggestions import (
    readable_activity_labels,
    suggested_places_from_activity_labels,
)
from ui.alerts import (
    advanced_reasons,
    advanced_short_explanation,
    badge_color_emoji,
    basic_reason_labels,
    basic_short_explanation,
    plot_alert_zone_heatmap,
)
from ui.dependencies import corr_basic_label, corr_direction, corr_strength
import services
from ui.trends import allowed_metric_columns, default_display_names
from ui.trends import plot_changepoint_contribution_bars



# ---------------------------------------------------------------------
# Streamlit config MUST be first Streamlit call
# ---------------------------------------------------------------------
st.set_page_config(page_title="ZoneMiner", layout="wide")
st.title("ZoneMiner")

# ---------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def cached_model(log_bytes: bytes, log_suffix: str, pnml_bytes: Optional[bytes]):
    return services.load_model_inputs(log_bytes, log_suffix, pnml_bytes).as_tuple()


@st.cache_data(show_spinner="Computing alignments and conformance tables (cached)…")
def cached_alignment_outputs(
    log_bytes: bytes,
    log_suffix: str,
    pnml_bytes: Optional[bytes],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    log, net, im, fm, _, _, _, _ = cached_model(log_bytes, log_suffix, pnml_bytes)
    return services.compute_alignment_tables(log, net, im, fm)


@st.cache_data(show_spinner=False)
def cached_changepoint_events(
    _zf: pd.DataFrame,
    zones: tuple[str, ...],
    metrics: tuple[str, ...],
    cp_strictness: int,
    min_size: int,
    min_points: int,
    max_per_series: int | None,
    jump: int,
    metric_display_items: tuple[tuple[str, str], ...],
) -> pd.DataFrame:
    return services.changepoint_events(
        zf=_zf,
        zones=list(zones),
        metrics=list(metrics),
        cp_strictness=cp_strictness,
        min_size=min_size,
        min_points=min_points,
        max_per_series=max_per_series,
        jump=jump,
        metric_display_map=dict(metric_display_items),
    )


@st.cache_data(show_spinner=False)
def cached_selection_changepoints(
    _zf: pd.DataFrame,
    zones: tuple[str, ...],
    metrics: tuple[str, ...],
    cp_strictness: int,
    min_size: int,
    min_points: int,
    jump: int,
    aggregate_method: str,
    selection_label: str,
    max_selection_cps: int | None,
    flank_points: int,
) -> pd.DataFrame:
    return services.selection_changepoints(
        zf=_zf,
        zones=list(zones),
        metrics=list(metrics),
        cp_strictness=cp_strictness,
        min_size=min_size,
        min_points=min_points,
        jump=jump,
        aggregate_method=aggregate_method,
        selection_label=selection_label,
        max_selection_cps=max_selection_cps,
        flank_points=flank_points,
    )


@st.cache_data(show_spinner=False)
def cached_selection_changepoint_contributions(
    _zf: pd.DataFrame,
    zones: tuple[str, ...],
    metrics: tuple[str, ...],
    _selection_cp_events: pd.DataFrame,
    min_points: int,
    metric_display_items: tuple[tuple[str, str], ...],
    selection_label: str,
    aggregate_method: str,
    flank_points: int,
) -> pd.DataFrame:
    return services.selection_changepoint_contributions(
        zf=_zf,
        zones=list(zones),
        metrics=list(metrics),
        selection_cp_events=_selection_cp_events,
        min_points=min_points,
        metric_display_map=dict(metric_display_items),
        selection_label=selection_label,
        aggregate_method=aggregate_method,
        flank_points=flank_points,
    )


@st.cache_data(show_spinner=False)
def cached_dependency_table(
    _zf: pd.DataFrame,
    src_metric: str,
    tgt_metric: str,
    max_lag: int,
    min_lag: int,
    min_points: int,
    correlate_changes: bool,
) -> pd.DataFrame:
    return services.dependency_table(
        zf=_zf,
        src_metric=src_metric,
        tgt_metric=tgt_metric,
        max_lag=max_lag,
        min_lag=min_lag,
        min_points=min_points,
        correlate_changes=correlate_changes,
    )


@st.cache_data(show_spinner=False)
def cached_basic_dependency_results(
    _zf: pd.DataFrame,
    metric_options: tuple[str, ...],
    max_lag: int,
    min_lag: int,
    min_points: int,
    correlate_changes: bool,
) -> pd.DataFrame:
    return services.basic_dependency_matrix(
        zf=_zf,
        metric_options=list(metric_options),
        max_lag=max_lag,
        min_lag=min_lag,
        min_points=min_points,
        correlate_changes=correlate_changes,
    )


def _uploaded_file_signature(f):
    """
    Lightweight signature to detect when an uploaded file changed.
    """
    if f is None:
        return None
    return (
        getattr(f, "name", None),
        getattr(f, "size", None),
        getattr(f, "type", None),
    )


def _zone_inputs_signature(zone_inputs):
    """
    Stable signature for detecting zone definition changes.
    Includes zone names and selected places.
    """
    normalized = []
    for zname, places in zone_inputs:
        normalized.append(
            [
                (zname or "").strip(),
                tuple(sorted(places or [])),
            ]
        )
    return tuple(normalized)


def _invalidate_analysis(reason: str):
    """
    Clear computed outputs so user must rerun analysis.
    """
    st.session_state.pop("res", None)
    st.session_state.pop("zf", None)

    changed = st.session_state.get("pending_input_changes", [])
    changed.append(reason)
    st.session_state["pending_input_changes"] = changed


def _clear_zone_definition_state():
    """
    Remove stored zone names / place selections / derived zone objects
    so old zone definitions do not survive after structural changes.
    """
    keys_to_delete = []

    for k in list(st.session_state.keys()):
        if (
            k.startswith("zone_name_")
            or k.startswith("zone_places_")
            or k.startswith("zone_select_")
            or k.startswith("zone_input_")
            or k.startswith("places_in_zone_")
            or k.startswith("zname_")
            or k.startswith("zsel_")
            or k.startswith("zact_")
        ):
            keys_to_delete.append(k)

    for k in keys_to_delete:
        st.session_state.pop(k, None)

    for k in ["zone_inputs", "zone_places", "all_zones"]:
        st.session_state.pop(k, None)


if "pending_input_changes" not in st.session_state:
    st.session_state["pending_input_changes"] = []
if "analysis_mode" not in st.session_state:
    st.session_state["analysis_mode"] = "Basic"


# ---------------------------------------------------------------------
# 1. Inputs
# ---------------------------------------------------------------------
inputs_expanded = st.session_state.get("log_file") is None
with st.expander("1. Inputs", expanded=inputs_expanded):
    st.caption("Upload the event log and optionally a Petri net. You can reopen this section at any time.")
    input_cols = st.columns([1, 1, 0.8])

    with input_cols[0]:
        log_file = st.file_uploader(
            "Event log (.xes or .csv)",
            type=["xes", "csv"],
            max_upload_size=256,
            help="Your event log. Must include case id, activity, and timestamps.",
            key="log_file",
        )

    with input_cols[1]:
        pn_file = st.file_uploader(
            "Petri net (.pnml)",
            type=["pnml"],
            help="Optional process model. If omitted, a Petri net is discovered from the log.",
            key="pn_file",
        )

    with input_cols[2]:
        if st.button(
            "Clear cached preprocessing",
            help="Clears cached alignments and intermediate results. Use this after changing inputs if results seem unexpected.",
        ):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.session_state.pop("res", None)
            st.session_state.pop("zf", None)
            _clear_zone_definition_state()
            st.success("Cache cleared. Next run will recompute alignments.")

    log_label = log_file.name if log_file is not None else "No log uploaded"
    pn_label = pn_file.name if pn_file is not None else "No Petri net uploaded"
    st.caption(f"Current log: {log_label}")
    st.caption(f"Current model: {pn_label}")


# ---------------------------------------------------------------------
# Upload log to begin
# ---------------------------------------------------------------------
if not log_file:
    st.info("Upload a log to begin.")
    st.stop()

current_log_sig = _uploaded_file_signature(log_file)
current_pn_sig = _uploaded_file_signature(pn_file)

timeframe_label = st.session_state.get("timeframe_label", "Daily")
timeframe = {
    "Hourly": "h",
    "Daily": "D",
    "Weekly": "7D",
    "Monthly": "30D",
}[timeframe_label]
num_zones = int(st.session_state.get("num_zones_input", 3))
mode = st.session_state.get("analysis_mode", "Basic")

if "last_timeframe" not in st.session_state:
    st.session_state["last_timeframe"] = timeframe
if "last_num_zones" not in st.session_state:
    st.session_state["last_num_zones"] = int(num_zones)
if "last_log_sig" not in st.session_state:
    st.session_state["last_log_sig"] = current_log_sig
if "last_pn_sig" not in st.session_state:
    st.session_state["last_pn_sig"] = current_pn_sig

if st.session_state["last_timeframe"] != timeframe:
    st.session_state["last_timeframe"] = timeframe
    _invalidate_analysis("timeframe")

if st.session_state["last_num_zones"] != int(num_zones):
    st.session_state["last_num_zones"] = int(num_zones)
    _clear_zone_definition_state()
    _invalidate_analysis("number of zones")

if st.session_state["last_log_sig"] != current_log_sig:
    st.session_state["last_log_sig"] = current_log_sig
    _clear_zone_definition_state()
    _invalidate_analysis("event log")

if st.session_state["last_pn_sig"] != current_pn_sig:
    st.session_state["last_pn_sig"] = current_pn_sig
    _clear_zone_definition_state()
    _invalidate_analysis("Petri net")

log_suffix = os.path.splitext(log_file.name)[1]
log_bytes = log_file.getvalue()
pnml_bytes = pn_file.getvalue() if pn_file else None

# Load (cached)
log, net, im, fm, process_tree, bpmn_graph, model_source, model_notice = cached_model(log_bytes, log_suffix, pnml_bytes)

EXCLUDED_PLACES = {"source", "sink", "start", "end"}
place_names = sorted([
    p.name for p in net.places
    if p.name not in EXCLUDED_PLACES
])
activity_labels = readable_activity_labels(process_tree, net)
zone_helper_enabled = bool(st.session_state.get("show_tree_view", False)) and process_tree is not None

pending_changes = sorted(set(st.session_state.get("pending_input_changes", [])))

top_cols = st.columns([1, 1], gap="small")
with top_cols[0]:
    st.markdown("**Log**")
    st.caption(log_label)
with top_cols[1]:
    source_label = "Uploaded Petri net" if model_source == "uploaded_petri_net" else "Discovered from log"
    st.markdown("**Model**")
    st.caption(source_label)

if pending_changes:
    st.warning(
        "Configuration changed since the last run: "
        + ", ".join(pending_changes)
        + ". Run analysis again to refresh results."
    )

zone_suggestion_preview: dict[int, list[str]] = {}
zone_suggestion_meta: list[tuple[str, str, int]] = []
zone_preview_palette = [
    ("#fef3c7", "#b45309"),
    ("#dbeafe", "#1d4ed8"),
    ("#dcfce7", "#15803d"),
    ("#fce7f3", "#be185d"),
    ("#ede9fe", "#7c3aed"),
    ("#ffe4e6", "#e11d48"),
]
highlighted_place_styles: dict[str, dict[str, str]] = {}

if zone_helper_enabled:
    for i in range(int(num_zones)):
        selected_activities_preview = st.session_state.get(f"zact_{i}", [])
        suggested_preview = suggested_places_from_activity_labels(
            net,
            list(selected_activities_preview),
            excluded_places=EXCLUDED_PLACES,
        )
        if not suggested_preview:
            continue
        zone_suggestion_preview[i] = suggested_preview
        zone_label_preview = str(st.session_state.get(f"zname_{i}", f"Zone {i+1}")).strip() or f"Zone {i+1}"
        fillcolor, border = zone_preview_palette[i % len(zone_preview_palette)]
        zone_suggestion_meta.append((zone_label_preview, border, len(suggested_preview)))
        for place_name in suggested_preview:
            existing = highlighted_place_styles.get(place_name)
            if existing is None:
                highlighted_place_styles[place_name] = {
                    "style": "filled",
                    "fillcolor": fillcolor,
                    "color": border,
                    "penwidth": "2.0",
                }
            else:
                existing["fillcolor"] = "#fde68a"
                existing["color"] = "#92400e"
                existing["penwidth"] = "2.5"

# ---------------------------------------------------------------------
# 2. Model and Zones
# ---------------------------------------------------------------------
zone_inputs = []
zone_places = {}

zone_summary_parts = []
for i in range(int(num_zones)):
    zname_preview = st.session_state.get(f"zname_{i}", f"Zone {i+1}")
    zsel_preview = st.session_state.get(f"zsel_{i}", [])
    place_count = len(zsel_preview) if isinstance(zsel_preview, list) else 0
    label = zname_preview.strip() if str(zname_preview).strip() else f"Zone {i+1}"
    zone_summary_parts.append(f"{label} ({place_count})")
zone_summary_text = " · ".join(zone_summary_parts) if zone_summary_parts else "No zones defined yet"

model_zones_expanded = st.session_state.get("zf") is None or bool(pending_changes)
with st.expander(f"2. Model and Zones · {zone_summary_text}", expanded=model_zones_expanded):
    st.caption(
        "The Petri net remains the canonical analysis model. Readable views are optional helpers for understanding and zone definition."
    )

    config_cols = st.columns([1, 1.1])
    with config_cols[0]:
        timeframe_label = st.selectbox(
            "Timeframe",
            ["Hourly", "Daily", "Weekly", "Monthly"],
            index=["Hourly", "Daily", "Weekly", "Monthly"].index(st.session_state.get("timeframe_label", "Daily")),
            key="timeframe_label",
            help="How the app groups events into time windows. Changing this requires a new analysis run.",
        )
        timeframe = {
            "Hourly": "h",
            "Daily": "D",
            "Weekly": "7D",
            "Monthly": "30D",
        }[timeframe_label]
    with config_cols[1]:
        st.caption("Changing timeframe requires a new analysis run.")

    if model_notice:
        st.info(model_notice)

    model_col, zones_col = st.columns([1.05, 0.95], gap="large")

    with model_col:
        st.markdown("#### Petri net")
        gviz = build_petri_graphviz_with_place_labels(
            net,
            im=im,
            fm=fm,
            highlighted_places=highlighted_place_styles,
        )
        show_graphviz_interactive(
            gviz,
            height=340,
            element_id=f"petri_container_{model_source}",
        )
        if zone_suggestion_meta:
            legend_parts = [
                f"<span style='display:inline-block;width:10px;height:10px;background:{color};border:1px solid {color};margin-right:6px;vertical-align:middle;'></span>{zone} ({count} suggested place(s))"
                for zone, color, count in zone_suggestion_meta
            ]
            st.markdown(
                "Suggested-place preview: " + " &nbsp;&nbsp; ".join(legend_parts),
                unsafe_allow_html=True,
            )

        show_tree_view = st.checkbox(
            "Help me define zones with a process tree",
            value=bool(st.session_state.get("show_tree_view", process_tree is not None)),
            disabled=process_tree is None,
            key="show_tree_view",
        )
        show_bpmn_view = st.checkbox(
            "Show BPMN view",
            value=bool(st.session_state.get("show_bpmn_view", False)),
            disabled=bpmn_graph is None,
            key="show_bpmn_view",
        )

        if show_tree_view and process_tree is not None:
            st.markdown("#### Process tree")
            tree_gviz = process_tree_visualizer.apply(
                process_tree,
                variant=process_tree_visualizer.Variants.SYMBOLIC,
            )
            show_graphviz_interactive(
                tree_gviz,
                height=280,
                element_id=f"process_tree_container_{model_source}",
            )
            st.caption("Readable structure view used to support zone definition. Final zones are still stored as Petri-net places.")

        if show_bpmn_view and bpmn_graph is not None:
            st.markdown("#### BPMN")
            bpmn_gviz = bpmn_visualizer.apply(bpmn_graph)
            show_graphviz_interactive(
                bpmn_gviz,
                height=300,
                element_id=f"bpmn_container_{model_source}",
            )
            st.caption("Business-readable view derived from the same canonical analysis model.")

    with zones_col:
        st.markdown("#### Define zones")
        st.caption(
            "Zones are stored as Petri-net places. You can use the process tree helper, then confirm or edit the final Petri-net place set here."
        )
        num_zones = st.number_input(
            "Number of zones",
            min_value=1,
            max_value=20,
            value=int(st.session_state.get("num_zones_input", 3)),
            step=1,
            key="num_zones_input",
            help="How many zones you want to define. Each zone is a group of Petri-net places.",
        )
        if zone_helper_enabled and activity_labels:
            st.caption("Optional helper: select readable activities to pre-suggest Petri-net places for each zone.")

        for i in range(int(num_zones)):
            zname_current = st.session_state.get(f"zname_{i}", f"Zone {i+1}")
            zsel_current = st.session_state.get(f"zsel_{i}", [])
            zone_label = str(zname_current).strip() or f"Zone {i+1}"
            place_count = len(zsel_current) if isinstance(zsel_current, list) else 0
            with st.expander(f"{zone_label} · {place_count} place(s)", expanded=(i == 0)):
                zname_raw = st.text_input(
                    f"Zone {i+1} name",
                    value=zname_current,
                    key=f"zname_{i}"
                )

                if zone_helper_enabled and activity_labels:
                    selected_activities = st.multiselect(
                        f"Suggest from activities for {zname_raw if str(zname_raw).strip() else f'Zone {i+1}'}",
                        options=activity_labels,
                        default=st.session_state.get(f"zact_{i}", []),
                        key=f"zact_{i}",
                    )
                    suggested_places = zone_suggestion_preview.get(i)
                    if suggested_places is None:
                        suggested_places = suggested_places_from_activity_labels(
                            net,
                            list(selected_activities),
                            excluded_places=EXCLUDED_PLACES,
                        )
                    if suggested_places:
                        st.caption("Suggested places: " + ", ".join(suggested_places))
                        if st.button("Apply suggestion", key=f"apply_suggestion_{i}"):
                            st.session_state[f"zsel_{i}"] = suggested_places
                        st.caption("This fills the place selection below. You can still edit it manually.")
                    elif selected_activities:
                        st.caption("No Petri-net place suggestion could be derived from the selected activities.")

                selected = st.multiselect(
                    f"Places in {zname_raw if str(zname_raw).strip() else f'Zone {i+1}'}",
                    options=place_names,
                    default=st.session_state.get(f"zsel_{i}", []),
                    key=f"zsel_{i}"
                )

                st.caption(f"{len(selected)} place(s) selected")
                zone_inputs.append((zname_raw, selected))


# ---------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------
validation = validate_zones(
    zone_inputs=zone_inputs,
    place_names=place_names,
    net=net,
    require_non_empty=True,
    allow_unassigned_places=True,
    require_connected=True,
)

zone_places = validation["zone_places"]
zone_errors = validation["errors"]
zone_warnings = validation["warnings"]
zone_config_valid = validation["zone_config_valid"]

# ---------------------------------------------------------------------
# Zone warnings
# ---------------------------------------------------------------------
if zone_warnings or zone_errors:
    with st.container(border=True):
        st.markdown("**Zone configuration feedback**")

        for msg in zone_warnings:
            st.warning(msg)

        for err in zone_errors:
            st.error(err)

# ----------------------------------------------------
# Detect zone-definition changes and invalidate analysis
# ----------------------------------------------------
current_zone_sig = _zone_inputs_signature(zone_inputs)

if "last_zone_sig" not in st.session_state:
    st.session_state["last_zone_sig"] = current_zone_sig

if st.session_state["last_zone_sig"] != current_zone_sig:
    st.session_state["last_zone_sig"] = current_zone_sig
    st.session_state.pop("res", None)
    st.session_state.pop("zf", None)
    changed = st.session_state.get("pending_input_changes", [])
    changed.append("zone definitions")
    st.session_state["pending_input_changes"] = changed
    st.warning("Zones changed. Click **Run analysis** to recompute results.")


# ---------------------------------------------------------------------
# Run analysis
# ---------------------------------------------------------------------
if "res" not in st.session_state:
    st.session_state.res = None
if "zf" not in st.session_state:
    st.session_state.zf = None

run = st.button("Run analysis", type="primary")

if run:
    if not zone_config_valid:
        st.error("Fix the zone definition before running analysis.")
        st.stop()

    token_place_df, trace_conformance_df, alignment_moves_df = cached_alignment_outputs(
        log_bytes, log_suffix, pnml_bytes
    )

    st.session_state.res = services.build_zone_analysis(
        token_place_df,
        trace_conformance_df,
        zone_places,
        timeframe,
        log=log,
        net=net,
        im=im,
        fm=fm,
        alignment_moves_df=alignment_moves_df,
    )
    st.session_state.zf = st.session_state.res["zone_features"]
    st.session_state["pending_input_changes"] = []

# Stop if not run yet
if st.session_state.zf is None or st.session_state.zf.empty:
    st.info("Click **Run analysis** to compute zone features.")
    st.stop()

res = st.session_state.res
zf = st.session_state.zf.copy()

with st.expander("3. Analysis", expanded=True):
    st.caption("Choose how much detail you want to see in the analysis results below.")
    mode = st.radio(
        "Mode",
        ["Basic", "Advanced"],
        index=["Basic", "Advanced"].index(st.session_state.get("analysis_mode", "Basic")),
        horizontal=True,
        key="analysis_mode",
        help="Basic shows a simplified interface with stronger defaults. Advanced exposes more metrics and settings.",
    )



DURATION_UNIT_SECONDS = get_duration_unit_seconds(timeframe_label)
DURATION_UNIT_LABEL = get_duration_unit_label(timeframe_label)
METRIC_EXPLANATIONS = get_metric_explanations(timeframe_label, DURATION_UNIT_LABEL)
METRIC_LABELS = get_dependency_metric_names(timeframe_label)


def _log_case_count(log) -> int:
    try:
        return int(len(log))
    except Exception:
        return 0


def _log_event_count(log) -> int:
    try:
        return int(sum(len(trace) for trace in log))
    except Exception:
        return 0


def _log_activity_count(log) -> int:
    names = set()
    try:
        for trace in log:
            for ev in trace:
                name = ev.get("concept:name")
                if name is not None:
                    names.add(str(name))
    except Exception:
        return 0
    return len(names)


def _latest_conformance_snapshot(zf: pd.DataFrame) -> dict[str, float]:
    if zf.empty or "window_start" not in zf.columns:
        return {}
    latest_ts = pd.to_datetime(zf["window_start"]).max()
    latest = zf.loc[zf["window_start"] == latest_ts].copy()
    if latest.empty:
        return {}
    row = latest.iloc[0]
    return {
        "window_start": latest_ts,
        "alignment_trace_count": float(row.get("alignment_trace_count", 0.0) or 0.0),
        "alignment_trace_deviation_rate": float(row.get("alignment_trace_deviation_rate", 0.0) or 0.0),
        "alignment_deviation_count": float(row.get("alignment_deviation_count", 0.0) or 0.0),
        "alignment_trace_fitness_mean": float(row.get("alignment_trace_fitness_mean", float("nan"))),
    }

# ---------------------------------------------------------------------
# Metric explanations
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# Global filters
# ---------------------------------------------------------------------
all_zones = sorted(zf["zone"].dropna().unique().tolist())


if zf.empty:
    st.warning("No data for the selected zones.")
    st.stop()

# ---------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------
tab_overview, tab_trends, tab_deps, tab_predict, tab_metrics  = st.tabs(
        ["Overview", "Trends", "Dependencies", "Prediction", "Metrics explained"]
)

with tab_overview:
    st.markdown("## Overview")

    alerts = zf.copy()

    lookback_windows = st.number_input(
        "Recent window range",
        min_value=1,
        max_value=200,
        value=10,
        step=1,
        help="Summary signals below are computed over the last N time windows.",
    )

    if alerts.empty or "window_start" not in alerts.columns:
        st.warning("Overview cannot be computed (missing window_start or no data).")

    else:
        alerts_recent = get_recent_alerts_window(alerts, int(lookback_windows))

        if alerts_recent.empty:
            st.info("No data in the selected lookback range.")

        elif "zone" not in alerts_recent.columns:
            st.warning("Overview cannot be computed (missing zone column).")

        else:
            flagged = pd.DataFrame()
            latest_zone_alerts = pd.DataFrame()
            overview_plot_df = pd.DataFrame()
            alert_rules_caption = None
            issue_rows: list[dict] = []

            # =========================================================
            # BASIC MODE
            # =========================================================
            if mode == "Basic":
                open_age_threshold = DURATION_UNIT_SECONDS
                backlog_threshold = 20.0

                flagged = compute_basic_alerts(
                    alerts_recent,
                    open_age_threshold=open_age_threshold,
                    backlog_threshold=backlog_threshold,
                )

                zones_flagged = (
                    sorted(flagged["zone"].dropna().unique().tolist())
                    if not flagged.empty else []
                )

                latest_zone_alerts = summarize_basic_alerts_per_zone(
                    flagged,
                    friendly=BASIC_ALERT_FRIENDLY,
                    open_age_threshold=open_age_threshold,
                    backlog_threshold=backlog_threshold,
                )

                if not flagged.empty:
                    overview_plot_df = flagged.copy()
                    overview_plot_df["reasons"] = overview_plot_df.apply(
                        lambda row: basic_reason_labels(row, open_age_threshold, backlog_threshold),
                        axis=1,
                    )
                    overview_plot_df["severity"] = overview_plot_df.apply(
                        lambda row: get_basic_alert_severity(
                            row,
                            open_age_threshold=open_age_threshold,
                            backlog_threshold=backlog_threshold,
                        ),
                        axis=1,
                    )
                    overview_plot_df["hover_text"] = overview_plot_df.apply(
                        lambda row: (
                            f"{row['zone']}<br>"
                            f"{row['window_start']}<br>"
                            f"{', '.join(row['reasons']) if isinstance(row['reasons'], list) and row['reasons'] else 'Alert triggered'}"
                        ),
                        axis=1,
                    )

                for _, row in latest_zone_alerts.head(3).iterrows():
                    issue_rows.append(
                        {
                            "priority": int(row["severity"]),
                            "title": f"{row['badge']} {row['zone']}",
                            "detail": basic_short_explanation(row, open_age_threshold, backlog_threshold),
                            "next_step": "Open Trends to inspect recent backlog and age signals for this zone.",
                        }
                    )

            # =========================================================
            # ADVANCED MODE
            # =========================================================
            else:
                excluded = {"zone", "window_start", "window_end"}
                numeric_candidates = [c for c in alerts_recent.columns if c not in excluded]

                default_metrics = get_default_alert_metrics(numeric_candidates)

                combine_mode_default = st.session_state.get("alert_combine_mode_ui", "ANY rule matches (OR)")
                selected_default = canonicalize_metric_names(
                    st.session_state.get("selected_alert_metrics", default_metrics)
                )

                preview_selected_metrics = selected_default if isinstance(selected_default, list) else default_metrics
                preview_combine_mode_ui = combine_mode_default
                preview_combine_mode = "ANY" if str(preview_combine_mode_ui).startswith("ANY") else "ALL"

                preview_parts = []
                for m in preview_selected_metrics:
                    default_thr = get_default_alert_threshold(m, DURATION_UNIT_SECONDS)
                    dir_preview = st.session_state.get(f"alert_dir_{m}", "≥ (high is bad)")
                    op_preview = "≥" if str(dir_preview).startswith("≥") else "≤"
                    thr_preview = float(st.session_state.get(f"alert_thr_{m}", default_thr))
                    preview_parts.append(f"{get_metric_label(m)} {op_preview} {thr_preview:g}")

                preview_joiner = " OR " if preview_combine_mode == "ANY" else " AND "
                preview_rules_caption = (
                    "Active rules: " + preview_joiner.join(preview_parts)
                    if preview_parts else
                    "Active rules: none selected"
                )
                alert_rules_caption = preview_rules_caption

                rules = []
                with st.expander("Trigger alert when", expanded=False):
                    combine_mode_ui = st.radio(
                        "Trigger alert when",
                        ["ANY rule matches (OR)", "ALL rules match (AND)"],
                        index=0 if combine_mode_default.startswith("ANY") else 1,
                        key="alert_combine_mode_ui",
                    )
                    combine_mode = "ANY" if combine_mode_ui.startswith("ANY") else "ALL"

                    selected_alert_metrics = st.multiselect(
                        "Metrics to use for alerts",
                        options=numeric_candidates,
                        default=[m for m in selected_default if m in numeric_candidates] if selected_default else default_metrics,
                        help="Pick multiple metrics; you'll set a threshold and direction for each.",
                        format_func=get_metric_label,
                        key="selected_alert_metrics",
                    )

                    if selected_alert_metrics:
                        for m in selected_alert_metrics:
                            c1, c2 = st.columns([2, 1])

                            with c1:
                                direction = st.selectbox(
                                    f"{get_metric_label(m)}: condition",
                                    options=["≥ (high is bad)", "≤ (low is bad)"],
                                    key=f"alert_dir_{m}",
                                )
                                op = "≥" if direction.startswith("≥") else "≤"

                            with c2:
                                default_thr = get_default_alert_threshold(m, DURATION_UNIT_SECONDS)
                                thr = st.number_input(
                                    f"{get_metric_label(m)}: threshold",
                                    value=float(st.session_state.get(f"alert_thr_{m}", default_thr)),
                                    key=f"alert_thr_{m}",
                                )

                            rules.append((m, op, float(thr)))
                    else:
                        st.warning("Select at least one metric above to configure alert rules.")

                    st.caption(preview_rules_caption)

                # Use current widget values after expander widgets are rendered
                combine_mode_ui = st.session_state.get("alert_combine_mode_ui", "ANY rule matches (OR)")
                combine_mode = "ANY" if combine_mode_ui.startswith("ANY") else "ALL"

                selected_alert_metrics = canonicalize_metric_names(
                    st.session_state.get("selected_alert_metrics", default_metrics)
                )
                rules = []

                for m in selected_alert_metrics:
                    if m not in numeric_candidates:
                        continue
                    default_thr = get_default_alert_threshold(m, DURATION_UNIT_SECONDS)
                    direction = st.session_state.get(f"alert_dir_{m}", "≥ (high is bad)")
                    op = "≥" if str(direction).startswith("≥") else "≤"
                    thr = float(st.session_state.get(f"alert_thr_{m}", default_thr))
                    rules.append((m, op, thr))

                if not rules:
                    st.info("No alert rules configured.")
                else:
                    flagged = compute_advanced_alerts(
                        alerts_recent=alerts_recent,
                        rules=rules,
                        combine_mode=combine_mode,
                    )

                    if not flagged.empty:
                        adv_timeline = flagged.copy()
                        adv_timeline["reasons"] = adv_timeline.apply(
                            lambda row: advanced_reasons(row, rules, METRIC_LABELS),
                            axis=1,
                        )
                        adv_timeline["severity"] = adv_timeline["reasons"].apply(len)
                        adv_timeline["badge"] = adv_timeline["severity"].map(badge_color_emoji)
                        adv_timeline["hover_text"] = adv_timeline.apply(
                            lambda row: (
                                f"{row['zone']}<br>"
                                f"{row['window_start']}<br>"
                                f"{'; '.join([r.replace('**', '') for r in row['reasons']]) if isinstance(row['reasons'], list) and row['reasons'] else 'Alert triggered'}"
                            ),
                            axis=1,
                        )
                        overview_plot_df = adv_timeline.copy()
                        latest_zone_alerts = (
                            adv_timeline.sort_values("window_start")
                            .groupby("zone")
                            .tail(1)
                            .sort_values(["severity", "zone"], ascending=[False, True])
                            .copy()
                        )

                        for _, row in latest_zone_alerts.head(3).iterrows():
                            violated_metrics = []
                            for metric, _, _ in rules:
                                reasons = row["reasons"] if isinstance(row["reasons"], list) else []
                                metric_label = METRIC_LABELS.get(metric, metric)
                                if any(r.startswith(f"**{metric_label} ") for r in reasons):
                                    violated_metrics.append(metric)

                            issue_rows.append(
                                {
                                    "priority": int(row["severity"]),
                                    "title": f"{row['badge']} {row['zone']}",
                                    "detail": advanced_short_explanation(violated_metrics),
                                    "next_step": "Open Trends to inspect the metrics that violated the current alert rules.",
                                }
                            )

            log_obj = res.get("log")
            net_obj = res.get("net")
            token_place_df = res.get("token_place_df", pd.DataFrame())
            trace_conformance_df = res.get("trace_conformance_df", pd.DataFrame())
            zone_leak_diag = res.get("zone_leak_diag", pd.DataFrame())

            cases_count = _log_case_count(log_obj)
            events_count = _log_event_count(log_obj)
            activities_count = _log_activity_count(log_obj)
            zones_count = len(all_zones)
            first_window_start = pd.to_datetime(zf["window_start"]).min()
            latest_window_start = pd.to_datetime(zf["window_start"]).max()

            deviating_traces = int(trace_conformance_df["alignment_has_deviation"].sum()) if not trace_conformance_df.empty and "alignment_has_deviation" in trace_conformance_df.columns else 0
            replayed_traces = int(len(trace_conformance_df)) if trace_conformance_df is not None else 0
            latest_conf = _latest_conformance_snapshot(zf)
            latest_deviation_rate = float(latest_conf.get("alignment_trace_deviation_rate", 0.0))
            latest_deviation_count = int(latest_conf.get("alignment_deviation_count", 0.0))
            flagged_zone_count = int(latest_zone_alerts["zone"].nunique()) if not latest_zone_alerts.empty else 0

            if not zone_leak_diag.empty and "open_ratio" in zone_leak_diag.columns:
                leak_row = zone_leak_diag.sort_values(["open_ratio", "tokens_open"], ascending=[False, False]).iloc[0]
                if float(leak_row["open_ratio"]) > 0.05:
                    issue_rows.append(
                        {
                            "priority": int(round(100 * float(leak_row["open_ratio"]))),
                            "title": f"Open-token leakage in {leak_row['zone']}",
                            "detail": f"{int(leak_row['tokens_open'])} token(s) remain open unexpectedly in this zone.",
                            "next_step": "Check process structure and replay assumptions for this zone.",
                        }
                    )

            if latest_deviation_rate >= 0.2 or latest_deviation_count > 0:
                issue_rows.append(
                    {
                        "priority": int(round(100 * latest_deviation_rate)) + min(latest_deviation_count, 20),
                        "title": "Recent model deviations detected",
                        "detail": f"Latest window deviation rate is {100.0 * latest_deviation_rate:.1f}% with {latest_deviation_count} deviation move(s).",
                        "next_step": "Inspect Trends or conformance metrics to see whether behavior is drifting away from the model.",
                    }
                )

            issue_rows = sorted(issue_rows, key=lambda x: x["priority"], reverse=True)

            if flagged_zone_count > 0:
                process_state_label = "Pressure detected"
                process_state_detail = f"{flagged_zone_count} zone(s) are currently flagged in the recent lookback window."
            elif latest_deviation_rate >= 0.2:
                process_state_label = "Behavior drifting"
                process_state_detail = "Recent traces deviate from the model even though zone-level alerts are currently limited."
            else:
                process_state_label = "Stable"
                process_state_detail = "No strong recent stress signal was found in the current lookback window."

            st.markdown("### Current snapshot")
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Cases", f"{cases_count:,}")
            k2.metric("Events", f"{events_count:,}")
            k3.metric("Zones", f"{zones_count}")
            k4.metric("Flagged zones", f"{flagged_zone_count}")
            k5.metric("Recent deviation rate", f"{100.0 * latest_deviation_rate:.1f}%")

            k6, k7 = st.columns(2)
            k6.metric("First window", first_window_start.strftime("%Y-%m-%d") if pd.notna(first_window_start) else "n/a")
            k7.metric("Latest window", latest_window_start.strftime("%Y-%m-%d") if pd.notna(latest_window_start) else "n/a")

            st.markdown("### Current state")
            st.write(f"**{process_state_label}**")
            st.write(process_state_detail)

            st.markdown("### Event log summary")
            e1 = st.columns(1)[0]
            e1.metric("Activities", f"{activities_count}")

            e5, e6 = st.columns(2)
            e5.metric("Replayed traces", f"{replayed_traces}")
            e6.metric("Traces with deviation", f"{deviating_traces}")

            st.markdown("### Top issues now")
            if not issue_rows:
                st.success("No major issue stands out in the current lookback window.")
            else:
                for issue in issue_rows[:5]:
                    with st.container(border=True):
                        st.markdown(f"**{issue['title']}**")
                        st.write(issue["detail"])
                        st.caption(issue["next_step"])

            if alert_rules_caption:
                with st.expander("Current alert criteria", expanded=False):
                    st.caption(alert_rules_caption)

            if not overview_plot_df.empty:
                with st.expander("Recent alert activity", expanded=False):
                    zone_order_plot = sorted(alerts_recent["zone"].dropna().astype(str).unique().tolist())
                    fig_alerts = plot_alert_zone_heatmap(
                        overview_plot_df,
                        zone_order=zone_order_plot,
                        title=f"Alerts over the last {int(lookback_windows)} windows",
                    )
                    st.plotly_chart(fig_alerts, width='stretch')



# =========================
# Trends
# =========================
with tab_trends:
    st.markdown("## Trends")
    st.caption("Create multiple charts. Each chart has its own zone, metric family, and metric selection.")

    # Always use the full advanced catalog here, then filter it per chart
    full_catalog = get_catalog_for_mode("Advanced", timeframe_label)

    if not full_catalog:
        st.warning("No supported metrics found in the computed features.")
    else:
        chart_count = st.number_input(
            "Number of charts",
            min_value=1,
            max_value=6,
            value=1,
            step=1,
        )

        for ci in range(int(chart_count)):
            st.markdown(f"### Chart {ci + 1}")

            # --------------------------------------------
            # Per-chart family selector
            # --------------------------------------------
            if mode == "Basic":
                family_choice = st.radio(
                    "Work on",
                    ["Token level", "Case level"],
                    horizontal=True,
                    key=f"trend_family_{ci}",
                )
            else:
                family_choice = st.selectbox(
                    "Metric family",
                    ["Token only", "Case only", "Conformance only", "All metrics"],
                    index=3,
                    key=f"trend_family_{ci}",
                    help="Filter the metric list for this chart.",
                )

            allowed_cols = allowed_metric_columns(family_choice)

            catalog_i = {
                label: col
                for label, col in full_catalog.items()
                if col in allowed_cols
            }

            if not catalog_i:
                st.info("No metrics available for the selected metric family.")
                st.divider()
                continue

            display_options = list(catalog_i.keys())
            reverse_catalog_i = {v: k for k, v in catalog_i.items()}

            c1, c2, c3, c4 = st.columns([2, 2, 1, 1])

            with c1:
                zones_i = st.multiselect(
                    "Zones to analyze",
                    options=all_zones,
                    default=all_zones,
                    key=f"zones_plot_{ci}",
                )

            with c2:
                default_display = [
                    d for d in default_display_names(family_choice)
                    if d in catalog_i
                ]

                metrics_display = st.multiselect(
                    "Metrics",
                    options=display_options,
                    default=default_display,
                    key=f"metrics_plot_{ci}",
                )

            with c3:
                normalize_i = st.checkbox("Normalize", value=False, key=f"norm_plot_{ci}")

            with c4:
                show_points = st.checkbox("Show points", value=False, key=f"pts_plot_{ci}")

            if not zones_i:
                st.info("Select at least one zone for this chart.")
                st.divider()
                continue

            if not metrics_display:
                st.info("Select at least one metric for this chart.")
                st.divider()
                continue

            metrics_i = [catalog_i[d] for d in metrics_display]

            zfi, long = prepare_trend_long_df(
                zf=zf,
                zones=zones_i,
                metrics=metrics_i,
                mode=mode,
                reverse_catalog=reverse_catalog_i,
                normalize=normalize_i,
            )

            if long.empty:
                st.info("No data available for the selected zones/metrics.")
                st.divider()
                continue

            fig = px.line(
                long,
                x="window_start",
                y="value",
                color="series",
                markers=show_points,
            )
            fig.update_layout(
                height=420,
                margin=dict(l=10, r=10, t=30, b=10),
                legend_title_text="",
            )

            # --- Change point detection (PELT) ---
            cp1, cp2 = st.columns(2)
            with cp1:
                do_cp = st.checkbox("Detect local change points", value=False, key=f"cp_on_{ci}")
            with cp2:
                detect_selection_cp = st.checkbox(
                    "Detect overall change points",
                    value=False,
                    key=f"cp_selection_{ci}",
                    help="Combines all selected lines into one normalized summary signal and detects changepoints on that combined signal.",
                )

            cp_strictness = 75 if mode == "Basic" else 50
            aggregate_method = "mean"
            cp_jump = 2 if mode == "Basic" else 1
            max_selection_cps = 3 if mode == "Basic" else None

            if do_cp or detect_selection_cp:
                if mode == "Advanced":
                    cp_strictness = st.slider(
                        "Change point strictness",
                        min_value=0,
                        max_value=100,
                        value=50,
                        step=1,
                        help="0 = maximum number of changepoints PELT can find. 100 = no changepoints.",
                        key=f"cp_strictness_{ci}",
                    )
                    st.caption("0 = maximum detected changepoints · 100 = none")

                if detect_selection_cp:
                    if mode == "Advanced":
                        aggregate_method = st.selectbox(
                            "Overall change-point aggregation",
                            options=["mean", "median"],
                            index=0,
                            key=f"cp_aggregate_method_{ci}",
                            help="How the selected standardized lines are combined into one overall summary signal.",
                        )
                    else:
                        aggregate_method = "mean"
                        st.caption("Overall change points use mean aggregation across the selected lines in Basic mode.")

                cp_events = pd.DataFrame()
                if do_cp:
                    cp_events = cached_changepoint_events(
                        _zf=zfi,
                        zones=tuple(zones_i),
                        metrics=tuple(metrics_i),
                        cp_strictness=cp_strictness,
                        min_size=3,
                        min_points=10,
                        max_per_series=None,
                        jump=cp_jump,
                        metric_display_items=tuple(sorted(reverse_catalog_i.items())),
                    )

                selection_cp_events = pd.DataFrame()
                selection_cp_contrib = pd.DataFrame()
                if detect_selection_cp:
                    selection_cp_events = cached_selection_changepoints(
                        _zf=zfi,
                        zones=tuple(zones_i),
                        metrics=tuple(metrics_i),
                        cp_strictness=cp_strictness,
                        min_size=3,
                        min_points=10,
                        jump=cp_jump,
                        aggregate_method=aggregate_method,
                        selection_label=f"Chart {ci + 1} selection",
                        max_selection_cps=max_selection_cps,
                        flank_points=3,
                    )
                    if not selection_cp_events.empty:
                        selection_cp_contrib = cached_selection_changepoint_contributions(
                            _zf=zfi,
                            zones=tuple(zones_i),
                            metrics=tuple(metrics_i),
                            _selection_cp_events=selection_cp_events,
                            min_points=10,
                            metric_display_items=tuple(sorted(reverse_catalog_i.items())),
                            selection_label=f"Chart {ci + 1} selection",
                            aggregate_method=aggregate_method,
                            flank_points=3,
                        )

                plotted_points = (
                    long[["window_start", "series", "value"]]
                    .drop_duplicates()
                    .rename(columns={"window_start": "timestamp"})
                    .copy()
                )
                plotted_points["timestamp"] = pd.to_datetime(plotted_points["timestamp"])

                trace_color_map = {}
                for trace in fig.data:
                    trace_name = getattr(trace, "name", None)
                    trace_line = getattr(trace, "line", None)
                    trace_color = getattr(trace_line, "color", None)
                    if trace_name:
                        trace_color_map[trace_name] = trace_color

                added_series_cp = False
                added_selection_cp = False

                if not cp_events.empty:
                    cp_plot = cp_events.merge(
                        plotted_points,
                        on=["timestamp", "series"],
                        how="left",
                    ).dropna(subset=["value"])

                    cp_symbols = [
                        "x",
                        "diamond",
                        "square",
                        "triangle-up",
                        "star",
                        "cross",
                        "triangle-down",
                        "hexagram",
                    ]
                    metric_symbol_map = {
                        m: cp_symbols[i % len(cp_symbols)]
                        for i, m in enumerate(metrics_i)
                    }

                    for series_name, grp in cp_plot.groupby("series", sort=False):
                        metric_col = grp["metric_column"].iloc[0]
                        marker_color = trace_color_map.get(series_name, "black")
                        marker_symbol = metric_symbol_map.get(metric_col, "x")

                        hover_text = [
                            (
                                f"{zone} · {metric}"
                                f"<br>Series change point #{order}"
                                f"<br>Timestamp: {ts}"
                                f"<br>Value: {val:.2f}"
                            )
                            for zone, metric, order, ts, val in zip(
                                grp["zone"],
                                grp["metric_label"],
                                grp["cp_order"],
                                grp["timestamp"],
                                grp["value"],
                            )
                        ]

                        fig.add_scatter(
                            x=grp["timestamp"],
                            y=grp["value"],
                            mode="markers",
                            marker=dict(
                                size=12,
                                symbol=marker_symbol,
                                color=marker_color,
                                line=dict(width=1, color=marker_color),
                            ),
                            name=f"{series_name} · change points",
                            legendgroup=series_name,
                            showlegend=False,
                            text=hover_text,
                            hovertemplate="%{text}<extra></extra>",
                        )

                        added_series_cp = True

                if detect_selection_cp and not selection_cp_events.empty:
                    for _, cp_row in selection_cp_events.iterrows():
                        ts = pd.to_datetime(cp_row["timestamp"])
                        fig.add_vline(
                            x=ts,
                            line_width=2,
                            line_dash="dash",
                            line_color="black",
                            opacity=0.75,
                        )

                    fig.add_scatter(
                        x=[selection_cp_events["timestamp"].min()],
                        y=[long["value"].min()],
                        mode="lines",
                        line=dict(color="black", width=2, dash="dash"),
                        name=f"Overall selection CP ({aggregate_method})",
                        hoverinfo="skip",
                        opacity=0.75,
                    )
                    added_selection_cp = True

                    if not selection_cp_contrib.empty:
                        with st.expander("Overall change-point contributors", expanded=False):
                            for ts, grp in selection_cp_contrib.groupby("timestamp", sort=True):
                                st.markdown(f"**{pd.to_datetime(ts)}**")
                                bar_fig = plot_changepoint_contribution_bars(
                                    grp.head(10),
                                    title="Contribution by selected series",
                                )
                                if bar_fig is not None:
                                    st.plotly_chart(bar_fig, width='stretch')

                if added_series_cp and added_selection_cp:
                    st.caption(
                        f"Markers show per-series change points; dashed vertical lines show overall change points for the current selection ({aggregate_method} aggregation)."
                    )
                elif added_series_cp:
                    st.caption("Change points are shown as markers on the matching series.")
                elif added_selection_cp:
                    st.caption(
                        f"Dashed vertical lines show overall change points for the current selection ({aggregate_method} aggregation)."
                    )
                else:
                    st.caption("No change points detected with the current settings.")

            key_suffix = (
                f"{ci}_{family_choice.replace(' ', '_')}_{'-'.join(zones_i)}_{'-'.join(metrics_i)}_"
                f"{int(normalize_i)}_{int(show_points)}_{int(do_cp)}_{int(detect_selection_cp)}_"
                f"{aggregate_method}_{cp_strictness}"
            )

            st.plotly_chart(fig, width='stretch', key=f"trend_plot_{key_suffix}")

            explainable_cols = [col for col in metrics_i if col in METRIC_EXPLANATIONS]
            if explainable_cols:
                with st.expander(f"Metric explanations (Chart {ci + 1})", expanded=False):
                    for col in explainable_cols:
                        title = reverse_catalog_i.get(col, col)
                        st.markdown(f"**{title}**")
                        st.markdown(METRIC_EXPLANATIONS[col])
                        st.markdown("---")

            st.divider()
# =========================
# Dependencies
# =========================
with tab_deps:
    st.header("Zone dependency insights (lead–lag correlation)")
    st.caption(
        "This tries to answer: “If something changes in Zone A now, when do we see an effect in Zone B?” "
        "We compute correlations with a time shift; a lag of k means B typically reacts k windows later."
    )
    st.markdown("")

    with st.expander("How to interpret this?", expanded=False):
        st.markdown(textwrap.dedent("""
        - **best_lag_windows** = estimated delay (**B after A**) in **time windows**.
        - **best_corr** in [-1, +1]. Large |corr| = stronger relationship.
        - Correlation ≠ causation, but it can be used for **early warning**.
        - **Correlate changes instead of raw levels** compares window-to-window movement, which often reduces fake correlations caused by shared trends.
        - In **Basic** mode we show a simplified, filtered list with only an **insight sentence**.
        """))
    st.markdown("")

    # ----------------------------------------------------
    # Metric lists + friendly names
    # ----------------------------------------------------
    ALL_METRICS = get_all_dependency_metrics(list(zf.columns))
    BASIC_CORR_METRICS = get_basic_dependency_metrics(list(zf.columns))
    metric_options = BASIC_CORR_METRICS if mode == "Basic" else ALL_METRICS

    DEP_METRIC_NAMES = get_dependency_metric_names(timeframe_label)


    unit = {
        "Hourly": "hours",
        "Daily": "days",
        "Weekly": "weeks",
        "Monthly": "months (30D windows)",
    }.get(timeframe_label, "windows")

    if not metric_options:
        st.warning("No supported dependency metrics found for the current dataset.")
        st.stop()

    # ----------------------------------------------------
    # BASIC MODE: simplified list (insight-only)
    # ----------------------------------------------------
    if mode == "Basic":
        st.info("Basic mode: show all very strong delayed cross-zone links (|corr| >= 0.9). If there are only a few, fill the list with the strongest remaining links down to |corr| >= 0.7.")

        c1, c2, c3 = st.columns(3)
        with c1:
            max_lag = int(st.number_input(
                "Max lag to test (time windows)",
                min_value=1,
                value=30,
                step=1,
                key="basic_dep_max_lag",
                help="How many future windows to test for delayed effects.",
            ))

        with c2:
            correlate_changes = st.checkbox(
                "Correlate changes instead of raw levels",
                value=True,
                key="basic_dep_correlate_changes",
                help="Uses x.diff() and y.diff() before correlation. This often reduces false correlations from shared trends.",
            )

        min_points = 8
        min_lag = 1

        dep_all = cached_basic_dependency_results(
            _zf=zf,
            metric_options=tuple(metric_options),
            max_lag=max_lag,
            min_lag=min_lag,
            min_points=min_points,
            correlate_changes=correlate_changes,
        )

        if dep_all is None or dep_all.empty:
            st.success("No strong cross-zone delayed correlations found.")
        else:
            dep_all = select_basic_dependency_rows(
                dep_all,
                priority_threshold=0.9,
                fallback_threshold=0.7,
                fallback_top_n=10,
            )

            if dep_all.empty:
                st.success("No delayed cross-zone correlations with |corr| >= 0.7 were found.")
            else:
                dep_all["src_metric_name"] = dep_all["src_metric"].map(DEP_METRIC_NAMES).fillna(dep_all["src_metric"])
                dep_all["tgt_metric_name"] = dep_all["tgt_metric"].map(DEP_METRIC_NAMES).fillna(dep_all["tgt_metric"])
                dep_all["relationship"] = dep_all["best_corr"].apply(corr_basic_label)

                dep_all["insight"] = dep_all.apply(
                    lambda r: (
                        f"If {r['from_zone']} ({r['src_metric_name']}) changes now, "
                        f"{r['to_zone']} ({r['tgt_metric_name']}) often changes about "
                        f"{int(r['best_lag_windows'])} {unit} later — {r['relationship']}."
                    ),
                    axis=1,
                )

                basic_dep_signature = (
                    tuple(metric_options),
                    int(max_lag),
                    bool(correlate_changes),
                )
                basic_dep_sig_key = "basic_dep_signature"
                basic_dep_limit_key = "basic_dep_visible_limit"
                if st.session_state.get(basic_dep_sig_key) != basic_dep_signature:
                    st.session_state[basic_dep_sig_key] = basic_dep_signature
                    st.session_state[basic_dep_limit_key] = 5

                visible_limit = max(5, int(st.session_state.get(basic_dep_limit_key, 5)))
                dep_show = dep_all[["insight"]].head(visible_limit).reset_index(drop=True)

                st.dataframe(
                    dep_show,
                    width='stretch',
                )
                st.caption(f"Showing {min(len(dep_all), visible_limit)} of {len(dep_all)} strong delayed cross-zone links.")

                if len(dep_all) > visible_limit:
                    if st.button("Show more", key="basic_dep_show_more"):
                        st.session_state[basic_dep_limit_key] = visible_limit + 5
                        st.rerun()

    # ----------------------------------------------------
    # ADVANCED MODE: manual controls (full table)
    # ----------------------------------------------------
    else:
        default_src_metric, default_tgt_metric = get_default_dependency_pair(metric_options)

        src_metric = st.selectbox(
            "Source metric (Zone A: changes now)",
            metric_options,
            index=metric_options.index(default_src_metric) if default_src_metric in metric_options else 0,
            format_func=lambda m: DEP_METRIC_NAMES.get(m, m),
        )

        tgt_metric = st.selectbox(
            "Target metric (Zone B: changes later)",
            metric_options,
            index=metric_options.index(default_tgt_metric) if default_tgt_metric in metric_options else 0,
            format_func=lambda m: DEP_METRIC_NAMES.get(m, m),
        )

        c1, c2, c3 = st.columns(3)
        with c1:
            max_lag = int(st.number_input(
                "Max lag to test (time windows)",
                min_value=1,
                value=30,
                step=1,
                key="adv_dep_max_lag",
            ))
        with c2:
            min_abs_corr = st.slider(
                "Min |correlation|",
                min_value=0.0,
                max_value=1.0,
                value=0.7,
                step=0.05,
                key="adv_dep_min_abs_corr",
            )

        with c3:
            ignore_zero_lag = st.checkbox(
                "Ignore lag 0",
                value=True,
                key="adv_dep_ignore_zero_lag",
            )

        correlate_changes = st.checkbox(
            "Correlate changes instead of raw levels",
            value=True,
            key="adv_dep_correlate_changes",
            help="Uses x.diff() and y.diff() before correlation. This often makes the result more propagation-like.",
        )

        dep = cached_dependency_table(
            _zf=zf,
            src_metric=src_metric,
            tgt_metric=tgt_metric,
            max_lag=max_lag,
            min_lag=1 if ignore_zero_lag else 0,
            min_points=8,
            correlate_changes=correlate_changes,
        )

        if dep is None or dep.empty:
            st.info("No valid pairs could be computed for the current settings.")
        else:
            dep = dep.dropna(subset=["best_corr", "best_lag_windows"]).copy()
            dep = dep[dep["best_corr"].abs() >= min_abs_corr].copy()

            if dep.empty:
                st.info("No pairs matched the current threshold. Try lowering the threshold or increasing max lag.")
            else:
                dep["delay_B_after_A"] = dep["best_lag_windows"].astype(int).astype(str) + f" {unit}"
                dep["relationship"] = dep["best_corr"].apply(
                    lambda c: f"{corr_strength(c)} ({'+' if c >= 0 else ''}{c:.2f}), {corr_direction(c)}"
                )
                src_metric_name = DEP_METRIC_NAMES.get(src_metric, src_metric)
                tgt_metric_name = DEP_METRIC_NAMES.get(tgt_metric, tgt_metric)

                dep["insight"] = dep.apply(
                    lambda r: (
                        f"If {r['from_zone']} ({src_metric_name}) changes now, "
                        f"{r['to_zone']} ({tgt_metric_name}) often changes about "
                        f"{int(r['best_lag_windows'])} {unit} later ({r['relationship']})."
                    ),
                    axis=1,
                )

                show_cols = [
                    "from_zone",
                    "to_zone",
                    "best_corr",
                    "best_lag_windows",
                    "overlap_points",
                    "delay_B_after_A",
                    "relationship",
                    "insight",
                ]
                st.dataframe(dep[show_cols].head(30), width='stretch')



# ---------------------------------------------------------------------
# Predict
# ---------------------------------------------------------------------


with tab_predict:
    st.markdown("## Prediction")
    st.warning(
        "Legacy retrospective ML reference: these scores do not implement causal prefix features "
        "or horizon-label purging and are not operational forecasting evidence. "
        "Use the React/FastAPI Prediction tab for the restricted causal protocol."
    )
    st.caption(
        "Compare decision tree, random forest, and gradient boosting on the same descriptive features "
        "and target definition."
    )

    ml_metric_options = list_numeric_zone_metrics(zf)
    default_feature_metrics = [m for m in get_default_feature_metrics(zf) if m in ml_metric_options][:6]

    if not ml_metric_options:
        st.warning("No numeric zone metrics are available for ML training.")
    else:
        K = "ml_entropy_dt_v2_"

        with st.form(key=K + "form"):
            c1, c2, c3 = st.columns(3)

            with c1:
                target_zone = st.selectbox(
                    "Target zone",
                    options=all_zones,
                    key=K + "target_zone",
                )

            with c2:
                feature_metrics = st.multiselect(
                    "Descriptive features",
                    options=ml_metric_options,
                    default=default_feature_metrics or ml_metric_options[: min(6, len(ml_metric_options))],
                    format_func=get_metric_label,
                    key=K + "feature_metrics",
                )
                feature_metrics = [
                    metric
                    for metric in canonicalize_metric_names(list(feature_metrics))
                    if metric in ml_metric_options
                ]
                history_lags = st.number_input(
                    "History lags",
                    min_value=0,
                    max_value=10,
                    value=3,
                    step=1,
                    key=K + "history_lags",
                    help="Adds lagged copies of every descriptive feature.",
                )

            with c3:
                model_keys = st.multiselect(
                    "Models",
                    options=list_supported_models(),
                    default=list_supported_models(),
                    format_func=get_model_label,
                    key=K + "model_keys",
                )
                horizon_mode = st.radio(
                    "Horizon mode",
                    options=["Search best 1..H", "Use fixed h"],
                    index=0,
                    key=K + "horizon_mode",
                )

                if horizon_mode == "Search best 1..H":
                    max_horizon = st.number_input(
                        "Max horizon H",
                        min_value=1,
                        max_value=50,
                        value=8,
                        step=1,
                        key=K + "max_horizon",
                    )
                    horizon = None
                else:
                    horizon = st.number_input(
                        "Prediction horizon h",
                        min_value=1,
                        max_value=30,
                        value=3,
                        step=1,
                        key=K + "horizon",
                    )
                    max_horizon = None

            st.markdown("### Model settings")
            m1, m2, m3 = st.columns(3)
            with m1:
                max_depth = st.number_input(
                    "Tree max depth",
                    min_value=1,
                    max_value=10,
                    value=3,
                    step=1,
                    key=K + "max_depth",
                )
            with m2:
                min_samples_leaf = st.number_input(
                    "Min samples per leaf",
                    min_value=1,
                    max_value=50,
                    value=5,
                    step=1,
                    key=K + "min_samples_leaf",
                )
            with m3:
                n_splits = st.number_input(
                    "TimeSeriesSplit folds",
                    min_value=2,
                    max_value=10,
                    value=5,
                    step=1,
                    key=K + "n_splits",
                )

            st.markdown("### Target feature settings")
            t1, t2, t3 = st.columns(3)

            with t1:
                default_target_metric = get_default_prediction_target_metric(ml_metric_options)
                target_metric = st.selectbox(
                    "Target feature",
                    options=ml_metric_options,
                    index=ml_metric_options.index(default_target_metric) if default_target_metric in ml_metric_options else 0,
                    format_func=get_metric_label,
                    key=K + "target_metric",
                )
                target_metric = canonical_metric_name(target_metric)
                if target_metric not in ml_metric_options:
                    target_metric = default_target_metric if default_target_metric in ml_metric_options else ml_metric_options[0]

            with t2:
                target_operator = st.selectbox(
                    "Operator",
                    options=["<=", ">="],
                    index=1,
                    key=K + "target_operator",
                )

            with t3:
                default_threshold = 0.0
                target_zone_metric_values = zf.loc[zf["zone"] == target_zone, target_metric].dropna()
                if not target_zone_metric_values.empty:
                    default_threshold = float(target_zone_metric_values.median())

                target_threshold = st.number_input(
                    "Threshold",
                    value=float(default_threshold),
                    step=0.1,
                    key=K + "target_threshold",
                )

            submitted = st.form_submit_button("Train models")

        if submitted:
            try:
                if not feature_metrics:
                    raise ValueError("Select at least one descriptive feature.")
                if not model_keys:
                    raise ValueError("Select at least one model.")

                X = make_wide_feature_table(
                    zf,
                    metrics=feature_metrics,
                    history_lags=int(history_lags),
                )

                y_current = build_binary_target_from_metric_threshold(
                    zf,
                    target_zone=target_zone,
                    target_metric=target_metric,
                    threshold=float(target_threshold),
                    operator=target_operator,
                )

                search_best_horizon = horizon_mode == "Search best 1..H"
                selected_horizon = int(horizon) if horizon is not None else 1
                results_by_model, horizon_scans_by_model, comparison_df = train_compare_models(
                    X,
                    y_current,
                    model_keys=model_keys,
                    search_best_horizon=bool(search_best_horizon),
                    fixed_horizon=int(selected_horizon),
                    max_horizon=int(max_horizon) if max_horizon is not None else int(selected_horizon),
                    max_depth=int(max_depth),
                    min_samples_leaf=int(min_samples_leaf),
                    n_splits=int(n_splits),
                )
                if comparison_df.empty or (comparison_df["status"] != "ok").all():
                    raise ValueError("No model could be trained with the current settings.")

                best_row = comparison_df.loc[comparison_df["status"] == "ok"].iloc[0]
                detail_model_key = str(best_row["model_key"])
                result = results_by_model[detail_model_key]

                st.session_state["ml_baseline_result"] = result
                st.session_state["ml_results_by_model"] = results_by_model
                st.session_state["ml_horizon_scans_by_model"] = horizon_scans_by_model
                st.session_state["ml_comparison_df"] = comparison_df
                st.session_state["ml_baseline_meta"] = {
                    "target_zone": target_zone,
                    "model_keys": list(model_keys),
                    "detail_model_key": detail_model_key,
                    "feature_metrics": list(feature_metrics),
                    "history_lags": int(history_lags),
                    "max_depth": int(max_depth),
                    "min_samples_leaf": int(min_samples_leaf),
                    "n_splits": int(n_splits),
                    "target_metric": target_metric,
                    "target_operator": target_operator,
                    "target_threshold": float(target_threshold),
                    "search_best_horizon": bool(search_best_horizon),
                    "max_horizon": int(max_horizon) if max_horizon is not None else None,
                    "fixed_horizon": int(horizon) if horizon is not None else None,
                }
                st.session_state["ml_feature_table"] = X
                st.session_state["ml_target_series"] = y_current
                st.session_state.pop("ml_baseline_error", None)

            except Exception as exc:
                st.session_state["ml_baseline_error"] = str(exc)
                st.session_state.pop("ml_baseline_result", None)
                st.session_state.pop("ml_results_by_model", None)
                st.session_state.pop("ml_horizon_scans_by_model", None)
                st.session_state.pop("ml_comparison_df", None)
                st.session_state.pop("ml_baseline_meta", None)
                st.session_state.pop("ml_feature_table", None)
                st.session_state.pop("ml_target_series", None)

        if st.session_state.get("ml_baseline_error"):
            st.error(st.session_state["ml_baseline_error"])

        result = st.session_state.get("ml_baseline_result")
        results_by_model = st.session_state.get("ml_results_by_model", {})
        horizon_scans_by_model = st.session_state.get("ml_horizon_scans_by_model", {})
        comparison_df = st.session_state.get("ml_comparison_df")
        meta = st.session_state.get("ml_baseline_meta")
        X_feature_table = st.session_state.get("ml_feature_table")
        y_target_series = st.session_state.get("ml_target_series")

        if result is not None and meta is not None:
            fallback_model_key = getattr(result, "model_key", "decision_tree")
            fallback_model_label = getattr(result, "model_label", get_model_label(fallback_model_key))
            if not results_by_model:
                results_by_model = {fallback_model_key: result}
            if fallback_model_key not in horizon_scans_by_model:
                horizon_scans_by_model[fallback_model_key] = None

            st.markdown("### Model comparison")
            if comparison_df is not None and not comparison_df.empty:
                show_comparison = comparison_df.copy()
                show_comparison["mean_f1"] = show_comparison["mean_f1"].round(3)
                show_comparison["mean_precision"] = show_comparison["mean_precision"].round(3)
                show_comparison["mean_recall"] = show_comparison["mean_recall"].round(3)
                show_comparison["positive_rate"] = (100.0 * show_comparison["positive_rate"]).round(1)
                st.dataframe(
                    show_comparison[
                        [
                            "model",
                            "selected_horizon",
                            "mean_f1",
                            "mean_precision",
                            "mean_recall",
                            "n_rows",
                            "positive_rows",
                            "positive_rate",
                            "status",
                        ]
                    ],
                    width='stretch',
                )

            detail_model_options = [k for k in meta.get("model_keys", []) if k in results_by_model]
            if not detail_model_options:
                detail_model_options = [fallback_model_key]
            default_detail_model_key = meta.get("detail_model_key", fallback_model_key)
            selected_detail_model = st.selectbox(
                "Detailed model view",
                options=detail_model_options,
                index=detail_model_options.index(default_detail_model_key) if default_detail_model_key in detail_model_options else 0,
                format_func=get_model_label,
                key=K + "detail_model_key",
            )
            result = results_by_model[selected_detail_model]

            st.markdown("### Selected model result")
            st.caption(
                "Model: {} | Target zone: {} | Target feature: {} {} {} | Selected horizon: {} window(s)".format(
                    getattr(result, "model_label", fallback_model_label),
                    meta["target_zone"],
                    meta["target_metric"],
                    meta["target_operator"],
                    meta["target_threshold"],
                    result.horizon,
                )
            )

            selected_result_model_key = getattr(result, "model_key", fallback_model_key)
            selected_result_model_label = getattr(result, "model_label", fallback_model_label)
            selected_scan_df = horizon_scans_by_model.get(selected_result_model_key)
            if meta.get("search_best_horizon") and selected_scan_df is not None:
                st.info(
                    "Best horizon selected for {} from 1..{}: h = {}".format(
                        selected_result_model_label,
                        meta["max_horizon"],
                        result.horizon,
                    )
                )
                with st.expander("Horizon comparison", expanded=False):
                    st.dataframe(selected_scan_df, width='stretch')

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Mean F1", "{:.3f}".format(result.mean_f1))
            k2.metric("Mean precision", "{:.3f}".format(result.mean_precision))
            k3.metric("Mean recall", "{:.3f}".format(result.mean_recall))
            k4.metric("Positive rate", "{:.1f}%".format(100.0 * result.positive_rate))

            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Supervised rows", "{}".format(result.n_rows))
            r2.metric("Positive rows", "{}".format(result.positive_rows))
            r3.metric(
                "Latest predicted risk",
                "n/a" if result.latest_pred_prob is None else "{:.1f}%".format(100.0 * result.latest_pred_prob),
            )
            r4.metric(
                "Latest predicted class",
                "n/a" if result.latest_pred_class is None else ("Positive" if result.latest_pred_class == 1 else "Negative"),
            )

            st.markdown("### Feature importance")
            st.dataframe(result.feature_importance_df.head(20), width='stretch')

            explain_with_shap = st.checkbox(
                "Explain with SHAP",
                value=False,
                disabled=not supports_shap_explanations(selected_result_model_key),
                key=K + "explain_with_shap",
                help="Show a SHAP-based global feature influence chart for random forest and hist gradient boosting.",
            )
            if not supports_shap_explanations(selected_result_model_key):
                st.caption("SHAP visualization is currently available for random forest and hist gradient boosting.")
            elif explain_with_shap:
                if not shap_is_available():
                    st.warning("SHAP is not available in the current environment.")
                else:
                    if X_feature_table is None or y_target_series is None:
                        X_feature_table = make_wide_feature_table(
                            zf,
                            metrics=meta["feature_metrics"],
                            history_lags=int(meta["history_lags"]),
                        )
                        y_target_series = build_binary_target_from_metric_threshold(
                            zf,
                            target_zone=meta["target_zone"],
                            target_metric=meta["target_metric"],
                            threshold=float(meta["target_threshold"]),
                            operator=meta["target_operator"],
                        )
                    try:
                        fig_shap = build_global_shap_beeswarm_figure(
                            result,
                            X_feature_table,
                            y_target_series,
                            top_n=10,
                        )
                        st.markdown("### SHAP beeswarm")
                        st.pyplot(fig_shap, clear_figure=True, width='stretch')
                    except Exception as exc:
                        st.warning(f"SHAP explanation could not be computed: {exc}")

            if model_supports_tree_details(selected_result_model_key):
                st.markdown("### Entropy of the target feature")
                st.write(
                    "Entropy(target feature) in the supervised dataset: **{:.3f}**".format(result.target_entropy)
                )

                st.markdown("### Best split based on information gain")
                if result.root_entropy_df is not None and not result.root_entropy_df.empty:
                    best_row = result.root_entropy_df.iloc[0]

                    st.success(
                        "Selected feature for first split: **{}** with threshold **{:.2f}** "
                        "(Information Gain = {:.3f})".format(
                            best_row["feature"],
                            float(best_row["threshold"]),
                            float(best_row["information_gain"]),
                        )
                    )

                    summary_df = pd.DataFrame(
                        {
                            "Item": [
                                "Threshold",
                                "Instances after split",
                                "Entropy(left)",
                                "Entropy(right)",
                                "Weighted entropy",
                                "Information gain",
                            ],
                            "Value": [
                                "{:.2f}".format(float(best_row["threshold"])),
                                "Left ({}, {}), Right ({}, {})".format(
                                    int(best_row["left_neg"]),
                                    int(best_row["left_pos"]),
                                    int(best_row["right_neg"]),
                                    int(best_row["right_pos"]),
                                ),
                                "{:.3f}".format(float(best_row["left_entropy"])),
                                "{:.3f}".format(float(best_row["right_entropy"])),
                                "{:.3f}".format(float(best_row["weighted_entropy"])),
                                "{:.3f}".format(float(best_row["information_gain"])),
                            ],
                        }
                    )
                    st.table(summary_df)

                    with st.expander("All descriptive features: entropy values after splitting", expanded=False):
                        entropy_show = result.root_entropy_df.copy()
                        entropy_show["threshold"] = entropy_show["threshold"].round(3)
                        entropy_show["left_entropy"] = entropy_show["left_entropy"].round(3)
                        entropy_show["right_entropy"] = entropy_show["right_entropy"].round(3)
                        entropy_show["weighted_entropy"] = entropy_show["weighted_entropy"].round(3)
                        entropy_show["information_gain"] = entropy_show["information_gain"].round(3)

                        entropy_show = entropy_show.rename(
                            columns={
                                "feature": "Descriptive feature",
                                "threshold": "Best threshold",
                                "left_entropy": "Entropy(left)",
                                "right_entropy": "Entropy(right)",
                                "weighted_entropy": "Weighted entropy",
                                "information_gain": "Information gain",
                            }
                        )

                        entropy_show["Split instances"] = entropy_show.apply(
                            lambda row: "Left ({}, {}), Right ({}, {})".format(
                                int(row["left_neg"]),
                                int(row["left_pos"]),
                                int(row["right_neg"]),
                                int(row["right_pos"]),
                            ),
                            axis=1,
                        )

                        st.dataframe(
                            entropy_show[
                                [
                                    "Descriptive feature",
                                    "Best threshold",
                                    "Split instances",
                                    "Entropy(left)",
                                    "Entropy(right)",
                                    "Weighted entropy",
                                    "Information gain",
                                ]
                            ],
                            width='stretch',
                        )
                else:
                    st.info("No valid information-gain table could be created for the current dataset.")

                st.markdown("### Decision tree")
                model = result.pipeline.named_steps["model"]
                display_feature_names = [f for f in result.feature_names]
                tree_depth = model.get_depth()
                fig_width = max(12, min(22, 4 + tree_depth * 2.2))
                fig_height = max(6, min(14, 3 + tree_depth * 1.8))

                fig, ax = plt.subplots(figsize=(fig_width, fig_height))
                plot_tree(
                    model,
                    feature_names=display_feature_names,
                    class_names=["Negative", "Positive"],
                    filled=True,
                    rounded=True,
                    fontsize=9,
                    ax=ax,
                )

                ax.set_title("Decision tree", pad=12)
                st.pyplot(fig, width='stretch')
                plt.close(fig)

            st.markdown("### Cross-validated confusion matrix and performance measures")

            tp = int(result.tp)
            fn = int(result.fn)
            fp = int(result.fp)
            tn = int(result.tn)

            precision_cm = float(tp) / float(tp + fp) if (tp + fp) > 0 else 0.0
            recall_cm = float(tp) / float(tp + fn) if (tp + fn) > 0 else 0.0
            accuracy_cm = float(tp + tn) / float(tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0.0
            f1_cm = (
                2.0 * precision_cm * recall_cm / float(precision_cm + recall_cm)
                if (precision_cm + recall_cm) > 0
                else 0.0
            )

            cm_col, formula_col = st.columns([1, 1.3])

            with cm_col:
                cm_display = pd.DataFrame(
                    [
                        ["TP = {}".format(tp), "FN = {}".format(fn)],
                        ["FP = {}".format(fp), "TN = {}".format(tn)],
                    ],
                    index=["Actual positive", "Actual negative"],
                    columns=["Predicted positive", "Predicted negative"],
                )
                st.table(cm_display)

            with formula_col:
                st.markdown(
                    "**Precision** = TP / (TP + FP) = {} / ({} + {}) = {:.3f}\n\n"
                    "**Recall** = TP / (TP + FN) = {} / ({} + {}) = {:.3f}\n\n"
                    "**Accuracy** = (TP + TN) / (TP + TN + FP + FN) = ({} + {}) / ({} + {} + {} + {}) = {:.3f}\n\n"
                    "**F1** = 2 × Precision × Recall / (Precision + Recall) = {:.3f}".format(
                        tp, tp, fp, precision_cm,
                        tp, tp, fn, recall_cm,
                        tp, tn, tp, tn, fp, fn, accuracy_cm,
                        f1_cm,
                    )
                )

# ---------------------------------------------------------------------
# Metrics explained
# ---------------------------------------------------------------------
if mode == "Advanced":
    with tab_metrics:
        st.header("Metrics explained (Advanced)")
        st.caption("Definitions of the metrics shown in Advanced mode.")

        unit_word = {
            "Hourly": "hours",
            "Daily": "days",
            "Weekly": "weeks",
            "Monthly": "months",
        }.get(timeframe_label, "time units")

        st.markdown("### Token-based metrics")

        with st.expander("Token entered — Tokens entering the zone"):
            st.write(
                "Number of tokens that entered the zone during the current window."
            )
            st.write(
                "This is the token-level inflow into the zone."
            )
            st.latex(r"token\_entered = \sum I(w_0 \le produced\_ts < w_1)")
            st.write("Units: tokens per window")

        with st.expander("Token exited — Tokens leaving the zone"):
            st.write(
                "Number of tokens that left the zone during the current window."
            )
            st.write(
                "This is the token-level outflow from the zone."
            )
            st.latex(r"token\_exited = \sum I(w_0 \le consumed\_ts < w_1)")
            st.write("Units: tokens per window")

        with st.expander("Tokens present at window end — End-of-window token backlog"):
            st.write(
                "Number of tokens still present in the zone when the current window ends."
            )
            st.write(
                "This is the token-level backlog at the end of the window."
            )
            st.latex(
                r"tokens\_present\_end = \sum I(produced\_ts < w_1 \land (consumed\_ts = NA \lor consumed\_ts \ge w_1))"
            )
            st.write("Units: tokens")

        with st.expander("Average tokens present in window — Average token load"):
            st.write(
                "Average number of tokens present in the zone during the current window."
            )
            st.write(
                "This is the main token-level load / occupancy metric."
            )
            st.latex(
                r"avg\_tokens\_present\_in\_window = \frac{\text{token occupancy time in window}}{\text{window length}}"
            )
            st.write("Units: average tokens in zone")

        with st.expander("Token netflow — Inflow minus outflow"):
            st.write(
                "Difference between token inflow and token outflow in the current window."
            )
            st.write(
                "Positive values mean token work is building up. Negative values mean the zone is clearing token work faster than new token work arrives."
            )
            st.latex(r"token\_netflow = token\_entered - token\_exited")
            st.write("Units: tokens per window")

        with st.expander(f"Average completed token time — Average time before token exit ({unit_word})"):
            st.write(
                "Average time spent in the zone by tokens that leave the zone during the current window."
            )
            st.write(
                "This includes only completed token stays, not tokens that are still open at window end."
            )
            st.latex(
                r"avg\_completed\_token\_time = \mathrm{mean}(consumed\_ts - produced\_ts \; \text{for tokens exiting in window})"
            )
            st.write(f"Units: {unit_word}")

        with st.expander(f"Average open token age — Average age of unfinished token work ({unit_word})"):
            st.write(
                "Average age of tokens that are still present in the zone at the end of the current window."
            )
            st.write(
                "This shows whether unfinished token work is becoming older, not just larger."
            )
            st.latex(
                r"avg\_open\_token\_age = \mathrm{mean}(w_1 - produced\_ts \; \text{for tokens present at } w_1)"
            )
            st.write(f"Units: {unit_word}")

        with st.expander("Token completion ratio — Token exit divided by token entry"):
            st.write(
                "Ratio of token outflow to token inflow in the current window."
            )
            st.write(
                "Values below 1 mean more token work arrived than left. Values above 1 mean the zone cleared more token work than arrived in that window."
            )
            st.latex(r"token\_completion\_ratio = \frac{token\_exited}{token\_entered}")
            st.write("Units: ratio")

        st.markdown("### Case-based metrics")

        with st.expander("Cases entering — Case-level inflow"):
            st.write(
                "Number of distinct cases whose case-level stay in the zone starts during the current window."
            )
            st.write(
                "This is case-based, not token-based. Multiple tokens from the same case do not increase this count."
            )
            st.latex(r"cases\_entering = \mathrm{nunique}(case\_id \; \text{with entry in window})")
            st.write("Units: cases per window")

        with st.expander("Cases leaving — Case-level outflow"):
            st.write(
                "Number of distinct cases whose case-level stay in the zone ends during the current window."
            )
            st.write(
                "This is the case-level outflow from the zone."
            )
            st.latex(r"cases\_leaving = \mathrm{nunique}(case\_id \; \text{with exit in window})")
            st.write("Units: cases per window")

        with st.expander("Cases active in zone — Case-level load during the window"):
            st.write(
                "Number of distinct cases that overlap the current window in this zone."
            )
            st.write(
                "A case is counted if it is present at any time during the window, even if it entered earlier or leaves later."
            )
            st.latex(r"cases\_active\_in\_zone = \mathrm{nunique}(case\_id \; \text{active in the window})")
            st.write("Units: cases")

        with st.expander("Cases present at window end — End-of-window case backlog"):
            st.write(
                "Number of distinct cases still present in the zone when the current window ends."
            )
            st.write(
                "This is the case-level backlog at the end of the window."
            )
            st.latex(r"cases\_present\_end = \mathrm{nunique}(case\_id \; \text{present at } w_1)")
            st.write("Units: cases")

        with st.expander(f"Average completed case duration — Average completed case stay duration ({unit_word})"):
            st.write(
                "Average duration of completed case-level stays that end during the current window."
            )
            st.write(
                "This is based on merged case-zone stays, so parallel token behavior within one case does not artificially inflate the duration measure."
            )
            st.latex(
                r"case\_completed\_mean\_duration = \mathrm{mean}(exit\_ts - entry\_ts \; \text{for completed case stays ending in window})"
            )
            st.write(f"Units: {unit_word}")

        with st.expander("Case completion ratio — Case exit divided by case entry"):
            st.write(
                "Ratio of case-level outflow to case-level inflow in the current window."
            )
            st.write(
                "Values below 1 mean more cases arrived than finished. Values above 1 mean the zone cleared more case work than arrived in that window."
            )
            st.latex(r"case\_completion\_ratio = \frac{cases\_leaving}{cases\_entering}")
            st.write("Units: ratio")

        st.markdown("### Conformance metrics")

        with st.expander("Alignment trace count — Number of traces contributing conformance evidence"):
            st.write(
                "Number of completed traces whose alignment is assigned to the current window."
            )
            st.write(
                "This is contextual rather than diagnostic: it tells you how many traces the conformance summary is based on."
            )
            st.latex(r"alignment\_trace\_count = \#\{\text{completed traces ending in the window}\}")
            st.write("Units: traces")

        with st.expander("Alignment trace fitness mean — Average fit of traces to the model"):
            st.write(
                "Average alignment fitness of traces assigned to the current window."
            )
            st.write(
                "Higher values mean the observed traces follow the model more closely. Lower values mean more repair is needed to explain the log."
            )
            st.latex(r"alignment\_trace\_fitness\_mean = \mathrm{mean}(fitness \; \text{of aligned traces in window})")
            st.write("Units: ratio from 0 to 1")

        with st.expander("Alignment deviation count — Total number of deviations from the model"):
            st.write(
                "Total number of non-synchronous alignment moves across traces assigned to the current window."
            )
            st.write(
                "This is the main volume measure of conformance problems: it counts how much repair was needed overall."
            )
            st.latex(r"alignment\_deviation\_count = \sum(\text{log-only moves} + \text{model-only moves})")
            st.write("Units: deviation moves")

else:
    with tab_metrics:
        st.header("Metrics explained (Basic)")
        st.caption("Simple explanations of the main metrics used in Basic mode.")

        unit_word = {
            "Hourly": "hours",
            "Daily": "days",
            "Weekly": "weeks",
            "Monthly": "months",
        }.get(timeframe_label, "time units")

        st.markdown("### Flow")

        with st.expander("Token entered — Tokens entering the zone"):
            st.write(
                "Number of tokens that entered the zone during the current time window."
            )
            st.write(
                "**How to read it:** A high value means a lot of token work is arriving in this zone."
            )
            st.write(
                "**Possible insight:** If token entered stays high while token exited stays lower, token work may start to accumulate."
            )
            st.latex(r"token\_entered = \sum I(w_0 \le produced\_ts < w_1)")
            st.write("Units: tokens per window")

        with st.expander("Token exited — Tokens leaving the zone"):
            st.write(
                "Number of tokens that left the zone during the current time window."
            )
            st.write(
                "**How to read it:** A high value means the zone is releasing token work quickly."
            )
            st.write(
                "**Possible insight:** If token exited is consistently lower than token entered, the zone may be struggling to keep up."
            )
            st.latex(r"token\_exited = \sum I(w_0 \le consumed\_ts < w_1)")
            st.write("Units: tokens per window")

        with st.expander("Tokens present at window end — Token backlog"):
            st.write(
                "Number of tokens that are still present in the zone when the current window ends."
            )
            st.write(
                "**How to read it:** A high value means unfinished token work is sitting in the zone."
            )
            st.write(
                "**Possible insight:** Rising token backlog can indicate congestion, waiting, or a local bottleneck."
            )
            st.latex(
                r"tokens\_present\_end = \sum I(produced\_ts < w_1 \land (consumed\_ts = NA \lor consumed\_ts \ge w_1))"
            )
            st.write("Units: tokens")

        st.markdown("### Load and delay")

        with st.expander("Average completed token time — Average time before token exit"):
            st.write(
                "Average time spent in the zone by tokens that leave the zone during the current window."
            )
            st.write(
                "**How to read it:** A high value means completed tokens are spending longer in this zone before moving on."
            )
            st.write(
                "**Possible insight:** Rising values can indicate slower handling, delays, or waiting time inside the zone."
            )
            st.latex(
                r"avg\_completed\_token\_time = \mathrm{mean}(consumed\_ts - produced\_ts \; \text{for tokens exiting in window})"
            )
            st.write(f"Units: {unit_word}")

        st.markdown("### Conformance")

        with st.expander("Trace deviation rate — Share of traces that deviate from the model"):
            st.write(
                "Share of completed traces in the window that need at least one deviation from the process model during alignment."
            )
            st.write(
                "**How to read it:** Higher values mean the recent behavior fits the model less well."
            )
            st.write("Units: ratio")

        with st.expander("Deviation count — Total amount of model mismatch"):
            st.write(
                "Total number of deviations from the model across traces in the window."
            )
            st.write(
                "**How to read it:** This shows total mismatch volume. Use it together with deviation rate to see whether the issue is concentrated or widespread."
            )
            st.write("Units: deviation moves")
