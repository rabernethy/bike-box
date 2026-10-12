"""Export a frame as a FreeCAD Python macro (Part workbench), building the
frame in 3-D from hollow tubes.

Coordinate mapping (model -> FreeCAD, both millimetres)::

    FreeCAD X =  model X   (forward, toward the front wheel)
    FreeCAD Y =  model Z   (lateral, toward the drive side)
    FreeCAD Z =  model Y   (up)

so the bike stands upright in FreeCAD with Z up and faces +X.  Tubes are
``Part.makeCone`` solids (``makeCylinder`` when straight-gauge and round) with
the inner bore cut away to leave a wall.  Oval/aero tubes are round cones
scaled across their width.  The BB shell is a hollow cylinder with its axis
along model Z (FreeCAD Y).  Mirrored tubes (stays, fork blades) are reflected
across the FreeCAD Y=0 plane.  When ``mitre`` is set the macro cuts each tube
end against the tube it joins.
"""
from __future__ import annotations

from pathlib import Path

from ..geometry.solver import Geometry, Tube


def _rgb(hex_color: str) -> tuple[float, float, float]:
    c = (hex_color or "#808080").lstrip("#")
    if len(c) < 6:
        return (0.5, 0.5, 0.5)
    return (int(c[0:2], 16) / 255.0, int(c[2:4], 16) / 255.0, int(c[4:6], 16) / 255.0)


_KIND_COLOR = {
    "main": "#9aa0a6", "stay": "#8a8f94", "fork": "#4a6fa5", "extra": "#b0893c",
}


def _fc(v3) -> tuple[float, float, float]:
    """model (x, y, z) -> FreeCAD (x, z, y)."""
    return (round(v3.x, 4), round(v3.z, 4), round(v3.y, 4))


def _tube_record(t: Tube) -> dict:
    wall = max(min(t.wall_mid, t.wall_end), 0.05)
    return {
        "name": t.name,
        "label": t.label,
        "a": _fc(t.a3()),
        "b": _fc(t.b3()),
        "ra": round(max(t.od_a / 2.0, 0.2), 4),
        "rb": round(max(t.od_b / 2.0, 0.2), 4),
        "wa": round(max(t.w_a, 0.4), 4),
        "wb": round(max(t.w_b, 0.4), 4),
        "wall": round(wall, 4),
        "profile": t.profile,
        "mirrored": bool(t.mirrored),
        "join_a": t.join_a,
        "join_b": t.join_b,
        "color": _rgb(_KIND_COLOR.get(t.kind, "#9aa0a6")),
    }


