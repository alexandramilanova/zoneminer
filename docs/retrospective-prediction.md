# Retrospective Prediction workflow

15 October 2026. The user explicitly chose to replace the strict forecasting
screen with a retrospective workflow. The restricted prospective
API is retained separately, without exposing its setup in the new screen.

## Small workflow update: class balance and comparable scores

Protocol `retrospective-v3` preserves the existing setup and model choices.
The new **Balance training classes** checkbox defaults to off. When enabled,
each training fold assigns weight `n / (2 * class_count)` to each example in
that class. The final fitted model calculates weights from its labeled training
rows separately. Evaluation observations, target threshold, folds and the
default model classification rules are unchanged. All three classifiers accept these
training weights; the separate prospective pipeline is unchanged. The option
is part of cached experiment identity. Weighted model probabilities remain
uncalibrated and do not estimate a verified operational event probability.

The primary comparison table now shows **pooled** precision, recall and F1 for
both classifiers and baselines, with evaluated-window and actual-positive
counts. Mean-fold scores remain in expandable details. Fold records include
training and evaluation class counts. A model that misses every evaluated
positive receives an explicit explanation, including its false-alarm count.

On the same fixed showcase condition recorded below (no threshold, horizon,
predictor or source-data changes), both options evaluated the same 25 windows
with five positives:

| Model | Original pooled F1 | Balanced pooled F1 |
| --- | ---: | ---: |
| Decision tree | 0.000 | 0.000 |
| Random forest | 0.000 | 0.667 |
| Histogram gradient boosting | 0.000 | 0.000 |
| Persistence baseline | 0.909 | 0.909 |

Balanced RF detects all five positives with five false alarms (precision 0.5,
recall 1.0). Persistence still performs better. This is a comparison of two
declared exploratory settings, not a newly untouched evaluation or a claim
that weighting fixes reconstruction leakage. No setting is selected
automatically using this result.

Verification: 210 Python tests, the full 59-test production Chrome suite,
frontend production build and descriptive parity gate passed. After the final
diagnostic/weighted-tree label edits, nine prediction Python tests and nine
prediction/replay browser tests passed against the final source, with a fresh
isolated browser-service cache. Tests check training-only weights, unchanged
evaluation origins/labels, future isolation of earlier folds, cache identity,
weighted-share labels and unchanged descriptive features. A preview cache
created while source files were being edited was replaced for the final run;
changing files under an already running interpreter is not a release build.

## Prediction method

The application evaluates whether current and recent zone measurements
classify a user-defined threshold condition in a later time window. Inputs are
reconstructed from complete-trace Petri-net alignment replay; the workflow is
exploratory and retrospective.

The protocol includes:


- Zone metrics reconstructed using complete-trace Petri-net alignment replay.
- User-selected zone/metric/operator/threshold and a fixed later-window target.
- Explicit predictor metrics from selected zones, with current and three lagged
  windows. The standard token preset combines production, consumption, occupancy,
  netflow and completed-duration measurements.
- Decision tree, random forest and histogram gradient boosting, depth 3,
  minimum leaf 5, up to five expanding temporal folds and seed 42. RF has 200
  estimators, preserving the existing implementation.
- Mean fold F1, precision and recall, positive/negative counts, skipped-fold
  reasons, the final fitted decision tree, importance and ensemble SHAP.
- All 43 canonical metric identifiers remain selectable where values exist,
  including case metrics, duration/age metrics and conformance. No new metric
  formula or replay algorithm is introduced.

The horizon is fixed before running rather than selected by searching reported
evaluation scores. A binary target is the threshold condition in the specific
window h steps after the feature window, not a crossing anywhere before h.
Origins and label availability are window ends in UTC, with [start,end) bins.

Correctness safeguards explicitly retained in the implementation:
undefined targets remain missing; lags and horizon shifting respect the full
regular grid; labels not available at a fold's first evaluation origin are
purged; preprocessing is fitted within each training fold. Folds without both
training classes are reported as skipped. Fewer than eight labeled windows,
single-class overall targets, missing predictor histories, duplicate windows,
invalid settings and zero valid folds produce informative errors. They are
not repaired into a successful score. The final model fits observed labels and
uses the latest feature row, whose future label is not known, for an explicitly
exploratory latest-window estimate. Entirely missing latest inputs give an
unavailable estimate instead of a fabricated prediction.

There is no separate held-out test or automated horizon/model search in this
screen. Repeated exploratory experiments are allowed and disclosed. Mean fold
scores and pooled scores are separately labeled. Majority and persistence
baselines use the same valid fold periods, with row counts when persistence
cannot be evaluated on every row. A plain-language verdict compares pooled F1
only where support matches. This is not a statistical significance test.

## Reconstruction and scientific interpretation

Existing validated complete-trace replay already supplies the reconstruction;
rewriting the source XES/CSV is unnecessary. Model-only visible moves contribute
inferred model firings; log-only moves do not fire model transitions. The
original uploaded log, model, descriptive artifacts and analytical definitions
are unchanged. Prediction reads the existing zone table without mutating it.

