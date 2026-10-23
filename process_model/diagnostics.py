from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd
from pm4py.objects.petri_net.obj import Marking


def add_leak_diagnostics(
    token_place_df: pd.DataFrame,
    zone_feat: pd.DataFrame,
    zone_places: Dict[str, List[str]],
    fm: Optional[Marking] = None,
):
    if token_place_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = token_place_df.copy()
    final_places = {p.name for p in fm.keys()} if fm else set()
    df["expected_final"] = df["place"].isin(final_places)
    df["is_open"] = df["consumed_ts"].isna() & ~df["expected_final"]

    place_diag = (
        df.groupby("place", as_index=False)
        .agg(
            tokens_produced=("place", "size"),
            tokens_open=("is_open", "sum"),
            open_ratio=("is_open", "mean"),
            expected_final_place=("expected_final", "max"),
            first_produced=("produced_ts", "min"),
            last_produced=("produced_ts", "max"),
        )
        .sort_values(["open_ratio", "tokens_open"], ascending=False)
        .reset_index(drop=True)
    )

    place_to_zones = {}
    for z, places in zone_places.items():
        for p in places:
            place_to_zones.setdefault(p, []).append(z)
    multi = {p: zs for p, zs in place_to_zones.items() if len(zs) > 1}
    if multi:
        sample = list(multi.items())[:15]
        msg = "Some places are assigned to multiple zones (will double-count):\n" + "\n".join(
            [f"- {p}: {zs}" for p, zs in sample]
        )
        raise ValueError(msg)

    df["zones"] = df["place"].map(place_to_zones).apply(lambda x: x if isinstance(x, list) else [])
    df = df.explode("zones")
    df = df[df["zones"].notna() & (df["zones"] != "")]

    zone_diag = (
        df.groupby("zones", as_index=False)
        .agg(
            tokens_produced=("place", "size"),
            tokens_open=("is_open", "sum"),
            open_ratio=("is_open", "mean"),
        )
        .rename(columns={"zones": "zone"})
        .sort_values(["open_ratio", "tokens_open"], ascending=False)
        .reset_index(drop=True)
    )

    return zone_diag, place_diag
