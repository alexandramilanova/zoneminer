# Calibrated forecasting: implementation and diagnostic evidence

Recorded 15 October 2026 on `alexandra_demo`. No branch, commit, source event
log, normative Petri net, generator or descriptive analytical baseline changed.

## What changed

Prediction can freeze a separate model learned from events strictly before a
mandatory calibration cutoff, including prefixes of unfinished cases. Only
observed identity/activity/time enter discovery. Case container order is
canonicalized; future completion and trace attributes are excluded. Its zones
are validated separately and do not alter descriptive zones or replay.

Bounded marking sets retain silent routing and duplicate-label alternatives.
Only end-window token/case occupancy common to every alternative is supplied.
Selected ambiguous occupancy rejects the experiment with bounds; it is never
imputed or dropped. No visible event is inserted or deleted. Forced routing is
immediate, competing choices retain pending alternatives, and no route
probabilities are claimed. Token matching histories are not fabricated from
merged markings. Cases have independent process markings; this does not model
shared resource tokens across cases. Existing supplied, uniquely routed models
retain their 23 supported causal metrics.

The original three classifiers, purged development evaluation, training-only
preprocessing, untouched later evaluation, baselines, latest-row forecast,
tree and SHAP views remain. A study does not bypass the dataset-wide holdout
ledger. Events are assumed available at recorded timestamps, without ingestion
delays. Final-place occupancy may persist after completion and is not an
unfinished-case or waiting-queue count.

## Public sources and identity

These are the original public logs, **not** the deleted fitted/filtered
files. Their compressed bytes match the MD5 values in official 4TU metadata.
The original repository rate-limited direct file downloads; mirrors were used
only after matching these checksums.

