# Large-log import and analysis validation

Validated locally on branch `alexandra_demo`, 2026-10-15, using the supplied
`BPI2020IRFit.xes` and automatic Inductive Miner discovery. The source log is
not bundled or modified. Timings are individual local Docker measurements,
not a hardware-independent performance guarantee.

## Failure and import policy

The complete source contains 6,449 cases and 71,729 events. There are 2,324
cases with decreasing timestamps in file order (3,773 adjacent decreases).
For case `declaration 73596`, the source records `Start trip` on 2017-02-08
after `End trip` on 2017-01-14. Passing that trace directly to timed replay
reproduced the reported non-decreasing timestamp error.

Previously CSV import sorted events but XES import did not. Both imports now
use stable within-case chronological ordering; ties keep source order. In
this XES file 13,430 events change position. No cases or events are removed,
and no timestamps or event attributes are repaired. The UI reports reordering
and explicitly cautions that source-data inconsistencies remain.

This preprocessing changes activity sequences: the file-order log has 123
variants, the ordered log 914. Discovery on the ordered log yields 53 places
and 61 transitions, compared with 28/38 on the original order. Therefore this
is an explicit import-policy change that can change discovered models and
analytical results. It is not evidence that the contradictory business dates
are correct. Direct timed-replay callers still reject decreasing timestamps.
Old analysis/replay caches have a different version namespace.

## Performance and equivalence

Native Rust4PM alignment was already cached by unique activity variant. On
the ordered log its search took approximately 1.5 seconds. Major additional
costs were repeated Petri-net validation/identity maps, scalar timestamp
parsing, per-case DataFrame sorting, and repeated full-table window scans.

Changes reuse validated maps within a run, use FIFO deques, sort case-stay
inputs once, and use exact timestamp indexes and integer occupancy integrals.
FIFO inversion statistics use exact rank counting rather than a pair matrix;
strict tie rules and the existing sample above 4,000 stays remain unchanged.
Weighted enabledness, transition identity, alignment costs, final marking,
case-stay merging, window boundaries, and metric definitions are preserved.

An unprofiled before/after comparison used **the same chronological log, net,
and alignments**. Every token interval, conformance row, timed move and daily
zone-feature value matched exactly (`assert_frame_equal(check_exact=True)`).
There were 275,416 token-place intervals, 6,449 trace summaries, 71,729 timed
visible moves, and 1,194 daily feature rows for one zone containing all internal
places. This zone is a performance-test configuration, not a proposed business
interpretation.

| Stage, seconds | Before optimization | After optimization |
|---|---:|---:|
| Timed token replay | 4.65 | 2.27 |
| Trace summaries and timed moves | 2.09 | 0.34 |
| Daily feature generation | 25.70 | 5.12 |

These stage timings exclude import, discovery, alignment search, and API
persistence. Separate production API timings with the final image were:

| Operation | Seconds | Result |
|---|---:|---|
| Upload and automatic discovery | 2.60 | All 6,449 cases / 71,729 events |
| First daily analysis | 11.07 | 1,194 feature rows |
| Weekly analysis, same zones | 2.60 | 172 rows; replay cache reused |

Daily and weekly tables both account for 262,518 internal-place productions
and 262,518 consumptions. Initial and final places were excluded from this
test zone. The full interval table includes their tokens, including final
marking tokens that legitimately remain unconsumed.

## Integration and tests

Changed code: `process_model/io.py` (import policy); `replay.py`,
`alignment_backends.py`, `conformance.py` (shared maps, timestamps and progress);
`features.py` and new `time_index.py` (exact aggregation optimization);
`services/pipeline.py` (notice and stages); `backend/runner.py` and new
`replay_cache.py` (bounded model cache, discovered identity persistence and
replay reuse); `backend/jobs.py`, `routers/analyses.py`, `routers/datasets.py`
(bounded/deduplicated jobs and threaded upload parsing); `backend/store.py`
(cache version); `frontend/src/pages/Workspace.tsx` and
`frontend/src/components/shared.tsx` (upload layout, collapsed examples, stages).
New tests are `tests/test_large_log_pipeline.py` and
`frontend/tests/uploads.spec.ts`. Documentation is in this report, README and
`process_model/REPLAY_SEMANTICS.md`. Prior forecasting work was retained.

- `python -m unittest discover -s tests`: 174 tests passed.
- Frontend production TypeScript/Vite build and Docker build passed.
- Parity gate passed: oracle/API pm4py exact; Rust4PM counts exact and continuous
  metrics within the existing 1% tolerance. No analytical baseline was updated.
- Chrome production browser suite: 48 tests passed, including upload ordering,
  collapsed examples, an out-of-order upload, zone validation and analysis.
- The upload workflow can also run the complete supplied XES file with
  `E2E_LARGE_LOG_PATH=/absolute/path/BPI2020IRFit.xes`; no subsampling is used.
  Both upload browser tests also passed with this full-log setting.

Independent new tests cover stable CSV/XES ordering, preserved timestamps and
attributes, missing timestamp rejection, event boundaries, open and zero-length
intervals, randomized interval integrals, large integer occupancy totals,
strict FIFO pair counts with ties and the sampling boundary, partial replay
cache recovery, concurrent cache reuse, backend separation, persistent discovered
identities/provenance, duplicate jobs and bounded compute concurrency.

Replay tables are persisted independently of zone/timeframe choices. Discovered
PNML is persisted so generated identities survive cache eviction/restarts.
Progress distinguishes queueing, alignment, replay, conformance and features.
A local-container persistence check stored `/app/var` in a named Docker volume.
Restarting the container retained the BPI dataset, exact discovered place and
transition identities, `discovered_from_log` provenance, and cached daily analysis.

## Limits

This validates this complete BPI log, not arbitrary log sizes or models. Logs,
models and intervals are still held in memory. Optimal alignment can become
expensive with difficult models or many distinct variants. Each selected zone
and window grid still has a feature-generation cost. Jobs remain in-process
and do not resume automatically after restart. The descriptive reconstruction
and source-date assumptions in [Replay semantics](../process_model/REPLAY_SEMANTICS.md)
continue to apply; chronological import does not establish prospective validity.
