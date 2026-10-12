"""Scene -> DXF (AutoCAD R12 / AC1009 ASCII), the most widely readable flavour.

Geometry is written at full size in millimetres, one DXF layer per scene layer.
Fills are not representable in R12 and are omitted; outlines are kept.
Curved tubes are written as polylines (unlike some tools, nothing is dropped).
"""
from __future__ import annotations

import math
from pathlib import Path

from ..render.scene import (Arc, AngleDim, Circle, LinearDim, Polyline, Scene, Text, explode_dimension)

# a few AutoCAD Colour Index entries with their RGB values
_ACI = {1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255), 5: (0, 0, 255), 6: (255, 0, 255),
        7: (0, 0, 0), 8: (128, 128, 128), 9: (192, 192, 192), 30: (255, 127, 0), 140: (0, 127, 255),
        200: (127, 0, 255), 250: (51, 51, 51), 251: (91, 91, 91), 252: (132, 132, 132), 253: (173, 173, 173)}


def aci(hex_color: str | None) -> int:
    if not hex_color or not hex_color.startswith("#") or len(hex_color) < 7:
        return 7
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    best, bd = 7, 1e18
    for idx, (R, G, B) in _ACI.items():
        dist = (r - R) ** 2 + (g - G) ** 2 + (b - B) ** 2
        if dist < bd:
            best, bd = idx, dist
    return best


class DxfWriter:
    def __init__(self, scale: float = 1.0, ox: float = 0.0, oy: float = 0.0, annot: float = 10.0):
        self.k = scale
        self.ox, self.oy = ox, oy
        self.annot = annot              # model mm per "paper" mm for dimension/annotation sizing
        self.ents: list[str] = []
        self.layers: dict[str, int] = {}

    def _xy(self, v):
        return v.x * self.k + self.ox, v.y * self.k + self.oy

    def _layer(self, name: str, color: int) -> str:
        name = "".join(c if c.isalnum() or c in "_-" else "_" for c in name.upper()) or "0"
        self.layers.setdefault(name, color)
        return name

    def _common(self, prim, color: int) -> str:
        return f"8\n{self._layer(prim.layer, color)}\n62\n{color}\n"

    def add_scene(self, scene: Scene) -> None:
        for prim in scene.visible():
            self.add_prim(prim)

    def add_prim(self, prim) -> None:
        if isinstance(prim, (LinearDim, AngleDim)):
            for sub in explode_dimension(prim, self.annot):
                self.add_prim(sub)
            return
        st = prim.style
        color = aci(st.stroke or (st.fill if isinstance(st.fill, str) else None))
        if isinstance(prim, Polyline):
            if len(prim.pts) < 2:
                return
            rings = [prim.pts] + (prim.holes if prim.closed else [])
            for ring in rings:
                self.polyline(prim, ring, prim.closed, color)
        elif isinstance(prim, Circle):
            x, y = self._xy(prim.c)
            self.ents.append(f"0\nCIRCLE\n{self._common(prim, color)}10\n{x:.4f}\n20\n{y:.4f}\n30\n0.0\n"
                             f"40\n{prim.r * self.k:.4f}\n")
        elif isinstance(prim, Arc):
            x, y = self._xy(prim.c)
            a0, a1 = prim.start, prim.start + prim.span
            if prim.span < 0:
                a0, a1 = a1, a0
            self.ents.append(f"0\nARC\n{self._common(prim, color)}10\n{x:.4f}\n20\n{y:.4f}\n30\n0.0\n"
                             f"40\n{prim.r * self.k:.4f}\n50\n{a0 % 360:.4f}\n51\n{a1 % 360:.4f}\n")
        elif isinstance(prim, Text):
            if not prim.text:
                return
            h = (prim.size * self.annot if prim.annotative else prim.size) * self.k
            ax, ay = (prim.anchor + "m")[0], (prim.anchor + "m")[1]
            hj = {"l": 0, "c": 1, "r": 2}[ax]
            vj = {"b": 1, "m": 2, "t": 3}[ay]
            for i, line in enumerate(prim.text.split("\n")):
                off = -i * h * 1.4
                px = prim.pos.x * self.k + self.ox - off * math.sin(math.radians(prim.angle))
                py = prim.pos.y * self.k + self.oy + off * math.cos(math.radians(prim.angle))
                txt = line.replace("°", "%%d")
                self.ents.append(f"0\nTEXT\n{self._common(prim, color)}10\n{px:.4f}\n20\n{py:.4f}\n30\n0.0\n"
                                 f"40\n{h:.4f}\n1\n{txt}\n50\n{prim.angle:.4f}\n72\n{hj}\n73\n{vj}\n"
                                 f"11\n{px:.4f}\n21\n{py:.4f}\n31\n0.0\n")

    def polyline(self, prim, pts, closed: bool, color: int) -> None:
        head = f"0\nPOLYLINE\n{self._common(prim, color)}66\n1\n10\n0.0\n20\n0.0\n30\n0.0\n70\n{1 if closed else 0}\n"
        verts = []
        for v in pts:
            x, y = self._xy(v)
            verts.append(f"0\nVERTEX\n8\n{self._layer(prim.layer, color)}\n10\n{x:.4f}\n20\n{y:.4f}\n30\n0.0\n")
        self.ents.append(head + "".join(verts) + f"0\nSEQEND\n8\n{self._layer(prim.layer, color)}\n")

    def document(self) -> str:
        layers = "".join(f"0\nLAYER\n2\n{n}\n70\n0\n62\n{c}\n6\nCONTINUOUS\n" for n, c in self.layers.items())
        return ("0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n9\n$INSUNITS\n70\n4\n0\nENDSEC\n"
                "0\nSECTION\n2\nTABLES\n"
                "0\nTABLE\n2\nLTYPE\n70\n1\n0\nLTYPE\n2\nCONTINUOUS\n70\n0\n3\nSolid line\n72\n65\n73\n0\n40\n0.0\n"
                "0\nENDTAB\n"
                f"0\nTABLE\n2\nLAYER\n70\n{len(self.layers)}\n{layers}0\nENDTAB\n0\nENDSEC\n"
                "0\nSECTION\n2\nBLOCKS\n0\nENDSEC\n"
                "0\nSECTION\n2\nENTITIES\n" + "".join(self.ents) + "0\nENDSEC\n0\nEOF\n")


def scene_to_dxf(scene: Scene, scale: float = 1.0, annot: float = 10.0) -> str:
    w = DxfWriter(scale, annot=annot)
    w.add_scene(scene)
    return w.document()


def save_dxf(scene: Scene, path, scale: float = 1.0, annot: float = 10.0) -> None:
    Path(path).write_text(scene_to_dxf(scene, scale, annot), encoding="ascii", errors="replace")