def freecad_macro(g: Geometry, mitre: bool = True) -> str:
    d = g.design
    tubes = [_tube_record(t) for t in g.tubes.values()]
    bb_od = float(d.get("bb_shell_od", 40.0))
    bb_w = float(d.get("bb_shell_width", 68.0))
    bb_wall = 3.0
    bb = {"r": round(bb_od / 2.0, 4), "w": round(bb_w, 4), "wall": bb_wall,
          "color": _rgb("#7a7f84")}

    dropouts = []
    for key in ("rear_axle", "front_axle"):
        if key in g.p:
            p = g.p[key]
            spacing = (d.get("rear_hub_spacing", 135.0) if key == "rear_axle"
                       else d.get("front_hub_spacing", 100.0))
            dropouts.append({"x": round(p.x, 4), "z": round(p.y, 4),
                             "half": round(float(spacing) / 2.0, 4),
                             "color": _rgb("#5a5f64")})

    header = f'''# -*- coding: utf-8 -*-
# Bike Box FreeCAD macro -- {d.title}
# Build the bicycle frame as 3-D hollow tubes (Part workbench).
# Model (x fwd, y up, z drive) maps to FreeCAD (X=x, Y=z, Z=y); Z is up.
import FreeCAD, Part
from FreeCAD import Vector, Placement, Rotation, Base
try:
    import FreeCADGui
except Exception:
    FreeCADGui = None

MITRE = {bool(mitre)!r}
TUBES = {tubes!r}
BB = {bb!r}
DROPOUTS = {dropouts!r}
'''

    body = r'''

doc = FreeCAD.newDocument("Bike Box")


def _axis(a, b):
    va, vb = Vector(*a), Vector(*b)
    v = vb - va
    L = v.Length or 1.0
    return va, v, L


def _cone(r1, r2, L):
    if abs(r1 - r2) < 1e-6:
        return Part.makeCylinder(r1, L)
    return Part.makeCone(r1, r2, L)


def _oval(shape, sx):
    if abs(sx - 1.0) < 1e-6:
        return shape
    m = Base.Matrix()
    m.scale(sx, 1.0, 1.0)
    try:
        return shape.transformGeometry(m)
    except Exception:
        return shape


def make_tube(t):
    a, v, L = _axis(t["a"], t["b"])
    rot = Rotation(Vector(0, 0, 1), v)
    place = Placement(a, rot)
    outer = _cone(t["ra"], t["rb"], L)
    w = t["wall"]
    inner = _cone(max(t["ra"] - w, 0.1), max(t["rb"] - w, 0.1), L)
    solid = outer.cut(inner)
    cutter = outer
    if t["profile"] != "round":
        sx = t["wa"] / max(t["ra"] * 2.0, 1e-6)
        solid = _oval(solid, sx)
        cutter = _oval(cutter, sx)
    solid.Placement = place
    cutter.Placement = place
    return solid, cutter


def make_bb():
    r, w, wall = BB["r"], BB["w"], BB["wall"]
    outer = Part.makeCylinder(r, w)
    inner = Part.makeCylinder(max(r - wall, 0.1), w)
    solid = outer.cut(inner)
    # axis along model Z (FreeCAD Y); centre at origin
    place = Placement(Vector(0, -w / 2.0, 0), Rotation(Vector(0, 0, 1), Vector(0, 1, 0)))
    solid.Placement = place
    outer.Placement = place
    return solid, outer


def make_dropout(dp, side):
    y = side * dp["half"]
    box = Part.makeBox(42, 4, 34, Vector(dp["x"] - 21, y - 2, dp["z"] - 20))
    return box


def add_object(name, shape, color):
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = shape
    if FreeCADGui is not None:
        try:
            obj.ViewObject.ShapeColor = (float(color[0]), float(color[1]), float(color[2]))
        except Exception:
            pass
    return obj


solids = {}
cutters = {}
for t in TUBES:
    s, c = make_tube(t)
    solids[t["name"]] = s
    cutters[t["name"]] = c

bb_solid, bb_cutter = make_bb()
cutters["bb"] = bb_cutter

if MITRE:
    for t in TUBES:
        for end in (t["join_a"], t["join_b"]):
            if end and end in cutters and end != t["name"]:
                try:
                    solids[t["name"]] = solids[t["name"]].cut(cutters[end])
                except Exception:
                    pass

for t in TUBES:
    shape = solids[t["name"]]
    add_object(t["name"], shape, t["color"])
    if t["mirrored"]:
        try:
            mirrored = shape.mirror(Vector(0, 0, 0), Vector(0, 1, 0))
            add_object(t["name"] + "_mirror", mirrored, t["color"])
        except Exception:
            pass

add_object("bb_shell", bb_solid, BB["color"])

for i, dp in enumerate(DROPOUTS):
    for side in (1, -1):
        try:
            add_object("dropout_%d_%s" % (i, "r" if side > 0 else "l"),
                       make_dropout(dp, side), dp["color"])
        except Exception:
            pass

doc.recompute()
try:
    import FreeCADGui
    FreeCADGui.SendMsgToActiveView("ViewFit")
except Exception:
    pass
'''
    return header + body


def save_freecad_macro(g: Geometry, path) -> Path:
    path = Path(path)
    path.write_text(freecad_macro(g), encoding="utf-8")
    return path
