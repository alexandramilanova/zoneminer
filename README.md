---
title: ZoneMiner
sdk: docker
app_port: 7860
---

# ZoneMiner — token-flow analysis for business processes

ZoneMiner analyzes business processes at an intermediate granularity between
single activities and the whole process: the user groups Petri-net **places into
zones** ("Payment & Risk", "Fulfillment", …), and the tool reconstructs token- and
case-level behavior via **alignment replay**, aggregates it into a time-windowed
**zone-feature table**, and offers descriptive and predictive analyses on top —
including an **animated token-flow replay** and a **click-on-the-net zone editor**.

Built at the Chair of Process and Data Science (PADS), RWTH Aachen University.
An independent tool for reproducible zone-level process analysis, combining
interactive model exploration, time-windowed measurements and interpretable
retrospective prediction.

**Availability:** local Docker or source installation · **License:** MIT application code; dependency licenses apply

## Features

- **Zone editor on the Petri net** — draw zones by clicking places directly in the
  model (cytoscape.js); validity (disjointness, connectedness) checked live.
- **Token replay** — every token's stay in every place, reconstructed by alignment
  replay and animated over time with a synchronized zone-occupancy timeline.
- **Overview & alerts** — per-zone load, open-token age, threshold alerts.
- **Trends & change points** — zone metrics over time windows with PELT-based
  change-point detection, plus a zone × window heatmap.
