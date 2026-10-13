"""Online design gallery (a 'marketplace' hosted in the project's GitHub repo).

Browse and download shared ``.bikebox`` designs from a ``gallery/`` folder in
the repository; share your own by opening a pre-filled GitHub issue. There is no
custom backend -- GitHub serves the files -- and all network use is a best-effort
GET of public URLs, never raising into the UI.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from . import __version__

REPO = "rabernethy/bike-box"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/gallery/"
INDEX_URL = RAW + "index.json"
_UA = {"User-Agent": f"BikeBox/{__version__}"}


def _get(url: str, timeout: float) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as r:  # noqa: S310
            return r.read()
    except Exception:
        return None


def fetch_index(timeout: float = 5.0) -> list[dict] | None:
    """The list of shared designs, or None if the gallery can't be reached.
    Each entry has ``name``, ``file``, ``author`` and ``description``."""
    raw = _get(INDEX_URL, timeout)
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    designs = data.get("designs") if isinstance(data, dict) else None
    if not isinstance(designs, list):
        return None
    return [d for d in designs if isinstance(d, dict) and d.get("file")]


def fetch_design(file: str, timeout: float = 15.0) -> bytes | None:
    """Download one design's ``.bikebox`` bytes (None on failure). The file name
    is restricted to a plain gallery file (no path traversal)."""
    name = str(file)
    if "/" in name or "\\" in name or name.startswith(".."):
        return None
    return _get(RAW + urllib.parse.quote(name), timeout)


def submit_url(title: str = "") -> str:
    """A pre-filled 'share your design' GitHub issue URL."""
    q = urllib.parse.urlencode({
        "title": title or "Gallery submission: <your design name>",
        "labels": "gallery",
        "body": ("Attach your .bikebox file and describe the design (name, author, a sentence or two). "
                 "We'll add it to the online gallery."),
    })
    return f"https://github.com/{REPO}/issues/new?{q}"
