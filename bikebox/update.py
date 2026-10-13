"""Update check and 'What's New'.

Checks the project's GitHub releases for a newer version and reads the bundled
changelog. Network use is limited to a single GET of this project's own public
releases endpoint; no user data is sent. The check is best-effort and never
raises into the UI.
"""
from __future__ import annotations

import json
import re
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
    return {"version": tag, "url": data.get("html_url") or RELEASES_URL,
            "notes": (data.get("body") or "").strip(), "newer": is_newer(tag)}


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
    return bool(load_settings().get("update_check", True))


def whats_new_unseen() -> bool:
    """True when the current version's notes haven't been shown yet."""
    return load_settings().get("last_whats_new") != __version__


def mark_whats_new_seen() -> None:
    save_settings(last_whats_new=__version__)
