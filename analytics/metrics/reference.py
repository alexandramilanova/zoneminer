"""Presentation contract for the implemented retrospective metrics.

Units here describe canonical API values; no numerical conversion is performed.
Descriptions and formulas document the calculations without changing their values.
"""
from analytics.metrics.schema import METRIC_SPECS_BY_NAME

WINDOW_RULE = (
    "Windows are [start, end). Events at end belong to the next window."
)
REPLAY_RULE = (
    "Retrospective complete-trace alignment reconstruction, not uniquely observed token paths. "
    "Model/silent moves use inferred timestamps; token identities use a FIFO convention. "
    "Occupancy includes all marked places, potentially final markings; it is not necessarily "
    "a waiting queue, unfinished cases, resource utilization, or an operational forecast."
)

# name: (unit label, formula / population, unavailable rule)
DETAILS = {
    "token_enter": ("tokens", "Count place intervals with production in [start, end).", "0 if no productions."),
    "token_exit": ("tokens", "Count place intervals with consumption in [start, end).", "0 if no consumptions."),
    "token_present_end": ("tokens", "Count intervals with production < end and (no consumption or consumption >= end).", "0 if no intervals qualify."),
    "token_avg_present_window": ("tokens (time average)", "Sum of interval overlap seconds with [start, end) / window seconds.", "0 if no positive overlap."),
    "token_netflow": ("tokens", "token_enter − token_exit.", "0 if both counts are zero."),
    "token_avg_duration_completed": ("seconds", "Mean(consumption − production) over place intervals consumed in [start, end).", "Unavailable if no intervals complete."),
    "token_avg_age_open": ("seconds", "Mean(end − production) over intervals present immediately before end.", "Unavailable if no intervals are present."),
    "token_completion_ratio": ("ratio (fraction)", "token_exit / token_enter.", "Unavailable if token_enter = 0."),
    "token_age_p90_open": ("seconds", "90th percentile(end − production) for intervals present immediately before end; linear interpolation.", "Unavailable if no intervals are present."),
    "token_aged_open_share": ("ratio (fraction)", "Share of present intervals whose age > 2 × whole-zone median completed place duration.", "Unavailable if no open intervals or reference median is missing/nonpositive."),
    "token_stagnation_index": ("ratio (multiple)", "Maximum present interval age / whole-zone median completed place duration.", "Unavailable if no open intervals or reference median is missing/nonpositive."),
    "case_enter": ("cases", "Distinct case IDs among stays entering in [start, end).", "0 if no entering cases."),
    "case_exit": ("cases", "Distinct case IDs among stays exiting in [start, end).", "0 if no exiting cases."),
    "case_active_window": ("cases", "Distinct cases with stay entry < end and (exit absent or exit >= start).", "0 if no stays qualify."),
    "case_present_end": ("cases", "Distinct cases with stay entry < end and (exit absent or exit >= end).", "0 if no stays qualify."),
    "case_avg_duration_completed": ("seconds", "Mean(exit − entry) over stays exiting in [start, end).", "Unavailable if no stays complete."),
    "case_completion_ratio": ("ratio (fraction)", "case_exit / case_enter.", "Unavailable if case_enter = 0."),
    "case_duration_p50": ("seconds", "50th percentile of completed stay durations exiting in [start, end); linear interpolation.", "Unavailable if no stays complete."),
    "case_duration_p90": ("seconds", "90th percentile of completed stay durations exiting in [start, end); linear interpolation.", "Unavailable if no stays complete."),
    "case_revisit_enter": ("stays", "Count entering stays with stay_id >= 2 in [start, end).", "0 if no revisits enter."),
    "case_rework_ratio": ("ratio (fraction)", "Revisit stays entering / all stays entering in [start, end).", "Unavailable if no stays enter."),
    "case_revisit_gap_mean": ("seconds", "Mean(entry − previous exit) for revisits entering in [start, end).", "Unavailable if no valid revisit gaps."),
    "case_batch_count": ("batches", "Count detected batches whose last member exits in [start, end).", "0 if no batch releases."),
    "case_batch_size_mean": ("stays per batch", "Mean size of batches whose last member exits in [start, end).", "Unavailable if no batch releases."),
    "case_batching_ratio": ("ratio (fraction)", "Batched completed stays exiting in this window / all completed stays exiting in this window.", "Unavailable if no stays complete."),
    "case_batch_wait_overhead_mean": ("seconds", "Mean(member duration − minimum duration in its batch) for batched stays exiting in this window.", "Unavailable if no batched members complete."),
    "case_fifo_inversion_ratio": ("ratio (fraction)", "Strictly inverted entry/exit pairs / all unordered pairs of completed stays.", "Unavailable with fewer than 2 completed stays."),
    "case_overtaken_rate": ("ratio (fraction)", "Completed stays overtaken at least once / compared completed stays.", "Unavailable with fewer than 2 completed stays."),
    "case_overtake_depth_mean": ("stays", "Mean number of stays passed, among stays passing at least one other stay.", "Unavailable if fewer than 2 stays or no overtakers."),
    "alignment_trace_count": ("traces", "Count aligned traces assigned by last recorded event in [start, end).", "0 if no traces are assigned."),
    "alignment_trace_fitness_mean": ("ratio (fraction)", "Arithmetic mean of backend-reported alignment fitness across assigned traces.", "Unavailable if no reported fitness values."),
    "alignment_trace_cost_mean": ("alignment cost units", "Arithmetic mean of backend-reported alignment cost across assigned traces.", "Unavailable if no reported costs."),
    "alignment_sync_move_count": ("moves", "Sum synchronous alignment moves across assigned traces.", "0 if no traces are assigned."),
    "alignment_log_move_count": ("moves", "Sum log-only alignment moves across assigned traces.", "0 if no traces are assigned."),
    "alignment_model_move_count": ("moves", "Sum visible model-only alignment moves across assigned traces.", "0 if no traces are assigned."),
    "alignment_deviation_count": ("moves", "alignment_log_move_count + alignment_model_move_count (visible only).", "0 if no traces are assigned."),
    "alignment_trace_deviation_rate": ("ratio (fraction)", "Assigned traces with at least one log-only or visible model-only move / assigned traces.", "Implementation returns 0 when no traces are assigned: absence of evidence, not perfect conformance."),
    "zone_sync_move_count": ("moves", "Count synchronous moves adjacent to this zone with replayed timestamp in [start, end).", "0 if no attributable moves."),
    "zone_log_move_count": ("moves", "Count log-only moves attributed to this zone in [start, end).", "0 if no attributable moves."),
    "zone_model_move_count": ("moves", "Count visible model-only moves adjacent to this zone in [start, end).", "0 if no attributable moves."),
    "zone_deviation_count": ("moves", "zone_log_move_count + zone_model_move_count.", "0 if no attributable deviations."),
    "zone_deviation_weight": ("move equivalents", "Sum 1/k per attributable deviation, where k is its number of adjacent zones.", "0 if no attributable deviations."),
    "zone_local_fitness": ("ratio (fraction)", "Weighted sync mass / (weighted sync mass + weighted deviation mass), each move weighted 1/k adjacent zones.", "Unavailable if total attributable mass = 0."),
}

def get_metric_reference(name: str) -> dict:
    spec = METRIC_SPECS_BY_NAME[name]
    unit, formula, unavailable = DETAILS[name]
    scope = ("process_window" if name.startswith("alignment_") else
             "zone_conformance" if name.startswith("zone_") else
             "token_place" if spec.family == "token" else "case_zone")
    return {
        "canonical_unit": spec.unit,
        "unit_label": unit,
        "scope": scope,
        "description": spec.description,
        "formula": formula,
        "unavailable": unavailable,
    }
