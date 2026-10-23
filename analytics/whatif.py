"""What-if capacity analysis per zone (EXTENSIONS C2, experimental).

A deliberately small, honest counterfactual: keep the zone's *actual arrival
moments* and each case's mined *service demand*, replay them through a
c-server FCFS queue, and let the user scale c. Everything else is held
fixed — in reality arrivals would react to upstream changes, so results are
approximations for building intuition, not guarantees, and every consumer of
this module says so.

- Service demands are resampled from the zone's low-load sojourns (what a
  case experiences when nothing queues ahead of it), permuted with a fixed
  seed for reproducibility.
- The baseline capacity c0 is *calibrated*: the smallest c whose simulated
  mean wait best matches the measured mean wait. A constant-c fit of a
  time-varying system is an approximation; how well the baseline curve
  tracks the measured occupancy is shown to the user as the validity check.
"""

from __future__ import annotations

import heapq

import numpy as np
import pandas as pd


def simulate_queue(
    arrivals_s: np.ndarray, services_s: np.ndarray, c: int
) -> tuple[np.ndarray, np.ndarray]:
    """FCFS c-server queue: returns (wait_s, finish_s) per case.

    ``arrivals_s`` must be sorted ascending; both arrays are seconds.
    """
    free: list[float] = [0.0] * max(1, int(c))
    heapq.heapify(free)
    waits = np.empty(arrivals_s.size)
    finishes = np.empty(arrivals_s.size)
    for i in range(arrivals_s.size):
        t = float(arrivals_s[i])
        earliest = heapq.heappop(free)
        start = max(t, earliest)
        finish = start + float(services_s[i])
        waits[i] = start - t
        finishes[i] = finish
        heapq.heappush(free, finish)
    return waits, finishes


def occupancy_curve(
    arrivals_s: np.ndarray, finishes_s: np.ndarray, grid_s: np.ndarray
) -> np.ndarray:
    """Number in system at each grid time (arrival <= t < finish)."""
    a = np.sort(arrivals_s)
    f = np.sort(finishes_s)
    return np.searchsorted(a, grid_s, side="right") - np.searchsorted(f, grid_s, side="right")


def whatif_capacity(
    stays: pd.DataFrame,
    zone: str,
    capacity_multiplier: float = 1.0,
    max_capacity_search: int = 300,
    grid_points: int = 120,
    seed: int = 42,
) -> dict | None:
    """Calibrate a constant-c queue to the zone, then re-run with scaled c.

    Returns None when the zone has too little data (< 20 completed stays).
    """
    g = stays[(stays["zone"] == zone) & stays["exit_ts"].notna()].copy()
    if len(g) < 20:
        return None
    g = g.sort_values("entry_ts")
    t0 = g["entry_ts"].min()
    arrivals = (g["entry_ts"] - t0).dt.total_seconds().to_numpy(dtype=float)
    sojourn = g["duration_s"].to_numpy(dtype=float)
    measured_finish = arrivals + sojourn

    # mined service demand: low-load sojourns, deterministically permuted
    lo_cut = np.percentile(sojourn, 25)
    low_load = sojourn[sojourn <= lo_cut]
    if low_load.size < 5:
        low_load = sojourn
    rng = np.random.RandomState(seed)
    services = low_load[rng.randint(0, low_load.size, size=arrivals.size)]

    measured_mean_sojourn = float(sojourn.mean())

    # calibrate c against the mean *sojourn* (wait + service): the simulated
    # sojourn falls monotonically toward the mean service demand as c grows,
    # so scan until it drops below the measured value and keep the best fit
    best = None
    for c in range(1, int(max_capacity_search) + 1):
        waits, finishes = simulate_queue(arrivals, services, c)
        sim_sojourn = float((waits + services).mean())
        err = abs(sim_sojourn - measured_mean_sojourn)
        if best is None or err < best[0]:
            best = (err, c, waits, finishes, sim_sojourn)
        if sim_sojourn < measured_mean_sojourn:
            break
    _, c0, base_waits, base_finishes, base_sojourn = best

    # calibration quality gate: when no constant c reproduces the measured
    # sojourns (e.g. the waiting is imposed by an external constraint rather
    # than the zone's own service times, or by a regime shift), the
    # counterfactual would be built on a fiction — report that instead of a
    # bogus baseline
    rel_err = abs(base_sojourn - measured_mean_sojourn) / max(measured_mean_sojourn, 1.0)
    calibrated = bool(rel_err <= 0.35)

    c_new = max(1, int(round(c0 * float(capacity_multiplier))))
    new_waits, new_finishes = simulate_queue(arrivals, services, c_new)

    horizon = float(max(measured_finish.max(), base_finishes.max(), new_finishes.max()))
    grid = np.linspace(0.0, horizon, int(grid_points))
    to_iso = lambda s: str(t0 + pd.Timedelta(seconds=float(s)))  # noqa: E731

    def summary(waits: np.ndarray, finishes: np.ndarray) -> dict:
        occ = occupancy_curve(arrivals, finishes, grid)
        return {
            "mean_wait_s": float(waits.mean()),
            "p90_wait_s": float(np.percentile(waits, 90)),
            "peak_backlog": int(occ.max()),
        }

    return {
        "zone": zone,
        "cases": int(arrivals.size),
        "calibration": {
            "fitted_capacity": int(c0),
            "measured_mean_sojourn_s": measured_mean_sojourn,
            "simulated_mean_sojourn_s": base_sojourn,
            "relative_error": rel_err,
            "calibrated": calibrated,
        },
        "capacity_multiplier": float(capacity_multiplier),
        "whatif_capacity": c_new,
        "baseline": summary(base_waits, base_finishes),
        "whatif": summary(new_waits, new_finishes),
        "curves": {
            "t": [to_iso(s) for s in grid],
            "measured_occ": occupancy_curve(arrivals, measured_finish, grid).tolist(),
            "baseline_occ": occupancy_curve(arrivals, base_finishes, grid).tolist(),
            "whatif_occ": occupancy_curve(arrivals, new_finishes, grid).tolist(),
        },
    }
