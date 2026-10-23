from __future__ import annotations


def corr_strength(c: float) -> str:
    a = abs(c)
    if a >= 0.9:
        return "very strong"
    if a >= 0.7:
        return "strong"
    if a >= 0.5:
        return "moderate"
    return "weak"


def corr_direction(c: float) -> str:
    return "moves together" if c >= 0 else "moves opposite"


def corr_basic_label(c: float) -> str:
    strength = "strong" if abs(c) >= 0.7 else "weak"
    direction = "together" if c >= 0 else "opposite"
    return f"{strength} {direction}"

