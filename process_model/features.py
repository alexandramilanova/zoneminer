from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from process_model.conformance import add_window_conformance_features, trace_conformance_table_from_alignments
from process_model.diagnostics import add_leak_diagnostics
from process_model.io import discover_petri_net_from_log, load_any_log, load_csv_log, load_pnml
from process_model.replay import compute_alignments, token_place_table_from_alignments
from process_model.time_index import EventTimeIndex, IntervalTimeIndex


def _validate_zone_places(zone_places: Dict[str, List[str]]) -> Dict[str, str]:
    place_to_zone: Dict[str, str] = {}
    multi: Dict[str, List[str]] = {}

    for zone, places in zone_places.items():
        for place in places:
            if place in place_to_zone and place_to_zone[place] != zone:
                multi.setdefault(place, [])
                if place_to_zone[place] not in multi[place]:
                    multi[place].append(place_to_zone[place])
                if zone not in multi[place]:
                    multi[place].append(zone)
            else:
                place_to_zone[place] = zone

    if multi:
        sample = list(multi.items())[:15]
        msg = (
            "Some places are assigned to multiple zones (this would double-count metrics):\n"
            + "\n".join([f"- {p}: {zs}" for p, zs in sample])
        )
        raise ValueError(msg)

    return place_to_zone


def build_case_zone_stays_from_places(
    token_place_df: pd.DataFrame,
    zone_places: Dict[str, List[str]],
) -> pd.DataFrame:
    cols = ["case_id", "zone", "stay_id", "entry_ts", "exit_ts", "is_open", "duration"]

    if token_place_df.empty:
        return pd.DataFrame(columns=cols)

    place_to_zone = _validate_zone_places(zone_places)

    df = token_place_df.copy()
    df["produced_ts"] = pd.to_datetime(df["produced_ts"])
    df["consumed_ts"] = pd.to_datetime(df["consumed_ts"])
    df["zone"] = df["place"].map(place_to_zone)
    df = df[df["zone"].notna()].copy()

    if df.empty:
        return pd.DataFrame(columns=cols)

    # One stable sort replaces a DataFrame sort for every case/zone group.
    # ngroup preserves the original first-seen group order in the output.
    df["_stay_group"] = df.groupby(["zone", "case_id"], sort=False).ngroup()
    df = df.sort_values(["_stay_group", "produced_ts", "consumed_ts"], na_position="last", kind="stable")
    rows = []
    for (zone, case_id), g in df.groupby(["zone", "case_id"], sort=False):
        intervals = []

        for start, end in zip(g["produced_ts"], g["consumed_ts"]):
            if pd.isna(start):
                continue
            if not intervals:
                intervals.append([start, end])
                continue

            _, last_end = intervals[-1]
            if pd.isna(last_end):
                continue
            if pd.isna(end):
                if start <= last_end:
                    intervals[-1][1] = pd.NaT
                else:
                    intervals.append([start, pd.NaT])
                continue
            if start <= last_end:
                if end > last_end:
                    intervals[-1][1] = end
            else:
                intervals.append([start, end])

        for stay_id, (entry_ts, exit_ts) in enumerate(intervals, start=1):
            rows.append(
                {
                    "case_id": str(case_id),
                    "zone": zone,
                    "stay_id": stay_id,
                    "entry_ts": entry_ts,
                    "exit_ts": exit_ts,
                    "is_open": pd.isna(exit_ts),
                    "duration": (exit_ts - entry_ts) if pd.notna(exit_ts) else pd.NaT,
                }
            )

    stays = pd.DataFrame(rows, columns=cols)
    # All-open exits otherwise lose the entry timezone, making comparisons
    # against a timezone-aware observation grid invalid.
    if stays["exit_ts"].isna().all():
        stays["exit_ts"] = pd.Series(pd.NaT, index=stays.index, dtype=stays["entry_ts"].dtype)
    # An all-open zone has only NaT durations, which pandas otherwise infers
    # as datetimes. Keep the duration contract even without completed stays.
    stays["duration"] = pd.array([row["duration"] for row in rows], dtype="timedelta64[ns]")
    return stays


