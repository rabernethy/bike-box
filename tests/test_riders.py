"""Rider database + literature fit schemes."""
import bikebox.fit.rider  # noqa: F401  (registers rider measurement params)
from bikebox.model import riders as R
from bikebox.model.design import Design


def _cfg(monkeypatch, tmp_path):
    monkeypatch.setenv("BIKEBOX_CONFIG_DIR", str(tmp_path / "cfg"))


def test_save_load_apply_delete(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path)
    d = Design()
    d.update({"rider_height": 1750, "inseam": 810, "shoulder_width": 420})
    R.save("Alex", R.rider_from_design(d))
    assert "Alex" in R.load_all()
    # apply to a fresh design
    d2 = Design()
    changed = R.apply(d2, "Alex")
    assert "rider_height" in changed and d2.f("rider_height") == 1750 and d2.f("inseam") == 810
    # rider db excludes bike-setup params
    assert "chainstay_length" not in R.load_all()["Alex"]
    R.delete("Alex")
    assert "Alex" not in R.load_all()


def test_track_scheme_exists_and_evaluates():
    from bikebox.fit import advisor
    assert "Track" in advisor.SCHEMES
    d = Design()
    d.update({"rider_height": 1780, "inseam": 820, "fit_scheme": "Track"})
    recs = advisor.evaluate("Track", d)
    labels = {getattr(r, "label", "") for r in recs}
    assert any("Saddle height" in l for l in labels)
    # track torso is flatter than classic road at the same flexibility
    def torso(scheme):
        for r in advisor.evaluate(scheme, d):
            if getattr(r, "label", "").startswith("Torso angle"):
                return r.value
    assert torso("Track") < torso("Classic road")
