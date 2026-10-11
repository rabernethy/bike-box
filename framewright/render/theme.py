"""Drawing styles derived from a design's display settings."""
from __future__ import annotations

from dataclasses import dataclass

from ..model.design import Design
from .scene import Style


@dataclass
class Theme:
    mode: str
    bg: str
    outline: str
    width: float
    dim: str
    centerline: str
    component: str
    component_fill: str
    tire: str
    rim: str
    rider: str
    frame_fill: str | None
    fork_fill: str | None
    ht_fill: str | None
    lug_fill: str | None
    decal: str
    ghost_width: float = 0.5

    @classmethod
    def from_design(cls, d: Design) -> "Theme":
        mode = d["display_mode"]
        w = d.f("outline_width")
        if mode == "blueprint":
            return cls(mode, "#173a6b", "#e8f0ff", w, "#ffffff", "#9fc3ff", "#e8f0ff", None, "#e8f0ff",
                       "#e8f0ff", "#9fc3ff", None, None, None, None, "#e8f0ff")
        if mode in ("outline", "centerline"):
            return cls(mode, d["color_background"], d["color_outline"], w, d["color_dimension"],
                       d["color_centerline"], d["color_outline"], "#ffffff", d["color_outline"], d["color_outline"],
                       d["color_rider"], "#ffffff", "#ffffff", "#ffffff", "#ffffff", d["color_outline"])
        return cls(mode, d["color_background"], d["color_outline"], w, d["color_dimension"],
                   d["color_centerline"], d["color_components"], "#8c8c8c", d["color_tire"], "#3c3c3c",
                   d["color_rider"], d["paint_frame"], d["paint_fork"], d["paint_head_tube"], d["paint_lugs"],
                   d["paint_decal"])

    # styles --------------------------------------------------------------------
    def frame(self, fill=None) -> Style:
        return Style(self.outline, self.width, fill if self.mode != "centerline" else None)

    def comp(self, fill: str | None = "default", width_k: float = 1.0) -> Style:
        f = self.component_fill if fill == "default" else fill
        if self.mode in ("outline", "blueprint", "centerline") and f is not None:
            f = None if self.mode == "blueprint" else "#ffffff"
        return Style(self.outline, self.width * width_k, f)

    def thin(self, color: str | None = None, k: float = 0.5) -> Style:
        return Style(color or self.outline, self.width * k, None)

    def centre(self) -> Style:
        return Style(self.centerline, 0.25, None, dash=(6.0, 1.5, 1.0, 1.5))

    def dimension(self) -> Style:
        return Style(self.dim, 0.25, None)

    def fill_only(self, color: str) -> Style:
        return Style(None, 0.0, color)
