"""Strict causal prefix replay, separate from retrospective complete alignment.

Forced silent routing is instantaneous under an explicit prediction-only
convention. No final marking is forced, no visible deviations are repaired,
and no competing branch is selected using later observations.
"""
from collections import defaultdict, deque

import pandas as pd

from process_model.semantics import validate_petri_net


class PrefixUnavailable(ValueError):
    pass


ROUTING_POLICY = 'forced-immediate-routing-v1'
MAX_SILENT_FIRINGS = 1000


def validate_prefix_model(net, im):
    validate_petri_net(net, im)
    if im is None:
        raise PrefixUnavailable('An explicit initial marking is required.')
    for transition in sorted(net.transitions, key=lambda t: t.name):
        if transition.label is not None:
            continue
        if not transition.in_arcs:
            raise PrefixUnavailable(f'Silent transition {transition.name!r} has no input places; immediate routing cannot terminate.')
        # Conservative model-level support restriction: even a currently
        # disabled competitor might become enabled by a later observation.
        # Do not silently assign priority to tau or select a branch in advance.
        competitors = {arc.target for incoming in transition.in_arcs
                       for arc in incoming.source.out_arcs if arc.target is not transition}
        if competitors:
            names = ', '.join(f'{t.name} ({t.label or "silent"})' for t in sorted(competitors, key=lambda t: t.name))
            raise PrefixUnavailable(f'Prediction-only immediate routing is ambiguous at silent transition {transition.name!r}: '
                                    f'competing transitions {names} share an input place. No silent branch priority is assumed; '
                                    'descriptive replay remains available.')


def prediction_history(log, net, im, cutoff):
    """Only events strictly before cutoff. Case existence begins at first event.

    Within-place indistinguishable tokens use the descriptive tool's FIFO
    convention. Initial tokens are instantiated at the first observed event.
    Equal timestamps within a case are rejected rather than imposing an order.
    Final-place tokens remain open; final markings are never used to finish a prefix.
    Forced silent transitions fire to quiescence at the triggering observation's
    timestamp. Initial routing occurs at the case's first observation, when its
    initial tokens become available. Inferred events retain exact identities,
    provenance and availability timestamps in a separate derived event table.
    """
    validate_prefix_model(net, im)
    cutoff = pd.to_datetime(cutoff, utc=True)
    by_label = defaultdict(list)
    for t in net.transitions:
        by_label[t.label].append(t)
    silent = sorted(by_label[None], key=lambda t: t.name)
    inputs = {t: sorted([(a.source.name, int(a.weight)) for a in t.in_arcs]) for t in net.transitions}
    outputs = {t: sorted([(a.target.name, int(a.weight)) for a in t.out_arcs]) for t in net.transitions}
    rows = []
    history = []
    seen_cases = set()
    for trace in log:
        events = []
        for event in trace:
            ts = pd.to_datetime(event.get('time:timestamp'), utc=True)
            if ts is None or pd.isna(ts):
                raise PrefixUnavailable('Every event requires a recorded timestamp.')
            if ts < cutoff:
                events.append((ts, event.get('concept:name')))
        if not events:
            continue
        case = str(trace.attributes.get('concept:name', ''))
        if not case or case in seen_cases:
            raise PrefixUnavailable('Observed cases require unique, nonempty case identities.')
        seen_cases.add(case)
        if any(b[0] <= a[0] for a, b in zip(events, events[1:])):
            raise PrefixUnavailable(f'Case {case}: tied or decreasing timestamps do not establish an exact event order.')
        marking = defaultdict(deque)

        def produce(place, ts):
            index = len(rows)
            rows.append(dict(case_id=case, token_id=f'{case}:{index}', place=place,
                             produced_ts=ts, consumed_ts=pd.NaT))
            marking[place].append(index)

        def enabled(transition):
            return all(len(marking[p]) >= count for p, count in inputs[transition])

        def fire(transition, ts, inferred):
            for place, count in inputs[transition]:
                for _ in range(count):
                    rows[marking[place].popleft()]['consumed_ts'] = ts
            for place, count in outputs[transition]:
                for _ in range(count):
                    produce(place, ts)
            history.append(dict(case_id=case, transition_id=transition.name, activity=transition.label,
                                timestamp=ts, available_at=ts, inferred=inferred,
                                source='immediate_silent_routing' if inferred else 'observed_event'))

        def route(ts):
            visited = set()
            for _ in range(MAX_SILENT_FIRINGS):
                candidate = next((t for t in silent if enabled(t)), None)
                if candidate is None:
                    return
                state = tuple(sorted((p, len(tokens)) for p, tokens in marking.items() if tokens))
                if state in visited:
                    raise PrefixUnavailable(f'Case {case}, {ts}: nonterminating immediate silent routing; repeated marking.')
                visited.add(state)
                fire(candidate, ts, True)
            if any(enabled(t) for t in silent):
                raise PrefixUnavailable(f'Case {case}, {ts}: immediate routing exceeds {MAX_SILENT_FIRINGS} firings per observation; no approximation is returned.')

        for place, count in im.items():
            for _ in range(int(count)):
                produce(place.name, events[0][0])
        route(events[0][0])
        for ts, label in events:
            candidates = [t for t in by_label[label] if t.label is not None and enabled(t)]
            if not candidates:
                raise PrefixUnavailable(f'Case {case}, {ts}: visible deviation: activity {label!r} has no enabled transition; no repair is inferred and no event is deleted.')
            if len(candidates) != 1:
                raise PrefixUnavailable(f'Case {case}, {ts}: activity {label!r} has multiple enabled transition identities; prefix reconstruction is ambiguous.')
            fire(candidates[0], ts, False)
            route(ts)
    frame = pd.DataFrame(rows, columns=['case_id', 'token_id', 'place', 'produced_ts', 'consumed_ts'])
    for col in ('produced_ts', 'consumed_ts'):
        frame[col] = pd.to_datetime(frame[col], utc=True)
    derived = pd.DataFrame(history, columns=['case_id', 'transition_id', 'activity', 'timestamp', 'available_at', 'inferred', 'source'])
    for col in ('timestamp', 'available_at'):
        derived[col] = pd.to_datetime(derived[col], utc=True)
    return frame, derived


def prefix_tokens(log, net, im, cutoff):
    """Compatibility wrapper returning only prediction-only token intervals."""
    return prediction_history(log, net, im, cutoff)[0]