Replay uses its existing inferred timing convention: previous reconstructed
time +1 microsecond for model/silent moves, with subsequent observed times
clamped if needed. This does not establish uniquely measured
silent execution timing. This convention is reported rather than replaced by
another undocumented repair. Multiple equally optimal alignments can yield
different reconstructed histories. Visible repair counts and affected cases
come from the saved conformance table; silent counts are not fabricated from
summaries that do not store them.

Temporal CV and label purging do not remove future dependence already present
in complete-trace repair, full-log discovery, whole-series duration yardsticks
or revisable batch definitions. The UI therefore calls this a **retrospective
prediction experiment**, not validated live forecasting. Model probabilities
are uncalibrated. SHAP uses training examples, reports its output scale, and
explains model behavior rather than causes. One-class or poor performance is a
legitimate outcome; samples, timestamps and thresholds are never altered to
improve it.

Token flow quantities use place productions and consumptions, including
internal movement. They must not be interpreted as zone-boundary crossing
counts. Final-place occupancy retains the supplied Petri-net meaning, including
completed-case tokens. Alternative boundary-flow or token-identity definitions
would require a separate methodological decision; labels and the Metrics
Reference describe the current implementation directly.

## User interface

Main settings are target zone, metric, condition/threshold, fixed horizon,
predictor zones and metric checkboxes. Three models, history lags and technical
hyperparameters are automatic. Calibration cutoffs, coverage declarations,
model checkboxes and development cutoffs are absent from this screen. Historical
ranges assist interpretation. Suggested thresholds use the upper quartile for
>= and lower quartile for <= of finite reconstructed target values. A sparse-value
guard avoids an all-positive default when distinct values allow it. Defaults
are editable; constant or missing series are explained. Suggestions depend on
historical values, never fitted models or evaluation scores; they are exploratory
starting points, not predeclared business limits. The experiment record preserves
whether a suggested or custom threshold was used.

Results show class balance and model comparison, then one model's confusion
counts and explanation. DT is initially selected; RF/HGB expose SHAP. Technical
fold records, latest estimate, reconstruction and downloadable provenance are
expandable. Changes invalidate results immediately; late responses cannot
restore results for an earlier configuration. Failed submissions preserve input.
The source feature-table hash, implementation hash, versions and defaults are
saved with each cached experiment; changing a configuration does not bypass or
modify the separate prospective holdout ledger.

## Showcase check, without parameter tuning

Fixed software/interpretation check on the unchanged daily showcase:
Payment & Risk, token_enter >=200, horizon one day, the six standard token
predictors from that zone, three lags and all three models. This condition is
not claimed as a validated business alert or a transferable operating limit.

- 35 labeled windows: 8 positive, 27 negative.
- Five valid temporal folds, 25 evaluated windows, 5 evaluation positives.
- DT/RF/HGB mean-fold and pooled F1: 0.00 for this condition.
- Persistence pooled F1: 0.909, precision 0.833, recall 1.00, on the same 25 rows.
- Reconstruction: 1,829 aligned cases; 1,102 with visible deviations;
  1,728 log-only moves and 584 inferred visible model moves. Silent moves are
  not separately counted by the saved summary table.

The classifiers train but do not improve on persistence here. No settings were
changed after inspecting this result. This recorded check used an explicit
manual threshold; it does not represent the new suggested-threshold policy. A working comparison interface is not
evidence of useful predictive performance or conference readiness. The earlier
raw BPI bounded-prefix failures concern the separate prospective method; they
are not fixed by relabeling retrospective reconstruction. No new large-log
end-to-end alignment benchmark is claimed in this change.

## Implementation and validation

- New `analytics/retrospective_prediction.py`: threshold/lag series, purged
  expanding CV, three classifiers, baselines, latest estimate and explanations.
- New `backend/retrospective_prediction.py` and analysis routes: typed requests,
  metric availability, immutable-input reads, repair audit and cached provenance.
- `frontend/src/pages/Prediction.tsx` and typed API client: replacement screen.
- Independent tests in `tests/test_retrospective_prediction.py`: known threshold
  shifts, missing targets, all metric families, purging, earlier-fold isolation,
  independent confusion/F1 calculations, latest unlabeled row, invalid conditions,
  API validation/cache and unchanged source tables.
- Prediction Playwright tests: all metric options, real three-model training,
  tree/SHAP, stale responses, errors, unchanged descriptive data and the actual
  showcase/pooled-baseline agreement. Calibration API integration is retained
  independently of the new screen.

Validation: 203 Python tests and 51 production Chrome tests pass. Frontend
and Docker builds pass. The descriptive parity gate passes: pm4py exact;
Rust4PM existing tolerances unchanged. No analytical baseline was updated.

Visual evidence (manually inspected):

- [Actual unchanged showcase](validation/retrospective-prediction/retrospective-showcase.png).
- [Fixed showcase check record](validation/retrospective-prediction/showcase-check.json).

Tree and SHAP fixture screenshots can be regenerated with
`frontend/tests/prediction.spec.ts`; redundant committed copies were removed.

The independent fixture's scores are correctness evidence, not evidence of useful
real-world prediction. The actual showcase illustrates a valid poor result and
a stronger simple baseline.

[Suggested threshold interface](validation/retrospective-prediction/threshold-defaults.png).