def _order_inversion_stats(
    entry_ns: np.ndarray, exit_ns: np.ndarray, max_pairs_n: int = 4000
) -> tuple:
    """FIFO-order statistics over completed stays (EXTENSIONS A1).

    Compares entry order vs. exit order pairwise (strict inequalities, so
    ties count as order-preserving):

    - inversion ratio: inverted pairs / all pairs, Kendall-tau style in [0, 1]
      (0 = perfect FIFO, 1 = fully reversed order)
    - overtaken rate: share of stays overtaken at least once (another stay
      entered strictly later and exited strictly earlier)
    - overtake depth mean: among stays that overtook at least one other,
      the average number of stays they passed

    Stays are compared within one call (in practice: one zone and window) —
    overtakes across window boundaries are not counted, which keeps the
    metric windowed and cheap; the fingerprint scatter shows the unwindowed
    picture. The historical deterministic evenly-strided subsample above
    ``max_pairs_n`` stays (by entry order) is retained. Strict pair counts
    are calculated in O(n log n) with rank counts rather than a pair matrix.
    """
    n = int(entry_ns.size)
    if n < 2:
        return np.nan, np.nan, np.nan
    if n > max_pairs_n:
        order = np.argsort(entry_ns, kind="stable")
        idx = order[np.linspace(0, n - 1, max_pairs_n).astype(int)]
        entry_ns, exit_ns = entry_ns[idx], exit_ns[idx]
        n = max_pairs_n
    # Count strict order inversions without allocating an n x n matrix.
    # Equal-entry groups are queried before any group member is inserted, so
    # neither equal entries nor equal exits become false overtakes.
    order = np.argsort(entry_ns, kind="stable")
    entries, exits = entry_ns[order], exit_ns[order]
    ranks = np.searchsorted(np.unique(exits), exits) + 1
    tree = [0] * (int(ranks.max()) + 1)
    depth = np.zeros(n, dtype=np.int64)
    boundaries = np.concatenate(([0], np.flatnonzero(entries[1:] != entries[:-1]) + 1, [n]))
    for lo, hi in zip(boundaries[:-1], boundaries[1:]):
        for i in range(lo, hi):
            rank, less_or_equal = int(ranks[i]), 0
            while rank:
                less_or_equal += tree[rank]
                rank -= rank & -rank
            depth[i] = int(lo) - less_or_equal
        for i in range(lo, hi):
            rank = int(ranks[i])
            while rank < len(tree):
                tree[rank] += 1
                rank += rank & -rank
    overtaken = np.zeros(n, dtype=bool)
    later_min = None
    for lo, hi in zip(boundaries[-2::-1], boundaries[:0:-1]):
        if later_min is not None:
            overtaken[lo:hi] = exits[lo:hi] > later_min
        group_min = int(exits[lo:hi].min())
        later_min = group_min if later_min is None else min(later_min, group_min)
    n_pairs = n * (n - 1) // 2
    inversion_ratio = float(depth.sum()) / float(n_pairs)
    overtaken_rate = float(overtaken.mean())
    overtakers = depth[depth > 0]
    depth_mean = float(overtakers.mean()) if overtakers.size else np.nan
    return inversion_ratio, overtaken_rate, depth_mean