- **Flow patterns** — per-zone performance spectrum (duration-quartile colored),
  cumulative flow diagrams, a batch & overtaking fingerprint scatter, an
  inter-zone handover Sankey with a time slider, a queueing profile
  (Little's-law consistency, burstiness, load-dependence), and heuristic
  bottleneck states (flowing / queueing / blocked / starving). The feature
  table carries matching metrics: FIFO inversions/overtaking, batching,
  revisits/rework, sojourn percentiles, open-token aging, and zone-attributed
  fitness — see [the flow-pattern reference](docs/flow-patterns-reference.md) for the research grounding.
- **Zone flow map** — the process collapsed to a zone graph on the Overview
  (load, flow volumes, bottleneck-state halos), plus alert "likely contributor"
  hints ranking upstream zones by lagged association.
- **Drift & comparison** — per-zone multivariate drift scores (energy
  distance), and a two-period comparison with Welch tests under
  false-discovery-rate control. Dependency scans carry FDR-controlled
  significance flags.
- **Open-case outlook** — descriptive remaining-time estimates for cases open
  at any chosen moment, by conditional survival on the zone's own history
  (no future data; actuals shown for validation).
- **Case journey in the replay** — click a place to see the cases sitting
  there, click a case to follow its whole path through the zones; bottleneck
  states halo the net in sync with the playback clock.
- **Queue-model lens & what-if (experimental)** — each zone fitted as a mined
  G/G/1 queue with an explicit fit verdict, and a capacity what-if that
  replays actual arrivals through a calibrated c-server queue — refusing to
  run when no constant capacity reproduces reality. Duration trends carry
  95% confidence bands.
- **Dependencies** — time-lagged cross-zone correlations. *Association, not
  causation* — the tool says so wherever these numbers appear.
- **Prediction** — retrospective threshold classification over
  complete-trace reconstructed zone features, comparing decision tree, random
  forest and histogram gradient boosting. Choose a target, threshold, fixed
  horizon and predictor metrics; technical defaults and temporal evaluation are
  automatic. All 43 metric identifiers remain available where values exist.
  Tree, SHAP, fold class counts and persistence/majority baselines explain results.
  Optional training-only class balancing handles imbalanced conditions; pooled
  model and baseline scores share the primary comparison table.
  These are exploratory reconstructed-history experiments, not validated live
  forecasts. See [the retrospective protocol](docs/retrospective-prediction.md).
- **Metrics reference** — every metric explained in-app, generated from one
  canonical metric schema.
- **Downloads** — Plotly charts export PNG/SVG; result tables export their
  displayed rows as CSV with numeric precision preserved. Trend-data CSVs
  include analysis identity, units, and normalization settings.
- **Optional model helpers** — process-tree availability is explained per
  model; compatible Petri nets can render BPMN directly without a process tree.
  Helper diagrams do not replace the net used for zones and replay.

## Architecture

```
frontend/            React + TypeScript + Vite SPA (cytoscape.js net view,
                     Plotly charts, SSE progress) — served by the backend after building
backend/             FastAPI service: upload, zone validation, analysis jobs with
                     staged SSE progress, DuckDB/Parquet persistence (content-
                     addressed: reusable artifacts for matching inputs)
services/            UI-agnostic orchestration layer (the single entry point both
                     the API and the legacy Streamlit app call)
process_model/       Process-mining core: log/PNML IO, alignment replay,
                     token/case zone features, window-level conformance,
                     zone validation & suggestion heuristic
  alignment_backends.py  switchable alignment engines: rust4pm (fast, default)
                         and pm4py (reference) — identical optimal costs
analytics/           Time-series analyses over the zone-feature table: alerts,
                     change points (PELT), lagged correlations; retrospective
                     classification and a restricted prospective research API,
                     canonical metric schema
app.py               Legacy Streamlit app — kept as the reference implementation
                     ("the oracle") for numerical parity checks; new numbers
                     are checked against it (tools/parity_gate.py)
data/demo/           Bundled demo dataset: seeded e-commerce order-fulfillment
                     log + hand-built Petri net + five-zone system
tests/               unittest suite incl. end-to-end regression baseline and
                     pm4py-vs-r4pm backend parity checks
tools/               demo-data generation, baseline recording, parity gate,
                     demo precompute
```

## Quickstart

Requires Python ≥ 3.12 and Node 22 for a source installation. Docker builds
both runtimes for you. Graphviz (`dot`) is needed for helper diagrams and the
legacy interface; install it through your OS package manager.

```bash
git clone https://github.com/alexandramilanova/zoneminer.git
cd zoneminer
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install --require-hashes -r requirements.txt

# build the frontend once
cd frontend && npm ci && npm run build && cd ..

# optional: precompute the demo analysis so the first click is instant
python tools/precompute_demo.py

# 8765 on purpose — Docker Desktop and other tools often occupy port 8000
uvicorn backend.main:app --port 8765
# open http://127.0.0.1:8765 and click "Load demo dataset"
# (Windows: just double-click "Start Zone Analytics.bat" instead)
```

Or with Docker (no host Python or Node installation needed):

```bash
docker build -t zone-analytics .
docker run --name zoneminer -p 127.0.0.1:7860:7860 -v zone-analytics-data:/app/var zone-analytics
# open http://127.0.0.1:7860
```

The named volume retains uploads, analyses, discovered models, and forecasting
records across container replacement. Keep it when upgrading the image. An
empty Docker named volume is initially populated from the image's precomputed
store; an empty host bind mount can hide that store instead.
Start this existing container again with `docker start zoneminer`.

For development, run `uvicorn backend.main:app --reload --port 8000` and,
in another terminal, `cd frontend && npm run dev`. Vite proxies `/api` to port
8000. The port 8765 quickstart serves the built frontend and needs no Vite proxy.

The legacy Streamlit interface still works: `pip install streamlit`, then
`python -m streamlit run app.py`.

## Tests

Python dependencies are generated from `pyproject.toml` into hash-verified locks.
For tests and the legacy interface, install
`pip install --require-hashes -r requirements-test.txt`.
See [dependency locking and license review](docs/dependency-review.md).

```bash
python -m unittest discover -s tests   # unit, regression baseline, API, backend parity
python tools/parity_gate.py            # oracle vs API (pm4py exact, r4pm within tolerance)
```

CI runs both plus the frontend build on every push (`.github/workflows/tests.yml`).
Browser tests run separately; see [frontend/tests/README.md](frontend/tests/README.md).

Local mode keeps a persistent trusted workspace. The optional anonymous runtime
isolates visitors in temporary workspaces with expiry, deletion, and resource
limits; see [the runtime contract](docs/anonymous-workspaces.md).
See [Hugging Face setup](docs/hugging-face.md) for private staging and the
[dependency requirements](docs/dependency-review.md) before public release.

## Data

The bundled demo dataset (`data/demo/`) is a seeded, fully reproducible synthetic
**online order-fulfillment** process (five zones, injected drifts: arrival surge,
payment-risk drift, fulfillment capacity bottleneck, quality drift) — regenerate
with `python tools/build_demo_data.py`. Public event logs may be uploaded separately; external datasets are not
redistributed with the application.

Four **example scenarios** (`data/examples/`, regenerate with
`python tools/build_examples.py`) are selectable directly in the app, each a
small seeded log + net + preconfigured zones built so one analysis family shows
textbook behavior: *Express lane* (priority overtaking), *Batch dispatch* (two
truck runs a day), *Review & rework* (documents loop back — real revisits and
conformance noise), and *Capacity cliff* (a bottleneck is born, starves its
downstream, and drains).

Uploads appear first in the workspace; example scenarios are collapsed by
default. XES and CSV imports stably order events within each case by recorded
timestamp and report reordering in the model notice. Equal timestamps keep file
order; source timestamps are never repaired. Inspect inconsistent source dates
before interpreting durations or discovered process order.

The API reuses validated alignment/replay tables when zones or time windows
change, persists discovered model identities, and separates alignment, token
reconstruction, and conformance progress. Its bounded model cache and compute
queue limit overlapping memory use. See [Replay semantics](process_model/REPLAY_SEMANTICS.md)
for cache versioning, configuration, and scalability limits.

## Methodological notes (deliberate scope boundaries)

These are documented decisions, not bugs:

The supported net classes, exact-identity replay checks, and retained timing
conventions are specified in [Replay semantics](process_model/REPLAY_SEMANTICS.md).

- **Two conformance granularities**: trace-level metrics (fitness, deviation
  rate) are window-level — computed from all traces completing in a window and
  attached identically to every zone's row. In addition, alignment *moves*
  (synchronous, move-on-log, move-on-model) are zone-attributed: each timed
  move counts toward the zones adjacent to its transition, in the window of
  its replayed timestamp. A move at a zone boundary counts for each adjacent
  zone; moves whose activity does not occur in the model cannot be attributed
  and appear only in the window-level totals.
- **Dependency analysis is lagged Pearson correlation** — association, not
  causation, and the UI language keeps that distinction everywhere.
- **Zone definition is manual** (supported by an activity-label suggestion
  heuristic, `process_model/zone_suggestions.py`); zones must be disjoint and
  connected in the place-adjacency graph so zone metrics stay well-defined.
- **Token vs. case counts diverge under parallelism** — one case can hold several
  tokens in the same zone at once. This divergence is a feature the tool
  visualizes, not an inconsistency.

## Citation

Paper in preparation for the ICPM 2027 Demo and Resources Track, Category A.
The manuscript is maintained separately from the application repository.
The source-install URL above identifies this application repository.
Release details and a citation will be added when published.

## License

Application code: MIT — see [LICENSE](LICENSE). Dependencies retain their own
licenses. PM4Py is used for model and log operations even with the default
rust4pm alignment engine; its licensing is relevant to the distributed stack.
Refer to [dependency requirements](docs/dependency-review.md) and
[frontend redistribution notices](THIRD_PARTY_NOTICES.txt).
