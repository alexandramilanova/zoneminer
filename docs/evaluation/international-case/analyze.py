"""Reproduce the BPI 2020 International payment case study.

Run from the repository root in the documented application environment. The
published XES log is supplied separately; no cases or events are sampled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import pandas as pd
from process_model.zone_validation import validate_zones
from services.pipeline import load_model_inputs, compute_alignment_tables, build_zone_analysis

HERE = Path(__file__).resolve().parent
EXPECTED_LOG = '381e793931dbe8c393e7504ec98d66172eb9ba89802d97652c054cd61036598e'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(log_path: Path, output: Path) -> None:
    raw = log_path.read_bytes()
    if digest(raw) != EXPECTED_LOG:
        raise ValueError('Input hash does not match the published International Declarations XES')
    model = (HERE / 'model.pnml').read_bytes()
    zones = json.loads((HERE / 'zones.json').read_text())
    bundle = load_model_inputs(raw, '.xes', model)
    checked = validate_zones(list(zones.items()), sorted(p.name for p in bundle.net.places), bundle.net)
    if not checked['zone_config_valid']:
        raise ValueError(f'Invalid zone configuration: {checked["errors"]}')
    tokens, conformance, moves = compute_alignment_tables(bundle.log, bundle.net, bundle.im, bundle.fm, backend='r4pm')
    analysis = build_zone_analysis(tokens, conformance, zones, '7D', net=bundle.net, im=bundle.im, fm=bundle.fm, alignment_moves_df=moves)
    stays = analysis['case_zone_stays']
    # Independently extract the first recorded request and handled events per
    # case. Only cases containing both and a replayed handled-branch stay enter
    # the paired comparison. All cases are retained in the replay above.
    records = []
    handled_events = []
    for trace in bundle.log:
        case = str(trace.attributes['concept:name'])
        times = {}
        for event in trace:
            label = event.get('concept:name')
            if label == 'Payment Handled':
                handled_events.append(pd.Timestamp(event['time:timestamp']))
            if label in ('Request Payment', 'Payment Handled') and label not in times:
                times[label] = pd.Timestamp(event['time:timestamp'])
        if len(times) == 2:
            records.append({'case_id': case, 'request': times['Request Payment'], 'handled': times['Payment Handled']})
    events = pd.DataFrame(records).set_index('case_id')
    handled = stays[(stays.zone == 'Payment handled branch') & ~stays.is_open].sort_values('entry_ts').drop_duplicates('case_id').set_index('case_id')
    joined = events.join(handled[['entry_ts', 'exit_ts']], how='inner')
    joined['recorded_days'] = (joined.handled - joined.request).dt.total_seconds() / 86400
    joined['zone_days'] = (joined.exit_ts - joined.entry_ts).dt.total_seconds() / 86400
    joined['entry_before_request_days'] = (joined.request - joined.entry_ts).dt.total_seconds() / 86400
    joined['exit_vs_handled_seconds'] = (joined.exit_ts - joined.handled).dt.total_seconds()
    rows = []
    groups = [('all', joined)] + [(str(year), joined[joined.request.dt.year == year]) for year in sorted(joined.request.dt.year.unique())]
    for label, frame in groups:
        rows.append({'request_year': label, 'paired_cases': len(frame),
                     'recorded_median_days': frame.recorded_days.median(),
                     'recorded_p90_days': frame.recorded_days.quantile(.9),
                     'zone_median_days': frame.zone_days.median(),
                     'entry_before_request_median_days': frame.entry_before_request_days.median(),
                     'entry_within_1_second_of_request': int((frame.entry_before_request_days.abs() * 86400 < 1).sum()),
                     'handled_exit_within_1_second': int((frame.exit_vs_handled_seconds.abs() < 1).sum()),
                     'handled_before_request': int((frame.recorded_days < 0).sum())})
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output / 'payment-summary.csv', index=False, float_format='%.9f')
    times = pd.to_datetime(pd.Series(handled_events), utc=True)
    calendar = pd.DataFrame({'year': times.dt.year, 'weekday': times.dt.day_name(),
                             'minute_utc': times.dt.strftime('%H:%M')})
    calendar.groupby(['year', 'weekday']).size().rename('handled_events').reset_index().to_csv(output / 'handled-weekdays.csv', index=False)
    calendar.groupby('minute_utc').size().rename('handled_events').reset_index().to_csv(output / 'handled-minutes-utc.csv', index=False)
    features = analysis['zone_features']
    features[['zone','window_start','window_end','case_enter','case_exit','case_present_end','case_duration_p50','case_duration_p90']].to_csv(output / 'weekly-zone-metrics.csv', index=False)
    info = {'source_doi': '10.4121/uuid:2bbf8f6a-fc50-48eb-aa9e-c4ea5ef7e8c5',
            'log_sha256': digest(raw), 'model_sha256': digest(model), 'cases': len(bundle.log),
            'events': sum(len(t) for t in bundle.log), 'token_intervals': len(tokens),
            'alignment_cases': len(conformance), 'alignment_backend': 'r4pm',
            'timeframe': '7D', 'unassigned_places': len(checked['unassigned_places']),
            'paired_cases': len(joined), 'zone_stays': stays.groupby('zone').size().to_dict()}
    (output / 'provenance.json').write_text(json.dumps(info, indent=2) + '\n')
    print(json.dumps(info, indent=2))
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.log, args.output)
