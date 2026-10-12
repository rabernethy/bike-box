"""Bill of materials.

Builds a parts list for a design: the frame tubes and fork (always, with their
specs computed from the design) plus any component assigned from the catalog via
the "… from catalog…" pickers (recorded in ``design.extras["bom"]``). Each row
carries the catalogued part name, brand and source when one was chosen.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..model import params as P

# frame tubes always listed, in build order: (slot key, label)
TUBE_SLOTS = [("tt", "Top tube"), ("dt", "Down tube"), ("st", "Seat tube"), ("ht", "Head tube"),
              ("cs", "Chainstays"), ("ss", "Seat stays")]

# component slots: catalog category -> label (listed when assigned)
COMPONENT_SLOTS = [("forks", "Fork"), ("headsets", "Headset"), ("stems", "Stem"), ("handlebars", "Handlebar"),
                   ("saddles", "Saddle"), ("seatposts", "Seatpost"), ("cranks", "Crankset"),
                   ("cassettes", "Cassette"), ("drivetrain", "Derailleur / groupset"), ("rims", "Rims"),
                   ("hubs", "Hubs"), ("tires", "Tires"), ("brakes", "Brakes"), ("bb_shells", "BB shell"),
                   ("dropouts", "Dropouts"), ("frame_hardware", "Lugs / hardware")]


@dataclass
class BomRow:
    component: str          # where it goes ("Down tube", "Fork", …)
    part: str              # catalogued part name, or "" if not sourced
    spec: str              # the dimensions/spec that matter
    brand: str = ""
    source: str = ""
    sourced: bool = False   # chosen from the catalog


def _num(v: float) -> str:
    return f"{v:g}"


def _wall(design, pos: str) -> str:
    end = f"{pos}_wall_end"
    mid = f"{pos}_wall_mid"
    if P.has(end):
        e, m = design.f(end), design.f(mid) if P.has(mid) else design.f(end)
        return f"{_num(e)}/{_num(m)}/{_num(e)}" if abs(e - m) > 1e-6 else _num(e)
    single = f"{pos}_wall"
    return _num(design.f(single)) if P.has(single) else ""


_OD_KEY = {"ht": "ht_od_top", "cs": "cs_od_bb", "ss": "ss_od_top"}  # positions with non-standard OD keys


def _tube_spec(design, pos: str, geometry=None) -> str:
    od_key = _OD_KEY.get(pos, f"{pos}_od")
    od = design.f(od_key) if P.has(od_key) else 0.0
    parts = []
    if od:
        parts.append(f"Ø{_num(od)}")
    w = _wall(design, pos)
    if w:
        parts.append(f"×{w}")
    if geometry is not None and pos in geometry.tubes:
        parts.append(f"{geometry.tubes[pos].chord:.0f} mm")
    mat = design.get("frame_material")
    if mat:
        parts.append(str(mat))
    return " ".join(parts)


def _fork_spec(design) -> str:
    bits = [f"{_num(design.f('fork_length'))} mm A-C", f"{_num(design.f('fork_offset'))} mm offset"]
    if design.get("fork_type") == "suspension":
        bits.append(f"{_num(design.f('fork_travel'))} mm travel")
    return ", ".join(bits)


def _entry_part(entry) -> tuple[str, str, str]:
    """(part name, brand, source) from a recorded bom entry."""
    if not isinstance(entry, dict):
        return "", "", ""
    return str(entry.get("name", "")), str(entry.get("brand", "") or ""), str(entry.get("source", "") or "")


def build(design, geometry=None) -> list[BomRow]:
    bom = design.extras.get("bom") or {}
    rows: list[BomRow] = []
    # frame material header
    rows.append(BomRow("Frame", "", str(design.get("frame_material", "")).capitalize(), sourced=False))
    for pos, label in TUBE_SLOTS:
        part, brand, src = _entry_part(bom.get(pos))
        rows.append(BomRow(label, part, _tube_spec(design, pos, geometry), brand, src, bool(part)))
    # fork (always; spec from the design, part if assigned)
    part, brand, src = _entry_part(bom.get("forks"))
    rows.append(BomRow("Fork", part, _fork_spec(design), brand, src, bool(part)))
    # other components only when assigned
    for cat, label in COMPONENT_SLOTS:
        if cat in ("forks",) or cat not in bom:
            continue
        part, brand, src = _entry_part(bom.get(cat))
        spec = str(bom[cat].get("variant") or bom[cat].get("model") or "") if isinstance(bom[cat], dict) else ""
        rows.append(BomRow(label, part, spec, brand, src, bool(part)))
    return rows


def to_csv(design, geometry=None) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Component", "Part", "Spec", "Brand", "Sourced", "Source"])
    for r in build(design, geometry):
        w.writerow([r.component, r.part, r.spec, r.brand, "yes" if r.sourced else "", r.source])
    return buf.getvalue()


def report_rows(design, geometry=None):
    """(label, value, status) rows for the analysis report."""
    out = []
    for r in build(design, geometry):
        value = r.part + (f"  ({r.spec})" if r.spec else "") if r.part else (r.spec or "—")
        out.append((r.component, value, "ok" if r.sourced else "info"))
    return out
