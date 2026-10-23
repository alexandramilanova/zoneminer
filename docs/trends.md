# Configurable trends and change points

## Scientific rules and intentional differences

The calculation and API contracts are documented below.

PELT squared-error (`l2`) cost, minimum segment size (3), minimum valid history
(8 windows), and the existing strictness-to-penalty search remain unchanged.
Strictness selects an approximate count based on zero-penalty candidates; integer
rounding means even a simple one-step signal may have no boundary at 50. Marker
locations need not be nested across strictness values.

The new workflow deliberately fixes two aggregation and contribution inconsistencies:

1. Constant components are excluded from the overall mean. Legacy aggregation
   included their standardized zeros. Insufficient/nonfinite observations are
   reported explicitly. The exact-pair selection has to retain at least two
   usable components, potentially from the same zone.
2. Contributions use the full adjacent detected segments, not the legacy default
   three-window flanks. For each standardized component, the absolute difference
   of segment means is divided by the sum of differences. Zero total difference
   returns no measured contributions. Components with no observations on either
   side are omitted and reported, never assigned invented values.

All detected boundaries are retained in the new workflow, so adjacent segments
are defined by the complete detected segmentation. Legacy endpoints can still
limit output to their old three-event defaults and retain their flank behavior.
New results may therefore differ intentionally from legacy contribution views;
no regression baseline is changed to accommodate that difference.

Aggregation preserves the established available-component mean at missing
windows, without interpolation. Coverage per window is exposed in the overall
signal table. Aggregate standardization uses population SD; display normalization
retains the existing sample-SD convention and never changes detection input.
These are retrospective calculations over reconstructed metrics, not online
forecasts, causal explanations, or independently observed token histories.

## API and module boundaries

`POST /api/analyses/{analysis_id}/trends/selection` takes:

```json
{
  "pairs": [
    {"zone": "Payment & Risk", "metric": "token_present_end"},
    {"zone": "Quality", "metric": "token_avg_age_open"}
  ],
  "normalize": false,
  "local_enabled": true,
  "overall_enabled": true,
  "cp_strictness": 50
}
```

Pairs are validated as exact typed identities; duplicates and invalid names are
rejected. Tuple identities handle zone names containing commas or `__`. Empty
selection is an explicit empty result. Legacy GET APIs remain unchanged.

The response returns exact-pair trend rows, per-series eligibility/local status,
local boundaries, and an overall result with status, usable component count,
aggregate signal/coverage, boundaries, contributions, segment intervals and
contribution coverage. Disabled detection makes no PELT calls. Failures are errors,
not successful empty detections.

`analytics/trend_selection.py` implements the workflow by reusing existing PELT
and standardization helpers. Services expose it; FastAPI validates and serializes
it. No changes were needed in `analytics/changepoints.py` or `analytics/trends.py`.

## Interface and preserved functionality

One default plot shows token presence across all zones. Add Plot creates an
independent empty plot. Each plot has a stable ID, editable title, explicit pair
selection/removal, independent normalization and observation markers, independent
local/overall switches and its own strictness/loading/error state. Duplicate
pairs cannot be added. Analysis changes reset plots and discard stale replies.

Mixed raw units use separate panels. Normalization allows a shared z-score axis.
Legends and hover identify zone and metric; colors retain zone identity, and
local diamonds match their series. All series use solid lines. Only overall
boundaries draw solid vertical lines, once per timestamp per panel. Tables identify every active
local or overall boundary, including coincident events.

The overall signal is inspectable separately with standardized units and coverage.
Top Contributions shows only positive percentages, descending, for the selected
boundary (up to ten bars); all measured components and their segment periods are
available in its table. Turning overall detection off hides contributions.

Per-plot metric heatmaps and supported completed-case-duration confidence
intervals remain available. The Series data section and clean-series index labels
were removed on request. Each plot can minimize its controls and supplementary
results, leaving its title and visualization visible without changing settings.
Drift explanations document the adjacent window groups, score interpretation,
missing values, and whole-history preprocessing. Whole-analysis drift scores and period
comparison remain separate. The React tab previously had no Basic/Advanced mode;
no new mode framework is introduced, and catalog metrics remain available with
readable names, descriptions and units. Global conformance selections explicitly
warn that choosing the repeated metric for several zones repeats its weight.

## Remaining scope boundaries

Plot configuration is page-local and resets on reload or analysis change.
Missing windows can change aggregate membership; their coverage is inspectable.
Opposite component movements can cancel in the mean, yielding no overall shift;
local analysis remains available. Global conformance repeats across zone rows.
P-values or causal change scores are not invented for PELT boundaries.

