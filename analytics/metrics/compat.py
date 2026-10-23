from __future__ import annotations


LEGACY_TO_CANONICAL = {
    "ATZ_seconds": "token_avg_duration_completed",
    "tokenproduced": "token_enter",
    "tokenconsumed": "token_exit",
    "tokenleft": "token_present_end",
    "token_entered": "token_enter",
    "token_exited": "token_exit",
    "tokens_present_end": "token_present_end",
    "avg_tokens_present_in_window": "token_avg_present_window",
    "avg_completed_token_time": "token_avg_duration_completed",
    "avg_open_token_age": "token_avg_age_open",
    "cases_entering": "case_enter",
    "cases_leaving": "case_exit",
    "cases_active_in_zone": "case_active_window",
    "cases_present_end": "case_present_end",
    "case_completed_mean_duration": "case_avg_duration_completed",
}


def canonical_metric_name(metric_name: str) -> str:
    return LEGACY_TO_CANONICAL.get(metric_name, metric_name)


def canonicalize_metric_names(metric_names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for metric_name in metric_names:
        canonical = canonical_metric_name(metric_name)
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return out
