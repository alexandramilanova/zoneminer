"""Zone place-suggestion heuristic: from activity labels to candidate places.

The user thinks in *activities* ("Pick Items", "Fraud Review"); zones are
defined on Petri-net *places*. This module bridges the two with a purely
structural heuristic — no replay, no log statistics:

1. **Label matching.** Find every visible transition whose label exactly
   matches one of the selected activity labels (after whitespace trimming).
2. **Adjacency scoring.** Every place directly consumed from or produced to
   by a matched transition scores +1 per adjacent arc — the places
   immediately "around" the selected activities.
3. **Connecting-path scoring.** For every pair of matched transitions, a BFS
   over the net graph looks for a path between them whose intermediate
   transitions are all *silent* (τ) — i.e. the two activities are connected
   without any other visible activity in between. Every place on the first
   such path found scores +2, pulling in the places *between* the selected
   activities, not just around them.
4. **Ranking.** Candidates are returned sorted by score (descending), ties
   alphabetically. Structural source/sink-style places are excluded.

Because the BFS returns the first path found and treats arcs as undirected
neighbor steps, the path chosen between two transitions is not guaranteed to
be the semantically "best" one in nets with many silent routes — the output
is a ranked *suggestion*, always subject to the user's confirmation and to
zone validation (disjointness, connectedness) afterwards.
"""

from __future__ import annotations

from collections import Counter, deque


# Structural entry/exit places that should never be suggested as zone members.
EXCLUDED_PLACE_NAMES = {"source", "sink", "start", "end"}


def process_tree_activity_labels(process_tree) -> list[str]:
    """Visible activity labels of a process tree, depth-first, deduplicated
    in first-seen order (preserves the tree's reading order)."""
    labels: list[str] = []

    def visit(node) -> None:
        if node is None:
            return
        label = getattr(node, "label", None)
        if label is not None:
            text = str(label).strip()
            if text:
                labels.append(text)
        for child in getattr(node, "children", []) or []:
            visit(child)

    visit(process_tree)

    seen = set()
    out = []
    for label in labels:
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out


def petri_net_activity_labels(net) -> list[str]:
    """Visible transition labels of a Petri net, deduplicated and sorted."""
    labels = []
    for transition in getattr(net, "transitions", []):
        label = getattr(transition, "label", None)
        if label is None:
            continue
        text = str(label).strip()
        if text:
            labels.append(text)

    seen = set()
    out = []
    for label in labels:
        if label not in seen:
            seen.add(label)
            out.append(label)
    return sorted(out)


def readable_activity_labels(process_tree, net) -> list[str]:
    """Activity labels for the zone-definition helper UI: process-tree order
    when a tree exists (more readable), else the net's sorted labels."""
    tree_labels = process_tree_activity_labels(process_tree) if process_tree is not None else []
    if tree_labels:
        return tree_labels
    return petri_net_activity_labels(net)


def suggested_places_from_activity_labels(
    net,
    activity_labels: list[str],
    *,
    excluded_places: set[str] | None = None,
) -> list[str]:
    """Rank the net's places as zone candidates for the given activities.

    Scoring (see module docstring): +1 per arc adjacent to a label-matched
    transition, +2 per membership on a silent-only connecting path between two
    matched transitions. Returns place names sorted by score descending, ties
    alphabetically. Empty input or no label match returns an empty list.
    """
    if not activity_labels:
        return []

    excluded = set(excluded_places or set()) | EXCLUDED_PLACE_NAMES
    selected = {str(label).strip() for label in activity_labels if str(label).strip()}
    if not selected:
        return []

    transition_matches = [
        transition
        for transition in getattr(net, "transitions", [])
        if getattr(transition, "label", None) is not None
        and str(transition.label).strip() in selected
    ]

    counts: Counter[str] = Counter()
    for transition in transition_matches:
        for arc in getattr(transition, "in_arcs", []):
            place_name = getattr(getattr(arc, "source", None), "name", None)
            if place_name and place_name not in excluded:
                counts[str(place_name)] += 1
        for arc in getattr(transition, "out_arcs", []):
            place_name = getattr(getattr(arc, "target", None), "name", None)
            if place_name and place_name not in excluded:
                counts[str(place_name)] += 1

    selected_transition_names = {str(transition.name) for transition in transition_matches}
    transition_by_name = {
        str(transition.name): transition
        for transition in getattr(net, "transitions", [])
    }

    def neighbors(node):
        for arc in getattr(node, "in_arcs", []):
            src = getattr(arc, "source", None)
            if src is not None:
                yield src
        for arc in getattr(node, "out_arcs", []):
            tgt = getattr(arc, "target", None)
            if tgt is not None:
                yield tgt

    def allowed_internal(node) -> bool:
        if hasattr(node, "label"):
            return getattr(node, "label", None) is None
        return True

    def collect_path_places(start_name: str, target_name: str) -> set[str]:
        start = transition_by_name[start_name]
        target = transition_by_name[target_name]
        queue = deque([(start, [start])])
        seen = {id(start)}

        while queue:
            node, path = queue.popleft()
            for nxt in neighbors(node):
                nxt_id = id(nxt)
                if nxt_id in seen:
                    continue
                if nxt is target:
                    path_places = {
                        str(getattr(item, "name"))
                        for item in path[1:]
                        if hasattr(item, "name")
                        and not hasattr(item, "label")
                        and str(getattr(item, "name")) not in excluded
                    }
                    return path_places

                if hasattr(nxt, "label"):
                    nxt_name = str(getattr(nxt, "name"))
                    if nxt_name in selected_transition_names:
                        continue
                    if not allowed_internal(nxt):
                        continue

                seen.add(nxt_id)
                queue.append((nxt, path + [nxt]))

        return set()

    transition_name_list = sorted(selected_transition_names)
    for i in range(len(transition_name_list)):
        for j in range(i + 1, len(transition_name_list)):
            for place_name in collect_path_places(transition_name_list[i], transition_name_list[j]):
                counts[place_name] += 2

    return [
        place_name
        for place_name, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