def _batch_flags(
    entry_ns: np.ndarray,
    exit_ns: np.ndarray,
    eps_gap_ns: int,
    k_min: int = 3,
    compression: float = 0.25,
) -> dict:
    """Batching-on-exit detection over one zone's completed stays
    (EXTENSIONS A2, following Klijn & Fahland's performance-spectrum batch
    mining, ported to zone boundaries).

    Inputs must be sorted by exit time. Consecutive exits with a gap
    <= ``eps_gap_ns`` form a candidate cluster; a cluster is a *batch* iff

    - it has at least ``k_min`` members, and
    - its exits are substantially more synchronized than its entries:
      exit span <= ``compression`` * entry span (with entry span > 0) —
      the "entries spread, exits clustered" signature of synchronized
      waiting. This also rejects steady high-throughput flow, where chained
      small exit gaps come with equally spread entries.

    Returns per-stay arrays (aligned with the input order) and per-batch
    arrays: ``batched`` (bool), ``wait_overhead_s`` (member sojourn minus the
    batch's minimum sojourn — the extra time attributable to waiting for the
    batch, 0 for unbatched stays), ``batch_last_exit_ns`` / ``batch_size``.
    """
    n = int(exit_ns.size)
    batched = np.zeros(n, dtype=bool)
    overhead_s = np.zeros(n, dtype=float)
    batch_last_exit = []
    batch_sizes = []
    if n >= k_min:
        gaps = np.diff(exit_ns)
        boundaries = np.flatnonzero(gaps > eps_gap_ns) + 1
        for lo, hi in zip(
            np.concatenate(([0], boundaries)), np.concatenate((boundaries, [n]))
        ):
            size = hi - lo
            if size < k_min:
                continue
            entry_span = int(entry_ns[lo:hi].max() - entry_ns[lo:hi].min())
            exit_span = int(exit_ns[hi - 1] - exit_ns[lo])
            if entry_span <= 0 or exit_span > compression * entry_span:
                continue
            batched[lo:hi] = True
            sojourn_s = (exit_ns[lo:hi] - entry_ns[lo:hi]) / 1e9
            overhead_s[lo:hi] = sojourn_s - sojourn_s.min()
            batch_last_exit.append(int(exit_ns[hi - 1]))
            batch_sizes.append(int(size))
    return {
        "batched": batched,
        "wait_overhead_s": overhead_s,
        "batch_last_exit_ns": np.asarray(batch_last_exit, dtype="int64"),
        "batch_size": np.asarray(batch_sizes, dtype="int64"),
    }


def transition_zone_map(net, zone_places: Dict[str, List[str]]) -> Dict[str, set]:
    """Map each transition name to the set of zones it is adjacent to
    (a zone containing at least one of the transition's input or output
    places). Boundary transitions map to every adjacent zone."""
    from process_model.replay import _petri_maps

    t_in_places, t_out_places, _ = _petri_maps(net)
    place_to_zone = {p: z for z, places in zone_places.items() for p in places}
    out: Dict[str, set] = {}
    for tname in set(t_in_places) | set(t_out_places):
        zones = {
            place_to_zone[p]
            for p in (t_in_places.get(tname, []) + t_out_places.get(tname, []))
            if p in place_to_zone
        }
        if zones:
            out[str(tname)] = zones
    return out


