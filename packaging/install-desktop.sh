#!/bin/sh
# Install a desktop launcher (menu entry + icon) for this Bike Box checkout.
# Per-user: writes only under ~/.local/share.  Remove with: install-desktop.sh --uninstall
set -eu

HERE="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS="$DATA/applications"
ICONS="$DATA/icons/hicolor"
PY="${FRAMEWRIGHT_PYTHON:-/usr/bin/python3}"

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$APPS/bikebox.desktop"
    for s in 48 64 128 256; do rm -f "$ICONS/${s}x${s}/apps/bikebox.png"; done
    update-desktop-database "$APPS" 2>/dev/null || true
    gtk-update-icon-cache -q -t "$ICONS" 2>/dev/null || true
    echo "Bike Box launcher removed"
    exit 0
fi

[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p "$APPS"

# icons, painted by the app itself
QT_QPA_PLATFORM=offscreen PYTHONPATH="$HERE" "$PY" - "$ICONS" <<'EOF'
import sys
from pathlib import Path
from bikebox.qt import QtWidgets
app = QtWidgets.QApplication(sys.argv[:1])
from bikebox.gui.app import app_icon
icon = app_icon()
for s in (48, 64, 128, 256):
    d = Path(sys.argv[1]) / f"{s}x{s}" / "apps"
    d.mkdir(parents=True, exist_ok=True)
    icon.pixmap(s, s).save(str(d / "bikebox.png"))
EOF

cat > "$APPS/bikebox.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.5
Name=Bike Box
GenericName=Bicycle Frame Designer
Comment=Open-source bicycle frame design: geometry, fit, drawings, miter templates
Exec=env PYTHONPATH=$HERE $PY -m bikebox %F
TryExec=$PY
Path=$HOME
Icon=bikebox
Terminal=false
StartupNotify=true
StartupWMClass=bikebox
Categories=Graphics;Engineering;
Keywords=bicycle;bike;frame;cad;geometry;framebuilding;
EOF

desktop-file-validate "$APPS/bikebox.desktop" 2>/dev/null || true
update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -q -t "$ICONS" 2>/dev/null || true
echo "Installed $APPS/bikebox.desktop (runs $HERE with $PY)"
