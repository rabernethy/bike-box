"""Batch export: many design files to many formats in one call."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..model.design import Design

DEFAULT_FORMATS = ("pdf", "svg", "png", "dxf", "csv")


def bulk_export(paths: Sequence, out_dir, formats: Sequence[str] = DEFAULT_FORMATS,
                opts=None) -> list[Path]:
    """Export each design in ``paths`` to ``out_dir`` in every requested format.

    ``paths`` are ``.bikebox`` (or ``.bcad``) files.  A single ``csv`` with every
    design is written once (``bulk.csv``); the other formats produce one file
    per design (``<stem>.<ext>``).  Returns the list of files written."""
    from .drawing import SheetOptions
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = opts or SheetOptions()
    formats = [f.lower().lstrip(".") for f in formats]
    written: list[Path] = []

    loaded: list[tuple[Path, Design]] = []
    for p in paths:
        p = Path(p)
        try:
            loaded.append((p, Design.load(p)))
        except Exception:
            continue

    for src, design in loaded:
        stem = src.stem
        if "pdf" in formats:
            from .drawing import save_pdf
            written.append(save_pdf(design, out_dir / f"{stem}.pdf", opts))
        if "svg" in formats:
            from .drawing import save_sheet_svg
            written.append(save_sheet_svg(design, out_dir / f"{stem}.svg", opts))
        if "png" in formats:
            from .drawing import save_sheet_png
            written.append(save_sheet_png(design, out_dir / f"{stem}.png", opts))
        if "dxf" in formats:
            from ..geometry.solver import solve
            from ..render.bike_scene import build_scene
            from .dxf import save_dxf
            scene = build_scene(solve(design), dimensions=opts.dimensions)
            save_dxf(scene, out_dir / f"{stem}.dxf")
            written.append(out_dir / f"{stem}.dxf")
        if "stl" in formats:
            from ..geometry.solver import solve
            from .stl import save_stl
            save_stl(solve(design), out_dir / f"{stem}.stl")
            written.append(out_dir / f"{stem}.stl")
        if "freecad" in formats:
            from ..geometry.solver import solve
            from .freecad import save_freecad_macro
            save_freecad_macro(solve(design), out_dir / f"{stem}.FCMacro")
            written.append(out_dir / f"{stem}.FCMacro")
        if "step" in formats:
            from ..geometry.solver import solve
            from .step import save_step
            save_step(solve(design), out_dir / f"{stem}.step")
            written.append(out_dir / f"{stem}.step")
        if "iges" in formats:
            from ..geometry.solver import solve
            from .iges import save_iges
            save_iges(solve(design), out_dir / f"{stem}.iges")
            written.append(out_dir / f"{stem}.iges")

    if "csv" in formats and loaded:
        from .csv_export import export_csv
        csv_path = out_dir / "bulk.csv"
        export_csv([(src.stem, d) for src, d in loaded], csv_path)
        written.append(csv_path)

    return written
