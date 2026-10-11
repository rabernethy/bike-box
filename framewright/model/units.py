"""Unit conversion and formatting."""
from __future__ import annotations

MM_PER_IN = 25.4


def to_display(mm: float, units: str) -> float:
    return mm / MM_PER_IN if units == "in" else mm


def from_display(value: float, units: str) -> float:
    return value * MM_PER_IN if units == "in" else value


def fmt_len(mm: float, units: str = "mm", decimals: int | None = None, suffix: bool = False) -> str:
    if mm != mm:            # NaN
        return "–"
    if units == "in":
        d = 2 if decimals is None else decimals
        s = f"{mm / MM_PER_IN:.{d}f}"
        return s + ('"' if suffix else "")
    d = 1 if decimals is None else decimals
    s = f"{mm:.{d}f}"
    return s + (" mm" if suffix else "")


def fmt_angle(deg: float, decimals: int = 1) -> str:
    if deg != deg:
        return "–"
    return f"{deg:.{decimals}f}°"


def fmt_value(value: float, unit: str, units: str = "mm") -> str:
    """Format a value whose schema unit is ``unit`` ('mm', 'deg', ...)."""
    if unit == "mm":
        return fmt_len(value, units)
    if unit == "deg":
        return fmt_angle(value)
    if unit == "g":
        return f"{value:.0f} g"
    if unit == "%":
        return f"{value:.1f} %"
    return f"{value:g}"
