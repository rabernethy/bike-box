"""Animated GIF morphing between two designs.

Interpolates with :meth:`Design.lerp`, renders each frame through
``render.bike_scene.build_scene`` + ``render.qt_render.render_image`` and writes
the frames with Pillow.  All frames share one framing (the union of every
frame's bounds) so the bike does not jump around.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..geometry.solver import solve
from ..model.design import Design
from ..render.bike_scene import build_scene
from ..render.qt_render import render_image
from ..render.scene import Scene


def morph_frames(a: Design, b: Design, n: int) -> list[Design]:
    """``n`` interpolated designs from ``a`` (t=0) to ``b`` (t=1)."""
    n = max(2, int(n))
    return [Design.lerp(a, b, i / (n - 1)) for i in range(n)]


def _qimage_to_pil(img):
    from PIL import Image as PILImage
    from ..qt import QtGui
    img = img.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    # account for row padding (bytesPerLine may exceed w*4)
    bpl = img.bytesPerLine()
    raw = bytes(ptr)
    if bpl == w * 4:
        return PILImage.frombytes("RGBA", (w, h), raw)
    rows = b"".join(raw[r * bpl:r * bpl + w * 4] for r in range(h))
    return PILImage.frombytes("RGBA", (w, h), rows)


def _union_bounds(scenes: Sequence[Scene], pad: float = 30.0):
    xs0, ys0, xs1, ys1 = [], [], [], []
    for sc in scenes:
        b = sc.bounds()
        xs0.append(b[0]); ys0.append(b[1]); xs1.append(b[2]); ys1.append(b[3])
    return (min(xs0) - pad, min(ys0) - pad, max(xs1) + pad, max(ys1) + pad)


def save_morph_gif(a: Design, b: Design, path, frames: int = 24, size: tuple[int, int] = (960, 600),
                   duration_ms: int = 80, pingpong: bool = True) -> int:
    """Write a morph GIF; returns the number of frames written."""
    designs = morph_frames(a, b, frames)
    scenes = [build_scene(solve(d), dimensions=False) for d in designs]
    bounds = _union_bounds(scenes)
    w, h = int(size[0]), int(size[1])
    pil_frames = [_qimage_to_pil(render_image(sc, w, h, bounds=bounds, background="#ffffff"))
                  for sc in scenes]
    if pingpong and len(pil_frames) > 2:
        pil_frames = pil_frames + pil_frames[-2:0:-1]
    # GIF has no alpha blending across frames; flatten to RGB
    rgb = [f.convert("RGB") for f in pil_frames]
    path = Path(path)
    rgb[0].save(str(path), save_all=True, append_images=rgb[1:], duration=duration_ms,
                loop=0, optimize=False, disposal=2)
    return len(rgb)
