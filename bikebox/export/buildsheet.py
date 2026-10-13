"""Build / cut sheet: one shop document (HTML → PDF) combining the key
geometry, the mitre cut list, the bill of materials and the fixture numbers."""
from __future__ import annotations

import html
from pathlib import Path

from ..analysis import bom as BOM
from ..analysis import jig
from ..geometry import mitre
from ..geometry.mitre import compute_mitres
from ..geometry.solver import Geometry
from ..model.units import fmt_angle, fmt_len
from . import mitre_output

_GEO = [("Stack", "stack", False), ("Reach", "reach", False), ("Head tube length", "head_tube_length", False),
        ("Head angle", "head_tube_angle", True), ("Seat angle", "seat_tube_angle", True),
        ("Seat tube (c-c)", "seat_tube_cc", False), ("Top tube (eff.)", "top_tube_effective", False),
        ("Chainstay", "chainstay_length", False), ("Front centre", "front_center", False),
        ("Wheelbase", "wheelbase", False), ("BB drop", "bb_drop", False), ("Trail", "trail", False),
        ("Standover", "standover", False)]


def _esc(x) -> str:
    return html.escape(str(x))


def _table(headers, rows) -> str:
    th = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    trs = []
    for r in rows:
        tds = "".join(f"<td>{_esc(c)}</td>" for c in r)
        trs.append(f"<tr>{tds}</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>"


def build_html(g: Geometry, units: str | None = None) -> str:
    d = g.design
    units = units or d["units"]
    title = d.get("title") or "Untitled frame"

    geo_rows = []
    for label, key, is_ang in _GEO:
        v = g.v.get(key)
        if v is None:
            continue
        geo_rows.append([label, fmt_angle(v) if is_ang else fmt_len(v, units, suffix=True)])

    cuts = compute_mitres(g, samples=180)
    cut_rows = mitre_output.cut_list_rows(g, cuts, units) if cuts else [["No mitred tubes"]]
    cut_head, cut_body = (cut_rows[0], cut_rows[1:]) if cuts else (["Cut list"], cut_rows)

    bom_rows = [[r.component, r.part or "—", r.spec, r.brand] for r in BOM.build(d, g)]

    fix_rows = [[lab, val, note] for lab, val, note in jig.fixture_numbers(g)]

    bo_rows = []
    for bo in getattr(g, "brazeons", []) or []:
        p = bo.get("point")
        xy = f"X {fmt_len(p.x, units)}, Y {fmt_len(p.y, units)}" if p is not None else ""
        bo_rows.append([bo.get("type", ""), bo.get("label", ""), bo.get("tube", ""),
                        fmt_len(float(bo.get("s", 0) or 0), units, suffix=True), xy])

    parts = [f"""<html><head><style>
      body {{ font-family: sans-serif; color: #111; }}
      h1 {{ font-size: 20px; margin: 0 0 2px 0; }}
      h2 {{ font-size: 14px; margin: 16px 0 4px 0; border-bottom: 1px solid #888; }}
      .sub {{ color: #555; font-size: 11px; margin-bottom: 8px; }}
      table {{ border-collapse: collapse; width: 100%; font-size: 11px; }}
      th, td {{ border: 1px solid #bbb; padding: 3px 6px; text-align: left; }}
      th {{ background: #eee; }}
    </style></head><body>
      <h1>{_esc(title)} — build sheet</h1>
      <div class="sub">{_esc(d.get('frame_material', '').capitalize())} ·
        {_esc(d.get('joint_style', ''))} · units: {_esc(units)}</div>
      <h2>Key geometry</h2>{_table(['Measurement', 'Value'], geo_rows)}
      <h2>Cut list (mitred tubes)</h2>{_table(cut_head, cut_body)}
      <h2>Bill of materials</h2>{_table(['Component', 'Part', 'Spec', 'Brand'], bom_rows)}
      <h2>Fixture setup</h2>{_table(['Datum', 'Value', 'Note'], fix_rows)}
      {'<h2>Braze-ons &amp; mounts</h2>' + _table(['Type', 'Label', 'Tube', 'Position', 'Coordinates'], bo_rows) if bo_rows else ''}
    </body></html>"""]
    return "".join(parts)


def save_pdf(g: Geometry, path, units: str | None = None) -> Path:
    from ..qt import QtGui
    try:
        from ..qt import QtPrintSupport
    except Exception:  # pragma: no cover
        QtPrintSupport = None
    path = Path(path)
    doc = QtGui.QTextDocument()
    doc.setHtml(build_html(g, units))
    if QtPrintSupport is not None and hasattr(QtPrintSupport, "QPrinter"):
        pr = QtPrintSupport.QPrinter(QtPrintSupport.QPrinter.PrinterMode.HighResolution)
        pr.setOutputFormat(QtPrintSupport.QPrinter.OutputFormat.PdfFormat)
        pr.setOutputFileName(str(path))
        _print = getattr(doc, "print_", None) or doc.print; _print(pr)
    else:                                   # fallback: QPdfWriter
        writer = QtGui.QPdfWriter(str(path))
        _print = getattr(doc, "print_", None) or doc.print; _print(writer)
    return path
