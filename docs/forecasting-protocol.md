# Restricted prospective research API protocol

The Prediction screen uses the [retrospective workflow](retrospective-prediction.md).
The following restricted prospective endpoints remain available for research/API
compatibility; they are separate from the frontend prediction workflow.

Status: restricted prospective profiles, `causal-calibrated-markings-v3`.
This is an implementation restriction, not a claim that arbitrary Petri nets
or the current order-process showcase support operational forecasting.

## Method overview

This restricted research API uses threshold-based binary targets, zone metrics,
history lags, decision tree/random forest/histogram gradient boosting, purged
temporal model comparison and model explanations. Training uses earlier data
and labels observable at each fitting origin. A fixed horizon and an untouched
later evaluation period are required for a prospective experiment. Numeric
metric conditions are distinct from anomaly-detector labels.

## Observation protocol

- Events are assumed available at recorded event times. There is no ingestion
  timestamp and no claim to handle delayed reporting or late corrections.
- Timestamp values without offsets are interpreted as UTC; offset-aware
  timestamps are normalized to UTC. This assumption must match the source log.
- Origin `t` is the end of the latest fully observed feature window `[t-d,t)`.
  Only events with timestamps **strictly less than t** are available. An event
  at t belongs to the next window. UTC is explicit; h, D, 7D, 30D are fixed bins.
- At horizon h, the target is the metric in `[t+(h-1)d,t+hd)`, not an excursion
  anywhere within h windows and not a first crossing. Its label is available at
  `t+hd`. Undefined metrics have no label; they are never negative examples.
- The analyst must choose target zone/metric/operator, finite numeric threshold,
  fixed horizon, predictor zone–metric pairs, development cutoff and observed
  coverage end. There are no automatic median thresholds or hidden predictors.
- The last selectable observation boundary is the end of the final recorded
  event bin. This is a selectable coverage declaration, **not evidence** that
  the source system was observed continuously through that time. The analyst
  explicitly confirms coverage; logging gaps cannot be inferred here.
- A forecast from an earlier cutoff is labeled historical if later events exist
  in the uploaded file. Such events are not used to build that experiment's
  features. Future-period forecasts are distinguished from held-out evaluations.
- Models and zones must have been fixed before the entire experiment. Full-log
  discovery is rejected for forecasting. A separate model may be learned from
  observed case prefixes strictly before an explicit calibration cutoff. It and
  its own validated zones are frozen before experimental feature windows begin.
  Prefix discovery may under-generalize later behavior or learn optional endings
  from unfinished cases; it is not an independently verified business model. Uploaded model provenance and prior analyst inspection
  cannot be independently established; the app records the declaration.
- A case begins at its first observed event. Initial marking tokens are
  instantiated then; cases not yet observed contribute nothing. Final-marking
  tokens retain their actual model occupancy. A final place assigned to a zone
  can therefore remain occupied; occupancy is not an unfinished-case count.

## Prefix profile under declared routing

`process_model/prefix.py` is separate from complete-trace alignment. It fires
enabled transitions matching observed events and forced immediate silent routing,
preserving arc weights and exact identity. It never adds visible model repairs, omits log events,
forces a final marking or closes unfinished tokens. Within-place matching
retains the existing FIFO convention for indistinguishable tokens; these token
identities and derived durations are reconstructed, not uniquely observed.

Support: ordinary weighted P/T nets, concurrent visible events with
strict per-case timestamps, multiple tokens, visible loops and terminating
conflict-free silent chains, splits and joins. Duplicate
labels are accepted only when exactly one matching transition is enabled at
each observed prefix. Multiple enabled identities, incompatible events and
per-case timestamp ties are rejected, rather than resolved using later events.

### Prediction-only immediate routing

The analyst explicitly adopts instantaneous **forced** silent routing. After
each observed firing, enabled silent transitions fire to quiescence at exactly
that observation's timestamp; no epsilon or next-event timestamp is used. Initial
routing occurs at the first case observation, when initial tokens become available.
This declares an eager routing convention without adopting complete-trace repair
or visible-event insertion/deletion.
An inferred timestamp is a declared model assumption, not an observed execution.

Two separate profiles are supported:

1. Supplied models with conflict-free silent routing retain the existing unique
   reconstructed-history path and its 23 causally supported metrics. Its strict
   resource limits and timestamp restrictions remain in force.
