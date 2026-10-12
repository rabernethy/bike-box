"""Component and tubing libraries.

Built-in libraries are JSON files in ``bikebox/data/libraries/``; users
add their own in ``<config>/libraries/*.json`` (see :func:`config_dir`).  User
items with the same category and id as a built-in replace it.  Nothing is
created on disk until :func:`save_user_item` is called.

File format::

    {"format": "bikebox-library", "version": 1,
     "category": "forks",                       # default for items (optional)
     "items": [{"id": "road-368-45", "name": "Road 368/45", "category": "forks",
                "values": {"fork_length": 368, "fork_offset": 45},
                "meta": {"note": "..."}}]}

``values`` maps parameter keys to values.  :func:`apply` also understands a
few shorthands (see :func:`expand_values`), mainly so tube sets can be stored
the way tubing catalogues quote them::

    {"material": "steel",
     "tubes": {"tt": {"od": 28.6, "wall": "0.9/0.6/0.9"}, "ht": {"od": 32.4, "wall": "1.0"}, ...}}

Butting strings ``"end/centre/end"`` become ``*_wall_end`` / ``*_wall_mid``;
a single value sets both.
"""
from __future__ import annotations

import functools
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import params as P

FORMAT = "bikebox-library"
FORMAT_VERSION = 1
BUILTIN_DIR = Path(__file__).resolve().parents[1] / "data" / "libraries"

# display order and labels; categories not listed here sort after these
CATEGORY_LABELS: dict[str, str] = {
    "tubing": "Tubing",
    "dropouts": "Dropouts",
    "bb_shells": "BB shells",
    "forks": "Forks",
    "headsets": "Headsets",
    "stems": "Stems",
    "handlebars": "Handlebars",
    "saddles": "Saddles",
    "seatposts": "Seatposts",
    "cranks": "Cranks",
    "chainrings": "Chainrings",
    "cassettes": "Cassettes & cogs",
    "wheels": "Wheels & tires",
    "hubs": "Hubs",
    "rims": "Rims",
    "tires": "Tires",
    "frame_hardware": "Frame hardware",
    "brakes": "Brakes",
    "drivetrain": "Derailleurs & groupsets",
}


@dataclass
class LibraryItem:
    id: str
    name: str
    category: str
    values: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def user(self) -> bool:
        return bool(self.meta.get("user"))


# --------------------------------------------------------------------------
# locations
# --------------------------------------------------------------------------
def config_dir() -> Path:
    """Bike Box's per-user configuration directory (not created here).

    ``$BIKEBOX_CONFIG_DIR`` if set, else ``%APPDATA%/bikebox`` on
    Windows, else ``$XDG_CONFIG_HOME/bikebox`` or ``~/.config/bikebox``.
    """
    env = os.environ.get("BIKEBOX_CONFIG_DIR") or os.environ.get("FRAMEWRIGHT_CONFIG_DIR")  # old name too
    if env:
        return Path(env)
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "bikebox"
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "bikebox"


def builtin_dir() -> Path:
    return BUILTIN_DIR


def user_dir() -> Path:
    """Directory for user library files (not created here)."""
    return config_dir() / "libraries"


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category.replace("_", " ").capitalize())


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def _items_from_doc(doc: Any, user: bool, source: str) -> list[LibraryItem]:
    if isinstance(doc, list):
        doc = {"items": doc}
    if not isinstance(doc, dict) or doc.get("format", FORMAT) not in (FORMAT, "framewright-library"):
        return []
    default_cat = str(doc.get("category") or "")
    out = []
    for raw in doc.get("items") or []:
        if not isinstance(raw, dict):
            continue
        cat = str(raw.get("category") or default_cat)
        name = str(raw.get("name") or raw.get("id") or "")
        if not cat or not name:
            continue
        values = raw.get("values")
        if not isinstance(values, dict):
            continue
        meta = dict(raw.get("meta") or {})
        meta["user"] = user
        if doc.get("catalog"):
            meta["catalog"] = True                 # sourced catalog item (values may be empty: reference part)
        meta.setdefault("source_file", source)
        out.append(LibraryItem(str(raw.get("id") or slugify(name)), name, cat, dict(values), meta))
    return out


