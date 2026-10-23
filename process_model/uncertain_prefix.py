"""Causal marking sets: never select one unobserved optional route.

Only end-of-window token/case occupancy is inferred. Histories reaching the
same marking may be merged for these metrics, never for durations or flows.
"""
from collections import Counter, defaultdict, deque
from functools import lru_cache
from heapq import heappop, heappush
from itertools import groupby

import numpy as np
import pandas as pd

from process_model.prefix import PrefixUnavailable
from process_model.semantics import validate_petri_net

OCCUPANCY_METRICS = ('token_present_end', 'case_present_end')
POLICY = 'bounded-marking-sets-immediate-routing-v1'
MAX_STATES = 256
MAX_BATCH_WORK = 4096
MAX_TOKENS = 10000


def needs_marking_sets(net):
    labels = Counter(t.label for t in net.transitions if t.label is not None)
    return any(n > 1 for n in labels.values()) or any(
        t.label is None and any(len(a.source.out_arcs) > 1 for a in t.in_arcs)
        for t in net.transitions)


class MarkingSetReplay:
    def __init__(self, net, im):
        validate_petri_net(net, im)
        if im is None:
            raise PrefixUnavailable('An explicit initial marking is required.')
        self.places = sorted(net.places, key=lambda p: p.name)
        self.index = {p.name: i for i, p in enumerate(self.places)}
        self.transitions = sorted(net.transitions, key=lambda t: t.name)
        self.inputs, self.outputs, self.by_label = {}, {}, defaultdict(list)
        self.failed_observations = {}
        self.forced, self.silent = set(), []
        for t in self.transitions:
            self.inputs[t] = [(self.index[a.source.name], int(a.weight)) for a in t.in_arcs]
            self.outputs[t] = [(self.index[a.target.name], int(a.weight)) for a in t.out_arcs]
            self.by_label[t.label].append(t)
            if t.label is None:
                if not t.in_arcs:
                    raise PrefixUnavailable(f'Silent transition {t.name!r} has no input; unbounded immediate routing is unsupported.')
                self.silent.append(t)
                competitors = {a.target for incoming in t.in_arcs for a in incoming.source.out_arcs if a.target is not t}
                if not competitors:
                    self.forced.add(t)
        self.initial = tuple(int(im.get(p, 0)) for p in self.places)

    def enabled(self, marking, transition):
        return all(marking[p] >= n for p, n in self.inputs[transition])

    def fire(self, marking, transition):
        result = list(marking)
        for p, n in self.inputs[transition]:
            result[p] -= n
        for p, n in self.outputs[transition]:
            result[p] += n
        if sum(result) > MAX_TOKENS:
            raise PrefixUnavailable(f'Marking-set replay exceeds {MAX_TOKENS} tokens per case; no approximation returned.')
        return tuple(result)

    @lru_cache(maxsize=2048)
    def closure(self, initial):
        todo, graph, terminal = deque([initial]), {}, set()
        while todo:
            marking = todo.popleft()
            enabled = [t for t in self.silent if self.enabled(marking, t)]
            forced = [t for t in enabled if t in self.forced]
            # Independent forced routes commute for markings, so one order
            # suffices. Any competing route also retains its pending decision:
            # another competitor can become enabled by a later observation.
            # Giving the currently enabled tau priority would lose legal prefixes.
            choices = forced[:1] or enabled
            if not forced:
                terminal.add(marking)
            successors = {self.fire(marking, t) for t in choices}
            graph[marking] = successors
            for following in successors:
                if following not in graph and following not in todo:
                    todo.append(following)
            if len(graph) + len(todo) > MAX_STATES:
                raise PrefixUnavailable(f'Silent closure exceeds {MAX_STATES} possible markings; no route is selected arbitrarily.')
        # Epsilon cycles may repeat the same marking arbitrarily many times.
        # That does not affect occupancy: merge them, never infer their event
        # counts or durations. Every reachable state must have a finite route
        # to a waiting/quiescent endpoint; closed divergent regions fail.
        predecessors = defaultdict(set)
        for before, successors in graph.items():
            for following in successors:
                predecessors[following].add(before)
        can_finish = set(terminal)
        ready = deque(terminal)
        while ready:
            for before in predecessors[ready.popleft()]:
                if before not in can_finish:
                    can_finish.add(before); ready.append(before)
        if len(can_finish) != len(graph):
            raise PrefixUnavailable('Closed silent cycle/region has no finite waiting or quiescent endpoint; nonterminating routing is unsupported.')
        return frozenset(terminal)

    def observe(self, states, batch):
        # Repeated incompatible variants must not repeatedly enumerate the
        # same rejected state space. Cache errors as well as successful steps;
        # the caller still rejects and reports every affected case.
        key = (states, batch)
        if key in self.failed_observations:
            raise PrefixUnavailable(self.failed_observations[key])
        try:
            return self._observe(states, batch)
        except PrefixUnavailable as exc:
            if len(self.failed_observations) >= 2048:
                self.failed_observations.pop(next(iter(self.failed_observations)))
            self.failed_observations[key] = str(exc)
            raise

    @lru_cache(maxsize=2048)
    def _observe(self, states, batch):
        """All model-compatible permutations of simultaneous observations."""
        work = deque((m, batch) for m in states)
        visited, finished = set(), set()
        while work:
            marking, remaining = work.popleft()
            key = (marking, remaining)
            if key in visited:
                continue
            visited.add(key)
            if len(visited) > MAX_BATCH_WORK:
                raise PrefixUnavailable(f'Simultaneous-event replay exceeds {MAX_BATCH_WORK} states; no file ordering is assumed.')
            if not remaining:
                finished.add(marking)
                if len(finished) > MAX_STATES:
                    raise PrefixUnavailable(f'Observed prefix exceeds {MAX_STATES} possible markings.')
                continue
            for label, count in remaining:
                next_remaining = tuple((other, n - (other == label)) for other, n in remaining if n - (other == label) > 0)
                for transition in self.by_label[label]:
                    if transition.label is not None and self.enabled(marking, transition):
                        for following in self.closure(self.fire(marking, transition)):
                            work.append((following, next_remaining))
        if not finished:
            raise PrefixUnavailable('visible deviation: no possible marking can replay the observed activity batch; no event is inserted or deleted.')
        return frozenset(finished)


