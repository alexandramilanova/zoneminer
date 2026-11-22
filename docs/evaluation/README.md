# Public-log case studies

The evaluation uses five complete public logs and targeted, process-informed
zones. Each case study contains its fixed model, zone definitions, aggregate
measurements, event-level checks and limitations:

- [International travel reimbursements](#international-travel-reimbursements):
  payment timing and the interpretation of a parallel model branch.
- [Prepaid travel costs](prepaid-case/README.md): permit submission and the
  next administrative event.
- [IT incidents](incidents-case/README.md): queued statuses and the following
  recorded event.
- [Sepsis cases](sepsis-case/README.md): within-case intervals from sepsis triage
  to a recorded antibiotic event.
- [Loan applications](loan2012-case/README.md): repeated offers and the interval
  between their recorded creation and sending.

## International travel reimbursements

How are payments handled after a travel declaration has been approved, and what
can a model-based token duration tell us about that stage? We study the complete
[BPI 2020 International Declarations log](https://doi.org/10.4121/uuid:2bbf8f6a-fc50-48eb-aa9e-c4ea5ef7e8c5): 6,449 cases and 72,151 events, with no case or event sampling. The
[challenge organizers' process description](https://www.tf-pm.org/competitions-awards/bpi-challenge/2020)
explains that payment is requested and made after approval, and explicitly asks
about throughput of the individual process steps. This motivates the two
payment-related zones and the event-level checks below.

### Zone definitions

We use the fixed [discovered Petri net](international-case/model.pnml) and the
[zone configuration](international-case/zones.json). The **Payment request
branch** consists of place `p_118`, which directly precedes `Request Payment`;
the **Payment handled branch** consists of place `p_120`, which directly
precedes `Payment Handled`. Both are single-place, connected, disjoint zones.
They are deliberately narrow process checkpoints: 91 of the model's 93 places
are unassigned, so the zones do not partition the entire reimbursement process.
The model also permits silent bypasses and parallel behavior. A token in a
place is a model-based state, not proof that a person is actively working or
that the corresponding recorded event will necessarily occur. For the broader
token-flow perspective, see [van der Aalst et al., *Visualizing Token Flows
Using Interactive Performance Spectra*](https://pmc.ncbi.nlm.nih.gov/articles/PMC7324234/).

The zone choice follows the organizers' description and the named transitions
in this specific discovered model. It is **not** claimed to reproduce Bittu
Chauhan's thesis split or to be domain-expert validation. Place identifiers are
model-specific; the supplied PNML is necessary to interpret or reproduce them.

### Findings

1. **Payment handling is strongly concentrated on two weekdays.** Of the 6,187
   recorded `Payment Handled` events, 2,656 occurred on Monday and 3,484 on
   Thursday: 6,140 (99.2%) combined. The pattern holds in both major years:
   1,262 of 1,263 events in 2017 and 4,719 of 4,764 in 2018. Event times are recorded in UTC; these
   events fall well away from midnight. This is consistent with a scheduled
   processing rhythm, but the log alone cannot establish the operational cause.
   The full [year-by-weekday counts](international-case/results/handled-weekdays.csv)
   and [minute-of-day counts](international-case/results/handled-minutes-utc.csv)
   make the pattern inspectable.
2. **Recorded payment turnaround is around three days for the paired cases.**
   Among 6,183 cases with both event types and a completed handled-branch stay,
   the median from the first `Request Payment` to the first `Payment Handled`
   event is 3.22 calendar days; the 90th percentile is 4.91 days. The medians
   are 3.17 days for 1,279 requests in 2017 and 3.23 days for 4,799 in 2018.
   This is a descriptive comparison, not a causal estimate or a claim that all
   cases followed the same process. Three paired cases have a handled event
   before their first request; they are retained in the summary. The organizers
   note that 2017 was a pilot covering only two departments, while 2018 covered
   the full institution, so these cohorts are not directly comparable as a
   controlled before-and-after experiment.
3. **The model-based duration measures a broader interval.** For the same
   paired cases, the handled-branch median stay is 5.34 days, and the median
   entry precedes the recorded request by 1.18 days. Only 114 entries are within
   one second of the request; all 6,183 exits match `Payment Handled` within
   one second. This discovered model enables the two payment branches in
   parallel, so interpreting the 5.34-day stay as the time *after* requesting
   payment would be misleading. This comparison illustrates why inspecting
   zone boundaries and events is essential when interpreting replayed tokens.

The [summary table](international-case/results/payment-summary.csv) gives the
paired sample sizes and year-level statistics. The
[weekly zone measurements](international-case/results/weekly-zone-metrics.csv)
show the underlying application output. Window boundaries are in UTC; case
duration percentiles are measured in seconds for stays completed in each
window. These results describe one historical
log and one discovered model; they do not validate operational usefulness with
process owners, establish causality, or measure interactive performance.

### Reproduce

The original event log is not redistributed. Download and decompress the
International Declarations XES from the [challenge page](https://www.tf-pm.org/competitions-awards/bpi-challenge/2020)
or its dataset DOI above. The script verifies the exact SHA-256 input hash in
[provenance](international-case/results/provenance.json), loads the supplied
PNML and zones, performs Rust4PM alignment and ZoneMiner replay on every case,
then produces the aggregate tables and checks against recorded events. It uses
7-day windows for the exported zone measurements; the case-level results use
individual timestamps rather than correlations or selected lags.

From a checkout with a built `zoneminer` Docker image, for example:

```sh
mkdir -p evaluation-output
# Replace /absolute/path/InternationalDeclarations.xes with the downloaded file.
docker run --rm -e OMP_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 \
  -v /absolute/path/InternationalDeclarations.xes:/input/log.xes:ro \
  -v "$(pwd)/evaluation-output:/output" zoneminer \
  python docs/evaluation/international-case/analyze.py /input/log.xes --output /output
```

The run used Linux ARM64, Python 3.12, PM4Py 2.7.23.11 and Rust4PM 0.6.0.post1,
with the repository's locked dependencies. The model was discovered using the
application's default Inductive Miner and is frozen here because rediscovery
may assign different place identifiers. The output directory must be writable by
the image's non-root user. The source log, case-level records and replay cache are
not included; only aggregate results are published.

## Reproducing the additional case studies

Download and decompress the publisher XES using the links in each study. Build
the application image from this checkout using `docker build -t zoneminer .`.
Use the appropriate study name (`incidents`, `prepaid`, `sepsis` or `loan2012`) and replace the log
path below with its absolute path. The output directory must be writable by the
image's non-root user. Use a separate output directory for each study so files
from different runs are not mixed:

```sh
mkdir -p evaluation-output/incidents
docker run --rm -e OMP_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 \
  -v /absolute/path/log.xes:/input/log.xes:ro \
  -v "$(pwd)/evaluation-output/incidents:/output" zoneminer \
  python docs/evaluation/run_case_study.py incidents /input/log.xes --output /output
```

The script checks the input SHA-256, validates the fixed zones, replays every
case, and writes only aggregate data. Like the first study, these runs used
Linux ARM64, Python 3.12, PM4Py 2.7.23.11 and Rust4PM 0.6.0.post1. Do not
rediscover the model when reproducing: generated place identifiers may change.
The Sepsis log has anonymized calendar timestamps, so its published results
exclude calendar-based and cross-case time-window comparisons. The larger loan
log requires substantially more memory and time than the smaller case studies.
