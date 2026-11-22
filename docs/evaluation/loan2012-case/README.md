# Loan applications: offer creation and sending

## Question and zones

The [BPI 2012 event log](https://doi.org/10.4121/uuid:3926db30-f712-4394-aebc-75976070e91f) records a loan application process. [Published analysis of the log](https://pmc.ncbi.nlm.nih.gov/articles/PMC6312323/) describes offers sent to eligible applicants, while [Schuster et al.](https://www.vldb.org/pvldb/vol16/p2666-schuster.pdf) illustrate creation and sending of a new offer within a case. We ask how many applications contain repeated offer-creation events and what the log records between creation and sending.

We replay the complete log: **13,087 cases and 262,200 events**. In the fixed [discovered Petri net](model.pnml), the [Application intake zone](zones.json), `p_4`, lies directly between `A_SUBMITTED` and `A_PARTLYSUBMITTED`; the **Offer preparation zone**, `p_28`, lies directly between `O_CREATED` and `O_SENT`. Both are connected, disjoint single-place zones. The other 52 of 54 places are unassigned. The log includes application, offer and work-item events; discovery here uses `concept:name` and does not distinguish work-item lifecycle states. These checkpoints do not constitute a complete or domain-validated process partition.

## Findings

- The log contains **7,030 offer-creation events in 5,015 applications**. Of those 5,015 applications, **1,438 (28.7%)** contain two or more recorded offer creations; 8,072 applications contain none. This is a count of recorded events, not evidence that an application failed or that an offer was unnecessary. The full [per-application offer-count distribution](results/offer-counts.csv) includes zero-offer cases.
- Every one of the **7,030 `O_CREATED` events** is immediately followed by `O_SENT` in its case. The median recorded interval is **35 milliseconds** and the 90th percentile is **79 milliseconds**. This near-immediate status change may reflect automated processing or logging conventions; it cannot be used to infer the time staff spent preparing an offer. See [next events](results/next-events.csv) and the [target-event summary](results/target-summary.json).
- The corresponding offer-zone entries and exits match the recorded creation and sending events within one second for all 7,030 occurrences. Because `p_28` has a direct visible transition at each boundary, its median stay corresponds to the recorded creation-to-sending interval in this model. The [zone summary](results/zone-summary.csv) also reports the application-intake checkpoint; these very short model intervals must not be equated with end-to-end loan handling.

These descriptive measurements concern the recorded process and discovered model. They do not establish why multiple offers were created, determine business outcomes, or validate model behavior with the financial institution.

## Reproduction

Download the original [4TU XES gzip](https://data.4tu.nl/file/533f66a4-8911-4ac7-8612-1235d65d1f37/3276db7f-8bee-4f2b-88ee-92dbffb5a893) and decompress it. The [shared script](../run_case_study.py) validates the input hash, loads the supplied model and zones, replays all cases with Rust4PM, and writes only aggregate results. The exact log and model hashes are recorded in [provenance](results/provenance.json). See the [evaluation index](../README.md#reproducing-the-additional-case-studies) for Docker commands; use the study name `loan2012`. [Weekly zone metrics](results/weekly-zone-metrics.csv) use UTC boundaries; duration percentiles are seconds for stays completed in the window.
