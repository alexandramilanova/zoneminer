# Prepaid travel costs: permit administration and approval

## Question and zones

The [BPI 2020 Prepaid Travel Costs log](https://doi.org/10.4121/uuid:5d2fe5e1-f91f-4a3b-ad9b-9e4126870165) concerns requests for reimbursement before a trip. The [challenge organizers](https://www.tf-pm.org/competitions-awards/bpi-challenge/2020) describe submission and administrative approval, followed by further approvals. We ask what is recorded immediately after a permit submission and whether the zone duration reflects that recorded interval.

We replay the complete log: **2,099 cases and 18,246 events**. In the fixed [discovered Petri net](model.pnml), the [Permit administration zone](zones.json), `p_23`, is directly after `Permit SUBMITTED by EMPLOYEE` and before possible administrative approval or rejection, with a silent bypass. The Payment approval zone, `p_54`, is between budget-owner/pre-approver and supervisor approval transitions, also with a silent bypass. These single-place zones are connected and disjoint; 56 of 58 model places remain unassigned. They are targeted checkpoints, not a complete or domain-validated partition.

## Findings

- There are **1,952 permit submissions in 1,859 cases**. The next recorded event is `Permit APPROVED by ADMINISTRATION` after **1,603 submissions (82.1%)**; other next events include pre-approver and supervisor decisions. For those 1,603 submission-to-administration-approval pairs, the median recorded interval is **5 seconds** and the 90th percentile is **130 seconds**. For all submissions, the median to the next recorded event is also **5 seconds**, and the 90th percentile is **136 seconds**. See [the complete next-event breakdown](results/next-events.csv).
- This short interval is present in both main years: the all-submission median is **6 seconds in 2017** (334 submissions) and **5 seconds in 2018** (1,618 submissions). The organizers explain that 2017 was a two-department pilot while 2018 covered the full institution; these cohorts are not a controlled comparison. The [year breakdown](results/trigger-years.csv) reports the full distributions.
- The permit-administration zone has a **4-second median** stay and a **75-second 90th percentile**. Its 1,952 entries match the corresponding permit submissions within one second; 1,641 of its exits match the next recorded event within one second. Silent bypasses explain why a zone exit need not be that next event. Consequently, neither the event interval nor the token stay demonstrates that a person actually reviewed the permit in seconds; automated steps and recording conventions are possible explanations, not established causes. See [boundary checks](results/episode-summary.json) and [zone summaries](results/zone-summary.csv).

The Payment approval zone's distribution is also provided, but the two zones cover different case populations and boundaries; their durations should not be interpreted as a controlled comparison of staff performance.

## Reproduction

Download the original [4TU XES gzip](https://data.4tu.nl/file/fb84cf2d-166f-4de2-87be-62ee317077e5/612068f6-14d0-4a82-b118-1b51db52e73a) and decompress it. The [shared script](../run_case_study.py) validates its hash, loads the supplied model and zones, replays all cases with Rust4PM, and regenerates only aggregate results. The exact log and model hashes are recorded in [provenance](results/provenance.json). See the [evaluation index](../README.md#reproducing-the-additional-case-studies) for Docker commands. [Weekly zone metrics](results/weekly-zone-metrics.csv) use UTC boundaries; duration percentiles are seconds for stays completed in the window.
