"""BikeCAD ``.bcad`` export.

Writes the design-defining geometry as a Java ``Properties`` XML document using
the same key meanings :mod:`bcad_import` reads, so a FrameWright design written
here re-opens in FrameWright (and loads in BikeCAD) with its core geometry
intact.  The front end is written in BikeCAD's stack-and-reach mode (the
unambiguous one), taken from the solved geometry, so the result does not depend
on which measurement mode the FrameWright design happened to use.

This is not a full BikeCAD document — only the frame-defining entries are
emitted, not the thousands of display settings a BikeCAD save contains.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from ..geometry.solver import Geometry, solve
from ..model.design import Design


def hex_to_argb(color: str) -> int:
    """A ``#rrggbb`` colour as the signed 32-bit ARGB integer BikeCAD stores."""
    c = str(color).lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        rgb = int(c[:6], 16)
    except ValueError:
        rgb = 0
    v = (0xFF << 24) | rgb
    return v - 0x100000000 if v >= 0x80000000 else v      # Java signed int


def _entries(d: Design, g: Geometry) -> list[tuple[str, Any]]:
    v = g.v
    e: list[tuple[str, Any]] = []

    def add(key, value):
        if value is not None:
            e.append((key, value))

    name = str(d.get("title") or "").strip()
    add("MODEL_NAME", name or None)

    # wheels
    for end in ("rear", "front"):
        bsd = d.f(f"{end}_bsd")
        add(f"BSD {end}", bsd)
        add(f"Wheel diameter {end}", round(bsd + 2 * d.f(f"{end}_tire_height"), 1))
        add(f"Wheel width {end}", d.f(f"{end}_tire_width"))

    # bottom bracket & rear end
    e.append(("BB measure style", 0))
    add("BB textfield", round(v.get("bb_drop", d.f("bb_drop")), 1))
    add("BB diameter", d.f("bb_shell_od"))
    add("BB length", d.f("bb_shell_width"))
    e.append(("CS measure style", 0))
    add("CS textfield", round(v.get("chainstay_length", d.f("chainstay_length")), 1))
    add("Dropout spacing", d.f("rear_hub_spacing"))

    # seat tube
    add("Seat angle", round(v.get("seat_tube_angle", d.f("seat_tube_angle")), 2))
    e.append(("ST measure style", 1 if d["st_length_mode"] == "ct" else 0))
    add("Seat tube length", round(v.get("seat_tube_ct" if d["st_length_mode"] == "ct" else "seat_tube_cc",
                                        d.f("seat_tube_length")), 1))
    add("Seat tube extension2", round(v.get("st_extension", 0.0), 1))

    # head tube, headset, fork
    add("Head angle", round(v.get("head_tube_angle", d.f("head_tube_angle")), 2))
    add("Head tube length textfield", round(v.get("head_tube_length", d.f("head_tube_length")), 1))
    ht_top, ht_bot = d.f("ht_od_top"), d.f("ht_od_bottom")
    if abs(ht_top - ht_bot) > 0.05:
        e += [("Head tube type", 1), ("Head tube d", ht_top), ("Head tube D", ht_bot)]
    else:
        e += [("Head tube type", 0), ("Head tube diameter", ht_top)]
    add("Head tube upper extension2", round(v.get("tt_ht_offset", d.f("tt_ht_offset")), 1))
    add("Head tube lower extension2", round(v.get("dt_ht_offset", d.f("dt_ht_offset")), 1))
    ft = 1 if d["fork_type"] == "suspension" else 0
    e.append(("Fork type", ft))
    add(f"FORK{ft}L", d.f("fork_length"))
    add(f"FORK{ft}R", d.f("fork_offset"))
    if ft == 1:
        travel = d.f("fork_travel")
        add("Fork travel", travel)
        add("Fork sag", round(d.f("fork_sag") / 100.0 * travel, 1))      # % → mm, as BikeCAD stores
    add("Lower stack height", d.f("lower_stack"))
    add("Upper stack height", d.f("upper_stack"))
    add("Headset spacers", d.f("spacers"))

    # front end: stack + reach (BikeCAD style 3) from the solved geometry
    e.append(("Top tube front center measure style", 3))
    add("Stack", round(v["stack"], 1))
    add("FCD textfield", round(v["reach"], 1))

    # top & down tube, stays
    def tube(prefix, front, rear, front2, wall):
        od = d.f(f"{prefix}_od")
        add(front, od)
        add(rear, d.f(f"{prefix}_od_end") or od)
        if d[f"{prefix}_profile"] != "round" and d.f(f"{prefix}_od2"):
            add(front2, d.f(f"{prefix}_od2"))
        add(wall, d.f(f"{prefix}_wall_mid"))
    tube("tt", "Top tube front diameter", "Top tube rear diameter", "Top tube front dia2", "Wall thickness Top tube")
    tube("dt", "Down tube front diameter", "Down tube rear diameter", "Down tube front dia2",
         "Wall thickness Down tube")
    add("Seat tube diameter", d.f("st_od"))
    add("Seat tube bottom diameter textfield", d.f("st_od_end") or d.f("st_od"))
    add("Wall thickness Seat tube", d.f("st_wall_mid"))
    add("Chain stay vertical diameter", d.f("cs_od_bb"))
    add("Chain stay horizontal diameter", d.f("cs_width_bb") or d.f("cs_od_bb"))
    add("Chain stay back diameter", d.f("cs_od_drop"))
    add("Wall thickness Chain stay", d.f("cs_wall"))
    add("Seat stay bottom diameter", d.f("ss_od_drop"))
    add("SEATSTAY_HR", d.f("ss_od_top"))
    add("Wall thickness Seat stay", d.f("ss_wall"))
    add("Seat stay junction0", round(v.get("ss_offset", d.f("ss_offset")), 1))
    add("MATERIAL", {"aluminium": "Aluminum", "steel": "Steel", "titanium": "Titanium", "carbon": "Carbon",
                     "stainless": "Stainless"}.get(d["frame_material"]))

    # saddle & seatpost
    e.append(("SADDLEPOSITIONMEASURESTYLE", 0))
    add("Saddle height", round(v.get("saddle_height", d.f("saddle_height")), 1))
    add("Saddle length", d.f("saddle_length"))
    add("Saddle thickness", d.f("saddle_stack"))
    add("Saddle angle", d.f("saddle_tilt"))
    add("Seatpost diameter", d.f("seatpost_od"))
    add("Seatpost setback", d.f("seatpost_offset"))
    add("Seatpost LENGTH", d.f("seatpost_length"))

    # cockpit
    add("Stem length", d.f("stem_length"))
    add("Stem angle", d.f("stem_angle"))
    bar = d["bar_type"]
    if bar == "drop":
        e += [("Handlebar style", 0)]
        add("Road bar reach", d.f("bar_reach"))
        add("Road bar drop", d.f("bar_drop"))
    elif bar == "bullhorn":
        e += [("Handlebar style", 2)]
        add("Bullhorn reach", d.f("bar_reach"))
        add("Bullhorn rise", d.f("bar_rise"))
    else:
        e += [("Handlebar style", 1)]
    add("Handlebar width", d.f("bar_width"))

    # drivetrain
    add("Crank length", d.f("crank_length"))
    rings = [int(x) for x in str(d.get("chainrings", "")).replace(",", " ").split() if x.strip().isdigit()]
    cogs = [int(x) for x in str(d.get("cogs", "")).replace(",", " ").split() if x.strip().isdigit()]
    if rings:
        e.append(("Number of chainrings", len(rings)))
        e += [(f"Teeth on chainring {k}", r) for k, r in enumerate(rings)]
    if cogs:
        e.append(("Number of cogs", len(cogs)))
        e += [(f"Teeth on cog {k}", c) for k, c in enumerate(cogs)]
    e.append(("BELTorCHAIN", 0 if d["drive_type"] == "belt" else 1))

    # paint, fenders, bottles
    e.append(("FIRST color sRGB", hex_to_argb(d.get("paint_frame", "#c8102e"))))
    e.append(("SECOND color sRGB", hex_to_argb(d.get("paint_head_tube", d.get("paint_frame", "#c8102e")))))
    e += [("Front Fender include", bool(d["fenders"])), ("Rear Fender include", bool(d["fenders"]))]
    add("Fender clearance", d.f("fender_clearance") if d["fenders"] else None)
    return e


def to_properties_xml(design: Design, geometry: Geometry | None = None) -> str:
    g = geometry if geometry is not None else solve(design)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<!DOCTYPE properties SYSTEM "http://java.sun.com/dtd/properties.dtd">',
             "<properties>",
             "<comment>Exported by FrameWright</comment>"]
    for key, value in _entries(design, g):
        if isinstance(value, bool):
            value = "true" if value else "false"
        lines.append(f'<entry key="{escape(str(key))}">{escape(str(value))}</entry>')
    lines.append("</properties>")
    return "\n".join(lines) + "\n"


def save_bcad(design: Design, path: str | Path) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(to_properties_xml(design), encoding="utf-8")
    tmp.replace(path)
