# Metric definitions and display units

## Evidence and implemented meaning

The canonical inventory has 43 metrics (`analytics/metrics/schema.py`). Their
structured reference (`analytics/metrics/reference.py`) is served by
`GET /api/analyses/{id}/metrics` alongside the legacy Markdown explanation.
React renders structured paragraphs and formulas, not literal Markdown syntax.
All metrics include identifiers, human units, scope, calculation/population,
empty-value rules and counts of non-null analysis rows. The shared reconstruction explanation describes the interpretation of inferred
token histories.

Verified against `process_model/features.py` and `process_model/conformance.py`:

- Token entries/exits count **place** productions/consumptions, including
  internal movements. Completed token durations and open ages are per-place,
  not merged token-zone stays. No waiting queue or business completion is implied.
- Snapshot occupancy is immediately before window end; events on the end
  boundary belong to the next window. Average occupancy integrates overlap time
  divided by window length and can be fractional. The final full bin extends
  beyond the latest known token timestamp.
- Case presence merges overlapping/touching intervals. Case entry/exit counts
  deduplicate cases per window, whereas completed durations and revisits use
  stays. `case_active_window` includes exits exactly at window start.
- Completion ratios can exceed one or be unavailable at zero denominators.
  Revisit share divides by entering **stays**, not distinct entering cases.
- Aging yardsticks use the entire timeline; batching is also whole-timeline.
  These retrospective quantities cannot simply be used as causal predictors.
  Revisit, overtaking and excess batch duration do not prove rework, unfairness,
  scheduled releases, SLA breaches or causal waiting.
- Global conformance uses whole traces assigned by their last recorded event,
  then repeats the same statistics on each zone row. It must not be summed
  across zones. Last event does not prove business completion.
- Local conformance uses adjacent transitions and replayed move times. Boundary
  counts can duplicate moves; weights split mass equally among adjacent zones.
  `zone_local_fitness` is **weighted** sync mass / total attributable mass, not
  backend cost-based alignment fitness. Unassignable moves are excluded locally.
  Silent moves do not count as deviations but may contribute to alignment cost.
- Empty global deviation rate is currently 0, not null: this is explicitly
  documented as absence of evidence rather than perfect conformance.

## Units and affected displays

React's metric charts/tables use canonical seconds and fractional ratios for
both hourly and daily analyses. No analytical values are rescaled. Normalized
trends use z-scores. Human unit labels distinguish tokens, cases, stays, batches,
traces, moves, alignment cost units and fractional move equivalents; machine
units for alignment cost and deviation mass have also been corrected.

The previous reference claimed hours/days while Trends rendered raw seconds.
Trends axes, line/change-point hover, heatmap hover, series tables and period
comparison means now show explicit units using a shared presentation helper.
Confidence bands retain seconds, matching their series. Aggregate change-point
contributions retain percentage and standardized jump units, not duration units.

Overview's compact open ages, Prediction's descriptive case outlook, Flow
Patterns' summary tables and handover tooltips share a null-safe duration
formatter with explicit s/min/h/d labels. Previously Flow Patterns converted
null handover delays to zero. The fingerprint hover and sojourn scatter already
converted seconds once to explicitly labeled hours; they retain that behavior.
Overview's age threshold remains explicitly in hours and is converted once
to seconds for the API; alert reason values now explicitly identify seconds.
Raw feature endpoints/exports retain their canonical values and identifiers.

## Definitions requiring methodological review

Token flow metrics aggregate place-level intervals. Internal movement within a
zone contributes a place consumption and production; these are not true
zone-boundary crossing counts. Defining boundary flows would require a separate
interval-merging and token-identity policy at splits and joins.

Case entries count distinct cases per window, not every stay. Case activity
follows the implemented interval-boundary convention. These definitions are
documented and are not silently changed to match a different interpretation.

Whether final-marking occupancy should represent business backlog, whether
whole-timeline aging/batching yardsticks are appropriate for the research
question, and whether alignment-derived times support business duration claims
also remain methodological questions. The present UI makes the assumptions
explicit and makes no operational forecasting or causal claims for these metrics.

