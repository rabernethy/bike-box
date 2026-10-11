"""CSV export: one design, a batch of designs, or a whole folder.

``design_record`` flattens a design to ``{column: text}``.  Input parameter
values keep their parameter key as the column name; computed geometry values
(``g.v``) are prefixed ``calc:`` so a reader can tell *driving* dimensions
(inputs) from *driven* ones (results).  ``export_csv`` writes thousands of
designs to a single file using the union of all their columns.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from ..geometry.solver import Geometry, solve
from ..model import params as P
from ..model.design import Design

CALC_PREFIX = "calc:"


def _fmt(value) -> str:
    if isinstance(value, float):
        if value != value:                       # NaN
            return ""
        return f"{value:.6g}"
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def design_record(design: Design, g: Geometry | None = None) -> dict[str, str]:
    """Flatten ``design`` to an ordered ``{column: text}`` record.

    Columns: ``title`` first, then one per registered parameter (its key), then
    one ``calc:<name>`` per computed geometry value."""
    g = g or solve(design)
    rec: dict[str, str] = {"title": design.title}
    for pd in P.all_params():
        rec[pd.key] = _fmt(design.get(pd.key, pd.default))
    for name in sorted(g.v):
        rec[CALC_PREFIX + name] = _fmt(g.v[name])
    return rec


def export_csv(items: Iterable[tuple[str, Design]], path) -> Path:
    """Write ``(name, design)`` rows to one CSV (union of all columns).

    ``name`` is written to a leading ``source`` column; ``title`` follows, then
    the union of parameter and ``calc:`` columns in a stable order."""
    records: list[tuple[str, dict[str, str]]] = []
    columns: list[str] = []
    seen: set[str] = set()
    for name, design in items:
        rec = design_record(design)
        for k in rec:
            if k not in seen:
                seen.add(k)
                columns.append(k)
        records.append((name, rec))

    # keep "title" first, then parameter keys, then calc: columns (stable)
    ordered = (["title"]
               + [c for c in columns if c != "title" and not c.startswith(CALC_PREFIX)]
               + [c for c in columns if c.startswith(CALC_PREFIX)])
    header = ["source"] + ordered
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for name, rec in records:
            w.writerow([name] + [rec.get(c, "") for c in ordered])
    return path


def export_folder_csv(folder, path, pattern: str = "*.fwd") -> Path:
    """Export every design file in ``folder`` to one CSV."""
    folder = Path(folder)
    items: list[tuple[str, Design]] = []
    for p in sorted(folder.glob(pattern)):
        try:
            items.append((p.stem, Design.load(p)))
        except Exception:
            continue
    return export_csv(items, path)


def read_csv_table(path) -> list[list[str]]:
    """Read a CSV back into rows of strings (for placing on a drawing)."""
    path = Path(path)
    with path.open("r", newline="", encoding="utf-8") as fh:
        return [list(row) for row in csv.reader(fh)]