2. Calibrated models, or models with competing silent routes/duplicate labels,
   use `process_model/uncertain_prefix.py`. All reachable bounded marking
   alternatives are retained, including a pending competing routing decision.
   A currently disabled competitor is not ruled out. Forced routes remain
   immediate; optional choices have no assumed priority or probability.

The second profile currently supplies **only token and case end occupancy**.
Identical markings may merge histories, so they do not establish flow counts,
ages, durations, or uniquely observed silent firings. Selected occupancy must
agree across all alternatives at every experimental window; otherwise the whole
experiment is rejected, with bounds and the first affected window. Ambiguity is
never median-imputed, and ambiguous cases or windows are not dropped.

Simultaneous events are replayed in every model-compatible order, preserving
multiplicities. Current observed events can eliminate incompatible alternatives;
future events never revise earlier snapshots. Finite silent cycles may merge
for occupancy. Closed divergent regions with no waiting/quiescent endpoint are
rejected. No final marking is forced and no visible event is added or removed.
Limits reject rather than approximate: 256 markings per closure/result, 4,096
simultaneous-event work states, 10,000 tokens per case and 4,096 study windows.

Calibration artifacts are persisted by observed-prefix content and cutoff, so
changing future events does not rediscover a differently named model. Only case
identity, activity and timestamp enter discovery; future attributes and eventual
case completion do not. Identical observed prefixes reuse the exact PNML. The
study is bound to the source prefix digest and timeframe. Descriptive model,
zones, log and cached analytical results are not modified. Calibration does not
prove compatibility with later events; incompatible observed prefixes fail.

`prediction_history` returns separate token and derived-event tables. Derived
events record exact transition identities, UTC timestamps, availability times,
inferred flags and provenance. Every visible event is retained; none is invented.
Each feature window reconstructs its own prefix, frozen at its boundary. Later
observations cannot choose a prior silent route or revise a prior snapshot.
The response records latest-cutoff observed/inferred counts, per-transition
counts and the first 20 inferred events for inspection. This preview is not the
full prediction event history. The original log, descriptive replay, intervals,
analytical definitions and cached descriptive results are unchanged.

The Prediction tab states this convention before training and requires explicit
acknowledgment. In the unique-history profile, all 23 supported metrics retain their definitions, but their
silent-related flows, occupancy and durations are estimates conditional on this
instantaneous-routing assumption. They are not independently observed token paths.
The protocol version and implementation hash distinguish these results from prior versions;
prior holdout records are retained and cannot be bypassed by switching versions.

Resource limits reject rather than approximate: at most 256 windows and
3 million event–window–zone combinations. These are engineering limits, not
scientific eligibility or performance guarantees.

## Metrics retained

Twenty-three of the 43 canonical metrics retain their implemented definitions
on each prefix snapshot under the declared routing convention. Earlier snapshots are frozen; they are not
rebuilt using the eventual complete trace. The descriptive core accepts optional
explicit observation boundaries to cover inactive and empty zones without
fabricated tokens. Existing descriptive calls and baselines retain their
original horizon semantics.

Supported: token production/consumption, end/average occupancy, netflow,
completed token duration, mean/p90 open age, completion ratio; case entries,
exits, active/end counts, completed mean/p50/p90 duration, completion ratio,
FIFO inversion, overtaken rate, overtake depth, revisits/rework ratio/revisit gap.
Existing deterministic order-statistic sampling for large completed-stay sets
is unchanged; exact replay under a routing convention does not imply an unlimited exact pair count.

Still descriptive, with disabled forecasting options and explicit reasons:

- 14 global/zone conformance metrics: no prospective equivalent of complete
  alignment attribution is assumed, and false zero deviations are not supplied.
- Aged-open share and stagnation index: the implemented yardstick uses the
  whole-timeline median completed duration. A frozen historical calibration
  would be a new declared policy; it has not been silently substituted.
- Four batch metrics: later exits can revise group membership, last release
  time and within-batch duration comparisons. They cannot be assumed final at
  the window end under the current whole-timeline grouping definition.

These six nonconformance metrics could be extended through explicitly specified
calibration or delayed-finalization protocols. No descriptive metric is deleted.

## Evaluation and fitting

Development examples must have feature origin before the development cutoff
and target-label availability at or before it. Each expanding CV fold further
purges training examples whose labels become available after the first
validation origin. Generic TimeSeriesSplit alone is insufficient.

