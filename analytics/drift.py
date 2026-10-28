"""Per-zone multivariate drift scores.

One series per zone answering "how much did this zone's *overall* behavior
change here?" — complementary to PELT change points on single metrics
(analytics/changepoints.py), which localize shifts per metric. Concept drift
in process mining is well studied (Bose et al., CAiSE 2011 / IEEE TNNLS
2014); zones give it a mid-level granularity between single activities and
the whole process.

Method: for each zone, take its windowed feature vectors (numeric metrics,
z-scored per zone over the whole timeline; the window-level ``alignment_*``
columns are excluded because they are identical across zones by design).
At window t, the drift score is the **energy distance** between the
distribution of the trailing ``half_window`` feature vectors and the leading
``half_window`` vectors:

    E(X, Y) = 2 E||x - y|| - E||x - x'|| - E||y - y'||

Energy distance is zero iff the distributions are equal and needs no
binning, which suits the short samples windowed data gives us. Scores are
descriptive change intensities — they say *that* and *how much* behavior
around t differs, not why.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

EXCLUDED_PREFIXES = ("alignment_",)
ID_COLUMNS = {"zone", "window_start", "window_end"}


def _energy_distance(x: np.ndarray, y: np.ndarray) -> float:
    """Energy distance between two multivariate samples (rows = samples)."""

    def mean_pairwise(a: np.ndarray, b: np.ndarray) -> float:
        d = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=2))
        return float(d.mean())

    return max(0.0, 2 * mean_pairwise(x, y) - mean_pairwise(x, x) - mean_pairwise(y, y))


def zone_drift_scores(
    zf: pd.DataFrame,
    zones: Optional[List[str]] = None,
    metrics: Optional[List[str]] = None,
    half_window: int = 5,
) -> pd.DataFrame:
    """Long frame [zone, window_start, drift_score].

    ``drift_score`` is NaN for the first/last ``half_window`` windows of each
    zone (not enough trailing/leading sample). NaN feature values are filled
    with the zone's column mean before z-scoring; constant columns are
    dropped per zone.
    """
    if zf.empty:
        return pd.DataFrame(columns=["zone", "window_start", "drift_score"])

    zone_list = zones or sorted(zf["zone"].dropna().unique().tolist())
    metric_list = metrics or [
        c
        for c in zf.columns
        if c not in ID_COLUMNS
        and not c.startswith(EXCLUDED_PREFIXES)
        and pd.api.types.is_numeric_dtype(zf[c])
    ]

    rows = []
    k = int(half_window)
    for zone in zone_list:
        g = zf[zf["zone"] == zone].sort_values("window_start")
        windows = g["window_start"].tolist()
        mat = g[metric_list].astype(float)
        mat = mat.fillna(mat.mean())
        std = mat.std(ddof=0)
        keep = std[std > 0].index
        if len(keep) == 0 or len(g) < 2 * k:
            for w in windows:
                rows.append({"zone": zone, "window_start": w, "drift_score": np.nan})
            continue
        z = ((mat[keep] - mat[keep].mean()) / std[keep]).to_numpy()
        # normalize by sqrt(dims) so scores are comparable across zones with
        # different numbers of informative features
        z = z / np.sqrt(z.shape[1])
        for i, w in enumerate(windows):
            if i < k or i + k > len(windows):
                rows.append({"zone": zone, "window_start": w, "drift_score": np.nan})
                continue
            score = _energy_distance(z[i - k : i], z[i : i + k])
            rows.append({"zone": zone, "window_start": w, "drift_score": score})
    return pd.DataFrame(rows, columns=["zone", "window_start", "drift_score"])
