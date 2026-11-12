# Selected cross-zone flow associations

This report publishes **only rows with |r| > 0.65**, in either direction. The threshold is a presentation filter, not a criterion for a successful tool run or proof of a useful or causal relationship. Nine full public event logs completed the analysis pipeline (187,214 cases; 834,858 events). The published association rows meet the stated filter. Scan counts below disclose the selection scope, including logs without a selected row.

## Selection protocol

- Source: **daily case entries** (`case_enter`) in one zone. Target: **daily case exits** (`case_exit`) in a different zone.
- Search lags: **1–7 daily windows**. A positive lag compares source entries on one day with target exits that many days later.
- For each ordered pair of different zones, keep the lag with the largest absolute Pearson correlation, choosing the smaller lag on an exact tie. Require at least **8 paired daily windows** and nonconstant series.
- Publish the pair only when **|r| > 0.65**. Both positive and negative values are eligible. Below-threshold coefficients are not published.
- CSVs contain the signed coefficient, selected lag, number of paired windows, and the number of source/target windows with nonzero flow. Daily windows with zero activity remain part of the calculation; long quiet periods can affect correlation.
- Nominal p-values use the usual Pearson t approximation, multiplied by seven for the lag search and capped at one. Nominal Benjamini–Hochberg q-values cover **all valid ordered zone pairs within each log, before filtering**. These are provided as exploratory diagnostics; they do not adjust for serial dependence and are not the publication filter. The values do not establish causality or independent validation.

These scans use connected structural groups of at most five places, not domain-validated zone definitions. Source timestamps and activity labels were retained. Import orders events chronologically within a case, preserving file order for equal timestamps. Full logs were used without case or event sampling. Model discovery used the application's default Inductive Miner; replay used Rust4PM; measurements used daily windows.

## Published selection

| Public log | Cases | Events | Valid zone pairs scanned | Selected pairs | Export |
| --- | ---: | ---: | ---: | ---: | --- |
| [BPI 2020: Prepaid Travel Costs](https://doi.org/10.4121/uuid:5d2fe5e1-f91f-4a3b-ad9b-9e4126870165) | 2,099 | 18,246 | 182 | 26 | [CSV](prepaid/selected-correlations.csv) |
| [BPI 2020: Request for Payment](https://doi.org/10.4121/uuid:895b26fb-6f25-46eb-9e48-0dca26fcd030) | 6,886 | 36,796 | 64 | 21 | [CSV](payment/selected-correlations.csv) |
| [BPI 2020: Domestic Declarations](https://doi.org/10.4121/uuid:3f422315-ed9d-4882-891f-e180b5b4feb5) | 10,500 | 56,437 | 49 | 23 | [CSV](domestic/selected-correlations.csv) |
| [BPI 2020: International Declarations](https://doi.org/10.4121/uuid:2bbf8f6a-fc50-48eb-aa9e-c4ea5ef7e8c5) | 6,449 | 72,151 | 529 | 226 | [CSV](international/selected-correlations.csv) |
| [Sepsis Cases](https://doi.org/10.4121/uuid:915d2bfb-7e84-49ad-a286-dc35f063a460) | 1,050 | 15,214 | 121 | 0 | No selected rows |
| [Road Traffic Fines](https://doi.org/10.4121/uuid:270fd440-1057-4fb9-89a9-b699b47990f5) | 150,370 | 561,470 | 49 | 2 | [CSV](traffic-fines/selected-correlations.csv) |
| [BPI 2013: Closed Problems](https://doi.org/10.4121/uuid:c2c3b154-ab26-4b31-a0e8-8f2350ddac11) | 1,487 | 6,660 | 20 | 3 | [CSV](bpic13closed/selected-correlations.csv) |
| [BPI 2013: Open Problems](https://doi.org/10.4121/uuid:3537c19d-6c64-4b1d-815d-915ab0e479da) | 819 | 2,351 | 16 | 7 | [CSV](bpic13open/selected-correlations.csv) |
| [BPI 2013: Incidents](https://doi.org/10.4121/uuid:500573e6-accc-4b0c-9576-aa5468b10cee) | 7,554 | 65,533 | 16 | 16 | [CSV](bpic13incidents/selected-correlations.csv) |

The selection contains **324 associations from 1,046 valid ordered zone pairs**. These are multiple descriptive views of the logs, not 324 independent discoveries. Structurally related zones can share flow patterns. The same source–target pair is represented once at its chosen lag.

## Reproduce and inspect

`correlation-summary.json` records counts and selection parameters for every scanned log. Each published log directory contains the exact place grouping (`zones.json`), input hash and source DOI (`provenance.json`), and only the selected association rows (`selected-correlations.csv`). Original logs, below-threshold correlations, and raw feature tables are not redistributed here.

Use application commit `23da351195144e1a30c3deb30d455ef09926c7a1`, with PM4Py 2.7.23.11 and the dependencies from that checkout. The experiments used Linux aarch64 in `zoneminer-submission-ready:local` (image `sha256:cc2e9a115e3e62be4d7d89c865f4de8db0154b0a75c6bc1b21da36ed2d39ef0e`).

1. Download the original publisher XES files from the DOI links and decompress them. Confirm the SHA-256 recorded in the corresponding provenance file. The published script uses short filenames such as `international.xes` and `bpic13incidents.xes`.
2. In the application Docker runtime, mount the application checkout read-only at `/app`, logs at `/logs`, and a writable copy of this report directory at `/results`.
3. Run `python /results/run_public_logs.py /logs/NAME.xes` for each input to regenerate the complete local zone-feature tables. Use `OMP_NUM_THREADS=1` and `OPENBLAS_NUM_THREADS=1`. No persisted replay cache is used by this script. Record environment and model identities; discovery/library versions may change generated place names.
4. Run `python /results/select_correlations.py` to regenerate the selected CSVs and counts. It reads the supplied `correlation-summary.json` as its input manifest when `results.json` is absent, and verifies up to five selected examples per log against the unchanged application's `lagged_best_corr` function.

The complete local measurements were retained for the paper's verification. This curated online selection is explicitly filtered and should not be interpreted as the full distribution of association strengths or a comparison of tool performance across datasets.
