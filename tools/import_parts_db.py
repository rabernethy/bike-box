"""Convert a framebuilder parts database into FrameWright library files.

Reads the ``parts.json`` of a framebuilder parts database (a JSON document
``{"meta": {...}, "parts": [...]}`` whose parts carry ``category``,
``subcategory``, ``vendor``, ``name``, ``material``, ``alloy`` and ``specs``)
and writes:

* ``framewright/data/libraries/tubing.json``   - one item per tube set
* ``framewright/data/libraries/dropouts.json`` - rear dropouts and fork ends

Only names and numeric/short specifications are copied; long descriptions,
notes, prices, images and URLs are left out.  Tube walls keep the database's
butting strings (``"0.9/0.6/0.9"``) - :func:`framewright.model.library.apply`
turns them into ``*_wall_end`` / ``*_wall_mid`` when an item is applied.

Usage::

    /usr/bin/python3 tools/import_parts_db.py [path/to/parts.json] [--out DIR]

The default source is ``../framebuilder-parts-db/data/parts.json`` next to the
FrameWright checkout (override with ``$FRAMEBUILDER_PARTS_DB``).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "framewright" / "data" / "libraries"
DEFAULT_SOURCE = ROOT.parent / "framebuilder-parts-db" / "data" / "parts.json"

FORMAT = "framewright-library"
VERSION = 1

# database tube names -> FrameWright tube keys (see model/library.py)
TUBE_KEYS = {
    "top_tube": "tt", "down_tube": "dt", "seat_tube": "st", "head_tube": "ht",
    "chain_stay": "cs", "chainstay": "cs", "seat_stay": "ss", "seatstay": "ss",
    "fork_blade": "fork_blade", "steerer": "steerer",
}
TUBE_ORDER = ["tt", "dt", "st", "ht", "cs", "ss", "fork_blade", "steerer"]
MATERIALS = {"steel", "stainless", "titanium", "aluminium", "aluminium7005", "carbon", "scandium", "bamboo", "wood"}
MATERIAL_ALIASES = {"aluminum": "aluminium", "chromoly": "steel", "crmo": "steel", "cromo": "steel"}


def _num(v: Any) -> float | int | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        f = float(str(v).strip())
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def _wall(v: Any) -> str | float | None:
    """Keep butting strings as ``"a/b/a"`` (normalised), plain numbers as numbers."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if not isinstance(v, str):
        return None
    parts = [p.strip().removesuffix("mm").strip() for p in v.split("/")]
    try:
        nums = [float(p) for p in parts if p]
    except ValueError:
        return None
    if not nums:
        return None
    if len(nums) == 1:
        return nums[0]
    return "/".join(f"{n:g}" for n in nums)


def _material(m: Any) -> str | None:
    m = str(m or "").strip().lower()
    m = MATERIAL_ALIASES.get(m, m)
    return m if m in MATERIALS else None


def _years(p: dict) -> str:
    a, b = p.get("year_introduced"), p.get("year_discontinued")
    if a and b:
        return f"{a}-{b}"
    if a:
        return f"{a}-"
    return ""


def _common_meta(p: dict) -> dict:
    meta = {"vendor": p.get("vendor") or "", "series": p.get("name") or ""}
    if p.get("alloy"):
        meta["alloy"] = p["alloy"]
    if p.get("material"):
        meta["material"] = p["material"]
    years = _years(p)
    if years:
        meta["years"] = years
    if p.get("availability"):
        meta["availability"] = p["availability"]
    tags = [t for t in (p.get("tags") or []) if isinstance(t, str) and len(t) <= 40]
    if tags:
        meta["tags"] = tags
    meta["source"] = "framebuilder-parts-db"
    return meta


