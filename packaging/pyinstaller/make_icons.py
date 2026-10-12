"""Render Bike Box application icons for the installers.

Writes, next to this script:
  * bikebox.ico  (Windows)  via Pillow
  * bikebox.icns (macOS)    via `iconutil` when available, else Pillow
  * bikebox-256.png / -512.png (Linux / fallback)

The icon itself is drawn by bikebox.gui.app.app_icon (no asset files), so this
just rasterises it at several sizes.  Missing optional tools are skipped rather
than failing the build.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))


def main() -> int:
    from bikebox.qt import QtWidgets
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["bikebox"])
    from bikebox.gui.app import app_icon
    icon = app_icon()
    sizes = [16, 32, 48, 64, 128, 256, 512, 1024]
    pngs: dict[int, Path] = {}
    tmp = Path(tempfile.mkdtemp())
    for s in sizes:
        pm = icon.pixmap(s, s)
        if pm.isNull():
            continue
        out = tmp / f"icon_{s}.png"
        pm.save(str(out), "PNG")
        pngs[s] = out
    # Linux / generic PNGs next to the spec
    for s in (256, 512):
        if s in pngs:
            (HERE / f"bikebox-{s}.png").write_bytes(pngs[s].read_bytes())

    # Windows .ico (needs Pillow)
    try:
        from PIL import Image
        imgs = [Image.open(pngs[s]) for s in (16, 32, 48, 64, 128, 256) if s in pngs]
        if imgs:
            imgs[0].save(HERE / "bikebox.ico", sizes=[(i.width, i.height) for i in imgs])
            print("wrote bikebox.ico")
    except Exception as exc:                       # noqa: BLE001 - optional
        print(f"skip .ico: {exc}")

    # macOS .icns
    if sys.platform == "darwin":
        try:
            iconset = tmp / "bikebox.iconset"
            iconset.mkdir(exist_ok=True)
            spec = {16: "16x16", 32: ["16x16@2x", "32x32"], 64: "32x32@2x", 128: "128x128",
                    256: ["128x128@2x", "256x256"], 512: ["256x256@2x", "512x512"], 1024: "512x512@2x"}
            for s, names in spec.items():
                if s not in pngs:
                    continue
                for nm in ([names] if isinstance(names, str) else names):
                    (iconset / f"icon_{nm}.png").write_bytes(pngs[s].read_bytes())
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "bikebox.icns")],
                           check=True)
            print("wrote bikebox.icns")
        except Exception as exc:                   # noqa: BLE001 - optional
            print(f"skip .icns: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
