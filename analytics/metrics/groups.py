from __future__ import annotations

from analytics.metrics.compat import canonical_metric_name
from analytics.metrics.schema import CANONICAL_METRICS, METRIC_SPECS_BY_NAME


def list_metric_names() -> list[str]:
    return [spec.name for spec in CANONICAL_METRICS]


def list_metric_labels() -> dict[str, str]:
    return {spec.name: spec.label for spec in CANONICAL_METRICS}


def get_metric_label(metric_name: str) -> str:
    canonical = canonical_metric_name(metric_name)
    spec = METRIC_SPECS_BY_NAME.get(canonical)
    return spec.label if spec else canonical


def get_metrics_by_family(family: str) -> list[str]:
    return [spec.name for spec in CANONICAL_METRICS if spec.family == family]


def get_basic_metric_names() -> list[str]:
    return [spec.name for spec in CANONICAL_METRICS if spec.basic_visible]


def get_advanced_metric_names() -> list[str]:
    return [spec.name for spec in CANONICAL_METRICS if spec.advanced_visible]


def get_default_dependency_metrics(zf_columns: list[str]) -> list[str]:
    return [
        spec.name
        for spec in CANONICAL_METRICS
        if spec.default_dependency and spec.name in zf_columns
    ]


def get_all_analysis_metrics(zf_columns: list[str]) -> list[str]:
    excluded = {"zone", "window_start", "window_end"}
    return [c for c in zf_columns if c not in excluded]


def get_default_ml_metrics(zf_columns: list[str]) -> list[str]:
    defaults = [
        spec.name
        for spec in CANONICAL_METRICS
        if spec.default_ml and spec.name in zf_columns
    ]
    if defaults:
        return defaults
    return get_all_analysis_metrics(zf_columns)


def is_duration_metric(metric_name: str) -> bool:
    spec = METRIC_SPECS_BY_NAME.get(canonical_metric_name(metric_name))
    return bool(spec and spec.is_duration)


def get_default_alert_metrics(zf_columns: list[str]) -> list[str]:
    preferred = [
        "token_present_end",
        "token_netflow",
        "token_avg_age_open",
        "token_avg_present_window",
        "case_present_end",
        "case_avg_duration_completed",
    ]
    return [metric for metric in preferred if metric in zf_columns]


def get_default_alert_threshold(metric_name: str, duration_unit_seconds: float) -> float:
    metric_name = canonical_metric_name(metric_name)
    if metric_name in {"token_avg_age_open", "token_avg_duration_completed", "case_avg_duration_completed"}:
        return float(duration_unit_seconds)
    if metric_name in {"token_present_end", "case_present_end"}:
        return 20.0
    if metric_name == "token_avg_present_window":
        return 5.0
    if metric_name == "token_netflow":
        return 1.0
    return 0.0


def get_default_dependency_pair(zf_columns: list[str]) -> tuple[str | None, str | None]:
    src_candidates = ["token_netflow", "token_enter", "case_enter", "token_present_end"]
    tgt_candidates = ["token_avg_age_open", "token_present_end", "case_avg_duration_completed", "case_present_end"]

    src = next((metric for metric in src_candidates if metric in zf_columns), None)
    tgt = next((metric for metric in tgt_candidates if metric in zf_columns and metric != src), None)
    return src, tgt


def get_default_prediction_target_metric(zf_columns: list[str]) -> str | None:
    preferred = [
        "token_present_end",
        "token_avg_age_open",
        "case_present_end",
        "case_avg_duration_completed",
    ]
    return next((metric for metric in preferred if metric in zf_columns), None)