def _explode_zone_moves(
    alignment_moves_df: pd.DataFrame, t_zones: Dict[str, set]
) -> pd.DataFrame:
    """(case_id, ts, move_type, t_name) -> one row per (move, adjacent zone).
    Moves whose transition maps to no zone are dropped here — the window-level
    conformance metrics still account for them.

    ``weight`` is the move's unit mass split equally over its adjacent zones
    (1/k for a boundary move adjacent to k zones) — the documented
    normalization for zone-attributed fitness (EXTENSIONS A8): summing
    weights over zones recovers each attributable move exactly once, unlike
    the plain counts, where a boundary move deliberately counts for every
    adjacent zone."""
    df = alignment_moves_df.dropna(subset=["t_name"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["ts", "move_type", "zone", "weight"])
    df["zone"] = df["t_name"].map(lambda t: sorted(t_zones.get(str(t), ())))
    df = df[df["zone"].map(len) > 0]
    df["weight"] = 1.0 / df["zone"].map(len)
    df = df.explode("zone")
    df["ts"] = pd.to_datetime(df["ts"])
    return df[["ts", "move_type", "zone", "weight"]]


def build_zone_token_features_from_places(
    token_place_df: pd.DataFrame,
    zone_places: Dict[str, List[str]],
    timeframe: str = "D",
    trace_conformance_df: Optional[pd.DataFrame] = None,
    alignment_moves_df: Optional[pd.DataFrame] = None,
    net=None,
    case_zone_df: Optional[pd.DataFrame] = None,
    batch_eps_gap: str = "15min",
    batch_k_min: int = 3,
    batch_compression: float = 0.25,
    observation_start=None,
    observation_end=None,
) -> pd.DataFrame:
    """Zone-feature table. When ``alignment_moves_df`` (from
    conformance.alignment_move_table_from_alignments) and ``net`` are given,
    zone-attributed conformance columns (zone_sync_move_count,
    zone_log_move_count, zone_model_move_count, zone_deviation_count) are
    computed; otherwise they are present as zeros so the schema is stable.

    ``case_zone_df`` accepts a precomputed result of
    ``build_case_zone_stays_from_places`` on the same inputs, so callers that
    also persist the stays table don't compute it twice.

    Optional explicit observation boundaries define a fixed half-open grid for
    causal prefix callers; their input must already exclude events at/after end.
    Empty zones are represented on this grid. Default descriptive behavior is unchanged.

    Observation horizon is inferred from the complete input token-place
    table, before excluding unassigned places: from the earliest production
    through the latest known production or consumption. Every observed zone
    uses that same grid, including windows after its own activity stops.
    Known consumptions are never capped by an arbitrary grace period.

    Windows are half-open [w0, w1). The grid starts at the floored earliest
    production and ends at the first grid boundary strictly AFTER the last
    known timestamp, so an event on a boundary belongs to the next window.
    ``token_present_end`` is the balance immediately BEFORE w1: events at w1
    are processed in the following window. Open intervals remain present
    through the final window; they are not extrapolated into further windows.
    The last window is a full bin, so its occupancy and ages extend from the
    last observed timestamp to that bin's end. This is an interval-derived
    horizon, not an externally supplied event-log observation cutoff.

    ``batch_eps_gap``/``batch_k_min``/``batch_compression`` parameterize
    batching-on-exit detection (see ``_batch_flags``); the defaults are shared
    by every caller so oracle and API stay identical."""
    explicit_grid = observation_start is not None and observation_end is not None
    if (observation_start is None) != (observation_end is None):
        raise ValueError("Both explicit observation boundaries are required")
    if token_place_df.empty and not explicit_grid:
        return pd.DataFrame()

    place_to_zone = _validate_zone_places(zone_places)
    df = token_place_df.copy()
    df["produced_ts"] = pd.to_datetime(df["produced_ts"])
    df["consumed_ts"] = pd.to_datetime(df["consumed_ts"])
    grid_start, grid_end = observation_start, observation_end
    observation_start = df["produced_ts"].min()
    last_produced = df["produced_ts"].max()
    last_consumed = df["consumed_ts"].max()
    observation_end = (
        last_produced if pd.isna(last_consumed) else max(last_produced, last_consumed)
    )
    df["zone"] = df["place"].map(place_to_zone)
    df = df[df["zone"].notna()].copy()

    if df.empty and not explicit_grid:
        return pd.DataFrame()

    if case_zone_df is None:
        case_zone_df = build_case_zone_stays_from_places(token_place_df, zone_places)

    # zone-attributed alignment moves (owner-requested feature): explode each
    # timed move to its adjacent zones once, then count per zone/window below
    if alignment_moves_df is not None and net is not None and not alignment_moves_df.empty:
        zone_moves = _explode_zone_moves(alignment_moves_df, transition_zone_map(net, zone_places))
    else:
        zone_moves = pd.DataFrame(columns=["ts", "move_type", "zone", "weight"])

    t0 = pd.Timestamp(grid_start) if explicit_grid else observation_start.floor(timeframe)
    t1 = pd.Timestamp(grid_end) if explicit_grid else observation_end.ceil(timeframe)
    # windows are half-open [w0, w1); ceil() is a no-op for a timestamp landing
    # exactly on a grid boundary, which would drop that final event — extend
    # the grid one period in that case
    if not explicit_grid and t1 == observation_end:
        t1 = t1 + pd.tseries.frequencies.to_offset(timeframe)
    if explicit_grid:
        t0, t1 = pd.Timestamp(grid_start), pd.Timestamp(grid_end)
        if t0 >= t1 or t0.floor(timeframe) != t0 or t1.floor(timeframe) != t1:
            raise ValueError("Explicit observation boundaries must be increasing window boundaries")
        if ((df["produced_ts"] >= t1) | (df["consumed_ts"].notna() & (df["consumed_ts"] >= t1))).any():
            raise ValueError("Explicit prefix input must exclude events at or after observation end")
    grid = pd.date_range(t0, t1, freq=timeframe)

    out = []
    for zone in sorted(zone_places if explicit_grid else df["zone"].dropna().unique()):
        zdf = df[df["zone"] == zone].copy()
        if case_zone_df.empty:
            czdf = pd.DataFrame(columns=["case_id", "zone", "stay_id", "entry_ts", "exit_ts", "is_open", "duration"])
        else:
            czdf = case_zone_df[case_zone_df["zone"] == zone].copy()

        if explicit_grid and czdf.empty:
            for col in ("entry_ts", "exit_ts"):
                czdf[col] = pd.Series(dtype=df["produced_ts"].dtype)
            czdf["duration"] = pd.Series(dtype="timedelta64[ns]")

        # revisit/rework precomputation (EXTENSIONS A5): stay_id >= 2 marks a
        # revisit; the gap to the same case's previous stay in this zone is
        # positive by construction (overlapping intervals would have merged)
        if not czdf.empty:
            czdf = czdf.sort_values(["case_id", "stay_id"]).copy()
            czdf["prev_exit_ts"] = czdf.groupby("case_id")["exit_ts"].shift(1)
        else:
            czdf = czdf.copy()
            czdf["prev_exit_ts"] = pd.Series(dtype=df["produced_ts"].dtype if explicit_grid else "datetime64[ns]")

        # zone-level reference for aging metrics (EXTENSIONS A6): the median
        # completed token duration over the whole timeline — a stable yardstick
        # for "how old is too old" that does not drift with the window
        _zone_completed_durations = (
            (zdf["consumed_ts"] - zdf["produced_ts"]).dropna().dt.total_seconds()
        )
        zone_median_token_duration = (
            float(_zone_completed_durations.median())
            if not _zone_completed_durations.empty
            else np.nan
        )

        # batching-on-exit detection runs once over the zone's whole exit
        # timeline (EXTENSIONS A2); the window loop below buckets members by
        # their own exit time and batches by their last member's exit time
        completed_sorted = czdf[czdf["exit_ts"].notna()].sort_values("exit_ts")
        b_entry_ns = completed_sorted["entry_ts"].values.astype("datetime64[ns]").astype("int64")
        b_exit_ns = completed_sorted["exit_ts"].values.astype("datetime64[ns]").astype("int64")
        bf = _batch_flags(
            b_entry_ns,
            b_exit_ns,
            eps_gap_ns=int(pd.Timedelta(batch_eps_gap).value),
            k_min=int(batch_k_min),
            compression=float(batch_compression),
        )

        token_index = IntervalTimeIndex(zdf["produced_ts"], zdf["consumed_ts"])
        case_index = IntervalTimeIndex(czdf["entry_ts"], czdf["exit_ts"])
        move_rows = zone_moves[zone_moves["zone"] == zone] if not zone_moves.empty else zone_moves
        move_index = EventTimeIndex(move_rows["ts"])

        for i in range(len(grid) - 1):
            w0, w1 = grid[i], grid[i + 1]
            window_seconds = (w1 - w0).total_seconds()

            produced_rows = token_index.starts.between(w0, w1)
            consumed_rows = token_index.ends.between(w0, w1)
            present_rows = token_index.present_before(w1)
            token_enter, token_exit = len(produced_rows), len(consumed_rows)
            token_present_end = len(present_rows)
            occupancy_time_seconds = token_index.occupied_seconds(w0, w1)
            token_avg_present_window = occupancy_time_seconds / window_seconds if window_seconds > 0 else 0.0
            token_netflow = token_enter - token_exit
            completed_tokens = zdf.iloc[consumed_rows]
            token_avg_duration_completed = (
                float((completed_tokens["consumed_ts"] - completed_tokens["produced_ts"]).dt.total_seconds().mean())
                if not completed_tokens.empty
                else np.nan
            )

            open_tokens = zdf.iloc[present_rows]
            token_avg_age_open = (
                float((w1 - open_tokens["produced_ts"]).dt.total_seconds().mean())
                if not open_tokens.empty
                else np.nan
            )

            token_completion_ratio = float(token_exit) / float(token_enter) if token_enter > 0 else np.nan

            entering = czdf.iloc[case_index.starts.between(w0, w1)]
            completed_case_stays = czdf.iloc[case_index.ends.between(w0, w1)]
            present_cases = czdf.iloc[case_index.present_before(w1)]
            case_enter = int(entering["case_id"].nunique())
            case_exit = int(completed_case_stays["case_id"].nunique())
            case_present_end = int(present_cases["case_id"].nunique())
            # A stay ending exactly at w0 is active in this window under the
            # existing >= start definition, and is included in completed rows.
            case_active_window = int(pd.concat([present_cases["case_id"], completed_case_stays["case_id"]], ignore_index=True).nunique())
            case_avg_duration_completed = (
                float(completed_case_stays["duration"].dt.total_seconds().mean())
                if not completed_case_stays.empty
                else np.nan
            )
            case_completion_ratio = float(case_exit) / float(case_enter) if case_enter > 0 else np.nan

            # FIFO/overtaking order statistics over the window's completed
            # stays (EXTENSIONS A1) — needs valid entry AND exit timestamps
            order_stays = completed_case_stays[completed_case_stays["entry_ts"].notna()]
            case_fifo_inversion_ratio, case_overtaken_rate, case_overtake_depth_mean = (
                _order_inversion_stats(
                    order_stays["entry_ts"].values.astype("datetime64[ns]").astype("int64"),
                    order_stays["exit_ts"].values.astype("datetime64[ns]").astype("int64"),
                )
            )

            # sojourn tail + aging metrics (EXTENSIONS A6): SLA breaches live
            # in the tail, not the mean
            completed_durations = completed_case_stays["duration"].dt.total_seconds().dropna()
            if not completed_durations.empty:
                case_duration_p50 = float(np.percentile(completed_durations, 50))
                case_duration_p90 = float(np.percentile(completed_durations, 90))
            else:
                case_duration_p50 = case_duration_p90 = np.nan
            open_ages = (
                (w1 - open_tokens["produced_ts"]).dt.total_seconds()
                if not open_tokens.empty
                else pd.Series(dtype=float)
            )
            token_age_p90_open = (
                float(np.percentile(open_ages, 90)) if not open_ages.empty else np.nan
            )
            if not open_ages.empty and np.isfinite(zone_median_token_duration) and zone_median_token_duration > 0:
                token_aged_open_share = float((open_ages > 2 * zone_median_token_duration).mean())
                token_stagnation_index = float(open_ages.max() / zone_median_token_duration)
            else:
                token_aged_open_share = np.nan
                token_stagnation_index = np.nan

            # revisit/rework metrics (EXTENSIONS A5), bucketed by entry time
            stays_entering = int(len(entering))
            revisits = entering[entering["stay_id"] >= 2]
            case_revisit_enter = int(len(revisits))
            case_rework_ratio = (
                float(case_revisit_enter) / float(stays_entering) if stays_entering > 0 else np.nan
            )
            revisit_gaps = (revisits["entry_ts"] - revisits["prev_exit_ts"]).dropna()
            case_revisit_gap_mean = (
                float(revisit_gaps.dt.total_seconds().mean()) if not revisit_gaps.empty else np.nan
            )

            # batching metrics (EXTENSIONS A2), bucketed by exit time
            exit_lo, exit_hi = np.searchsorted(b_exit_ns, [w0.value, w1.value], side="left")
            if exit_hi > exit_lo:
                batched = bf["batched"][exit_lo:exit_hi]
                case_batching_ratio = float(batched.mean())
                member_overheads = bf["wait_overhead_s"][exit_lo:exit_hi][batched]
                case_batch_wait_overhead_mean = float(member_overheads.mean()) if member_overheads.size else np.nan
            else:
                case_batching_ratio = case_batch_wait_overhead_mean = np.nan
            batch_lo, batch_hi = np.searchsorted(bf["batch_last_exit_ns"], [w0.value, w1.value], side="left")
            case_batch_count = int(batch_hi - batch_lo)
            case_batch_size_mean = float(bf["batch_size"][batch_lo:batch_hi].mean()) if case_batch_count else np.nan

            zmv = move_rows.iloc[move_index.between(w0, w1)]
            if not zmv.empty:
                zone_sync = int((zmv["move_type"] == "sync").sum())
                zone_log = int((zmv["move_type"] == "log").sum())
                zone_model = int((zmv["move_type"] == "model").sum())
                sync_w = float(zmv.loc[zmv["move_type"] == "sync", "weight"].sum())
                dev_w = float(zmv.loc[zmv["move_type"] != "sync", "weight"].sum())
                zone_deviation_weight = dev_w
                zone_local_fitness = sync_w / (sync_w + dev_w) if (sync_w + dev_w) > 0 else np.nan
            else:
                zone_sync = zone_log = zone_model = 0
                zone_deviation_weight = 0.0
                zone_local_fitness = np.nan

            out.append(
                {
                    "zone": zone,
                    "window_start": w0,
                    "window_end": w1,
                    "token_enter": token_enter,
                    "token_exit": token_exit,
                    "token_present_end": token_present_end,
                    "token_avg_present_window": token_avg_present_window,
                    "token_netflow": token_netflow,
                    "token_avg_duration_completed": token_avg_duration_completed,
                    "token_avg_age_open": token_avg_age_open,
                    "token_completion_ratio": token_completion_ratio,
                    "token_age_p90_open": token_age_p90_open,
                    "token_aged_open_share": token_aged_open_share,
                    "token_stagnation_index": token_stagnation_index,
                    "case_enter": case_enter,
                    "case_exit": case_exit,
                    "case_active_window": case_active_window,
                    "case_present_end": case_present_end,
                    "case_avg_duration_completed": case_avg_duration_completed,
                    "case_completion_ratio": case_completion_ratio,
                    "case_duration_p50": case_duration_p50,
                    "case_duration_p90": case_duration_p90,
                    "case_fifo_inversion_ratio": case_fifo_inversion_ratio,
                    "case_overtaken_rate": case_overtaken_rate,
                    "case_overtake_depth_mean": case_overtake_depth_mean,
                    "case_batch_count": case_batch_count,
                    "case_batch_size_mean": case_batch_size_mean,
                    "case_batching_ratio": case_batching_ratio,
                    "case_batch_wait_overhead_mean": case_batch_wait_overhead_mean,
                    "case_revisit_enter": case_revisit_enter,
                    "case_rework_ratio": case_rework_ratio,
                    "case_revisit_gap_mean": case_revisit_gap_mean,
                    "zone_sync_move_count": zone_sync,
                    "zone_log_move_count": zone_log,
                    "zone_model_move_count": zone_model,
                    "zone_deviation_count": zone_log + zone_model,
                    "zone_deviation_weight": zone_deviation_weight,
                    "zone_local_fitness": zone_local_fitness,
                }
            )

    feat = pd.DataFrame(out)
    if feat.empty:
        return feat
    feat = feat.sort_values(["zone", "window_start"]).reset_index(drop=True)
    return add_window_conformance_features(feat, trace_conformance_df)


def add_compound_metrics(zone_feat: pd.DataFrame) -> pd.DataFrame:
    return zone_feat


def run_pipeline(
    log_path: str,
    pnml_path: Optional[str],
    zone_places: Dict[str, List[str]],
    timeframe: str = "D",
):
    if log_path.lower().endswith(".xes"):
        log = load_any_log(log_path)
    elif log_path.lower().endswith(".csv"):
        log = load_csv_log(log_path)
    else:
        raise ValueError("Unsupported log format (use .xes or .csv)")

    if pnml_path:
        net, im, fm = load_pnml(pnml_path)
    else:
        net, im, fm = discover_petri_net_from_log(log)

    aligned = compute_alignments(log, net, im, fm)
    token_place_df = token_place_table_from_alignments(log, net, im, fm, aligned=aligned)
    trace_conformance_df = trace_conformance_table_from_alignments(log, aligned)
    case_zone_stays = build_case_zone_stays_from_places(token_place_df, zone_places)
    zone_feat = build_zone_token_features_from_places(
        token_place_df,
        zone_places,
        timeframe=timeframe,
        trace_conformance_df=trace_conformance_df,
    )
    zone_diag, place_diag = add_leak_diagnostics(token_place_df, zone_feat, zone_places, fm=fm)

    return {
        "log": log,
        "net": net,
        "im": im,
        "fm": fm,
        "token_place_df": token_place_df,
        "trace_conformance_df": trace_conformance_df,
        "case_zone_stays": case_zone_stays,
        "zone_features": zone_feat,
        "zone_leak_diag": zone_diag,
        "place_leak_diag": place_diag,
    }
