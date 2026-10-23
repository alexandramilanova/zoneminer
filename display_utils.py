from __future__ import annotations

import pandas as pd


_TIMEFRAME_TO_SECONDS = {
    "Hourly": 3600.0,
    "Daily": 86400.0,
    "Weekly": 7 * 86400.0,
    "Monthly": 30 * 86400.0,
}

_TIMEFRAME_TO_LABEL = {
    "Hourly": "hours",
    "Daily": "days",
    "Weekly": "weeks",
    "Monthly": "months",
}


def get_duration_unit_seconds(timeframe_label: str) -> float:
    return _TIMEFRAME_TO_SECONDS.get(timeframe_label, 86400.0)


def get_duration_unit_label(timeframe_label: str) -> str:
    return _TIMEFRAME_TO_LABEL.get(timeframe_label, "days")


def duration_to_display(x, timeframe_label: str):
    """
    Convert duration values from raw seconds into the current display unit
    (hours / days / weeks / months).
    Works for scalars and pandas Series.
    """
    unit_seconds = get_duration_unit_seconds(timeframe_label)
    x = pd.to_numeric(x, errors="coerce")
    return x / unit_seconds


def format_duration(x, timeframe_label: str, decimals: int = 2) -> str:
    """
    Format one duration value for cards/tables, e.g. '1.25 days'.
    Assumes x is stored in raw seconds.
    """
    x = pd.to_numeric(x, errors="coerce")
    if pd.isna(x):
        return "—"

    unit_label = get_duration_unit_label(timeframe_label)
    unit_seconds = get_duration_unit_seconds(timeframe_label)
    return f"{x / unit_seconds:.{decimals}f} {unit_label}"


def format_number(x, decimals: int = 2, na_text: str = "—") -> str:
    """
    Safe generic numeric formatter for cards/tables.
    """
    x = pd.to_numeric(x, errors="coerce")
    if pd.isna(x):
        return na_text
    return f"{x:.{decimals}f}"