| Original dataset | Official record | Download location used | Verified compressed MD5 |
| --- | --- | --- | --- |
| BPI Challenge 2012 | [4TU](https://data.4tu.nl/articles/dataset/BPI_Challenge_2012/12689204) | [Original-file mirror](https://raw.githubusercontent.com/gianmarchioni/MSc_Projects-BPM_LSTM/main/BPI_Challenge_2012.xes.gz) | `74c7ba9aba85bfcb181a22c9d565e5b5` |
| BPI Challenge 2017 | [4TU](https://data.4tu.nl/articles/dataset/BPI_Challenge_2017/12696884) | [Original-file mirror](https://raw.githubusercontent.com/Patrick-Megard/ProcessMining-Loans/master/Datasets/BPI%20Challenge%202017.xes.gz) | `10b37a2f78e870d78406198403ff13d2` |
| BPI2020 International Declarations | [4TU](https://data.4tu.nl/articles/dataset/BPI_Challenge_2020_International_Declarations/12687374) | [Original-file mirror](https://ndownloader.figshare.com/files/24023492) | `1ec65e046f70bb399cc6d2c154cd615a` |

Raw downloads remain outside the repository. JSON reports record SHA-256,
counts, import-order diagnostics, calibration prefix digest, dates, model size,
every-case replay outcomes and reasons. These public data may have their own
license terms; source records remain authoritative.

## Fixed diagnostic design

Daily UTC windows; calibration ends at 20% of the recorded calendar span;
development ends at 70%; one-day horizon; target occupancy >=1; three lags;
DT/RF/HGB. No model, threshold, horizon or window tuning for success. Zones are
all components linked by silent transitions in the calibration model, including
initial/final components. This is a predetermined structural diagnostic,
**not validated business-zone selection**. Counts of positive examples and
performance are produced only after supported replay. A resource failure does
not prove model/log incompatibility; the first unsupported batch can mask later
deviations. No cases are removed to obtain a score.

Reproduce with dependencies installed, using an external input file:

```sh
python tools/forecasting_diagnostics.py /path/to/log.xes.gz --output report.json
```

The diagnostic accepts compressed logs; the application upload contract remains
`.xes` / `.csv`. This tool creates separate calibration artifacts under the
configured data directory. The app requires explicit experiment choices rather
than imposing these diagnostic defaults.

## Public-log outcomes

The following results use the final canonicalized calibration implementation. No classifier score is
reported when the observed input cannot be reconstructed within supported bounds.

| Dataset | Cases | Events | Final diagnostic |
| --- | ---: | ---: | --- |
| BPI2012 | 13,087 | 262,200 | 13,087 first failures: bounded-replay limit. No training. |
| BPI2017 | 31,509 | 1,202,267 | 31,471 first failures: bounded-replay limit; 38 first failures: visible deviation. No training. |
| BPI2020 International Declarations | 6,449 | 72,151 | 6,449 first failures: bounded-replay limit. No training. |

## Bundled scenarios under the same diagnostic

- Small demo: 120/455 cases have a first visible incompatibility with the
  calibration model. Showcase: 35/1,829. These are calibration-model language
  failures, not independent proof that the normative descriptive model is wrong.
- Batch dispatch, capacity cliff and express lane: all observed cases replay,
  but only 2, 7 and 6 label-eligible development examples respectively remain
  after calibration, horizon and lags. At >=1 the tested identifiable targets
  are single-class; no useful comparison with a baseline can be claimed.
- Review/rework: all cases replay under its separately discovered calibration
  model; one token target is ambiguous and other targets have only four
  eligible development examples. This does not change the previously reported
  incompatibility with the supplied normative review/rework model.
- No threshold was changed to manufacture a training success. These settings
  give zero completed training experiments across the bundled scenarios; no
  fold or performance scores are reported because prerequisites fail. Rejection is
  a diagnostic result, not a zero F1 score.

These are causal prediction-core diagnostics, not full large-log browser or
complete-trace alignment performance benchmarks.

## Changed modules

- `process_model/uncertain_prefix.py`: bounded alternative markings, exact
  weighted enabledness, occupancy bounds and rejection caching.
- `backend/calibration.py`: earlier-prefix model artifacts and validated frozen
  prediction studies.
- `analytics/forecasting.py`, `backend/forecasting.py`, and
  `backend/routers/analyses.py`: profile selection, post-calibration windows,
  metric eligibility, explicit ambiguity rejection and API/provenance contracts.
- `frontend/src/api.ts`, `frontend/src/pages/Prediction.tsx`, and
  `frontend/src/components/PredictionSetup.tsx`: separate calibration/zone
  setup, persistence, mandatory controls and clear restriction explanations.
- `tests/test_calibrated_forecasting.py`, `tests/test_backend_api.py`, and
  prediction/calibration Playwright tests: independent semantics and integration.
- `tools/forecasting_diagnostics.py`: fixed-design reproducible diagnostics.
- README, protocol, paper description and validation artifacts: corrected
  capability claims and recorded evidence.

## Independent tests and integration validation

- 196 Python tests pass. New tests cover weighted concurrent token counts,
  enabledness, duplicate labels, competing/disabled silent routes, finite silent
  loops versus closed divergence, limits, boundary ties, unfinished cases,
  invariant versus ambiguous occupancy, explicit visible deviations,
  future-isolated features **and all three model predictions**, calibration
  future-attribute/case-order isolation, source binding and zone validation.
- Frontend build and Docker build pass. Full production Chrome suite: 49 pass;
  final-image prediction/calibration subset: 5 pass.
- Descriptive parity gate passes: pm4py exact; Rust4PM existing tolerances
  unchanged. No baseline updated.
- The browser fixture runs all three classifiers and verifies that descriptive
  feature responses remain unchanged. The superseded interface screenshot has been retired; numerical validation
  records remain available.
  Its scores demonstrate implementation correctness, **not real-log usefulness**.

## Remaining limits and decision

Explicit enumeration currently fails beyond 256 markings per closure/result,
4,096 simultaneous-event work states, 10,000 tokens per case or 4,096 study
windows. This is an initial bounded implementation, not general scalable prefix
alignment. Rejection results are cached to avoid repeatedly exploring identical
failed variants; affected cases are still counted and rejected.

Do not advertise operational BPI forecasting from these results. Supporting
these raw logs requires a more scalable exact/symbolic marking representation
or a separately justified fixed process model and observable zone definition.
Simply selecting one repaired route, dropping difficult cases, or enlarging a
limit until a favorable score appears is not validation. Calibration models can
under-generalize unseen behavior or learn optional endings from unfinished
prefixes. Model quality and meaningful business zones still need independent
review. No unbiased before/after accuracy comparison with earlier retrospective scores is
established, and useful performance over persistence/class imbalance remains
unverified on these public logs.
