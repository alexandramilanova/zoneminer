# Incident management: what follows a queued status?

## Question and zones

The [BPI 2013 incidents log](https://doi.org/10.4121/uuid:500573e6-accc-4b0c-9576-aa5468b10cee) describes IT service tickets. A [published BPI 2013 analysis](https://ceur-ws.org/Vol-1052/paper3.pdf) discusses the transition between queued and accepted statuses in incident handling. We ask how often a queued event is followed by an accepted event and how long it takes until the next recorded event.

We replay the complete log: **7,554 cases and 65,533 events**. The fixed [Petri net](model.pnml) was discovered with the application's default Inductive Miner; it uses the log's `concept:name` status (`Accepted`, `Queued`, `Completed`, `Unmatched`), not the more detailed lifecycle/substatus. We chose [two disjoint, connected single-place zones](zones.json): `p_21` immediately after `Queued` and `p_8` immediately after `Accepted`. These are status checkpoints within this model; the other 15 of 17 places are unassigned. The model is permissive, with silent transitions and possible parallel paths, so these zones are not a domain-validated partition of the incident process.

## Findings

- The log has **11,544 queued events in 4,511 cases**. The next recorded event in the same case is `Accepted` for 10,729 of those events (92.9%), another `Queued` event for 777, and `Completed` for 38. For queued-to-accepted pairs, the median recorded interval is **43.4 minutes** and the 90th percentile is **2.40 days**. These are event-to-event times, not verified human handling times. See [all next-event counts and timings](results/next-events.csv).
- Timing is skewed: across all 11,544 queued events, the median to the next recorded event is **35.2 minutes**, but the 90th percentile is **2.29 days**. Of the queued events, 11,268 occurred in 2012, so these numbers principally describe that year's records. The [year breakdown](results/trigger-years.csv) makes this concentration visible.
- A replay-based duration would answer a different question. All 11,544 matched entries into `p_21` occur within one second of the queued event, but only **4,480 exits** fall within one second of the next recorded event. The model's median `p_21` stay is **0.77 days**, compared with 0.024 days between queued and the next event. Thus its occupancy cannot be presented as the observed waiting time to the next status without further model validation. Multiple occurrences are matched chronologically within case; ties and silent transitions can affect such matching. See [boundary checks](results/episode-summary.json) and [zone summaries](results/zone-summary.csv).

These findings are descriptive. A status is not necessarily the start of active work, and the differences in event and token intervals do not identify the cause of delays.

## Reproduction

Download the original [4TU XES gzip](https://data.4tu.nl/file/0fc5c579-e544-4fab-9143-fab1f5192432/aa51ffbb-25fd-4b5a-b0b8-9aba659b7e8c) and decompress it. The [shared script](../run_case_study.py) validates its hash, loads the supplied model and zones, replays all cases with Rust4PM, and regenerates only aggregate results. The exact log and model hashes are recorded in [provenance](results/provenance.json). See the [evaluation index](../README.md#reproducing-the-additional-case-studies) for Docker commands. [Weekly zone metrics](results/weekly-zone-metrics.csv) use UTC boundaries; duration percentiles are seconds for stays completed in the window.
