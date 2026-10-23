# Supported replay semantics

Replay supports ordinary, uncolored place/transition Petri nets with positive
integer arc weights, non-negative integer marking counts, silent transitions,
multiple tokens per place, loops, choices, and concurrent split/join behavior.
Node identities must be unique across the net; non-empty visible activity
labels may repeat. Each input supplies one explicit initial
marking and one explicit final marking, possibly containing several places and
token multiplicities. Empty markings are allowed; missing markings are not.

Both engines retain exact transition identities for every synchronous and model
move, including silent moves. Label-only legacy alignments are accepted only
for unambiguous visible labels; silent moves without exact identities are
rejected rather than guessed. A transition fires only if **every** input place
has the number of tokens its weighted input arc requires. It consumes and
produces precisely the specified multiplicities. Replay must consume the whole
trace and finish at exactly the supplied final marking, including token counts
and absence of extra tokens. Invalid histories raise errors; no missing tokens
are invented and no negative markings are clamped away.

pm4py's ordinary default alignment search remains in use for the existing demo
profile. Weighted arcs or initial/final totals other than one use pm4py's exact
semantics-based Dijkstra search, with the same default alignment costs
(synchronous 0, silent 1, log/visible model move 10000). Rust4PM receives the
original arc weights and marking multiplicities. Equivalent optimal alignments
need not choose the same path or order; equal costs alone do not prove equal
histories. Independent small-net tests verify specified paths and histories.

Final-marking tokens remain unconsumed intervals (`consumed_ts = NaT`). This is
the actual final Petri-net state, not evidence of an incomplete alignment.
Replay does not delete or artificially close these tokens. The existing leak
diagnostics exclude final places; zone occupancy can still include them when a
user assigns final places to a zone. Whether completed-case occupancy should be
excluded is a separate analytical policy, unchanged by this correction.

## Explicit rejection

- Reset, inhibitor, colored, data-guarded, stochastic/timed, and custom node/arc
  semantics are unsupported. They are not converted to ordinary arcs.
- Parallel arc objects with the same endpoints must be expressed as one arc
  with the combined weight; they are rejected to avoid backend disagreement.
- PNML import accepts a single flat ordinary P/T net (coremodel/ptnet profile),
  with exactly one explicit final marking and the supported ordinary XML
  elements plus ProM visibility annotations. Hierarchies, unknown extensions,
  multiple nets/pages, duplicate node IDs, and missing or alternative final
  markings are rejected before the importer can discard, infer, or merge them.
- Empty traces and missing event timestamps cannot yield timed token histories
  and are rejected. CSV and XES imports stably order each case by its recorded
  timestamps, retaining file order for ties and reporting reordered cases and
  events in the model notice. Original files, timestamps, and event attributes
  are preserved. This preprocessing can change the discovered model and
  alignments; it does not repair erroneous dates or certify the business order.
  Direct replay callers still must supply non-decreasing timestamps.
  Malformed, incomplete, or contradictory
  alignments are rejected, including alignments ending at a different marking.
- A log-only move carries no model transition identity. With a unique matching
  label it retains the existing adjacent-zone attribution. If several model
  transitions share that label, replay itself remains defined but zone
  attribution is rejected: choosing a transition or distributing its weight
  would require an explicit scientific policy. Unmatched activities retain the
  existing window-level-only conformance treatment.

## Retained scientific assumptions

Alignment replay is retrospective and completes traces to the specified final
marking, possibly inserting model moves; it is not prefix/online replay.
Observed moves use their event timestamps. Model/silent moves use the previous
clock plus one microsecond, and a following observed move cannot precede that
inferred clock. Initial tokens retain the historical first-firing timestamp
(first event for a log-only alignment). Indistinguishable tokens within a place
are consumed FIFO. These are reconstruction conventions, not independently
observed token identities or service times. No boundedness or soundness proof
is performed; alignment search on unbounded or difficult models may not finish.

Corrected analyses use a new cache namespace so previously persisted replay
artifacts cannot bypass these checks. Existing artifacts are not overwritten.
The model-graph API and net diagram also preserve and annotate non-unit arc
weights; initial/final marking multiplicities remain available in the API.

## Reuse and scalability

The API persists the exact discovered net so generated place/transition
identities survive memory-cache eviction and server restarts. Its provenance
remains `discovered_from_log`. Validated replay tables are cached by dataset,
backend, and import/replay version, independently of zone and time-window
choices. Changing either choice reuses these tables but recomputes zone metrics.
The chronological-import version does not reuse older analytical artifacts.

Rust4PM aligns distinct activity sequences in native parallel batches of up to
64 variants. Compact activity-only projections retain each variant's frequency;
returned sequences and frequencies are checked before mapping results back to
the original case order. Progress advances after each complete batch. Registry
projections and temporary files are released even when a native call fails.
Search failures or missing/duplicate results fail the analysis instead of
publishing a partial replay. Alignment costs and search options are unchanged.
Rust4PM uses Rayon workers; `RAYON_NUM_THREADS` can bound their count when set
before server startup. Parallel search increases peak memory relative to serial
alignment. Completed replay caches remain compatible and need no invalidation.
Use `python tools/benchmark_alignments.py` to compare the old serial calls with
native batches on the showcase (or supply `--log` and optional `--pnml`). The
benchmark checks equal costs and fitness and validates both token histories on
the same net. It reports path and history differences separately: equally
optimal paths can differ even with identical transition UUIDs.

Repeated time-window queries use exact sorted timestamp indexes with the same
half-open boundaries. Token queues retain FIFO order and weighted enabledness
and final-marking checks remain mandatory. Optimization does not select cheaper
alignment costs, drop cases, or approximate the window integrals. Existing
FIFO pair subsampling above 4,000 completed stays per window remains unchanged.

The API uses a bounded model cache (default three datasets) and compute queue
(default one active analysis); configure `ZONE_ANALYTICS_MODEL_CACHE_SIZE` and
`ZONE_ANALYTICS_MAX_JOBS` if available memory permits. Jobs and their progress
are still in-process; a server restart interrupts queued/running work. Loading
and replay still materialize the full log and interval tables in memory, and
optimal alignment can be expensive for complex models or many distinct traces.

## Complete replay delivery

Token-interval and zone-stay endpoints expose offset pages over the immutable
persisted row order, with `row_count`, `total_count`, `offset` and
`next_offset` (null on the last page). `limit` must be positive and is bounded
at 50,000 token intervals or 200,000 stays per response; `offset` cannot be
negative. Zone-stay filtering happens before pagination.

The browser loads all pages and verifies their offsets, counts and total
before publishing the complete table. Missing/failed pages produce an error,
not a partial animation or flow chart. Replay cancels obsolete page loads
when the analysis changes, clears old state, and reports the loaded interval
count. Journey failures are shown explicitly. Pagination bounds individual
responses; the current browser and backend still materialize the complete
history in memory. This is not a claim of unlimited browser scalability.
