"""Guards for the catalog caching that keeps the parts pickers snappy.

These are deterministic (they assert the cache is reused and stays correct), not
wall-clock benchmarks, so they don't flake on slow CI runners.
"""
from bikebox.analysis.report import full_report
from bikebox.analysis.tirefit import max_tire_width
from bikebox.geometry import clearance as C
from bikebox.geometry.solver import solve
from bikebox.model import library as L
from bikebox.model.design import Design


def _g():
    return solve(Design())


def test_full_report_memoised_per_geometry():
    g = _g()
    a = full_report(g)
    assert full_report(g) is a                      # one build per geometry, shared by all panels
    assert full_report(_g()) is not a               # a fresh geometry recomputes


def test_clearance_keys_filter_matches_full_and_skips_rest():
    g = _g()
    want = {"cs_tire", "ss_tire", "st_tire", "fork_crown_tire", "fork_blade_tire"}
    partial = C.clearance_details(g, use_cache=False, keys=want)
    full = C.clearance_details(solve(Design()), use_cache=False)
    for k in want:
        if k in full:
            assert partial[k].value == full[k].value or (
                partial[k].value != partial[k].value and full[k].value != full[k].value)
    # the expensive contacts are not computed when not asked for
    for skipped in ("heel", "heel_cs", "toe_clearance_3d", "toe_steer_angle", "lean_angle_3d", "cs_crank"):
        assert skipped not in partial


def test_tirefit_still_produces_a_result():
    r = max_tire_width(Design(), "rear")
    f = max_tire_width(Design(), "front")
    assert r and f and r["width"] > 0 and f["width"] > 0


def test_all_items_is_cached_not_rebuilt():
    a = L._merged()
    b = L._merged()
    assert a is b                                  # same cache object, no rebuild
    # the item objects are reused across read calls (what makes repeated
    # items()/search() cheap), so identity is stable while nothing changes
    first = L.items(L.categories()[0])[0]
    again = L.items(L.categories()[0])[0]
    assert first is again


def test_search_index_matches_item_set():
    index = L._merged()["search_index"]
    assert len(index) == len(L.all_items())
    # every item is reachable and the haystack is lowercase
    for hay, it in index:
        assert hay == hay.lower()
        assert it.id.lower() in hay


def test_search_is_consistent_with_items():
    # a brand query returns a subset of all items, all genuinely matching
    hits = L.search("columbus")
    assert hits
    assert len(hits) < len(L.all_items())
    for it in hits:
        meta = {k: v for k, v in it.meta.items() if k not in ("user", "source_file")}
        hay = " ".join([it.id, it.name, it.category] + [str(x) for x in L._flatten(meta)]).lower()
        assert "columbus" in hay


def test_empty_search_returns_everything_in_order():
    allc = L.search("")
    assert len(allc) == len(L.all_items())
    keys = [L._cat_key(it.category) for it in allc]
    assert keys == sorted(keys)                    # display (category) order


def test_cache_invalidates_on_user_item_change(tmp_path, monkeypatch):
    monkeypatch.setenv("BIKEBOX_CONFIG_DIR", str(tmp_path))
    L.reload()
    cat = L.categories()[0]
    before = len(L.items(cat))
    L.save_user_item(cat, "Perf Guard Item", {}, {"brand": "T"})
    assert len(L.items(cat)) == before + 1         # cache saw the new file
    assert any(i.name == "Perf Guard Item" for i in L.search("perf guard item"))
    assert L.remove_user_item(cat, "user-perf-guard-item")
    assert not any(i.id == "user-perf-guard-item" for i in L.items(cat))
    L.reload()