def convert_tubing(p: dict) -> dict | None:
    specs = p.get("specs") or {}
    raw = specs.get("tubes") or {}
    tubes: dict[str, dict] = {}
    for name, t in raw.items():
        key = TUBE_KEYS.get(str(name).lower())
        if key is None or not isinstance(t, dict):
            continue
        od = _num(t.get("od_mm", t.get("od")))
        wall = _wall(t.get("wall_mm", t.get("wall")))
        if od is None:
            continue
        spec: dict[str, Any] = {"od": od}
        if wall is not None:
            spec["wall"] = wall
        tubes[key] = spec
    if not tubes:
        return None
    tubes = {k: tubes[k] for k in TUBE_ORDER if k in tubes}
    values: dict[str, Any] = {}
    mat = _material(p.get("material"))
    if mat:
        values["material"] = mat
    values["tubes"] = tubes
    meta = _common_meta(p)
    for k in ("butting", "treatment"):
        if specs.get(k):
            meta[k] = specs[k]
    for k in ("tensile_mpa", "set_weight_g"):
        n = _num(specs.get(k))
        if n is not None:
            meta[k] = n
    return {"id": p["id"], "name": f"{p.get('vendor', '')} {p.get('name', '')}".strip(),
            "values": values, "meta": meta}


def convert_dropout(p: dict) -> dict | None:
    specs = p.get("specs") or {}
    front = p.get("subcategory") == "fork_end"
    spacing = [n for n in (_num(s) for s in (specs.get("spacing_mm") or [])) if n is not None]
    if isinstance(specs.get("spacing_mm"), (int, float)):
        spacing = [_num(specs["spacing_mm"])]
    values: dict[str, Any] = {}
    if spacing:
        values["front_hub_spacing" if front else "rear_hub_spacing"] = max(spacing)
    disc = str(specs.get("disc_mount") or "none").lower()
    if disc not in ("", "none", "no"):
        values["brake_front" if front else "brake_rear"] = "disc"
    meta = _common_meta(p)
    meta["position"] = "front" if front else "rear"
    meta["kind"] = p.get("subcategory") or ""
    for k in ("type", "axle", "disc_mount", "der_hanger", "construction", "attachment"):
        if specs.get(k):
            meta[k] = specs[k]
    if spacing:
        meta["spacing_mm"] = spacing
    return {"id": p["id"], "name": f"{p.get('vendor', '')} {p.get('name', '')}".strip(),
            "values": values, "meta": meta}


def library(category: str, label: str, items: list[dict], source: str) -> dict:
    return {"format": FORMAT, "version": VERSION, "category": category, "label": label,
            "source": source, "items": items}


def convert(data: dict) -> tuple[dict, dict]:
    parts = data.get("parts") or []
    tubing, dropouts = [], []
    for p in parts:
        if not isinstance(p, dict) or "id" not in p:
            continue
        cat, sub = p.get("category"), p.get("subcategory")
        if cat == "tubing" or sub == "tube_set":
            item = convert_tubing(p)
            if item:
                tubing.append(item)
        elif cat == "dropout":
            item = convert_dropout(p)
            if item:
                dropouts.append(item)
    tubing.sort(key=lambda i: (i["meta"].get("vendor", "").lower(), i["name"].lower()))
    dropouts.sort(key=lambda i: (i["meta"]["position"] != "rear", i["meta"].get("vendor", "").lower(),
                                 i["name"].lower()))
    src = "framebuilder-parts-db"
    version = (data.get("meta") or {}).get("version")
    if version:
        src += f" {version}"
    return (library("tubing", "Tubing", tubing, src), library("dropouts", "Dropouts", dropouts, src))


def write_json(path: Path, doc: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Convert a framebuilder parts database to FrameWright libraries")
    ap.add_argument("source", nargs="?", type=Path,
                    default=Path(os.environ.get("FRAMEBUILDER_PARTS_DB", DEFAULT_SOURCE)))
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    if not args.source.is_file():
        print(f"parts database not found: {args.source}", file=sys.stderr)
        return 1
    data = json.loads(args.source.read_text(encoding="utf-8"))
    tubing, dropouts = convert(data)
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / "tubing.json", tubing)
    write_json(args.out / "dropouts.json", dropouts)
    print(f"tubing: {len(tubing['items'])} tube sets -> {args.out / 'tubing.json'}")
    print(f"dropouts: {len(dropouts['items'])} dropouts -> {args.out / 'dropouts.json'}")
    return 0


if __name__