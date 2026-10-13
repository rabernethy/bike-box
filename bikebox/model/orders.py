"""Customer / order records and quoting.

A design carries one order in ``design.extras["order"]`` (customer, status,
pricing). The quote is built from the bill of materials plus labour and a frame
build price. A lightweight order log is kept per user so past orders can be
listed. Catalog parts carry no prices, so line prices are the shop's own.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .library import config_dir

DEFAULT_ORDER = {
    "customer": {"name": "", "email": "", "phone": "", "address": "", "notes": ""},
    "order_no": "", "status": "quote", "due": "",
    "currency": "USD", "labor_hours": 0.0, "labor_rate": 0.0, "frame_price": 0.0,
    "prices": {},            # {BOM component label: unit price}
}
STATUSES = ["quote", "accepted", "building", "painting", "shipped", "done", "cancelled"]


def get_order(design) -> dict:
    o = design.extras.get("order")
    if not isinstance(o, dict):
        return json.loads(json.dumps(DEFAULT_ORDER))
    merged = json.loads(json.dumps(DEFAULT_ORDER))
    merged.update(o)
    merged["customer"] = {**DEFAULT_ORDER["customer"], **(o.get("customer") or {})}
    return merged


def quote(design, geometry=None) -> dict:
    """Line items + totals from the BOM and the order's pricing."""
    from ..analysis import bom as BOM
    o = get_order(design)
    prices = o.get("prices", {})
    lines = []
    parts_total = 0.0
    bom_entries = design.extras.get("bom") or {}
    cat_price = {}                           # component label -> catalogued price (imported stock)
    for r in BOM.build(design, geometry):
        if r.component == "Frame":
            continue
        # a manual per-order price overrides; otherwise fall back to an imported catalog price
        entry = next((e for e in bom_entries.values()
                      if isinstance(e, dict) and e.get("name") == r.part), None)
        default = float(entry["price"]) if isinstance(entry, dict) and isinstance(entry.get("price"),
                                                                                  (int, float)) else 0.0
        price = float(prices.get(r.component, default) or default)
        name = r.part or r.spec or "—"
        lines.append({"component": r.component, "part": name, "price": price})
        parts_total += price
    labor = float(o.get("labor_hours", 0) or 0) * float(o.get("labor_rate", 0) or 0)
    frame = float(o.get("frame_price", 0) or 0)
    return {"currency": o.get("currency", "USD"), "lines": lines, "parts_total": parts_total,
            "labor": labor, "frame_price": frame, "total": parts_total + labor + frame}


# -- order log (per user) ---------------------------------------------------------
def _file() -> Path:
    return config_dir() / "orders.json"


def load_orders() -> list[dict]:
    p = _file()
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return d.get("orders", []) if isinstance(d, dict) else []


def log_order(design, geometry=None) -> Path:
    """Append/replace a summary of this design's order in the per-user log
    (keyed by order number, or appended when there is none)."""
    o = get_order(design)
    q = quote(design, geometry)
    entry = {"order_no": o.get("order_no", ""), "customer": o["customer"].get("name", ""),
             "title": design.get("title", ""), "status": o.get("status", ""),
             "due": o.get("due", ""), "total": round(q["total"], 2), "currency": q["currency"],
             "saved": date.today().isoformat()}
    orders = load_orders()
    key = entry["order_no"].strip()
    if key:
        orders = [e for e in orders if str(e.get("order_no", "")).strip() != key]
    orders.append(entry)
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"format": "bikebox-orders", "version": 1, "orders": orders}, indent=1),
                   encoding="utf-8")
    tmp.replace(p)
    return p


def set_order(design, order: dict) -> None:
    design.extras["order"] = order
