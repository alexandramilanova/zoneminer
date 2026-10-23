# Flow-pattern reference

This is a reference to implemented behavior, replacing the former feature plan.
Canonical definitions and units are maintained in `analytics/metrics/schema.py`
and exposed in the in-app metric reference. See [metric semantics](metric-semantics.md)
and [replay semantics](../process_model/REPLAY_SEMANTICS.md) for interpretation.
The labels below identify groups still mentioned in implementation comments.

| Label | Implemented behavior |
| --- | --- |
| A1 | FIFO inversions, overtaken share and overtake depth over completed case-zone stays. |
| A2 | Gap-clustered batching measures; whole-timeline detection is retrospective. |
| A3 | Queueing diagnostics from case-zone stays. |
| A4 | Inter-zone handover structure. |
| A5 | Revisits over distinct case-zone stays. |
| A6 | Duration tails and open-token aging measures. |
| A7 | Heuristic flowing, queueing, blocked and starving indications. |
| A8 | Zone-attributed conformance; weighted boundary attribution differs from raw move counts. |
| A9 | Multivariate drift using energy distance. |
| A10 | Descriptive open-case remaining-time estimates using conditional survival. |
| B1–B4 | Performance spectrum, cumulative flow, handover Sankey and ordering scatter. |
| B5–B6 | Metric heatmaps and replay case journeys/state overlays. |
| B7–B8 | Period comparison and the zone flow map. |
| C1–C2 | Experimental queue-model lens and calibrated capacity scenarios. |
| C3 | Upstream alert hints ranked by lagged association. |
| C5 | Duration confidence intervals and statistical guardrails. |

Token flow counts place-level productions/consumptions, including internal zone
movements. Case-level flow views use merged case-zone stays. Occupancy is not
resource utilization, and dependency/alert hints do not establish causation.
Capacity scenarios are experimental and refuse to run when calibration fails.
The current Prediction screen is retrospective; see
[its protocol](retrospective-prediction.md).

The performance-spectrum views build on Denisov, Fahland and van der Aalst,
*Unbiased, Fine-Grained Description of Processes Performance from Event Data*
(BPM 2018). The batching interpretation draws on Klijn and Fahland,
*Performance Mining for Batch Processing Using the Performance Spectrum*
(BPM 2019 Workshops). These references motivate the interpretation; the
canonical schema and implementation specify this application's exact metrics.
