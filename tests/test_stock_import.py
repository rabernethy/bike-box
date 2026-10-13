"""CSV stock import into the user library."""
from bikebox.model import library as L
from bikebox.model.design import Design


def _cfg(monkeypatch, tmp_path):
    monkeypatch.setenv("BIKEBOX_CONFIG_DIR", str(tmp_path / "cfg"))


def test_import_stock_csv(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path)
    csv = tmp_path / "forks.csv"
    csv.write_text("name,brand,fork_length,fork_offset,price,notes\n"
                   "ENVE Gravel,ENVE,400,47,650,carbon\n"
                   "Steel Fork,ACME,385,45,,\n"
                   ",NoName,300,40,100,\n")              # last row has no name -> skipped (brand used? no name/model)
    added, errors = L.import_stock_csv("forks", csv)
    assert added == 3                                    # brand 'NoName' used as fallback name
    items = {i.name: i for i in L.items("forks") if i.meta.get("user")}
    assert "ENVE Gravel" in items
    enve = items["ENVE Gravel"]
    assert enve.values["fork_length"] == 400 and enve.values["fork_offset"] == 47
    assert enve.meta["price_usd"] == 650 and enve.meta["brand"] == "ENVE"


def test_imported_price_feeds_quote():
    from bikebox.model import orders as O
    d = Design()
    d.extras["bom"] = {"forks": {"name": "ENVE Gravel", "category": "forks", "price": 650}}
    assert O.quote(d, None)["parts_total"] == 650


def test_bad_numeric_reported(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path)
    csv = tmp_path / "f.csv"
    csv.write_text("name,fork_length\nBad,notanumber\n")
    added, errors = L.import_stock_csv("forks", csv)
    assert added == 1 and any("not a number" in e for e in errors)
