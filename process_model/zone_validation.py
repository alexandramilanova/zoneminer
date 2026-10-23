# zone_validation.py
from __future__ import annotations

from typing import Any

import pandas as pd


def build_place_adjacency(net) -> dict[str, set[str]]:
    """
    Build an undirected place-to-place adjacency through transitions.
    Two places are considered connected if they share a transition.
    """
    adj = {p.name: set() for p in net.places}

    for t in net.transitions:
        in_places = [
            a.source.name
            for a in net.arcs
            if a.target == t and hasattr(a.source, "name")
        ]
        out_places = [
            a.target.name
            for a in net.arcs
            if a.source == t and hasattr(a.target, "name")
        ]

        connected = list(set(in_places + out_places))

        for i in range(len(connected)):
            for j in range(len(connected)):
                if i != j:
                    adj[connected[i]].add(connected[j])

    return adj


def is_connected_zone(selected_places: list[str], place_adj: dict[str, set[str]]) -> bool:
    """
    Check whether all selected places belong to one connected component.
    """
    selected = set(selected_places)
    if len(selected) <= 1:
        return True

    start = next(iter(selected))
    seen = {start}
    stack = [start]

    while stack:
        cur = stack.pop()
        for nxt in place_adj.get(cur, set()):
            if nxt in selected and nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)

    return seen == selected


def _find_duplicate_zone_names(clean_names: list[str]) -> list[str]:
    if not clean_names:
        return []

    return (
        pd.Series([name for name in clean_names if name])
        .loc[lambda s: s.duplicated()]
        .unique()
        .tolist()
    )


def _find_duplicate_places(zone_places: dict[str, list[str]]) -> list[str]:
    all_selected = [p for places in zone_places.values() for p in places]
    if not all_selected:
        return []

    return (
        pd.Series(all_selected)
        .loc[lambda s: s.duplicated()]
        .unique()
        .tolist()
    )


def _format_duplicate_place_details(
    duplicate_places: list[str],
    zone_places: dict[str, list[str]],
) -> list[str]:
    place_to_zones: dict[str, list[str]] = {}

    for z, places in zone_places.items():
        for p in places:
            place_to_zones.setdefault(p, []).append(z)

    return [f"{p}: {place_to_zones[p]}" for p in duplicate_places]


def validate_zones(
    zone_inputs: list[tuple[str, list[str]]],
    place_names: list[str],
    net,
    require_non_empty: bool = True,
    allow_unassigned_places: bool = True,
    require_connected: bool = True,
) -> dict[str, Any]:
    """
    Validate user-defined zones.

    Returns a dict with:
      - zone_places: cleaned mapping {zone_name: [places]}
      - errors: list[str]
      - warnings: list[str]
      - zone_config_valid: bool
      - unassigned_places: list[str]
      - duplicate_places: list[str]
      - disconnected_zones: list[str]
    """
    zone_places: dict[str, list[str]] = {}
    errors: list[str] = []
    warnings: list[str] = []

    if not zone_inputs:
        errors.append("Define at least one zone.")

    clean_names = [(zname or "").strip() for zname, _ in zone_inputs]

    # 1) Empty zone names
    empty_zone_idxs = [i for i, name in enumerate(clean_names) if not name]
    if empty_zone_idxs:
        errors.append(
            "Zone names cannot be empty. Please rename: "
            + ", ".join([f"Zone {i+1}" for i in empty_zone_idxs])
        )

    # 2) Duplicate zone names
    duplicate_zone_names = _find_duplicate_zone_names(clean_names)
    if duplicate_zone_names:
        errors.append(
            "Zone names must be unique. Duplicate names found: "
            + ", ".join(duplicate_zone_names)
        )

    # Only continue if name validation passed
    if not errors:
        zone_places = {
            (zname or "").strip(): list(selected or [])
            for zname, selected in zone_inputs
        }

        # Membership is independent of connectivity: a nonexistent singleton
        # would otherwise pass the connected-component check trivially.
        # Standalone callers may omit the net when connectivity is disabled.
        # API callers always supply the uploaded/discovered net itself.
        known_places = {p.name for p in net.places} if net is not None else set(place_names)
        for zone, selected in zone_places.items():
            unknown = sorted(set(selected) - known_places)
            if unknown:
                errors.append(
                    f"Zone '{zone}' references nonexistent Petri-net place(s): "
                    + ", ".join(unknown)
                )

        # 3) Empty zone contents
        if require_non_empty:
            empty_place_zones = [z for z, places in zone_places.items() if len(places) == 0]
            if empty_place_zones:
                errors.append(
                    "Each zone must contain at least one place. Empty zones found: "
                    + ", ".join(empty_place_zones)
                )

        # 4) Overlapping place assignments
        duplicate_places = _find_duplicate_places(zone_places)
        if duplicate_places:
            duplicate_details = _format_duplicate_place_details(duplicate_places, zone_places)
            errors.append(
                "Each place can belong to only one zone. Overlapping assignments found:\n- "
                + "\n- ".join(duplicate_details)
            )
        else:
            duplicate_places = []

        # 5) Unassigned places
        assigned_places = {p for places in zone_places.values() for p in places}
        unassigned_places = sorted(set(place_names) - assigned_places)

        if unassigned_places:
            if allow_unassigned_places:
                warnings.append(
                    f"{len(unassigned_places)} place(s) are not assigned to any zone and will be excluded from analysis: "
                    + ", ".join(unassigned_places[:15])
                    + (" ..." if len(unassigned_places) > 15 else "")
                )
            else:
                errors.append(
                    "Every place must belong to exactly one zone. Unassigned places found: "
                    + ", ".join(unassigned_places)
                )

        # 6) Connected zones
        if require_connected:
            place_adj = build_place_adjacency(net)
            disconnected_zones = [
                z for z, places in zone_places.items()
                if len(places) > 1 and not is_connected_zone(places, place_adj)
            ]
            if disconnected_zones:
                errors.append(
                    "Each zone must be connected in the Petri net. Disconnected zones found: "
                    + ", ".join(disconnected_zones)
                )
        else:
            disconnected_zones = []

    else:
        duplicate_places = []
        unassigned_places = []
        disconnected_zones = []

    return {
        "zone_places": zone_places,
        "errors": errors,
        "warnings": warnings,
        "zone_config_valid": len(errors) == 0,
        "unassigned_places": unassigned_places,
        "duplicate_places": duplicate_places,
        "disconnected_zones": disconnected_zones,
    }
