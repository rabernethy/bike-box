"""The design document: parameter values plus structured extras.

Files are JSON (``.bikebox``).  Values are stored by parameter key; unknown keys
are kept (so files written by newer versions survive a round trip) and missing
keys fall back to schema defaults.
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
from pathlib import Path
from typing import Any

from . import params as P

FORMAT = "bikebox-design"
FORMAT_VERSION = 1
FILE_SUFFIX = ".bikebox"


def _default_extras() -> dict[str, Any]:
    return {
        # dimension ids shown on the drawing (see geometry.dimensions.CATALOG)
        "visible_dimensions": None,          # None -> catalog defaults
        "dimension_offsets": {},             # id -> signed offset (mm)
        "dimension_states": {},              # name -> [ids]
        "user_dimensions": [],               # [{id,kind,points,offset,label}]
        "notes": [],                         # [{id,x,y,text,size,color,leader}]
        "photo": None,                       # {path,x,y,mm_per_px,rotation,opacity,flip}
        "title_block": {},                   # free-form fields for the drawing sheet
        "tables": [],                        # [{title, rows:[[...]], x, y}]
        "extra_tubes": [],                   # [{name,a,b,od,wall,...}]
        "brazeons": [],                      # [{type,tube,s|pos,from,side,label}] user-placed mounts
        "order": None,                       # customer/order record (see model.orders)
        "routing": [],                       # [{type,internal,points:[spec...],label}] cable/hose routes
        "decals": [],                        # [{tube,pos,text|image,font,size,color,angle,...}]
        "snapshots": [],                     # [{name, time, values}]
        "fit_formulas": {},                  # custom fitting schemes for the fit advisor
        "fit_inputs": {},                    # extra fit-advisor inputs (flexibility, style ...)
        "component_masses": {},              # measured component masses (g) overriding estimates
        "meta": {},
    }


class Design:
    """A bicycle design.  Behaves like a mapping for parameter values."""

    def __init__(self, values: dict[str, Any] | None = None, extras: dict[str, Any] | None = None):
        self.values: dict[str, Any] = P.defaults()
        self._unknown: dict[str, Any] = {}
        self.extras: dict[str, Any] = _default_extras()
        if values:
            self.update(values)
        if extras:
            for k, v in extras.items():
                self.extras[k] = v

    # -- mapping access ------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        try:
            return self.values[key]
        except KeyError:
            if P.has(key):              # registered after this design was created
                v = P.get(key).default
                self.values[key] = v
                return v
            raise

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        return key in self.values or P.has(key)

    def set(self, key: str, value: Any) -> Any:
        if P.has(key):
            value = P.get(key).coerce(value)
            self.values[key] = value
        else:
            self._unknown[key] = value
        return value

    def update(self, values: dict[str, Any]) -> None:
        for k, v in values.items():
            try:
                self.set(k, v)
            except (TypeError, ValueError):
                continue

    def f(self, key: str) -> float:
        """Shorthand for ``float(design[key])``."""
        return float(self[key])

    def lst(self, key: str) -> list[float]:
        return P.parse_list(self[key])

    # -- copying / comparison --------------------------------------------------
    def copy(self) -> "Design":
        d = Design.__new__(Design)
        d.values = dict(self.values)
        d._unknown = dict(self._unknown)
        d.extras = copy.deepcopy(self.extras)
        return d

    def diff(self, other: "Design") -> dict[str, tuple[Any, Any]]:
        out = {}
        for k in set(self.values) | set(other.values):
            a, b = self.values.get(k), other.values.get(k)
            if a != b:
                out[k] = (a, b)
        return out

    @staticmethod
    def lerp(a: "Design", b: "Design", t: float) -> "Design":
        """Interpolate numeric parameters (used for morph animations)."""
        d = a.copy() if t < 0.5 else b.copy()
        for pd in P.all_params():
            if not pd.morph or pd.kind not in (P.FLOAT, P.INT):
                continue
            va, vb = a[pd.key], b[pd.key]
            v = va + (vb - va) * t
            d.values[pd.key] = v if pd.kind == P.FLOAT else int(round(v))
        return d

    # -- serialisation ---------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        defaults = P.defaults()
        vals = {k: v for k, v in self.values.items()}
        vals.update(self._unknown)
        meta = dict(self.extras.get("meta") or {})
        meta["modified"] = _dt.datetime.now().isoformat(timespec="seconds")
        meta.setdefault("created", meta["modified"])
        from .. import __version__
        meta["app_version"] = __version__
        extras = dict(self.extras)
        extras["meta"] = meta
        return {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "values": vals,
            "changed_from_default": sorted(k for k, v in self.values.items() if defaults.get(k) != v),
            "extras": extras,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=1, sort_keys=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Design":
        if data.get("format") not in (FORMAT, "framewright-design", None):     # accept the pre-rename token
            raise ValueError(f"not a Bike Box design (format={data.get('format')!r})")
        extras = _default_extras()
        extras.update(data.get("extras") or {})
        return cls(data.get("values") or {}, extras)

    @classmethod
    def from_json(cls, text: str) -> "Design":
        return cls.from_dict(json.loads(text))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        if path.suffix.lower() == ".bcad":
            from ..export.bcad_export import save_bcad
            save_bcad(self, path)
            return
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(self.to_json(), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: str | Path) -> "Design":
        path = Path(path)
        if path.suffix.lower() == ".bcad":
            from ..export.bcad_import import load_bcad
            return load_bcad(path)
        return cls.from_json(path.read_text(encoding="utf-8"))

    # -- convenience -------------------------------------------------------------
    @property
    def title(self) -> str:
        return str(self.values.get("title") or "Untitled design")

    def snapshot(self, name: str) -> None:
        self.extras.setdefault("snapshots", []).append({
            "name": name,
            "time": _dt.datetime.now().isoformat(timespec="seconds"),
            "values": dict(self.values),
        })

    def snapshot_design(self, name: str) -> "Design | None":
        for s in self.extras.get("snapshots", []):
            if s.get("name") == name:
                d = self.copy()
                d.extras["snapshots"] = []
                d.update(s["values"])
                return d
        return None
