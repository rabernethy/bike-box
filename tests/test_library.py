import pytest

from framewright.geometry.solver import solve
from framewright.model import library as L
from framewright.model import params as P
from framewright.model import templates as T
from framewright.model.design import Design

BUILTINS = [t for t in T.list_templates() if t.builtin]
EXPECTED_SLUGS = {
    "road_race", "endurance_road", "gravel", "touring", "randonneur_650b", "track", "cyclocross",
    "xc_hardtail_29", "trail_hardtail_275", "city_step_through", "mixte", "kids_24", "time_trial", "fat_bike",
}


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    """Point the per-user config directory at a temporary folder."""
    monkeypatch.delenv("FRAMEWRIGHT_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    return tmp_path / ".config" / "framewright"


# --------------------------------------------------------------------------
# templates
# --------------------------------------------------------------------------
def test_all_expected_templates_present():
    assert EXPECTED_SLUGS <= {t.slug for t in BUILTINS}
    for t in BUILTINS:
        assert t.description and t.name and t.category


def _ratio(v):
    return v["stack"] / v["reach"]


CATEGORY_CHECKS = {
    "road": lambda d, g: (1.35 <= _ratio(g.v) <= 1.6 and 71 <= g.v["head_tube_angle"] <= 74
                          and 400 <= g.v["chainstay_length"] <= 425 and 50 <= g.v["trail"] <= 65),
    "gravel": lambda d, g: (d.f("rear_tire_width") >= 35 and 415 <= g.v["chainstay_length"] <= 450
                            and len(d.lst("chainrings")) == 1 and not d["front_derailleur"]),
    "cyclocross": lambda d, g: 55 <= g.v["bb_drop"] <= 70 and g.v["bb_height"] >= 275,
    "touring": lambda d, g: (g.v["chainstay_length"] >= 440 and len(d.lst("chainrings")) == 3
                             and d["fenders"] and d["rack_rear"] and d["brake_front"] == "cantilever"),
    "randonneur": lambda d, g: (g.v["trail"] < 50 and d.f("rear_bsd") == 584 and d["joint_style"] == "lugged"
                                and d["fork_blade_shape"] == "curved" and d["fenders"] and d["rack_front"]),
    "track": lambda d, g: (g.v["bb_drop"] < 65 and d.f("rear_hub_spacing") == 120 and d["drive_type"] == "singlespeed"
                           and d["brake_front"] == "none" and d["brake_rear"] == "none" and len(d.lst("cogs")) == 1),
    "mtb": lambda d, g: (64 <= g.v["head_tube_angle"] <= 70 and d["fork_type"] == "suspension"
                         and 100 <= d.f("fork_travel") <= 160 and d.f("rear_hub_spacing") == 148
                         and abs(d.f("rear_tire_height") - d.f("rear_tire_width")) <= 0.1 * d.f("rear_tire_width")),
    "city": lambda d, g: "tt" not in g.tubes and any(n.startswith("x") for n in g.tubes) and d["fenders"],
    "kids": lambda d, g: d.f("rear_bsd") == 507 and d.f("crank_length") <= 150 and g.v["standover"] < 680,
    "tt": lambda d, g: (g.v["seat_tube_angle"] >= 76 and d["dt_profile"] == "aero"
                        and d.f("dt_od2") < d.f("dt_od") and _ratio(g.v) < 1.35),
    "fat": lambda d, g: d.f("rear_bsd") == 559 and d.f("rear_tire_width") >= 90 and d.f("rear_hub_spacing") >= 170,
    "tandem": lambda d, g: (d["frame_type"] == "tandem" and 650 <= g.v["tandem_bb_distance"] <= 850
                            and {"st2", "tt2", "boom"} <= set(g.tubes) and g.v["stoker_knee_room"] > 0),
    "ebike": lambda d, g: d["bb_housing"] == "mid_motor" and d["battery"] != "none" and d["fenders"],
}


@pytest.mark.parametrize("info", BUILTINS, ids=lambda t: t.slug)
def test_template_loads_solves_and_is_plausible(info, qapp):
    from framewright.render.bike_scene import build_scene

    d = T.load_template(info.slug)
    assert d.extras["meta"]["template"] == info.slug
    assert "created" not in d.extras["meta"]
    g = solve(d)
    scene = build_scene(g)
    assert scene.bounds()[2] > scene.bounds()[0]
    v = g.v
    # generic sanity for any bicycle
    assert 900 <= v["wheelbase"] <= (1950 if d["frame_type"] == "tandem" else 1250)
    assert 250 <= v["bb_height"] <= 340
    assert 35 <= v["trail"] <= 130
    assert v["head_tube_length"] >= 80
    assert v["rear_tire_clearance"] >= 3
    assert v["seatpost_insertion"] >= d.f("seatpost_min_insertion")
    assert 0 < v["pedal_clearance"]
    crown_gap = v["fork_length"] - d.f("fork_crown_height") - g.wheels["front"].outer_r
    assert crown_gap > (d.f("fender_clearance") if d["fenders"] else 3)
    # toe overlap only tolerated on small (kids) sizes; no other warnings at all
    others = [w for w in g.warnings if not w.startswith("Toe overlap")]
    assert others == []
    if info.category != "kids":
        assert v["toe_clearance"] >= 0
    check = CATEGORY_CHECKS[info.category]
    assert check(d, g), info.slug


def test_step_through_and_mixte_extra_tubes():
    g = solve(T.load_template("city_step_through"))
    step = g.tubes["x0_step"]
    ht, st = g.tubes["ht"], g.tubes["st"]
    assert step.a.dist(ht.a) < ht.length / 2          # low on the head tube
    assert step.b.dist(st.a) < st.length / 3          # near the BB on the seat tube
    assert step.bend > 0                               # sags below the chord
    g = solve(T.load_template("mixte"))
    lat = g.tubes["x0_lateral"]
    assert lat.mirrored and lat.b.dist(g.p["stay_node"]) < 1e-6
    assert "tt" not in g.tubes and "ss" in g.tubes


def test_load_template_by_title_and_path():
    info = next(t for t in BUILTINS if t.slug == "gravel")
    a = T.load_template(info.name)
    b = T.load_template(info.path)
    assert a.diff(b) == {}
    with pytest.raises(FileNotFoundError):
        T.load_template("no such template")


def test_user_template_round_trip(config_home):
    d = T.load_template("touring")
    d.set("chainstay_length", 461)
    path = T.save_user_template(d, "My Tourer", "longer stays")
    assert path.parent == config_home / "templates" and path.is_file()
    infos = [t for t in T.list_templates() if not t.builtin]
    assert [t.name for t in infos] == ["My Tourer"]
    assert infos[0].description == "longer stays"
    back = T.load_template("My Tourer")
    assert back.f("chainstay_length") == 461
    assert back.diff(d) == {}
    # saving again under the same name replaces it
    T.save_user_template(d, "My Tourer")
    assert len([t for t in T.list_templates() if not t.builtin]) == 1
    assert T.remove_user_template("My Tourer")
    assert not path.exists()
    assert not T.remove_user_template("gravel")      # built-ins are never removed


def test_no_directories_created_on_use(config_home):
    T.list_templates()
    L.categories()
    L.search("fork")
    assert not config_home.exists()


# --------------------------------------------------------------------------
# libraries
# --------------------------------------------------------------------------
def test_categories_non_empty():
    cats = L.categories()
    for c in ("forks", "headsets", "stems", "handlebars", "saddles", "seatposts", "cranks", "chainrings",
              "cassettes", "wheels", "bb_shells"):
        assert c in cats
        assert L.items(c), c
        assert L.category_label(c)


def test_every_library_value_maps_to_schema():
    for it in L.all_items():
        expanded = L.expand_values(it.values)
        assert expanded, it.id
        for k, v in expanded.items():
            assert P.has(k), (it.id, k)
            pd = P.get(k)
            if pd.kind == P.CHOICE:
                assert str(v) in {c[0] for c in pd.choices}, (it.id, k, v)


def test_every_item_applies_and_solves():
    for it in L.all_items():
        d = T.load_template("gravel")
        L.apply(d, it)
        solve(d)


def test_fork_presets():
    forks = {i.name: i for i in L.items("forks")}
    for travel, ac in ((100, 501), (110, 511), (120, 521)):
        for off in (44, 51):
            it = next(i for n, i in forks.items() if n.startswith(f"29er suspension {travel} mm, {off} offset"))
            assert it.values["fork_length"] == ac and it.values["fork_travel"] == travel
    d = Design()
    changed = L.apply(d, next(i for i in forks.values() if i.name.startswith("29er suspension 120 mm, 44")))
    assert d["fork_type"] == "suspension" and d.f("fork_length") == 521
    assert "fork_type" in changed and "fork_length" in changed


@pytest.mark.parametrize("spec,expected", [
    ("0.9/0.6/0.9", (0.9, 0.6)), ("1.0", (1.0, 1.0)), (0.8, (0.8, 0.8)), ("0.9/0.6", (0.9, 0.6)),
    ("0.8/0.5/0.4/0.7", (0.8, 0.4)), ("0.7/0.4/0.6", (0.7, 0.4)), ("1.0mm", (1.0, 1.0)),
])
def test_parse_wall(spec, expected):
    assert L.parse_wall(spec) == pytest.approx(expected)


def test_tubeset_apply_sets_walls_from_butting_strings():
    item = L.LibraryItem("test-set", "Test set", "tubing", {
        "material": "titanium",
        "tubes": {
            "top_tube": {"od_mm": 28.6, "wall_mm": "0.9/0.6/0.9"},
            "down_tube": {"od": 31.8, "wall": "0.8/0.5/0.8"},
            "seat_tube": {"od": 28.6, "wall": "0.9/0.6"},
            "head_tube": {"od": 32.4, "wall": "1.0"},
            "chain_stay": {"od": 22.2, "wall": "0.9"},
            "seat_stay": {"od": 15.0, "wall": "0.7"},
            "fork_blade": {"od": 22.2, "wall": "1.0/0.8"},
        }})
    d = Design()
    d.set("tt_profile", "aero")
    changed = L.apply(d, item)
    assert d.f("tt_wall_end") == 0.9 and d.f("tt_wall_mid") == 0.6 and d.f("tt_od") == 28.6
    assert d["tt_profile"] == "round"
    assert d.f("dt_wall_end") == 0.8 and d.f("dt_wall_mid") == 0.5 and d.f("dt_od") == 31.8
    assert d.f("st_wall_end") == 0.9 and d.f("st_wall_mid") == 0.6
    assert d.f("ht_od_top") == d.f("ht_od_bottom") == 32.4 and d.f("ht_wall") == 1.0
    assert d.f("cs_od_bb") == 22.2 and d.f("cs_wall") == 0.9
    assert d.f("ss_od_top") == 15.0 and d.f("ss_wall") == 0.7
    assert d.f("fork_blade_od") == 22.2
    assert d["frame_material"] == "titanium"
    assert {"tt_wall_end", "tt_wall_mid", "frame_material", "ht_od_top"} <= set(changed)
    solve(d)


def test_apply_ignores_unknown_keys_and_bad_choices():
    d = Design()
    before = d.copy()
    changed = L.apply(d, {"no_such_key": 3, "frame_material": "unobtainium", "tt_wall": "1.0/0.7/1.0"})
    assert changed == ["tt_wall_end", "tt_wall_mid"]
    assert d["frame_material"] == before["frame_material"]


def test_search():
    assert any(i.category == "forks" for i in L.search("29er suspension"))
    assert all("bsa" in (i.name + str(i.meta)).lower() for i in L.search("bsa"))
    assert len(L.search("")) == len(L.all_items())


def test_user_library_save_merge_and_remove(config_home):
    n = len(L.items("stems"))
    path = L.save_user_item("stems", "My 95 mm stem", {"stem_length": 95, "stem_angle": -8}, {"note": "custom"})
    assert path.parent == config_home / "libraries"
    items = L.items("stems")
    assert len(items) == n + 1
    mine = [i for i in items if i.user]
    assert [i.name for i in mine] == ["My 95 mm stem"] and mine[0].meta["note"] == "custom"
    # same name replaces instead of duplicating
    L.save_user_item("stems", "My 95 mm stem", {"stem_length": 95, "stem_angle": -6})
    mine = [i for i in L.items("stems") if i.user]
    assert len(mine) == 1 and mine[0].values["stem_angle"] == -6
    d = Design()
    assert L.apply(d, mine[0]) == ["stem_length"] and d.f("stem_length") == 95
    # a brand-new category shows up
    L.save_user_item("tubing", "Shop set", {"tubes": {"tt": {"od": 31.8, "wall": "0.7/0.4/0.7"}}})
    assert "tubing" in L.categories()
    assert L.search("shop set")[0].category == "tubing"
    assert L.remove_user_item("stems", mine[0].id)
    assert len(L.items("stems")) == n


def test_user_item_overrides_builtin_with_same_id(config_home):
    builtin = L.items("cranks")[0]
    path = config_home / "libraries" / "override.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"format": "framewright-library", "version": 1, "category": "cranks", "items": '
                    '[{"id": "%s", "name": "Override", "values": {"crank_length": 171}}]}' % builtin.id)
    items = L.items("cranks")
    assert items[0].name == "Override" and items[0].user
    assert len([i for i in items if i.id == builtin.id]) == 1
    assert items[0].values["crank_length"] == 171
