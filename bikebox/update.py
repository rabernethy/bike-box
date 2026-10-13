"""Update check and 'What's New'.

Checks the project's GitHub releases for a newer version and reads the bundled
changelog. Network use is limited to a single GET of this project's own public
releases endpoint; no user data is sent. The check is best-effort and never
raises into the UI.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import __version__
from .model.library import config_dir

REPO = "rabernethy/bike-box"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
CHANGELOG = Path(__file__).resolve().parent / "data" / "CHANGELOG.md"


def current_version() -> str:
    return __version__


def _parts(v: str) -> tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", v or "")][:3]
    return tuple(nums + [0] * (3 - len(nums)))


def is_newer(candidate: str, current: str = __version__) -> bool:
    return _parts(candidate) > _parts(current)


def check_latest(timeout: float = 4.0) -> dict | None:
    """The latest published release, or None if it can't be reached.
    Returns ``{version, url, notes, newer}``."""
    req = urllib.request.Request(
        LATEST_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": f"BikeBox/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 (fixed https URL)
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    tag = str(data.get("tag_name", "")).lstrip("vV")
    if not tag:
        return None
    assets = [{"name": a.get("name", ""), "url": a.get("browser_download_url", ""),
               "size": int(a.get("size", 0) or 0)}
              for a in (data.get("assets") or []) if a.get("browser_download_url")]
    return {"version": tag, "url": data.get("html_url") or RELEASES_URL,
            "notes": (data.get("body") or "").strip(), "newer": is_newer(tag), "assets": assets}


# -- download & install ----------------------------------------------------------
def asset_for_platform(assets: list[dict]) -> dict | None:
    """Pick the release asset matching this OS (Windows installer, macOS disk
    image, Linux tarball)."""
    if sys.platform.startswith("win"):
        exts, prefer = (".exe", ".msi"), "setup"
    elif sys.platform == "darwin":
        exts, prefer = (".dmg",), ""
    else:
        exts, prefer = (".tar.gz", ".appimage", ".tgz"), "linux"
    cands = [a for a in assets if a.get("name", "").lower().endswith(exts)]
    if not cands:
        return None
    cands.sort(key=lambda a: (prefer not in a["name"].lower(), len(a["name"])))
    return cands[0]


def download(url: str, dest: Path, progress=None) -> Path:
    """Download ``url`` to ``dest`` (progress is an optional callback(fraction))."""
    req = urllib.request.Request(url, headers={"User-Agent": f"BikeBox/{__version__}"})
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:   # noqa: S310
            total = int(r.headers.get("Content-Length", 0) or 0)
            done = 0
            with tmp.open("wb") as fh:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(done / total)
            if total and done < total:               # truncated (e.g. ran out of space)
                raise OSError(f"incomplete download ({done} of {total} bytes)")
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)                  # don't leave a partial file behind
        raise
    return dest


def launch_installer(path: Path) -> None:
    """Open the downloaded installer / image so the user can complete the update
    (a packaged app can't safely overwrite itself while running)."""
    path = Path(path)
    if sys.platform.startswith("win"):
        os.startfile(str(path))                          # noqa: S606 (user-initiated installer)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])  # reveal the tarball


# -- changelog / what's new ------------------------------------------------------
def changelog_text() -> str:
    try:
        return CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        return ""


def latest_notes() -> str:
    """The changelog entry for the current version (its heading + body)."""
    text = changelog_text()
    if not text:
        return ""
    blocks = re.split(r"(?m)^## ", text)
    want = _parts(__version__)
    for b in blocks:
        if _parts(b.split("\n", 1)[0]) == want:
            return "## " + b.strip()
    # fall back to the first versioned entry
    for b in blocks[1:]:
        if re.match(r"\d", b):
            return "## " + b.strip()
    return text.strip()


# -- settings (per user) ---------------------------------------------------------
def _settings_file() -> Path:
    return config_dir() / "settings.json"


def load_settings() -> dict:
    try:
        d = json.loads(_settings_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(**changes) -> None:
    s = load_settings()
    s.update(changes)
    p = _settings_file()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def update_check_enabled() -> bool:
    return bool(load_settings().get("update_check", False))      # opt-in; off by default


def whats_new_unseen() -> bool:
    """True when the current version's notes haven't been shown yet."""
    return load_settings().get("last_whats_new") != __version__


def mark_whats_new_seen() -> None:
    save_settings(last_whats_new=__version__)
