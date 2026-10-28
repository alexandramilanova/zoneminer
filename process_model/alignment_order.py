"""A canonical representative of commuting firings in an optimal alignment."""
import heapq
import pandas as pd


def canonical_alignment(alignment, net, timestamps=None):
    """Preserve dependent firings and observed order; order independent moves.

    Firings sharing any input/output place are kept in their original order.
    Thus reordering swaps only disjoint firings, which cannot change enabledness,
    arc multiplicities, the final marking or alignment cost. Observed events
    retain their trace order. Distinct recorded times are barriers; inferred
    firings cannot cross them. Structural ordering resolves same-time ties.
    """
    from process_model.replay import _petri_maps, alignment_transition_name

    moves = alignment["alignment"]
    transitions = {t.name: t for t in net.transitions}
    labels = _petri_maps(net)[2]
    successors = [[] for _ in moves]
    indegree = []
    keys = []
    last_touch = {}
    last_observed = None
    times = [pd.Timestamp(t) for t in timestamps] if timestamps is not None else None
    if times is not None:
        times = [t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC") for t in times]
    observed_index = 0
    current_time = times[0] if times else 0
    barrier = None
    time_group = []
    for i, (log_move, model_move) in enumerate(moves):
        name = alignment_transition_name(alignment, i, log_move, model_move, net, labels, transitions)
        dependencies = set()
        if name is not None:
            transition = transitions[name]
            inputs = sorted((a.source.name, int(a.weight)) for a in transition.in_arcs)
            outputs = sorted((a.target.name, int(a.weight)) for a in transition.out_arcs)
            footprint = {p for p, _ in inputs + outputs}
            dependencies.update(last_touch[p] for p in footprint if p in last_touch)
            for p in footprint:
                last_touch[p] = i
            structural = (model_move or "", tuple(inputs), tuple(outputs))
        else:
            structural = ("", (), ())
        observed = log_move not in (None, ">>")
        if barrier is not None:
            dependencies.add(barrier)
        if observed:
            stamp = times[observed_index] if times is not None else observed_index
            observed_index += 1
            if stamp != current_time:
                dependencies.update(time_group)
                time_group = []
                barrier = i
                current_time = stamp
            if last_observed is not None:
                dependencies.add(last_observed)
            last_observed = i
        time_group.append(i)
        keys.append((1, i) if observed else (0, structural))
        indegree.append(len(dependencies))
        for previous in dependencies:
            successors[previous].append(i)
    ready = [(keys[i], i) for i, count in enumerate(indegree) if not count]
    heapq.heapify(ready)
    order = []
    while ready:
        _, i = heapq.heappop(ready)
        order.append(i)
        for following in successors[i]:
            indegree[following] -= 1
            if not indegree[following]:
                heapq.heappush(ready, (keys[following], following))
    result = dict(alignment, alignment=[moves[i] for i in order])
    for field in ("transition_names", "tau_names"):
        original = alignment.get(field, {})
        result[field] = {new: original[old] for new, old in enumerate(order) if old in original}
    return result