Use the same valid folds, predictors, history and horizon for every classifier.
Report skipped-fold reasons and reject if none remain. Undefined target labels
are excluded without shifting across gaps; structural missing history rows are
removed. Reject one-class development targets, insufficient eligible history,
unknown metrics/zones, no development observations for a selected predictor,
or a latest feature row with no available predictors.

Median imputation is fitted separately within each fold, then on development
training for the frozen held-out evaluator. An entirely missing feature inside
an individual fold uses zero through `keep_empty_features=True`; it is constant
in that fold's training and cannot produce a learned split. There is no
whole-series standardization or feature selection. DT/RF retain entropy splits,
depth 3, minimum leaf 5; RF has 200 trees. HGB retains its existing constructor
settings, including depth 3 and minimum leaf 5. All random seeds are 42.

Choose the model by development mean F1 (ties follow the explicit model list),
not held-out scores. The held-out evaluator is not refitted inside the test
period. Report its precision, recall, F1, confusion matrix, positive/negative
counts, and majority-class/persistence baselines. Persistence has fewer rows
when the current target is undefined; its evaluated count is explicit.
Undefined metric denominators in precision/recall/F1 use zero; the interface
states this. Single-class or small held-out samples carry warnings. Passing the
minimum 8 development / 2 test examples is **not evidence of statistical power**.

The final forecast model is refitted using only labels observable by the
selected observation end. Its input is the latest feature row, whose future
label is unobserved. It reports fitting origin, target period, class,
uncalibrated probability and training/label provenance. Historical evaluation
predictions and final forecast outputs are never presented interchangeably.

## Explanation and reproducibility

DT nodes are read from the final fitted tree, including the imputer's output
feature names. SHAP explains the final RF/HGB using deterministic samples and
background from their eligible training data only (up to 64 rows each).
Interventional Tree SHAP explains RF class-1 probability or HGB class-1 raw
log-odds; output scales are labeled. Additivity is checked. Missing/unsupported
SHAP is reported as unavailable, never replaced by zero importance. Correlated
features can redistribute credit; explanations are not causes. The beeswarm
colors rescale values *within each feature* and do not modify model inputs.

Experiment JSON includes protocol/implementation hashes, dependency versions,
settings, folds, counts, scores, baselines and forecast provenance. A dataset-wide
locked persistent ledger caches identical experiments and rejects changed
configurations reusing overlapping evaluated periods, including changes of zone
system/analysis. This does not police external data inspection, reuploads with
altered content, deleted ledgers, or a user interpreting the comparison table
as permission to select the best held-out score. A genuinely new later test
period is needed after tuning on a prior test period.

## Showcase and conference interpretation

Both bundled order-process logs contain optional silent `tSkipQC` competing
with visible `tQC`. This no longer causes a blanket model rejection: marking
sets retain both possibilities. Full-log discovered models require a separate
calibration study; zones on that model must be defined separately. Actual
visible deviations, nonidentifiable selected occupancy, one-class targets and
insufficient eligible history still prevent forecasting. Configuration eligibility
is not proof that a log conforms or that a classifier can be trained.

A separate deterministic browser fixture tests calibration, zone validation,
all three classifiers, tree visualization, persistence and unchanged descriptive
results. Its scores are correctness evidence, not real-world predictive validity.
Software tests and feasibility diagnostics do not establish real-world predictive validity.

## Reproducible feasibility diagnostics

`python tools/forecasting_diagnostics.py log.xes --output report.json` audits
all observed cases, separately checks calibration-prefix compatibility, then
attempts every structural diagnostic zone and both occupancy targets only when
the entire log is compatible. `.xes.gz` is accepted by this diagnostic; the app's
upload contract remains `.xes`/`.csv`. Settings are fixed: daily windows,
20% of calendar span for calibration, development ending at 70%, horizon one,
threshold >=1, three history lags and all three classifiers. No search for a
successful threshold, zone, cutoff or horizon is performed. Zones are all
silent-linked place components, including initial/final components; they are
structural diagnostics, not validated business zones. Completed-case final
place tokens persist and must not be called unfinished cases or waiting queues.
The diagnostic checks every case even after finding an incompatible one, but
never trains by discarding failed cases. Language compatibility alone does not
establish predictive usefulness. Downloaded raw originals differ from previously
supplied fitted/filtered files.
