"""A small database of riders (body measurements) saved per user.

Each rider is a named set of the physical-measurement parameters (the person,
not the bike), stored as JSON in the user config dir so it can be applied to any
design and drive the fit advisor. Bike-setup values are deliberately excluded.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import params as P
from .library import config_dir


def _ensure_params() -> None:
    """Rider measurement params are registered by bikebox.fit.rider; make sure
    that has run so this works even when used headlessly without the GUI."""
    if not P.has("rider_height"):
        import bikebox.fit.rider  # noqa: F401  (registers the rider params)

# the body/anatomy parameters that describe a rider (not the bike)
RIDER_KEYS = [
    "rider_height", "inseam", "torso_length", "arm_length", "shoulder_width", "foot_length", "rider_mass",
    "thigh_length", "lower_leg_length", "upper_arm_length", "forearm_length", "head_neck_length",
    "hip_above_saddle", "hip_forward", "cleat_offset", "ankle_angle", "ankling", "elbow_bend", "head_tilt",
    "fit_flexibility",
]


def _file() -> Path:
    return config_dir() / "riders.json"


def load_all() -> dict[str, dict]:
    """{name: {param: value}} of saved riders (empty if none)."""
    p = _file()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("riders", {}) if isinstance(data, dict) else {}


def _write(riders: dict[str, dict]) -> Path:
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"format": "bikebox-riders", "version": 1, "riders": riders}, indent=1),
                   encoding="utf-8")
    tmp.replace(p)
    return p


def rider_from_design(design) -> dict[str, Any]:
    """The rider measurements currently set on a design."""
    _ensure_params()
    return {k: design.get(k) for k in RIDER_KEYS if P.has(k)}


def save(name: str, values: dict[str, Any]) -> Path:
    name = name.strip()
    riders = load_all()
    riders[name] = {k: v for k, v in values.items() if k in RIDER_KEYS}
    return _write(riders)


def delete(name: str) -> None:
    riders = load_all()
    if name in riders:
        del riders[name]
        _write(riders)


def apply(design, name_or_values) -> list[str]:
    """Apply a rider (by saved name or a values dict) to the design; returns
    the keys whose value changed."""
    _ensure_params()
    values = load_all().get(name_or_values, {}) if isinstance(name_or_values, str) else dict(name_or_values)
    changed = []
    for k, v in values.items():
        if k in RIDER_KEYS and P.has(k):
            old = design.get(k)
            try:
                new = design.set(k, v)
            except (TypeError, ValueError):
                continue
            if new != old:
                changed.append(k)
    return changed
