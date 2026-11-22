# ZoneMiner

ZoneMiner explores business processes through **zones**: groups of Petri-net
places representing parts of a process, such as Payment & Risk or Fulfillment.
It reconstructs token and case movements through alignment replay, measures
zone behavior over time, and connects aggregate patterns to individual cases.

Developed at the Chair of Process and Data Science (PADS), RWTH Aachen University.

## Run with Docker

Docker is the simplest local installation; host Python and Node installations
are not required. Get the image from [Docker Hub](https://hub.docker.com/r/alexandramilanova/zoneminer).

```sh
docker run --name zoneminer -p 127.0.0.1:7860:7860 -v zoneminer-data:/app/var alexandramilanova/zoneminer:latest
```

Open [http://127.0.0.1:7860](http://127.0.0.1:7860), then choose **Load demo dataset**
or upload your own log. Keep the terminal running while using the application.
Stop it with Ctrl+C; restart the existing container with `docker start zoneminer`.

The named volume retains uploads, analyses and discovered models across container
replacement. Keep it when upgrading the image. A new, empty named volume receives
the image's precomputed demo store; an empty host bind mount can hide that store.

## Use the tool

1. Load the bundled demo or upload an uncompressed XES or CSV event log. You may
   also upload a PNML Petri net. For a log without a model, choose the discovery
   noise threshold; the model can be rediscovered later without changing the log.
2. Define zones by selecting places in the model. The zone overview shows each
   zone's size and total place coverage; click a zone to edit it. Zones must be
   disjoint and connected. Activity-label suggestions can help with selection.
3. Choose a time window and run the analysis. The demo includes a precomputed
   analysis for a quick first exploration.
4. Explore the views below, or use **Tour**, available before upload and after
   analysis. Export charts and tables to retain results.

| View | What it provides |
| --- | --- |
| Overview | Zone load, open-token age, alerts and a zone flow map. |
| Token replay | Animated token movement, synchronized occupancy and individual case journeys. |
| Trends and change points | Selected metric series, change detection and an optional heatmap. |
| Flow patterns | Performance spectra, cumulative flows, batching, overtaking, handovers and queueing profiles. |
| Dependencies | Lagged cross-zone associations, paired-window coverage and an explained statistical check. |
| Prediction | Retrospective threshold classification with temporal evaluation, baselines, trees and SHAP explanations. |
| Metrics reference | Definitions, units and scope for the available measurements. |

Expandable analysis sections start closed. Charts export PNG or SVG; tables
export their displayed rows as CSV. Trend-data exports include units,
normalization settings and analysis identity.

Four small bundled scenarios illustrate express-lane overtaking, batch dispatch,
review and rework, and a capacity bottleneck. They are available in the workspace
alongside the five-zone order-fulfillment demo.

## Access and resources

The submission uses the Docker installation described above. Difficult alignment problems can take substantial
time and memory. There is no default fixed upload-size or event-count cap, but
available resources limit what can finish.

## Public-log evaluation

The [evaluation report](docs/evaluation/README.md) presents five case studies
using complete public logs: international reimbursements, prepaid travel costs,
IT incidents, sepsis cases and loan applications. Each uses process-informed zones, reports specific findings,
compares replay with recorded events, and provides a reproducible configuration.
The external event logs are not redistributed with the application.

## Source installation

Use Python 3.12 and Node.js 22, matching the Docker runtime. Install Graphviz
(`dot`) through your operating system's package manager for helper diagrams.
From the repository directory:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
python tools/precompute_demo.py
uvicorn backend.main:app --host 127.0.0.1 --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Demo precomputation is optional.
On Windows, create the environment with `py -3.12 -m venv .venv` and activate it
with `.venv\Scripts\activate` in Command Prompt. After installing dependencies and
building the frontend, `Start Zone Analytics.bat` starts the application.

For development, run `uvicorn backend.main:app --reload --port 8000` and, in a
second terminal, `cd frontend` followed by `npm run dev`. Vite proxies `/api` to
port 8000. The built application on port 8765 needs no Vite development server.

## Tests and reproducibility

Install the hash-locked test dependencies in the activated environment:

```sh
pip install --require-hashes -r requirements-test.txt
python -m unittest discover -s tests
python tools/parity_gate.py
cd frontend
node --test tests/replay-index.test.mjs tests/request-queue.test.mjs
```

The parity gate compares the API pipeline with the legacy reference: the PM4Py
path must match exactly; the Rust4PM path must match counts exactly and continuous
measurements within the gate's tolerance.

For browser checks, follow the [browser test guide](frontend/tests/README.md).
Use an isolated test data directory because these tests upload logs and create
analyses. CI runs the backend tests, parity gate, TypeScript/build checks,
frontend unit tests and Chromium regression suite. Firefox, WebKit and anonymous
workspace suites are also available for release validation.

Regenerate the demo with `python tools/build_demo_data.py` and the example
scenarios with `python tools/build_examples.py`. Python dependency locks are
generated from `pyproject.toml`; see [dependency locking](docs/dependency-review.md).

## Methods and implementation

- Zones group places, rather than activities. One case can hold several tokens
  in a zone under parallelism, so token and case counts can differ.
- Imports order events by recorded timestamp within each case and retain file
  order for ties. They report reordering and do not repair source timestamps.
- Dependency analysis uses lagged Pearson correlation. Statistical support does
  not establish causality or practical importance.
- Prediction reconstructs complete-trace history for retrospective experiments;
  it is not a validated live forecasting service.
- Trace-level conformance is shared across zone rows for a time window.
  Alignment moves are additionally attributed to adjacent zones; a boundary
  move can contribute to more than one zone.

| Directory | Responsibility |
| --- | --- |
| `frontend/` | React/TypeScript interface, model editor, charts and replay. |
| `backend/` | FastAPI, analysis jobs, private sessions and DuckDB/Parquet persistence. |
| `services/` | Shared analysis orchestration. |
| `process_model/` | Log/model import, alignment, replay, zone validation and features. |
| `analytics/` | Metrics, trends, changes, dependencies and prediction. |
| `data/` | Synthetic demo and example scenarios. |
| `tests/`, `tools/` | Regression checks, parity, data generation and maintenance tools. |

`app.py` retains the legacy Streamlit reference used by numerical parity checks.
To run that interface, install `requirements-test.txt`, then use
`python -m streamlit run app.py`.

Replay uses per-place time indexes. Model graphs and deterministic analysis views
are cached, while charts load on demand. Alignment/replay artifacts can be reused
when zones or time windows change. For semantics, cache identities and resource
configuration, see [replay semantics](process_model/REPLAY_SEMANTICS.md).

Further references: [metric semantics](docs/metric-semantics.md),
[trends](docs/trends.md), [flow patterns](docs/flow-patterns-reference.md),
[retrospective prediction](docs/retrospective-prediction.md), and the
[restricted prospective research API](docs/forecasting-protocol.md).

## Citation

A paper is being prepared for the ICPM 2027 Demo and Resources Track, Category A.
The manuscript is maintained separately from the application repository.
Publication details and a citation will be added when available.

## License

Application-authored code is licensed under MIT; see [LICENSE](LICENSE).
Dependencies retain their own licenses. PM4Py is used for log and model operations
with either alignment engine and declares AGPL-3.0-or-later. See the
[dependency and redistribution notes](docs/dependency-review.md) and
[frontend notices](THIRD_PARTY_NOTICES.txt) for the distributed stack.
