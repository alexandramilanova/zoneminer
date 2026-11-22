"""Replay a public-log case study and compare its zone and event timings."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pandas as pd
from process_model.zone_validation import validate_zones
from services.pipeline import load_model_inputs, compute_alignment_tables, build_zone_analysis

HERE = Path(__file__).resolve().parent
CASES = {
    'incidents': {
        'hash': '240a370cfca2a8b5def0ef722672f469c01812a554f000e602bc9a5bcbc2314e',
        'doi': '10.4121/uuid:500573e6-accc-4b0c-9576-aa5468b10cee',
        'trigger': 'Queued', 'zone': 'After queued',
    },
    'prepaid': {
        'hash': 'fa88510a5b55ed329ebb014370dd6631db7f93b1b01cc378cc2f95296ea5ea9c',
        'doi': '10.4121/uuid:5d2fe5e1-f91f-4a3b-ad9b-9e4126870165',
        'trigger': 'Permit SUBMITTED by EMPLOYEE', 'zone': 'Permit administration',
    },
    'sepsis': {
        'hash': 'b501d2063678b9471e3cb1be04d961f924ae5be6ecc8154701bb57a24c7ae0ab',
        'doi': '10.4121/uuid:915d2bfb-7e84-49ad-a286-dc35f063a460',
        'trigger': 'ER Sepsis Triage', 'zone': 'After sepsis triage', 'target': 'IV Antibiotics',
    },
    'loan2012': {
        'hash': 'd13660dedf2269e32dfb7ec2228d7cb3c9665e0a4c54edf7bd18f1fad6f12232',
        'doi': '10.4121/uuid:3926db30-f712-4394-aebc-75976070e91f',
        'trigger': 'O_CREATED', 'zone': 'Offer preparation', 'target': 'O_SENT',
    },
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def distribution(values: pd.Series) -> dict:
    values = values.dropna()
    return {'count': int(len(values)), 'median_days': float(values.median()) if len(values) else None,
            'p90_days': float(values.quantile(.9)) if len(values) else None}


def main(study: str, log_path: Path, output: Path) -> None:
    config = CASES[study]
    directory = HERE / f'{study}-case'
    raw, model = log_path.read_bytes(), (directory / 'model.pnml').read_bytes()
    if digest(raw) != config['hash']:
        raise ValueError('The decompressed XES does not match the published input hash')
    zones = json.loads((directory / 'zones.json').read_text())
    bundle = load_model_inputs(raw, '.xes', model)
    validation = validate_zones(list(zones.items()), sorted(p.name for p in bundle.net.places), bundle.net)
    if not validation['zone_config_valid']:
        raise ValueError(f"Invalid zones: {validation['errors']}")
    tokens, conformance, moves = compute_alignment_tables(bundle.log, bundle.net, bundle.im, bundle.fm, backend='r4pm')
    analysis = build_zone_analysis(tokens, conformance, zones, '7D', net=bundle.net,
                                   im=bundle.im, fm=bundle.fm, alignment_moves_df=moves)
    stays = analysis['case_zone_stays']

    # Each trigger is paired with the next recorded event in its case. The
    # case/occurrence pair is used only locally to validate replay boundaries;
    # no case identifiers or individual event records are exported.
    episodes = []
    for trace in bundle.log:
        case_id = str(trace.attributes['concept:name'])
        ordinal = 0
        for index, event in enumerate(trace):
            if event['concept:name'] != config['trigger']:
                continue
            ordinal += 1
            next_event = trace[index + 1] if index + 1 < len(trace) else None
            target_event = None
            if config.get('target'):
                for following in trace[index + 1:]:
                    if following['concept:name'] == config['trigger']:
                        break
                    if following['concept:name'] == config['target']:
                        target_event = following
                        break
            episodes.append({'case_id': case_id, 'ordinal': ordinal,
                             'trigger': pd.Timestamp(event['time:timestamp']),
                             'next_label': next_event['concept:name'] if next_event else None,
                             'next_time': pd.Timestamp(next_event['time:timestamp']) if next_event else pd.NaT,
                             'target_time': pd.Timestamp(target_event['time:timestamp']) if target_event else pd.NaT})
    frame = pd.DataFrame(episodes)
    frame['next_days'] = (frame.next_time - frame.trigger).dt.total_seconds() / 86400
    frame['target_time'] = pd.to_datetime(frame.target_time, utc=True)
    frame['target_days'] = (frame.target_time - frame.trigger).dt.total_seconds() / 86400
    if study == 'loan2012':
        per_case = frame.groupby('case_id').size().value_counts().sort_index()
        counts = [{'offers_created': 0, 'cases': len(bundle.log) - frame.case_id.nunique()}]
        counts.extend({'offers_created': int(offers), 'cases': int(number)} for offers, number in per_case.items())
    selected = stays[(stays.zone == config['zone']) & ~stays.is_open].sort_values(['case_id', 'entry_ts', 'exit_ts']).copy()
    selected['ordinal'] = selected.groupby('case_id').cumcount() + 1
    joined = frame.merge(selected, on=['case_id', 'ordinal'], how='inner')
    start_delta = (joined.entry_ts - joined.trigger).dt.total_seconds().abs()
    end_delta = (joined.exit_ts - joined.next_time).dt.total_seconds().abs()

    output.mkdir(parents=True, exist_ok=True)
    if study == 'loan2012':
        pd.DataFrame(counts).to_csv(output / 'offer-counts.csv', index=False)
    zone_rows = []
    for name, group in stays.groupby('zone'):
        row = {'zone': name, 'stays': int(len(group)), 'cases': int(group.case_id.nunique()),
               'open_stays': int(group.is_open.sum())}
        row.update(distribution(group.duration.dt.total_seconds() / 86400))
        zone_rows.append(row)
    pd.DataFrame(zone_rows).to_csv(output / 'zone-summary.csv', index=False, float_format='%.9f')
    summary = {'trigger': config['trigger'], 'trigger_events': len(frame),
               'trigger_cases': int(frame.case_id.nunique()), **distribution(frame.next_days),
               'matched_occurrences': len(joined), 'entry_within_1_second': int((start_delta < 1).sum()),
               'exit_within_1_second_of_next_event': int((end_delta < 1).sum())}
    (output / 'episode-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    if config.get('target'):
        paired = frame[frame.target_time.notna()]
        joined_target = joined[joined.target_time.notna()]
        target_end_delta = (joined_target.exit_ts - joined_target.target_time).dt.total_seconds().abs()
        target_summary = {'trigger': config['trigger'], 'target': config['target'],
                          'trigger_events': len(frame), 'paired_events': len(paired),
                          'paired_cases': int(paired.case_id.nunique()),
                          **distribution(paired.target_days),
                          'matched_occurrences': len(joined_target),
                          'exit_within_1_second_of_target': int((target_end_delta < 1).sum())}
        (output / 'target-summary.json').write_text(json.dumps(target_summary, indent=2) + '\n')
    next_rows = []
    for label, group in frame.groupby('next_label', dropna=False):
        row = {'next_event': label, 'trigger_events': len(group)}
        row.update(distribution(group.next_days))
        next_rows.append(row)
    pd.DataFrame(next_rows).sort_values('trigger_events', ascending=False).to_csv(output / 'next-events.csv', index=False, float_format='%.9f')
    if study != 'sepsis':
        year_rows = []
        for year, group in frame.groupby(frame.trigger.dt.year):
            row = {'trigger_year': int(year), 'trigger_events': len(group)}
            row.update(distribution(group.next_days))
            year_rows.append(row)
        pd.DataFrame(year_rows).to_csv(output / 'trigger-years.csv', index=False, float_format='%.9f')
    if study != 'sepsis':
        features = analysis['zone_features']
        features[['zone', 'window_start', 'window_end', 'case_enter', 'case_exit', 'case_present_end',
                  'case_duration_p50', 'case_duration_p90']].to_csv(output / 'weekly-zone-metrics.csv', index=False)
    provenance = {'source_doi': config['doi'], 'log_sha256': digest(raw), 'model_sha256': digest(model),
                  'cases': len(bundle.log), 'events': sum(len(trace) for trace in bundle.log),
                  'token_intervals': len(tokens), 'alignment_cases': len(conformance),
                  'alignment_backend': 'r4pm', 'timeframe': '7D',
                  'unassigned_places': len(validation['unassigned_places'])}
    (output / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(json.dumps(provenance, indent=2))
    print(json.dumps(summary, indent=2))
    print(pd.DataFrame(zone_rows).to_string(index=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('study', choices=CASES)
    parser.add_argument('log', type=Path, help='decompressed publisher XES')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.study, args.log, args.output)
