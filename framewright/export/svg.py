"""Scene -> SVG (true scale, paper millimetres)."""
from __future__ import annotations

import base64
import math
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from ..render.scene import (Arc, AngleDim, Circle, Gradient, Image, LinearDim, Polyline, Scene, Style, Text,
                            explode_dimension)


_GENERIC_FONTS = {"sans serif": "sans-serif", "sans": "sans-serif", "sansserif": "sans-serif", "serif": "serif",
                  "monospace": "monospace", "mono": "monospace"}


def css_font_family(font: str) -> str:
    """Qt-style family name -> CSS font-family list with a generic fallback."""
    generic = _GENERIC_FONTS.get(font.strip().lower())
    if generic:
        return generic
    return f"'{font}', sans-serif"


class SvgWriter:
    """Accumulates SVG elements.  Model points map to paper mm as
    ``(x * scale + ox, -y * scale + oy)``."""

    def __init__(self, scale: float = 0.1, ox: float = 0.0, oy: float = 0.0, embed_images: bool = True):
        self.k = scale
        self.ox = ox
        self.oy = oy
        self.parts: list[str] = []
        self.defs: list[str] = []
        self._gid = 0
        self.embed_images = embed_images

    def pt(self, v) -> tuple[float, float]:
        return v.x * self.k + self.ox, -v.y * self.k + self.oy

    def _paint(self, st: Style) -> str:
        attrs = []
        if st.stroke and st.width > 0:
            attrs.append(f'stroke="{st.stroke}" stroke-width="{st.width:.3f}" stroke-linecap="{st.cap}" '
                         f'stroke-linejoin="{st.join}"')
            if st.dash:
                attrs.append(f'stroke-dasharray="{",".join(f"{v:.2f}" for v in st.dash)}"')
        else:
            attrs.append('stroke="none"')
        f = st.fill
        if f is None:
            attrs.append('fill="none"')
        elif isinstance(f, Gradient):
            self._gid += 1
            gid = f"g{self._gid}"
            x1, y1 = self.pt(_P(*f.p0))
            x2, y2 = self.pt(_P(*f.p1))
            stops = "".join(f'<stop offset="{max(0, min(1, o)):.4f}" stop-color="{c}"/>' for o, c in f.stops)
            self.defs.append(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{x1:.3f}" '
                             f'y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}">{stops}</linearGradient>')
            attrs.append(f'fill="url(#{gid})" fill-rule="evenodd"')
        else:
            attrs.append(f'fill="{f}" fill-rule="evenodd"')
        if st.opacity < 1:
            attrs.append(f'opacity="{st.opacity:.3f}"')
        return " ".join(attrs)

    def add_scene(self, scene: Scene, layer_groups: bool = True) -> None:
        current = None
        for prim in scene.visible():
            if layer_groups and prim.layer != current:
                if current is not None:
                    self.parts.append("</g>")
                self.parts.append(f'<g id={quoteattr(prim.layer + "_" + str(len(self.parts)))} '
                                  f'inkscape:groupmode="layer" inkscape:label={quoteattr(prim.layer)}>')
                current = prim.layer
            self.add_prim(prim)
        if layer_groups and current is not None:
            self.parts.append("</g>")

    def add_prim(self, prim) -> None:
        if isinstance(prim, (LinearDim, AngleDim)):
            for sub in explode_dimension(prim, 1.0 / self.k):
                self.add_prim(sub)
            return
        st = prim.style
        if isinstance(prim, Polyline):
            if len(prim.pts) < 2:
                return
            d = "M" + " L".join(f"{x:.3f},{y:.3f}" for x, y in map(self.pt, prim.pts))
            if prim.closed:
                d += " Z"
                for h in prim.holes:
                    if len(h) > 2:
                        d += " M" + " L".join(f"{x:.3f},{y:.3f}" for x, y in map(self.pt, h)) + " Z"
            paint = self._paint(st if prim.closed else st.with_(fill=None))
            self.parts.append(f'<path d="{d}" {paint}/>')
        elif isinstance(prim, Circle):
            x, y = self.pt(prim.c)
            self.parts.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="{prim.r * self.k:.3f}" {self._paint(st)}/>')
        elif isinstance(prim, Arc):
            r = prim.r * self.k
            a0 = math.radians(prim.start)
            a1 = math.radians(prim.start + prim.span)
            x0, y0 = self.pt(_P(prim.c.x + prim.r * math.cos(a0), prim.c.y + prim.r * math.sin(a0)))
            x1, y1 = self.pt(_P(prim.c.x + prim.r * math.cos(a1), prim.c.y + prim.r * math.sin(a1)))
            large = 1 if abs(prim.span) > 180 else 0
            sweep = 0 if prim.span > 0 else 1        # y is flipped
            self.parts.append(f'<path d="M{x0:.3f},{y0:.3f} A{r:.3f},{r:.3f} 0 {large} {sweep} {x1:.3f},{y1:.3f}" '
                              f'{self._paint(st.with_(fill=None))}/>')
        elif isinstance(prim, Text):
            if not prim.text:
                return
            x, y = self.pt(prim.pos)
            size = prim.size if prim.annotative else prim.size * self.k
            fs = size * 1.38
            ax, ay = (prim.anchor + "m")[0], (prim.anchor + "m")[1]
            anchor = {"l": "start", "c": "middle", "r": "end"}[ax]
            lines = prim.text.split("\n")
            total = fs * 1.2 * len(lines)
            first = {"t": fs * 0.95, "m": -total / 2 + fs * 0.95, "b": -total + fs * 0.95}[ay]
            weight = ' font-weight="bold"' if prim.bold else ""
            italic = ' font-style="italic"' if prim.italic else ""
            tsp = "".join(f'<tspan x="0" y="{first + i * fs * 1.2:.3f}">{escape(s)}</tspan>' for i, s in enumerate(lines))
            box = ""
            if prim.box:
                w = max(len(s) for s in lines) * fs * 0.55
                bx = {"start": 0, "middle": -w / 2, "end": -w}[anchor]
                box = (f'<rect x="{bx - 1:.3f}" y="{first - fs:.3f}" width="{w + 2:.3f}" height="{total + 1:.3f}" '
                       f'fill="white" fill-opacity="0.85" stroke="{st.stroke or "#000"}" stroke-width="0.2"/>')
            self.parts.append(f'<g transform="translate({x:.3f},{y:.3f}) rotate({-prim.angle:.3f})">{box}'
                              f'<text font-family={quoteattr(css_font_family(prim.font))} font-size="{fs:.3f}" text-anchor="{anchor}" '
                              f'fill="{st.stroke or "#000"}"{weight}{italic}>{tsp}</text></g>')
        elif isinstance(prim, Image):
            p = Path(prim.path)
            if not p.exists():
                return
            try:
                from ..qt import QtGui
                img = QtGui.QImage(str(p))
                w, h = img.width(), img.height()
            except Exception:
                return
            href = str(p)
            if self.embed_images:
                mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
                href = f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
            x, y = self.pt(prim.origin)
            k = prim.mm_per_px * self.k
            flip = f" scale(-1,1)" if prim.flip else ""
            self.parts.append(f'<image x="0" y="0" width="{w}" height="{h}" href="{href}" opacity="{st.opacity:.2f}" '
                              f'transform="translate({x:.3f},{y:.3f}) rotate({-prim.rotation:.3f}) scale({k:.6f}){flip}"/>')

    def document(self, width_mm: float, height_mm: float, background: str | None = None, title: str = "") -> str:
        bg = f'<rect x="0" y="0" width="{width_mm:.3f}" height="{height_mm:.3f}" fill="{background}"/>' if background else ""
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
                f'width="{width_mm:.3f}mm" height="{height_mm:.3f}mm" viewBox="0 0 {width_mm:.3f} {height_mm:.3f}">\n'
                f'<title>{escape(title)}</title>\n<defs>{"".join(self.defs)}</defs>\n{bg}\n'
                + "\n".join(self.parts) + "\n</svg>\n")


class _P:
    __slots__ = ("x", "y")

    def __init__(self, x, y):
        self.x, self.y = x, y


def scene_to_svg(scene: Scene, scale: float = 0.1, margin_mm: float = 10.0, title: str = "",
                 background: bool = True) -> str:
    """Whole scene at ``scale`` (paper mm per model mm; 1.0 = full size)."""
    x0, y0, x1, y1 = scene.bounds()
    w = (x1 - x0) * scale + 2 * margin_mm
    h = (y1 - y0) * scale + 2 * margin_mm
    sw = SvgWriter(scale, -x0 * scale + margin_mm, y1 * scale + margin_mm)
    sw.add_scene(scene)
    return sw.document(w, h, scene.background if background else None, title)


def save_svg(scene: Scene, path, scale: float = 0.1, title: str = "") -> None:
    Path(path).write_text(scene_to_svg(scene, scale, title=title), encoding="utf-8")
