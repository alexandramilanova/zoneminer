# Browser regression tests

`model-views-downloads.spec.ts` checks example placement, unavailable-helper
explanations, direct BPMN rendering, and actual CSV/PNG/SVG downloads. CSV
checks cover units, precision, quoting, and spreadsheet-formula protection.

Use an isolated test API: these tests upload a small fixture and run analyses.
Do not point them at a production service or a personal persistent data store.

For a local API on port 8000 (with `ZONE_ANALYTICS_DATA_DIR` set to a temporary
folder), run from `frontend/`:

```sh
npm ci
npx playwright install chromium firefox webkit
npm run test:e2e
```

The default suite now uses Chromium, Firefox and WebKit. Install all three with
`npx playwright install chromium firefox webkit`. A Chrome executable override
applies only to the Chromium project. Use `--project=chromium` for a targeted run.
WebKit coverage is not a substitute for a final check in branded Safari.

The separate anonymous suite uses its own isolated API configured for anonymous
mode, with HTTP-only localhost cookie support enabled for that test server:
`E2E_BASE_URL=http://127.0.0.1:17883 npx playwright test --config anonymous.playwright.config.ts`.
It exercises real uploads, analysis, cross-visitor isolation and deletion in all
three engines. The full local suite intentionally shares fixtures across test
contexts and should not target anonymous mode.

Playwright starts Vite automatically. To test the built application served by a
Docker container instead, set `E2E_BASE_URL=http://127.0.0.1:7860`.
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` optionally selects an installed Chrome
executable instead of Playwright's downloaded Chromium.

The suite uses real API validation and analysis, plus temporary DOM overlays to
exercise CSS panels, native dialogs, nested dialogs, and native popovers. It
checks viewport bounds, hit testing, keyboard focus, preserved invalid drafts,
and stale asynchronous validation. Analytical baseline files are not changed.

`changepoints.spec.ts` uses deterministic API-response fixtures to check marker
geometry, shared timestamps, hover details, contribution percentages/units, and
stale/error responses. Its separate real-showcase test compares rendered
markers and tables against actual API results at strictness 50, 75, and 100,
and saves local/aggregate screenshots in its Playwright output directory.
These are visualization tests, not independent validation of PELT's statistics.

`metrics.spec.ts` checks the structured reference against actual hourly and daily
API analyses, including counts, seconds, fractional ratios, global and local
conformance, missing values, search, scope filters, mobile access and errors.
It compares raw API duration series with Plotly's plotted values (no scaling)
and checks units in axes, hover, heatmap and table. Compact duration formatting
is tested separately, so canonical seconds cannot accidentally be converted twice.

The configurable Trends workflow uses typed exact zone–metric pairs via
`POST /analyses/{id}/trends/selection`. Change-point browser tests cover multiple
independent plots, all four local/overall switch combinations, mixed-unit small
multiples, optional observation markers, failures and late responses, as well as
positive contribution percentages attached to independently selected boundaries.
Real-showcase screenshots include local-only, overall-only, both, multiple plots
and contributions. Independent arithmetic and segmentation tests live in
`tests/test_trend_selection.py`; legacy GET API/parity behavior is preserved.

`prediction.spec.ts` tests the retrospective screen: all 43 metric
identifiers, fewer controls, explicit retrospective interpretation, fixed
horizon, all three real classifiers, class counts, tree, SHAP, baseline verdicts,
one-class errors, stale responses, and unchanged descriptive features. A
separate actual-showcase experiment checks UI/API agreement and saves a
screenshot without adjusting its fixed threshold/horizon for a better score.
The deterministic workflow fixture is software evidence, not a benchmark.

`calibration.spec.ts` retains API integration coverage for the earlier restricted
prospective research path. Its model/zone setup is no longer exposed in the
Prediction screen. Independent retrospective scientific and API tests are in
`tests/test_retrospective_prediction.py`; prospective tests remain separate.
