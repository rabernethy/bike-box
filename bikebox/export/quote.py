"""Customer quote (HTML → PDF) built from the order record and the BOM."""
from __future__ import annotations

import html
from pathlib import Path

from ..model import orders as O

_SYM = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "$", "AUD": "$"}


def _esc(x):
    return html.escape(str(x))


def _money(v, cur):
    return f"{_SYM.get(cur, '')}{v:,.2f}"


def build_html(design, geometry=None) -> str:
    o = O.get_order(design)
    q = O.quote(design, geometry)
    cur = q["currency"]
    c = o["customer"]
    cust = "<br>".join(_esc(x) for x in (c.get("name"), c.get("email"), c.get("phone"), c.get("address"))
                       if x)
    rows = "".join(f"<tr><td>{_esc(l['component'])}</td><td>{_esc(l['part'])}</td>"
                   f"<td class='r'>{_money(l['price'], cur)}</td></tr>" for l in q["lines"])
    extra = (f"<tr><td colspan='2'>Parts subtotal</td><td class='r'>{_money(q['parts_total'], cur)}</td></tr>"
             f"<tr><td colspan='2'>Frame build (labour)</td><td class='r'>{_money(q['labor'], cur)}</td></tr>"
             f"<tr><td colspan='2'>Frame</td><td class='r'>{_money(q['frame_price'], cur)}</td></tr>"
             f"<tr class='tot'><td colspan='2'>Total</td><td class='r'>{_money(q['total'], cur)}</td></tr>")
    return f"""<html><head><style>
      body {{ font-family: sans-serif; color: #111; }}
      h1 {{ font-size: 20px; margin: 0; }} .sub {{ color:#555; font-size:11px; }}
      table {{ border-collapse: collapse; width: 100%; font-size: 12px; margin-top: 10px; }}
      th, td {{ border: 1px solid #bbb; padding: 4px 7px; text-align: left; }}
      td.r, th.r {{ text-align: right; }} tr.tot td {{ font-weight: bold; background:#eee; }}
    </style></head><body>
      <h1>Quote — {_esc(design.get('title') or 'Custom frame')}</h1>
      <div class="sub">Order {_esc(o.get('order_no') or '—')} · status: {_esc(o.get('status'))}
        {' · due ' + _esc(o['due']) if o.get('due') else ''}</div>
      <p><b>Customer</b><br>{cust or '—'}</p>
      {('<p>' + _esc(c['notes']) + '</p>') if c.get('notes') else ''}
      <table><thead><tr><th>Component</th><th>Part</th><th class='r'>Price</th></tr></thead>
      <tbody>{rows}{extra}</tbody></table>
      <p class="sub">Prices are the builder's own; parts not priced show {_money(0, cur)}.</p>
    </body></html>"""


def save_pdf(design, path, geometry=None) -> Path:
    from ..qt import QtGui
    try:
        from ..qt import QtPrintSupport
    except Exception:  # pragma: no cover
        QtPrintSupport = None
    path = Path(path)
    doc = QtGui.QTextDocument()
    doc.setHtml(build_html(design, geometry))
    _print = getattr(doc, "print_", None) or doc.print
    if QtPrintSupport is not None and hasattr(QtPrintSupport, "QPrinter"):
        pr = QtPrintSupport.QPrinter(QtPrintSupport.QPrinter.PrinterMode.HighResolution)
        pr.setOutputFormat(QtPrintSupport.QPrinter.OutputFormat.PdfFormat)
        pr.setOutputFileName(str(path))
        _print(pr)
    else:
        _print(QtGui.QPdfWriter(str(path)))
    return path
