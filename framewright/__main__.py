"""FrameWright entry point.

    framewright [design.fwd ...]                 start the GUI
    framewright export design.fwd out.pdf|svg|png|dxf|csv   headless export
    framewright info design.fwd                  print key geometry
"""
from __future__ import annotations

import sys
from pathlib import Path


def _headless_export(src: str, dst: str) -> int:
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from .qt import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    from .geometry.solver import solve
    from .model.design import Design
    from .render.bike_scene import build_scene
    d = Design.load(src)
    g = solve(d)
    ext = Path(dst).suffix.lower()
    if ext == ".svg":
        from .export.svg import save_svg
        save_svg(build_scene(g), dst, 0.2, d.title)
    elif ext == ".dxf":
        from .export.dxf import save_dxf
        save_dxf(build_scene(g), dst)
    elif ext == ".png":
        from .render.qt_render import render_image
        render_image(build_scene(g), 2400, 1500).save(dst)
    elif ext == ".pdf":
        from .export.drawing import save_pdf
        save_pdf(d, dst)
    elif ext == ".csv":
        from .export.csv_export import export_csv
        export_csv([(d.title, d)], dst)
    else:
        print(f"unsupported format: {ext}", file=sys.stderr)
        return 2
    print(f"wrote {dst}")
    return 0


def _info(src: str) -> int:
    from .geometry.solver import solve
    from .model.design import Design
    from .model.units import fmt_len
    d = Design.load(src)
    g = solve(d)
    print(d.title)
    for k in ("stack", "reach", "top_tube_effective", "head_tube_length", "head_tube_angle", "seat_tube_angle",
              "chainstay_length", "bb_drop", "wheelbase", "front_center", "trail", "standover", "toe_clearance"):
        v = g.v[k]
        print(f"  {k:22s} {v:9.2f}")
    for w in g.warnings:
        print("  warning:", w)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "export" and len(argv) == 3:
        return _headless_export(argv[1], argv[2])
    if argv and argv[0] == "info" and len(argv) == 2:
        return _info(argv[1])
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    from .gui.app import run
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
