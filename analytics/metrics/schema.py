from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSpec:
    name: str
    label: str
    family: str
    unit: str
    description: str
    basic_visible: bool = False
    advanced_visible: bool = True
    default_dependency: bool = False
    default_ml: bool = False

    @property
    def is_duration(self) -> bool:
        return self.unit == "seconds"


CANONICAL_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec(
        name="token_enter",
        label="Token place productions",
        family="token",
        unit="count",
        description="Number of token-place intervals produced in the zone during the current window, including internal place movements.",
        basic_visible=True,
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="token_exit",
        label="Token place consumptions",
        family="token",
        unit="count",
        description="Number of token-place intervals consumed in the zone during the current window, including internal place movements.",
        basic_visible=True,
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="token_present_end",
        label="Token present at window end",
        family="token",
        unit="count",
        description="Number of tokens still present in the zone when the current window ends.",
        basic_visible=True,
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="token_avg_present_window",
        label="Token average present in window",
        family="token",
        unit="count",
        description="Average token occupancy within the current window.",
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="token_netflow",
        label="Token netflow",
        family="token",
        unit="count",
        description="Place-level token productions minus consumptions in the current window.",
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="token_avg_duration_completed",
        label="Mean completed token-place duration",
        family="token",
        unit="seconds",
        description="Mean place residence time of token-place intervals consumed in this zone during the current window.",
        basic_visible=True,
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="token_avg_age_open",
        label="Token average open age",
        family="token",
        unit="seconds",
        description="Mean age since place production of token intervals present immediately before the window ends.",
        default_ml=True,
    ),
    MetricSpec(
        name="token_completion_ratio",
        label="Token completion ratio",
        family="token",
        unit="ratio",
        description="Ratio of token exits to token entries in the current window.",
    ),
    # Aging/tail metrics: SLA breaches are
    # made of tail behavior, not means. The aging yardstick is the zone's
    # overall median completed token duration (whole timeline), so "aged"
    # keeps one meaning across windows.
    MetricSpec(
        name="token_age_p90_open",
        label="Open-token age p90",
        family="token",
        unit="seconds",
        description=(
            "90th percentile of the ages of tokens still present in the zone at the "
            "end of the current window."
        ),
        default_ml=True,
    ),
    MetricSpec(
        name="token_aged_open_share",
        label="Aged open-token share",
        family="token",
        unit="ratio",
        description=(
            "Share of tokens still present at the end of the current window that are "
            "older than twice the zone's overall median completed token duration."
        ),
        basic_visible=True,
        default_ml=True,
    ),
    MetricSpec(
        name="token_stagnation_index",
        label="Stagnation index",
        family="token",
        unit="ratio",
        description=(
            "Age of the oldest open token at the end of the current window divided by "
            "the zone's overall median completed token duration."
        ),
    ),
    MetricSpec(
        name="case_enter",
        label="Case enter",
        family="case",
        unit="count",
        description="Number of distinct cases whose case-level stay starts during the current window.",
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="case_exit",
        label="Case exit",
        family="case",
        unit="count",
        description="Number of distinct cases whose case-level stay ends during the current window.",
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="case_active_window",
        label="Case active in window",
        family="case",
        unit="count",
        description="Distinct cases with a stay starting before window end and ending at or after window start, or still open.",
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="case_present_end",
        label="Case present at window end",
        family="case",
        unit="count",
        description="Number of distinct cases still present in the zone at the end of the current window.",
        default_ml=True,
    ),
    MetricSpec(
        name="case_avg_duration_completed",
        label="Case average completed duration",
        family="case",
        unit="seconds",
        description="Average duration of completed case-level stays that end during the current window.",
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="case_completion_ratio",
        label="Case completion ratio",
        family="case",
        unit="ratio",
        description="Ratio of case exits to case entries in the current window.",
    ),
    MetricSpec(
        name="case_duration_p50",
        label="Case duration p50",
        family="case",
        unit="seconds",
        description=(
            "Median duration of completed case-zone stays ending in the current window."
        ),
    ),
    MetricSpec(
        name="case_duration_p90",
        label="Case duration p90",
        family="case",
        unit="seconds",
        description=(
            "90th percentile duration of completed case-zone stays ending in the "
            "current window (completed stays only; no SLA threshold implied)."
        ),
        basic_visible=True,
        default_ml=True,
    ),
    # Revisit/rework metrics: a revisit is
    # a case's second-or-later maximal stay in the same zone (stay_id >= 2).
    # Rework is a classic waste indicator; pairs with the zone-attributed
    # deviation counts.
    MetricSpec(
        name="case_revisit_enter",
        label="Revisit entries",
        family="case",
        unit="count",
        description=(
            "Number of case-zone stays starting in the current window that are a "
            "case's second or later visit to this zone."
        ),
        default_ml=True,
    ),
    MetricSpec(
        name="case_rework_ratio",
        label="Revisit share (legacy rework ratio)",
        family="case",
        unit="ratio",
        description=(
            "Share of case-zone stays starting in the current window that are revisits "
            "(the case had already been in this zone and comes back)."
        ),
        basic_visible=True,
        default_ml=True,
    ),
    MetricSpec(
        name="case_revisit_gap_mean",
        label="Mean revisit gap",
        family="case",
        unit="seconds",
        description=(
            "Among revisits starting in the current window, the average time since the "
            "same case last left this zone."
        ),
    ),
    # Batching-on-exit metrics: a batch is
    # >= 3 stays whose exits cluster (consecutive gaps <= 15 min) while their
    # entries are spread out (exit span <= 25% of entry span) — the signature
    # of synchronized waiting, following Klijn & Fahland's performance-
    # spectrum batch mining ported to zone boundaries. Detection runs over
    # the zone's whole timeline; windows count members/batches by exit time.
    MetricSpec(
        name="case_batch_count",
        label="Batches released",
        family="case",
        unit="count",
        description=(
            "Number of batches (groups of three or more case-zone stays with clustered "
            "exits after spread-out entries) whose release falls in the current window."
        ),
        default_ml=True,
    ),
    MetricSpec(
        name="case_batch_size_mean",
        label="Mean batch size",
        family="case",
        unit="count",
        description="Average number of case-zone stays per batch released in the current window.",
    ),
    MetricSpec(
        name="case_batching_ratio",
        label="Batching ratio",
        family="case",
        unit="ratio",
        description=(
            "Share of case-zone stays completing in the current window that left the "
            "zone as part of a batch (clustered exits after spread-out entries)."
        ),
        basic_visible=True,
        default_ml=True,
    ),
    MetricSpec(
        name="case_batch_wait_overhead_mean",
        label="Batch excess duration",
        family="case",
        unit="seconds",
        description=(
            "Among batched stays completing in the current window, the average extra "
            "time spent in the zone compared to the quickest member of their batch — "
            "a descriptive duration difference, not a causal estimate of waiting."
        ),
    ),
    # FIFO/overtaking order statistics:
    # computed pairwise over the case-zone stays completing in the window
    # (cross-window overtakes are not counted). Reveals service discipline
    # (priority handling, parallel servers, unstable queues) invisible to
    # averages — a zone can have a healthy mean sojourn while systematically
    # starving some cases.
    MetricSpec(
        name="case_fifo_inversion_ratio",
        label="FIFO inversion ratio",
        family="case",
        unit="ratio",
        description=(
            "Share of pairs of case-zone stays completing in the current window whose "
            "exit order inverts their entry order (0 = perfect first-in-first-out, "
            "1 = fully reversed). Pairs are compared within the window."
        ),
        basic_visible=True,
        default_ml=True,
    ),
    MetricSpec(
        name="case_overtaken_rate",
        label="Overtaken-stay rate",
        family="case",
        unit="ratio",
        description=(
            "Share of case-zone stays completing in the current window that were "
            "overtaken at least once — another case entered the zone later and "
            "left it earlier."
        ),
        default_ml=True,
    ),
    MetricSpec(
        name="case_overtake_depth_mean",
        label="Mean overtake depth",
        family="case",
        unit="count",
        description=(
            "Among completed stays that overtook at least one other stay in the current window, "
            "the average number of stays they passed."
        ),
    ),
    MetricSpec(
        name="alignment_trace_count",
        label="Alignment trace count",
        family="conformance",
        unit="count",
        description="Number of aligned traces assigned to the current window by their last recorded event timestamp.",
        advanced_visible=True,
        default_ml=True,
    ),
    MetricSpec(
        name="alignment_trace_fitness_mean",
        label="Alignment trace fitness mean",
        family="conformance",
        unit="ratio",
        description="Average alignment fitness of traces assigned to the current window.",
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="alignment_trace_cost_mean",
        label="Alignment trace cost mean",
        family="conformance",
        unit="cost_units",
        description="Average alignment cost of traces assigned to the current window.",
        advanced_visible=False,
    ),
    MetricSpec(
        name="alignment_sync_move_count",
        label="Alignment sync move count",
        family="conformance",
        unit="count",
        description="Number of synchronous log-model moves across traces assigned to the current window.",
        advanced_visible=False,
    ),
    MetricSpec(
        name="alignment_log_move_count",
        label="Alignment log move count",
        family="conformance",
        unit="count",
        description="Number of log-only alignment moves across traces assigned to the current window.",
        advanced_visible=False,
    ),
    MetricSpec(
        name="alignment_model_move_count",
        label="Alignment model move count",
        family="conformance",
        unit="count",
        description="Number of visible model-only alignment moves across traces assigned to the current window (silent moves excluded).",
        advanced_visible=False,
    ),
    MetricSpec(
        name="alignment_deviation_count",
        label="Alignment deviation count",
        family="conformance",
        unit="count",
        description="Log-only plus visible model-only alignment moves across traces assigned to the current window (silent moves excluded).",
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="alignment_trace_deviation_rate",
        label="Alignment trace deviation rate",
        family="conformance",
        unit="ratio",
        description="Share of traces in the current window whose alignment contains at least one deviation from the model.",
        advanced_visible=False,
    ),
    # Zone-attributed conformance (owner-requested feature, 2026-08-11):
    # alignment moves are attributed to the zones adjacent to the fired (or,
    # for log-only moves, label-matched) transition, and counted in the window
    # of the move's replayed timestamp. Unlike the window-level alignment_*
    # metrics above, these VARY per zone. A move at a zone boundary counts for
    # each adjacent zone; moves not attributable to any zone are excluded here
    # (the window-level metrics still include them).
    MetricSpec(
        name="zone_sync_move_count",
        label="Sync moves (zone)",
        family="conformance",
        unit="count",
        description=(
            "Number of synchronous log-model alignment moves attributed to this zone "
            "in the current window (transition adjacent to a zone place; boundary "
            "moves count for each adjacent zone)."
        ),
        basic_visible=True,
        default_ml=True,
    ),
    MetricSpec(
        name="zone_log_move_count",
        label="Moves on log (zone)",
        family="conformance",
        unit="count",
        description=(
            "Number of log-only alignment moves (observed but not allowed by the model) "
            "attributed to this zone in the current window, via the model transition "
            "matching the event's activity label."
        ),
        basic_visible=True,
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="zone_model_move_count",
        label="Moves on model (zone)",
        family="conformance",
        unit="count",
        description=(
            "Number of model-only alignment moves (required by the model but not observed) "
            "attributed to this zone in the current window."
        ),
        basic_visible=True,
        default_dependency=True,
        default_ml=True,
    ),
    MetricSpec(
        name="zone_deviation_count",
        label="Deviations (zone)",
        family="conformance",
        unit="count",
        description=(
            "Total non-synchronous alignment moves (moves on log + moves on model) "
            "attributed to this zone in the current window."
        ),
        basic_visible=True,
        default_dependency=True,
        default_ml=True,
    ),
    # Zone-attributed fitness: each move's
    # unit mass is split equally over its adjacent zones (1/k for boundary
    # moves) — the documented normalization, so summing weights over zones
    # recovers every attributable move exactly once (the plain counts above
    # deliberately count boundary moves for each adjacent zone instead).
    MetricSpec(
        name="zone_deviation_weight",
        label="Deviation mass (zone)",
        family="conformance",
        unit="move_equivalents",
        description=(
            "Boundary-normalized deviation mass attributed to this zone in the current "
            "window: each non-synchronous alignment move contributes 1 split equally "
            "over its adjacent zones, so the zone values sum to the attributable "
            "deviations without double-counting boundary moves."
        ),
        default_ml=True,
    ),
    MetricSpec(
        name="zone_local_fitness",
        label="Local fitness (zone)",
        family="conformance",
        unit="ratio",
        description=(
            "Boundary-normalized share of synchronous moves among all alignment moves "
            "attributed to this zone in the current window (a local synchronous share, "
            "not cost-based alignment fitness)."
        ),
        basic_visible=True,
        default_ml=True,
    ),
)


METRIC_SPECS_BY_NAME = {spec.name: spec for spec in CANONICAL_METRICS}