def occupancy_features(log, net, im, zones, timeframe, start, end):
    start, end = pd.to_datetime(start, utc=True), pd.to_datetime(end, utc=True)
    if start >= end or start.floor(timeframe) != start or end.floor(timeframe) != end:
        raise ValueError('Prediction boundaries must be increasing completed-window boundaries.')
    grid = pd.date_range(start, end, freq=timeframe)
    if len(grid) > 4097:
        raise PrefixUnavailable('Marking-set replay supports at most 4096 study windows.')
    replay = MarkingSetReplay(net, im)
    names = sorted(zones)
    indices = [[replay.index[p] for p in zones[name]] for name in names]

    @lru_cache(maxsize=2048)
    def bounds(states):
        counts = np.array([[sum(m[p] for p in selected) for selected in indices] for m in states], dtype=np.int64)
        return np.stack([counts.min(axis=0), counts.max(axis=0), (counts > 0).min(axis=0), (counts > 0).max(axis=0)])

    def batches(trace):
        previous = None
        def timestamp(event):
            stamp = pd.Timestamp(event.get('time:timestamp'))
            return stamp.tz_localize('UTC') if stamp.tzinfo is None else stamp.tz_convert('UTC')
        for stamp, events in groupby(trace, key=timestamp):
            if pd.isna(stamp) or previous is not None and stamp < previous:
                raise PrefixUnavailable('Missing or decreasing event timestamps; chronological import is required.')
            previous = stamp
            # Do not inspect unavailable future labels, even during iterator
            # lookahead after the last observed batch.
            if stamp >= end:
                return
            labels = Counter(e.get('concept:name') for e in events)
            if any(not isinstance(label, str) or not label for label in labels):
                raise PrefixUnavailable('Every observed event requires an activity label.')
            yield stamp, tuple(sorted(labels.items()))

    heap, cases, seen = [], {}, set()
    for sequence, trace in enumerate(log):
        iterator = iter(batches(trace))
        first = next(iterator, None)
        if first is not None and first[0] < end:
            case = str(trace.attributes.get('concept:name', ''))
            if not case or case in seen:
                raise PrefixUnavailable('Observed case identities must be unique and nonempty.')
            seen.add(case)
            heappush(heap, (first[0], sequence, case, first[1], iterator))
    totals = np.zeros((4, len(names)), dtype=np.int64)
    output, processed, tied, peak, ever_ambiguous = [], 0, 0, 1, set()
    delta = pd.tseries.frequencies.to_offset(timeframe)
    for cutoff in grid[1:]:
        while heap and heap[0][0] < cutoff:
            stamp, sequence, case, batch, iterator = heappop(heap)
            before = cases.get(case)
            try:
                states = before if before is not None else replay.closure(replay.initial)
                after = replay.observe(states, batch)
            except PrefixUnavailable as exc:
                failure = PrefixUnavailable(f'Case {case}, {stamp}: {exc}')
                failure.diagnostics = dict(processed_events=processed, observed_cases=len(cases), peak_markings=peak,
                                           case=case, timestamp=str(stamp), activities=dict(batch))
                raise failure from exc
            if before is not None:
                totals -= bounds(before)
            totals += bounds(after)
            cases[case] = after
            peak = max(peak, len(after))
            if len(after) > 1:
                ever_ambiguous.add(case)
            processed += sum(n for _, n in batch)
            tied += int(sum(n for _, n in batch) > 1)
            following = next(iterator, None)
            if following is not None and following[0] < end:
                heappush(heap, (following[0], sequence, case, following[1], iterator))
        for i, name in enumerate(names):
            row = dict(zone=name, window_start=cutoff - delta, window_end=cutoff)
            for metric, lo, hi in [('token_present_end', 0, 1), ('case_present_end', 2, 3)]:
                lower, upper = int(totals[lo, i]), int(totals[hi, i])
                row.update({metric: float(lower) if lower == upper else np.nan,
                            metric + '_lower': lower, metric + '_upper': upper})
            output.append(row)
    result = pd.DataFrame(output)
    result.attrs['prediction_reconstruction'] = dict(policy=POLICY, cutoff=str(end), observed_events=processed,
        inferred_silent_events=None, visible_events_inserted=0, visible_events_deleted=0,
        silent_transition_counts={}, inferred_event_preview=[], preview_limit=0,
        peak_markings=peak, cases_with_alternatives=len(ever_ambiguous), observed_cases=len(cases), tied_timestamp_batches=tied,
        note='Multiple possible markings; no uniquely observed silent history, duration, flow or route probability is asserted.')
    return result
