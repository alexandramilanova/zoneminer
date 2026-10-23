"""UI-agnostic service layer over the zone-analytics pipeline.

This package is the single entry point for *orchestrating* the analytical
pipeline (``process_model/``) and the time-series analyses (``analytics/``)
without any UI framework involved. The Streamlit app wraps these functions
with ``@st.cache_*``; the FastAPI backend wraps the
same functions with HTTP routes. Neither adds analytical logic of its own.

Modules:
    pipeline  -- load inputs, compute alignments, build the zone-feature table
    analysis  -- change points, dependencies, and other analyses over the table
"""

from services.pipeline import (
    ModelBundle,
    build_zone_analysis,
    compute_alignment_tables,
    load_model_inputs,
    run_demo_pipeline,
)
from services.analysis import (
    selected_trend_analysis,
    basic_dependency_matrix,
    changepoint_events,
    dependency_table,
    selection_changepoint_contributions,
    selection_changepoints,
)

__all__ = [
    "selected_trend_analysis",
    "ModelBundle",
    "basic_dependency_matrix",
    "build_zone_analysis",
    "changepoint_events",
    "compute_alignment_tables",
    "dependency_table",
    "load_model_inputs",
    "run_demo_pipeline",
    "selection_changepoint_contributions",
    "selection_changepoints",
]