def _load_dir(directory: Path, user: bool) -> list[LibraryItem]:
    if not directory.is_dir():
        return []
    out: list[LibraryItem] = []
    for path in sorted(directory.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.extend(_items_from_doc(doc, user, path.name))
    return out


CATALOG_DIR = Path(__file__).resolve().parents[1] / "data" / "catalog"


@functools.lru_cache(maxsize=1)
def _builtin_items() -> tuple[LibraryItem, ...]:
    """Generic libraries followed by the sourced parts catalog."""
    return tuple(_load_dir(builtin_dir(), user=False) + _load_dir(CATALOG_DIR, user=False))


def reload() -> None:
    """Forget cached built-in libraries (user libraries are always re-read)."""
    _builtin_items.cache_clear()


def all_items() -> list[LibraryItem]:
    """Built-in items in file order with user items merged in (same category+id replaces)."""
    merged: dict[tuple[str, str], LibraryItem] = {}
    for it in _builtin_items():
        merged[(it.category, it.id)] = LibraryItem(it.id, it.name, it.category, dict(it.values), dict(it.meta))
    for it in _load_dir(user_dir(), user=True):
        merged[(it.category, it.id)] = it
    return list(merged.values())


def _cat_key(cat: str) -> tuple[int, str]:
    order = list(CATEGORY_LABELS)
    return (order.index(cat) if cat in order else len(order), cat)


def categories() -> list[str]:
    """Non-empty categories in display order."""
    return sorted({it.category for it in all_items()}, key=_cat_key)


def items(category: str) -> list[LibraryItem]:
    return [it for it in all_items() if it.category == category]


def get(item_id: str, category: str | None = None) -> LibraryItem | None:
    for it in all_items():
        if it.id == item_id and (category is None or it.category == category):
            return it
    return None


def _flatten(v: Any) -> Iterable[str]:
    if isinstance(v, dict):
        for x in v.values():
            yield from _flatten(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _flatten(x)
    elif v is not None and not isinstance(v, bool):
        yield str(v)


def search(text: str) -> list[LibraryItem]:
    """Items whose id, name, category or metadata contain every word of ``text``."""
    words = str(text).lower().split()
    out = []
    for it in sorted(all_items(), key=lambda i: _cat_key(i.category)):
        meta = {k: v for k, v in it.meta.items() if k not in ("user", "source_file")}
        hay = " ".join([it.id, it.name, it.category, category_label(it.category), *_flatten(meta)]).lower()
        if all(w in hay for w in words):
            out.append(it)
    return out


# --------------------------------------------------------------------------
# applying
# --------------------------------------------------------------------------
TUBE_ALIASES = {
    "tt": "tt", "top_tube": "tt", "dt": "dt", "down_tube": "dt", "st": "st", "seat_tube": "st",
    "ht": "ht", "head_tube": "ht", "cs": "cs", "chain_stay": "cs", "chainstay": "cs",
    "ss": "ss", "seat_stay": "ss", "seatstay": "ss",
    "fork": "fork", "fork_blade": "fork", "blade": "fork", "steerer": "steerer",
}
MATERIAL_ALIASES = {"aluminum": "aluminium", "chromoly": "steel", "crmo": "steel", "cromo": "steel",
                    "titanium 3al-2.5v": "titanium"}


def parse_wall(spec: Any) -> tuple[float, float]:
    """``"0.9/0.6/0.9"`` -> (end, centre) = (0.9, 0.6).  A single value sets both;
    ``"a/b"`` is end/centre; asymmetric or multi-step butting uses the thicker
    end and the thinnest centre section."""
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        return float(spec), float(spec)
    parts = [s.strip().lower().removesuffix("mm").strip() for s in str(spec).split("/")]
    nums = [float(s) for s in parts if s]
    if not nums:
        raise ValueError(f"no wall thickness in {spec!r}")
    if len(nums) == 1:
        return nums[0], nums[0]
    if len(nums) == 2:
        return max(nums), min(nums)
    return max(nums[0], nums[-1]), min(nums[1:-1])


def _get(spec: Any, *keys: str) -> Any:
    if not isinstance(spec, dict):
        return spec if keys and keys[0] in ("od", "od_mm") else None
    for k in keys:
        if k in spec and spec[k] is not None:
            return spec[k]
    return None


def _tube_values(tube: str, spec: Any) -> dict[str, Any]:
    od = _get(spec, "od", "od_mm")
    wall = _get(spec, "wall", "wall_mm")
    out: dict[str, Any] = {}
    end = mid = None
    if wall is not None:
        try:
            end, mid = parse_wall(wall)
        except (TypeError, ValueError):
            end = mid = None
    if tube in ("tt", "dt", "st"):
        if od is not None:
            out[f"{tube}_od"] = od
            out[f"{tube}_profile"] = _get(spec, "profile") or "round"
            od2 = _get(spec, "od2", "width")
            out[f"{tube}_od2"] = od2 if od2 is not None else od
            od_end = _get(spec, "od_end")
            out[f"{tube}_od_end"] = od_end if od_end is not None else 0.0
        if end is not None:
            out[f"{tube}_wall_end"], out[f"{tube}_wall_mid"] = end, mid
        butt = _get(spec, "butt_length")
        if butt is not None:
            out[f"{tube}_butt_length"] = butt
    elif tube == "ht":
        if od is not None:
            out["ht_od_top"] = od
            out["ht_od_bottom"] = _get(spec, "od_bottom") or od
        if end is not None:
            out["ht_wall"] = end
    elif tube == "cs":
        if od is not None:
            out["cs_od_bb"] = od
        tip = _get(spec, "od_end", "od_tip")
        if tip is not None:
            out["cs_od_drop"] = tip
        if end is not None:
            out["cs_wall"] = end
        prof = _get(spec, "profile")
        if prof:
            out["cs_profile"] = prof
    elif tube == "ss":
        if od is not None:
            out["ss_od_top"] = od
        tip = _get(spec, "od_end", "od_tip")
        if tip is not None:
            out["ss_od_drop"] = tip
        if end is not None:
            out["ss_wall"] = end
        prof = _get(spec, "profile")
        if prof:
            out["ss_profile"] = prof
    elif tube == "fork":
        if od is not None:
            out["fork_blade_od"] = od
        tip = _get(spec, "od_end", "od_tip")
        if tip is not None:
            out["fork_blade_od_tip"] = tip
    elif tube == "steerer":
        if od is not None:
            out["steerer_od"] = od
    return out


def _material(m: Any) -> str:
    s = str(m).strip().lower()
    return MATERIAL_ALIASES.get(s, s)


def expand_values(values: dict[str, Any]) -> dict[str, Any]:
    """Expand library shorthands into parameter keys.

    * ``"tubes": {tube: {"od", "wall", ...}}`` - tube-set specs (tube names may
      be ``tt``/``top_tube`` etc.; ``fork_blade``, ``steerer`` too).
    * ``"material"`` -> ``frame_material``.
    * ``"tt_wall"``/``"dt_wall"``/``"st_wall"`` butting strings -> ``*_wall_end`` + ``*_wall_mid``;
      string ``ht_wall``/``cs_wall``/``ss_wall`` use the end value.
    * ``"ht_od"`` -> top and bottom OD, ``"cs_od"`` -> ``cs_od_bb``, ``"ss_od"`` -> ``ss_od_top``.

    Explicit parameter keys win over values derived from ``tubes``.
    """
    out: dict[str, Any] = {}
    if "material" in values:
        out["frame_material"] = _material(values["material"])
    tubes = values.get("tubes")
    if isinstance(tubes, dict):
        for name, spec in tubes.items():
            key = TUBE_ALIASES.get(str(name).strip().lower())
            if key:
                out.update(_tube_values(key, spec))
    for k, v in values.items():
        if k in ("tubes", "material"):
            continue
        m = re.fullmatch(r"(tt|dt|st)_wall", k)
        if m:
            try:
                out[f"{m[1]}_wall_end"], out[f"{m[1]}_wall_mid"] = parse_wall(v)
            except (TypeError, ValueError):
                pass
        elif k in ("ht_wall", "cs_wall", "ss_wall") and isinstance(v, str):
            try:
                out[k] = parse_wall(v)[0]
            except ValueError:
                pass
        elif k == "ht_od":
            out["ht_od_top"] = out["ht_od_bottom"] = v
        elif k == "cs_od":
            out["cs_od_bb"] = v
        elif k == "ss_od":
            out["ss_od_top"] = v
        else:
            out[k] = v
    return out


def item_tube_positions(item: LibraryItem | dict[str, Any]) -> set[str]:
    """Canonical tube positions (tt/dt/st/ht/cs/ss/fork/steerer) an item specs."""
    values = item.values if isinstance(item, LibraryItem) else dict(item)
    tubes = values.get("tubes")
    out: set[str] = set()
    if isinstance(tubes, dict):
        for name in tubes:
            key = TUBE_ALIASES.get(str(name).strip().lower())
            if key:
                out.add(key)
    return out


def apply_tube(design, item: LibraryItem | dict[str, Any], pos: str) -> list[str]:
    """Apply only one tube position of a tubing item (so a builder can pick a
    tube per frame position without disturbing the others or the material)."""
    values = item.values if isinstance(item, LibraryItem) else dict(item)
    tubes = values.get("tubes") or {}
    spec = None
    for name, s in tubes.items():
        if TUBE_ALIASES.get(str(name).strip().lower()) == pos:
            spec = s
            break
    if spec is None:
        return []
    return apply(design, {"tubes": {pos: spec}})


def apply(design, item: LibraryItem | dict[str, Any]) -> list[str]:
    """Apply a library item to ``design``; returns the keys whose value changed.
    Keys not in the parameter schema and invalid choice values are ignored."""
    values = item.values if isinstance(item, LibraryItem) else dict(item)
    changed: list[str] = []
    for key, val in expand_values(values).items():
        if not P.has(key):
            continue
        pd = P.get(key)
        if pd.kind == P.CHOICE and pd.choices and str(val) not in {c[0] for c in pd.choices}:
            continue
        old = design[key]
        try:
            new = design.set(key, val)
        except (TypeError, ValueError):
            continue
        if new != old:
            changed.append(key)
    return changed


# --------------------------------------------------------------------------
# user libraries
# --------------------------------------------------------------------------
def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
    return s or "item"


def _user_file(category: str) -> Path:
    return user_dir() / f"{slugify(category).replace('-', '_')}.json"


def save_user_item(category: str, name: str, values: dict[str, Any], meta: dict[str, Any] | None = None) -> Path:
    """Add (or replace, matched by name) an item in the user library for
    ``category``; returns the file written."""
    if not str(category).strip() or not str(name).strip():
        raise ValueError("category and name are required")
    path = _user_file(category)
    doc: dict[str, Any] = {"format": FORMAT, "version": FORMAT_VERSION, "category": category, "items": []}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and existing.get("format", FORMAT) == FORMAT:
                doc.update(existing)
                doc["items"] = [i for i in existing.get("items") or [] if isinstance(i, dict)]
        except (OSError, ValueError):
            pass
    item_id = "user-" + slugify(name)
    entry = {"id": item_id, "name": str(name), "category": category, "values": dict(values),
             "meta": dict(meta or {})}
    doc["items"] = [i for i in doc["items"]
                    if not (i.get("id") == item_id and (i.get("category") or doc.get("category")) == category)]
    doc["items"].append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)
    return path


def remove_user_item(category: str, item_id: str) -> bool:
    """Remove a user item; returns True when something was removed."""
    path = _user_file(category)
    if not path.is_file():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    before = list(doc.get("items") or [])
    doc["items"] = [i for i in before if not (isinstance(i, dict) and i.get("id") == item_id)]
    if len(doc["items"]) == len(before):
        return False
    path.write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    return True
