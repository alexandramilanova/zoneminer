# Sepsis cases: triage and recorded antibiotic events

## Question and zones

The [Sepsis Cases event log](https://doi.org/10.4121/uuid:915d2bfb-7e84-49ad-a286-dc35f063a460) contains 1,050 hospital cases and 15,214 events. [Mannhardt and Blinde's analysis](https://pure.tue.nl/ws/portalfiles/portal/68704626/bpmds_08_paper.pdf) describes triage, antibiotic administration and laboratory tests as distinct parts of the pathway and examines their timing. We ask what the log records between sepsis triage and a subsequent antibiotic event, and whether replayed zone boundaries match the recorded events.

We replay the complete log using the fixed [discovered model](model.pnml) and [two disjoint single-place zones](zones.json). `p_40` is directly after `ER Sepsis Triage`, with outgoing transitions to `IV Antibiotics` or a silent bypass; `p_32` directly precedes `LacticAcid`. Both zones are connected, while the other 37 of 39 model places are unassigned. This is an automatically discovered model, not the domain-expert model in the cited paper, nor a validated clinical workflow.

The dataset's absolute timestamps were randomized for anonymization, but within-case intervals were retained ([dataset description](https://bupaverse.github.io/eventdataR/reference/sepsis.html)). Therefore this study reports **within-case intervals only**; calendar trends and cross-case occupancy over time would not be meaningful. We do not publish year or weekly summaries for this log.

## Findings

- Of the **1,049 recorded sepsis-triage events**, **823** have a later recorded `IV Antibiotics` event before any next sepsis-triage event in the same case. Among these 823 paired cases, the median recorded interval is **1.53 hours** and the 90th percentile is **3.94 hours**. The remaining 226 triage events have no qualifying later antibiotic event in the available trace; this does not establish that antibiotics were not administered. The [target summary](results/target-summary.json) gives the denominator and pairing rule.
- All 1,049 triage-zone entries match the recorded triage event within one second. For all **823 paired cases**, the corresponding `p_40` exit also matches the antibiotic event within one second. Other events often intervene: antibiotics are the immediate next event after only 76 triage events. The [next-event breakdown](results/next-events.csv) and [boundary checks](results/episode-summary.json) show why the next logged event is not necessarily the end of the triage-to-antibiotic interval.
- The triage zone has a silent bypass, so its aggregate [zone-stay distribution](results/zone-summary.csv) also includes cases without a qualifying later recorded antibiotic event. It must not be interpreted as treatment timing for all 1,049 cases.

These are historical, descriptive event-log measurements, not an assessment of clinical quality, compliance, treatment appropriateness or current medical guidance. Recorded events may be incomplete, and the automatically discovered model has not been validated by clinicians.

## Reproduction

Download the original [4TU XES gzip](https://data.4tu.nl/file/33632f3c-5c48-40cf-8d8f-2db57f5a6ce7/643dccf2-985a-459e-835c-a82bce1c0339) and decompress it. The [shared script](../run_case_study.py) validates the input hash, loads the supplied model and zones, replays all cases with Rust4PM, and writes only aggregate results. The exact log and model hashes are recorded in [provenance](results/provenance.json). See the [evaluation index](../README.md#reproducing-the-additional-case-studies) for Docker commands; use the study name `sepsis`.
