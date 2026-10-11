"""Parts catalog: schema validation and helpers.

The catalog (``framewright/data/catalog/*.json``) holds real components with
sourced specifications; see ``docs/CATALOG.md``.  Files use the library format,
so :mod:`framewright.model.library` loads them alongside the generic libraries.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import params as P

CATALOG_DIR = Path(__file__).resolve().parents[1] / "data" / "catalog"

ALLOWED: dict[str, set[str]] = {
    "forks": {"fork_type", "fork_length", "fork_offset", "fork_travel", "fork_stanchion_od", "fork_crown_height",
              "fork_crown_width", "fork_blade_shape", "front_hub_spacing", "steerer_od", "fork_material"},
    "tubing": {"material", "tubes"},
    "frame_hardware": {"bb_shell_od", "bb_shell_width", "lug_ht_angle", "lug_st_angle", "dropout_type",
                       "rear_hub_spacing", "front_hub_spacing", "ht_od_top", "ht_od_bottom"},
    "dropouts": {"dropout_type", "rear_hub_spacing", "front_hub_spacing", "brake_rear", "brake_front"},
    "rims": {"front_bsd", "rear_bsd", "rim_depth_front", "rim_depth_rear", "spokes_front", "spokes_rear"},
    "hubs": {"front_hub_spacing", "rear_hub_spacing", "hub_flange_front", "hub_flange_rear", "spokes_front",
             "spokes_rear"},
    "tires": {"front_bsd", "rear_bsd", "front_tire_width", "rear_tire_width", "front_tire_height",
              "rear_tire_height"},
    "stems": {"stem_type", "stem_length", "stem_angle", "stem_clamp_height", "steerer_od", "bar_od", "quill_height"},
    "handlebars": {"bar_type", "bar_reach", "bar_drop", "bar_rise", "bar_backsweep", "bar_width", "bar_od"},
    "cranks": {"crank_length", "chainrings", "chainline", "q_factor", "drive_type"},
    "cassettes": {"cogs", "drive_type"},
    "drivetrain": {"front_derailleur", "drive_type", "chainrings", "cogs"},
    "headsets": {"lower_stack", "upper_stack", "steerer_od"},
    "bb_shells": {"bb_shell_od", "bb_shell_width"},
    "brakes": {"brake_front", "brake_rear", "rotor_front", "rotor_rear", "brake_reach"},
    "saddles": {"saddle_length", "saddle_stack"},
    "seatposts": {"seatpost_od", "seatpost_offset", "seatpost_length", "seatpost_min_insertion", "seatpost_type",
                  "dropper_travel"},
}
TUBE_KEYS = {"tt", "dt", "st", "ht", "cs", "ss", "fork_blade", "steerer"}
TUBE_FIELDS = {"od", "wall", "butt_length", "od_end", "od_tip", "od_bottom", "profile", "od2", "length_mm",
               "butt_lengths", "notes", "taper_length"}
SOURCE_KINDS = {"manufacturer", "distributor", "retailer", "independent"}
STATUSES = {"current", "discontinued", "unknown"}
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_WALL = re.compile(r"^\d+(\.\d+)?(/\d+(\.\d+)?)*$")


def _check_value(key: str, val: Any) -> str | None:
    if not P.has(key):
        return f"unknown parameter {key!r}"
    pd = P.get(key)
    if pd.kind in (P.FLOAT, P.INT):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return f"{key} must be a number, got {val!r}"
        if pd.min is not None and val < pd.min or pd.max is not None and val > pd.max:
            return f"{key}={val} outside {pd.min}..{pd.max}"
    elif pd.kind == P.CHOICE:
        if str(val) not in {c[0] for c in pd.choices}:
            return f"{key}={val!r} not one of {[c[0] for c in pd.choices]}"
    elif pd.kind == P.LIST:
        if not P.parse_list(val):
            return f"{key} must be a list of numbers, got {val!r}"
    elif pd.kind == P.BOOL and not isinstance(val, bool):
        return f"{key} must be true/false"
    return None


def _check_tubes(tubes: Any) -> list[str]:
    errs = []
    if not isinstance(tubes, dict) or not tubes:
        return ["tubes must be a non-empty object"]
    for name, spec in tubes.items():
        if name not in TUBE_KEYS:
            errs.append(f"tubes: unknown tube {name!r}")
            continue
        if not isinstance(spec, dict):
            errs.append(f"tubes.{name} must be an object")
            continue
        for f, v in spec.items():
            if f not in TUBE_FIELDS:
                errs.append(f"tubes.{name}: unknown field {f!r}")
        od = spec.get("od")
        if od is not None and (not isinstance(od, (int, float)) or not 5 <= od <= 80):
            errs.append(f"tubes.{name}.od={od!r} implausible")
        wall = spec.get("wall")
        if wall is not None:
            if isinstance(wall, (int, float)):
                ok = 0.2 <= wall <= 6
            else:
                ok = bool(_WALL.match(str(wall))) and all(0.2 <= float(x) <= 6 for x in str(wall).split("/"))
            if not ok:
                errs.append(f"tubes.{name}.wall={wall!r} invalid")
    return errs


def validate_item(item: Any, category: str) -> list[str]:
    errs: list[str] = []
    if not isinstance(item, dict):
        return ["item is not an object"]
    iid = item.get("id")
    if not isinstance(iid, str) or not _SLUG.match(iid):
        errs.append(f"bad id {iid!r}")
    if not str(item.get("name") or "").strip():
        errs.append("missing name")
    if item.get("category", category) != category:
        errs.append(f"category {item.get('category')!r} != file category {category!r}")
    values = item.get("values")
    if not isinstance(values, dict):
        errs.append("values must be an object")
        values = {}
    allowed = ALLOWED.get(category)
    for k, v in values.items():
        if allowed is not None and k not in allowed:
            errs.append(f"value key {k!r} not allowed for {category}")
            continue
        if k == "tubes":
            errs += _check_tubes(v)
        elif k == "material":
            if str(v) not in {c[0] for c in P.MATERIALS}:
                errs.append(f"material {v!r} unknown")
        else:
            e = _check_value(k, v)
            if e:
                errs.append(e)
    meta = item.get("meta")
    if not isinstance(meta, dict):
        return errs + ["meta must be an object"]
    if not str(meta.get("brand") or "").strip():
        errs.append("meta.brand missing")
    srcs = meta.get("sources")
    if not isinstance(srcs, list) or not srcs:
        errs.append("meta.sources must list at least one source")
    else:
        for s in srcs:
            if not isinstance(s, dict) or not str(s.get("url", "")).startswith(("http://", "https://")):
                errs.append(f"bad source {s!r}")
            elif s.get("kind") not in SOURCE_KINDS:
                errs.append(f"source kind {s.get('kind')!r} not in {sorted(SOURCE_KINDS)}")
    if meta.get("status") not in STATUSES:
        errs.append(f"meta.status {meta.get('status')!r} not in {sorted(STATUSES)}")
    specs = meta.get("specs")
    if specs is not None and not isinstance(specs, dict):
        errs.append("meta.specs must be an object")
    derived = meta.get("derived") or {}
    if not isinstance(derived, dict) or any(k not in values for k in derived):
        errs.append("meta.derived keys must be keys of values")
    return errs


def validate_file(path: str | Path) -> list[str]:
    path = Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{path.name}: cannot read: {exc}"]
    if not isinstance(doc, dict) or doc.get("format") != "framewright-library":
        return [f"{path.name}: not a framewright-library document"]
    cat = str(doc.get("category") or "")
    if cat not in ALLOWED:
        return [f"{path.name}: unknown category {cat!r}"]
    errs = []
    seen: set[str] = set()
    for i, item in enumerate(doc.get("items") or []):
        for e in validate_item(item, cat):
            errs.append(f"{path.name}[{i}] {item.get('id') if isinstance(item, dict) else ''}: {e}")
        iid = item.get("id") if isinstance(item, dict) else None
        if iid in seen:
            errs.append(f"{path.name}[{i}]: duplicate id {iid!r}")
        seen.add(iid)
    if not doc.get("items"):
        errs.append(f"{path.name}: no items")
    return errs


def catalog_files() -> list[Path]:
    return sorted(CATALOG_DIR.glob("*.json")) if CATALOG_DIR.is_dir() else []


def stats() -> dict[str, int]:
    out = {}
    for f in catalog_files():
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
            out[str(doc.get("category"))] = len(doc.get("items") or [])
        except (OSError, ValueError):
            continue
    return out


if __name__ == "__main__":                      # python3 -m framewright.model.catalog [files]
    import sys
    # register parameters from feature modules so every key validates
    for mod in ("framewright.geometry.solver", "framewright.geometry.clearance"):
        __import__(mod)
    files = [Path(a) for a in sys.argv[1:]] or catalog_files()
    total = 0
    for f in files:
        errs = validate_file(f)
        total += len(errs)
        n = len(json.loads(f.read_text(encoding="utf-8")).get("items") or []) if f.exists() else 0
        print(f"{f.name}: {n} items, {len(errs)} problems")
        for e in errs[:200]:
            print("  " + e)
    sys.exit(1 if total else 0)
