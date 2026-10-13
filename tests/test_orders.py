"""Customer / order records and quoting."""
from bikebox.model import orders as O
from bikebox.model.design import Design


def _cfg(monkeypatch, tmp_path):
    monkeypatch.setenv("BIKEBOX_CONFIG_DIR", str(tmp_path / "cfg"))


def test_quote_totals():
    d = Design()
    d.extras["bom"] = {"forks": {"name": "ENVE", "category": "forks"},
                       "saddles": {"name": "Flite", "category": "saddles"}}
    O.set_order(d, {**O.get_order(d), "labor_hours": 10, "labor_rate": 65, "frame_price": 950,
                    "prices": {"Fork": 500, "Saddle": 130}})
    q = O.quote(d, None)
    assert q["parts_total"] == 630            # 500 + 130
    assert q["labor"] == 650                  # 10 * 65
    assert q["total"] == 630 + 650 + 950
    # the Frame header row is not a priced line
    assert all(l["component"] != "Frame" for l in q["lines"])


def test_get_order_defaults_merge():
    d = Design()
    o = O.get_order(d)
    assert o["status"] == "quote" and "name" in o["customer"] and o["currency"] == "USD"
    O.set_order(d, {**O.get_order(d), "customer": {"name": "Sam"}})
    assert O.get_order(d)["customer"]["name"] == "Sam"
    assert "email" in O.get_order(d)["customer"]    # defaults still filled


def test_order_log(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path)
    d = Design()
    O.set_order(d, {**O.get_order(d), "order_no": "BB-7", "customer": {"name": "Pat"}, "frame_price": 800})
    O.log_order(d, None)
    orders = O.load_orders()
    assert len(orders) == 1 and orders[0]["order_no"] == "BB-7" and orders[0]["total"] == 800
    # saving the same order number replaces, not duplicates
    O.set_order(d, {**O.get_order(d), "order_no": "BB-7", "frame_price": 900})
    O.log_order(d, None)
    assert len(O.load_orders()) == 1 and O.load_orders()[0]["total"] == 900


def test_quote_html_and_pdf(tmp_path, qapp):
    from bikebox.export import quote
    d = Design()
    O.set_order(d, {**O.get_order(d), "customer": {"name": "Sam Rider"}, "order_no": "BB-1"})
    html = quote.build_html(d, None)
    assert "Sam Rider" in html and "Total" in html and "BB-1" in html
    p = tmp_path / "q.pdf"
    quote.save_pdf(d, p, None)
    assert p.read_bytes()[:5] == b"%PDF-"
