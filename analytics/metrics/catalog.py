from __future__ import annotations

from analytics.metrics.groups import (
    get_advanced_metric_names as _get_advanced_metric_names,
    get_all_analysis_metrics,
    get_basic_metric_names as _get_basic_metric_names,
    get_default_dependency_metrics,
    get_metric_label,
    list_metric_labels,
)
from analytics.metrics.schema import METRIC_SPECS_BY_NAME


def _metric_explanation(spec_name: str, duration_unit_label: str) -> str:
    # Legacy Streamlit consumes Markdown. React consumes the same structured
    # contract, so neither client has to parse scientific prose out of Markdown.
    from analytics.metrics.reference import get_metric_reference

    spec = METRIC_SPECS_BY_NAME[spec_name]
    ref = get_metric_reference(spec_name)
    unit = ref["unit_label"]
    if spec.is_duration:
        unit += f" (canonical/API); legacy duration views may convert to {duration_unit_label}"
    return (
        f"**{spec.label}**\n\n{ref['description']}\n\n"
        f"**Unit:** {unit}.\n\n**Calculation:** {ref['formula']}\n\n"
        f"**Empty values:** {ref['unavailable']}"
    )


def get_metric_explanations(timeframe_label: str, duration_unit_label: str) -> dict[str, str]:
    return {
        spec_name: _metric_explanation(spec_name, duration_unit_label)
        for spec_name in METRIC_SPECS_BY_NAME
    }


def get_basic_metric_catalog(timeframe_label: str) -> dict[str, str]:
    labels = list_metric_labels()
    return {labels[name]: name for name in _get_basic_metric_names()}


def get_advanced_metric_catalog() -> dict[str, str]:
    labels = list_metric_labels()
    return {labels[name]: name for name in _get_advanced_metric_names()}


def get_catalog_for_mode(mode: str, timeframe_label: str) -> dict[str, str]:
    if mode == "Basic":
        return get_basic_metric_catalog(timeframe_label)
    return get_advanced_metric_catalog()


def get_basic_metric_names(timeframe_label: str) -> dict[str, str]:
    return list_metric_labels()


def get_basic_dependency_metrics(zf_columns: list[str]) -> list[str]:
    return get_default_dependency_metrics(zf_columns)


def get_all_dependency_metrics(zf_columns: list[str]) -> list[str]:
    return get_all_analysis_metrics(zf_columns)


def get_dependency_metric_names(timeframe_label: str) -> dict[str, str]:
    return list_metric_labels()


def get_metric_label_map() -> dict[str, str]:
    return {name: get_metric_label(name) for name in METRIC_SPECS_BY_NAME}
