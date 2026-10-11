"""BikeCAD ``.bcad`` import (placeholder).

``.bcad`` files are Java ``Properties`` XML documents.  The key names are not
publicly documented, so a faithful mapping needs real sample files to build
and test against.  Until then this module reads the file safely, reports what
it found and refuses to guess, rather than silently producing a wrong bike.
"""
from __future__ import annotations

from pathlib import Path


class BcadImportError(ValueError):
    pass


def read_properties(path: str | Path) -> dict[str, str]:
    """Parse a Java properties XML file into a dict (safe XML parser)."""
    try:
        from defusedxml import ElementTree as ET
    except ImportError as exc:                     # pragma: no cover
        raise BcadImportError("defusedxml is required to read .bcad files") from exc
    root = ET.parse(str(path)).getroot()
    return {e.get("key"): (e.text or "") for e in root.iter("entry") if e.get("key")}


def load_bcad(path: str | Path):
    props = read_properties(path)
    raise BcadImportError(
        f"BikeCAD import is not supported yet ({len(props)} properties found in {Path(path).name}). "
        "Key mapping needs sample .bcad files; contributions welcome.")
