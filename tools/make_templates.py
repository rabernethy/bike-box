"""Generate the built-in design templates (``framewright/data/templates/*.fwd``).

Each template is a complete, realistic medium-size design for one category of
bicycle.  The designs are built programmatically from the parameter schema so
they can be regenerated whenever the schema grows::

    /usr/bin/python3 tools/make_templates.py              # write the .fwd files
    /usr/bin/python3 tools/make_templates.py --report     # + print key numbers and warnings
    QT_QPA_PLATFORM=offscreen /usr/bin/python3 tools/make_templates.py --render /tmp/fw_png

Numbers are typical published geometry for the category (not copied from any
one manufacturer).  ``extras["meta"]`` carries ``description``, ``category``,
``template`` (the slug) and ``order`` (sort position in the template list).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from framewright.geometry.solver import solve  # noqa: E402  (registers solver params)
from framewright.model.design import Design  # noqa: E402

OUT_DIR = ROOT / "framewright" / "data" / "templates"

# --------------------------------------------------------------------------
# shared building blocks
# --------------------------------------------------------------------------
COMMON = {
    "designer": "FrameWright",
    "front_v_mode": "stack",
    "front_h_mode": "reach",
    "st_length_mode": "ct",
    "tt_mode": "st_extension",
    "bb_mode": "drop",
    "cs_mode": "length",
}

ROAD_COCKPIT = {
    "stem_type": "threadless", "stem_length": 100, "stem_angle": -6, "stem_clamp_height": 40,
    "bar_type": "drop", "bar_reach": 80, "bar_drop": 125, "bar_width": 420, "bar_od": 31.8,
    "lever_type": "road_sti", "hood_reach": 40, "hand_position": "hoods",
}
FLAT_COCKPIT = {
    "stem_type": "threadless", "stem_clamp_height": 40, "bar_od": 31.8,
    "lever_type": "flat", "hand_position": "grips",
}


def tubes(prefix: str, od: float, wall: str, butt: float | None = None, **extra) -> dict:
    """Tube values for ``prefix`` (tt/dt/st) from an OD and a butting string."""
    walls = [float(w) for w in wall.split("/")]
    end, mid = max(walls[0], walls[-1]), min(walls[1:-1] or walls)
    out = {f"{prefix}_od": od, f"{prefix}_od2": od, f"{prefix}_wall_end": end, f"{prefix}_wall_mid": mid}
    if butt is not None:
        out[f"{prefix}_butt_length"] = butt
    out.update({f"{prefix}_{k}": v for k, v in extra.items()})
    return out


def wheels(bsd: float, width: float, height: float, front: tuple[float, float, float] | None = None) -> dict:
    fb, fw, fh = front or (bsd, width, height)
    return {"rear_bsd": bsd, "rear_tire_width": width, "rear_tire_height": height,
            "front_bsd": fb, "front_tire_width": fw, "front_tire_height": fh}


def merge(*dicts: dict, **kw) -> dict:
    out: dict = {}
    for d in dicts:
        out.update(d)
    out.update(kw)
    return out


# --------------------------------------------------------------------------
# the templates
# --------------------------------------------------------------------------
TEMPLATES: list[dict] = []


def template(slug: str, title: str, category: str, description: str, values: dict, extras: dict | None = None):
    TEMPLATES.append({"slug": slug, "title": title, "category": category, "description": description,
                      "values": merge(COMMON, values, title=title), "extras": extras or {}})


template(
    "road_race", "Road race 56", "road",
    "Steel race bike, 56 cm: 73.5° seat / 73° head angles, 408 mm chainstays, 700x25 tires, "
    "rim calipers, 2x11 drivetrain and a low, long position.",
    merge(
        wheels(622, 25, 25),
        tubes("tt", 31.8, "0.7/0.4/0.7", 80), tubes("dt", 35.0, "0.7/0.4/0.7", 90),
        tubes("st", 28.6, "0.7/0.45/0.7", 120),
        ROAD_COCKPIT,
        frame_size_label="56", frame_material="steel", joint_style="tig",
        head_tube_angle=73.0, seat_tube_angle=73.5, stack=565, reach=400,
        seat_tube_length=540, st_extension=20, tt_ht_offset=18, dt_ht_offset=30,
        bb_drop=72, chainstay_length=408, rear_hub_spacing=130, front_hub_spacing=100,
        bb_shell_od=41, bb_shell_width=68,
        ht_od_top=36, ht_od_bottom=36, ht_wall=1.1, cs_od_bb=22.2, cs_od_drop=14, cs_wall=0.8,
        ss_od_top=16, ss_od_drop=12.7, ss_wall=0.7,
        fork_type="rigid", fork_length=368, fork_offset=45, fork_crown_height=22, fork_crown_width=105,
        fork_blade_od=28, fork_blade_od_tip=14, fork_blade_shape="straight",
        lower_stack=11, upper_stack=8, spacers=15, steerer_od=28.6,
        stem_length=110, saddle_height=740, saddle_length=270, saddle_ref_to_nose=140,
        seatpost_od=27.2, seatpost_length=350,
        drive_type="derailleur", crank_length=170, chainrings="52, 36",
        cogs="11, 12, 13, 14, 15, 17, 19, 21, 23, 25, 28", front_derailleur=True, chainline=43.5,
        rim_depth_front=30, rim_depth_rear=30, spokes_front=24, spokes_rear=28, cross_front=0, cross_rear=2,
        brake_front="caliper", brake_rear="caliper", brake_reach=49,
        bottle_dt=True, bottle_st=True, fenders=False, rack_rear=False, rack_front=False,
        paint_frame="#c8102e", paint_fork="#c8102e", paint_head_tube="#f4f4f4",
    ))

template(
    "endurance_road", "Endurance road 56", "road",
    "Titanium endurance/sportive bike, 56 cm: taller stack, 72° head angle, 420 mm chainstays, "
    "700x32 tires, flat-mount disc brakes, thru-axles and 50/34 x 11-34 gearing.",
    merge(
        wheels(622, 32, 31),
        tubes("tt", 31.8, "0.9/0.9/0.9", 0), tubes("dt", 38.1, "0.9/0.9/0.9", 0),
        tubes("st", 31.8, "1.0/0.9/1.0", 0),
        ROAD_COCKPIT,
        frame_size_label="56", frame_material="titanium", joint_style="tig",
        head_tube_angle=72.0, seat_tube_angle=73.0, stack=592, reach=386,
        seat_tube_length=545, st_extension=25, tt_ht_offset=18,
        bb_drop=76, chainstay_length=420, rear_hub_spacing=142, front_hub_spacing=100,
        bb_shell_od=44, bb_shell_width=68,
        ht_od_top=44, ht_od_bottom=56, ht_wall=1.4, cs_od_bb=22.2, cs_od_drop=16, cs_wall=0.9,
        ss_od_top=16, ss_od_drop=14, ss_wall=0.9,
        fork_type="rigid", fork_length=375, fork_offset=50, fork_crown_height=24, fork_crown_width=110,
        fork_blade_od=30, fork_blade_od_tip=16, fork_blade_shape="straight",
        lower_stack=13, upper_stack=10, spacers=30, steerer_od=28.6,
        bar_drop=120, bar_reach=75, saddle_height=735,
        seatpost_od=27.2, seatpost_length=350,
        drive_type="derailleur", crank_length=172.5, chainrings="50, 34",
        cogs="11, 12, 13, 14, 15, 17, 19, 21, 24, 27, 30, 34", front_derailleur=True,
        rim_depth_front=25, rim_depth_rear=25, spokes_front=24, spokes_rear=28,
        brake_front="disc", brake_rear="disc", rotor_front=160, rotor_rear=160,
        bottle_dt=True, bottle_st=True,
        paint_frame="#a7a9ac", paint_fork="#2b2b2b", paint_head_tube="#a7a9ac", paint_decal="#1a1a1a",
        decal_text="FRAMEWRIGHT Ti",
    ))

template(
    "gravel", "Gravel 1x 56", "gravel",
    "Steel gravel bike, 56 cm: 71.5° head / 73.5° seat, 430 mm chainstays, 700x40 tires, "
    "1x11 (40 x 11-42), flared drop bar, 160 mm discs and 12 mm thru-axles.",
    merge(
        wheels(622, 40, 39),
        tubes("tt", 31.8, "0.8/0.5/0.8", 80), tubes("dt", 35.0, "0.8/0.5/0.8", 90),
        tubes("st", 28.6, "0.8/0.5/0.8", 120),
        ROAD_COCKPIT,
        frame_size_label="56", frame_material="steel", joint_style="tig",
        head_tube_angle=71.5, seat_tube_angle=73.5, stack=600, reach=385,
        seat_tube_length=540, st_extension=30, tt_ht_offset=18,
        bb_drop=72, chainstay_length=430, rear_hub_spacing=142, front_hub_spacing=100,
        bb_shell_od=41, bb_shell_width=68,
        ht_od_top=44, ht_od_bottom=44, ht_wall=1.2, cs_od_bb=22.2, cs_od_drop=16, cs_wall=0.8,
        ss_od_top=16, ss_od_drop=14, ss_wall=0.7,
        fork_type="rigid", fork_length=395, fork_offset=50, fork_crown_height=28, fork_crown_width=115,
        fork_blade_od=30, fork_blade_od_tip=16, fork_blade_shape="straight",
        lower_stack=12, upper_stack=8, spacers=25, steerer_od=28.6,
        stem_length=90, bar_drop=115, bar_reach=70, bar_width=440, saddle_height=735,
        seatpost_od=27.2, seatpost_length=350,
        drive_type="derailleur", crank_length=172.5, chainrings="40",
        cogs="11, 13, 15, 17, 19, 21, 24, 28, 32, 36, 42", front_derailleur=False, chainline=47.5,
        rim_depth_front=24, rim_depth_rear=24, spokes_front=28, spokes_rear=28,
        brake_front="disc", brake_rear="disc", rotor_front=160, rotor_rear=160,
        bottle_dt=True, bottle_st=True,
        paint_frame="#5a6b3a", paint_fork="#5a6b3a", paint_head_tube="#e8e1cf",
    ))

template(
    "touring", "Touring 56", "touring",
    "Fillet-brazed steel loaded tourer, 56 cm: 455 mm chainstays, 72° head angle, 700x37 tires, "
    "cantilever brakes, 36-spoke wheels, 48/36/26 triple, front and rear racks, fenders and a kickstand plate.",
    merge(
        wheels(622, 37, 36),
        tubes("tt", 28.6, "0.9/0.6/0.9", 80), tubes("dt", 31.8, "0.9/0.6/0.9", 90),
        tubes("st", 28.6, "0.9/0.6/0.9", 120),
        ROAD_COCKPIT,
        frame_size_label="56", frame_material="steel", joint_style="fillet", fillet_radius=10,
        head_tube_angle=71.5, seat_tube_angle=73.0, stack=615, reach=388,
        seat_tube_length=560, st_extension=25, tt_ht_offset=20,
        bb_drop=78, chainstay_length=455, rear_hub_spacing=135, front_hub_spacing=100,
        bb_shell_od=41, bb_shell_width=68,
        ht_od_top=36, ht_od_bottom=36, ht_wall=1.2, cs_od_bb=22.2, cs_od_drop=16, cs_wall=0.9,
        ss_od_top=16, ss_od_drop=14, ss_wall=0.9,
        fork_type="rigid", fork_length=400, fork_offset=55, fork_crown_height=30, fork_crown_width=110,
        fork_blade_od=28.6, fork_blade_od_tip=16, fork_blade_shape="curved",
        lower_stack=12, upper_stack=10, spacers=35, steerer_od=28.6,
        stem_length=90, stem_angle=0, bar_drop=125, bar_reach=75, bar_width=440, saddle_height=735,
        seatpost_od=27.2, seatpost_length=350,
        drive_type="derailleur", crank_length=170, chainrings="48, 36, 26",
        cogs="11, 13, 15, 17, 20, 23, 26, 30, 34", front_derailleur=True, chainline=47.5,
        rim_depth_front=20, rim_depth_rear=20, spokes_front=36, spokes_rear=36, cross_front=3, cross_rear=3,
        brake_front="cantilever", brake_rear="cantilever",
        bottle_dt=True, bottle_st=True, pump_pegs=True, kickstand_plate=True,
        fenders=True, fender_clearance=12, fender_width=50,
        rack_rear=True, rack_height=385, rack_front=True,
        paint_frame="#1f4d3a", paint_fork="#1f4d3a", paint_head_tube="#e8e1cf", decal_text="TOURING",
    ))

template(
    "randonneur_650b", "650b randonneur 57", "randonneur",
    "Lugged steel 650b randonneur, 57 cm: horizontal top tube, 72.5°/73° lug angles, low-trail curved fork "
    "(60 mm offset, ~42 mm trail), 650x42 tires, fenders, front rack, quill stem and long-reach centre-pulls.",
    merge(
        wheels(584, 42, 40),
        tubes("tt", 25.4, "0.8/0.5/0.8", 80), tubes("dt", 28.6, "0.8/0.5/0.8", 90),
        tubes("st", 28.6, "0.8/0.5/0.8", 120),
        ROAD_COCKPIT,
        frame_size_label="57", frame_material="steel", joint_style="lugged",
        lug_style="long_point", lug_ht_angle=72.5, lug_st_angle=73, lug_socket_length=32, lug_point_length=22,
        front_v_mode="ht_length", head_tube_length=140, tt_mode="angle", top_tube_angle=0,
        head_tube_angle=72.5, seat_tube_angle=73.0, reach=395,
        seat_tube_length=585, tt_ht_offset=18, dt_ht_offset=28,
        bb_drop=68, chainstay_length=448, rear_hub_spacing=130, front_hub_spacing=100,
        bb_shell_od=38, bb_shell_width=68,
        ht_od_top=31.7, ht_od_bottom=31.7, ht_wall=0.9, cs_od_bb=22.2, cs_od_drop=14, cs_wall=0.8,
        ss_od_top=14, ss_od_drop=12.7, ss_wall=0.7,
        fork_type="rigid", fork_length=385, fork_offset=60, fork_crown_height=30, fork_crown_width=110,
        fork_blade_od=26, fork_blade_od_tip=13, fork_blade_shape="curved",
        lower_stack=13.5, upper_stack=25, steerer_od=25.4,
        stem_type="quill", quill_height=45, stem_length=90, stem_angle=-6, bar_od=26.0,
        bar_drop=125, bar_reach=75, bar_width=420, saddle_height=740, saddle_length=280, saddle_stack=55,
        seatpost_od=27.2, seatpost_length=300,
        drive_type="derailleur", crank_length=172.5, chainrings="48, 32",
        cogs="11, 12, 13, 15, 17, 19, 21, 24, 28, 32", front_derailleur=True,
        rim_depth_front=18, rim_depth_rear=18, spokes_front=32, spokes_rear=32, cross_front=3, cross_rear=3,
        brake_front="caliper", brake_rear="caliper", brake_reach=57,
        bottle_dt=True, bottle_st=True, pump_pegs=True,
        fenders=True, fender_clearance=15, fender_width=55, rack_front=True, rack_rear=False,
        paint_frame="#1c3f6e", paint_fork="#1c3f6e", paint_head_tube="#efe6cf", paint_lugs="#efe6cf",
        decal_text="Randonneur",
    ))

template(
    "track", "Track 56", "track",
    "Steel track frame, 56 cm: 73.5° head / 74.5° seat angles, 55 mm BB drop, 395 mm chainstays, "
    "120 mm rear spacing, fixed gear (49x15), no brakes, deep track drops.",
    merge(
        wheels(622, 23, 22),
        tubes("tt", 31.8, "0.8/0.5/0.8", 80), tubes("dt", 35.0, "0.8/0.5/0.8", 90),
        tubes("st", 28.6, "0.8/0.5/0.8", 120),
        ROAD_COCKPIT,
        frame_size_label="56", frame_material="steel", joint_style="tig",
        head_tube_angle=73.5, seat_tube_angle=74.5, stack=540, reach=408,
        seat_tube_length=545, st_extension=15, tt_ht_offset=18,
        bb_drop=55, chainstay_length=395, rear_hub_spacing=120, front_hub_spacing=100,
        bb_shell_od=41, bb_shell_width=68,
        ht_od_top=36, ht_od_bottom=36, ht_wall=1.1, cs_od_bb=22.2, cs_od_drop=16, cs_wall=0.9,
        ss_od_top=16, ss_od_drop=14, ss_wall=0.8,
        fork_type="rigid", fork_length=365, fork_offset=40, fork_crown_height=22, fork_crown_width=100,
        fork_blade_od=28, fork_blade_od_tip=15, fork_blade_shape="straight",
        lower_stack=11, upper_stack=8, spacers=10, steerer_od=28.6,
        stem_length=120, stem_angle=-10, bar_drop=150, bar_reach=95, bar_width=400,
        lever_type="none", hand_position="drops", saddle_height=735,
        seatpost_od=27.2, seatpost_length=300,
        drive_type="singlespeed", crank_length=165, chainrings="49", cogs="15", front_derailleur=False,
        chainline=42,
        rim_depth_front=40, rim_depth_rear=40, spokes_front=24, spokes_rear=28, cross_front=0, cross_rear=2,
        brake_front="none", brake_rear="none",
        bottle_dt=False, bottle_st=False, dt_cable_stops=False, ss_bridge=False,
        paint_frame="#202020", paint_fork="#202020", paint_head_tube="#e0e0e0", paint_decal="#00b2a9",
        decal_text="PISTA",
    ))

template(
    "cyclocross", "Cyclocross 56", "cyclocross",
    "Aluminium cyclocross race bike, 56 cm: high 63 mm BB drop, 71.5° head angle, 425 mm chainstays, "
    "700x33 tires with mud clearance, discs, 46/36 x 11-28 and a shoulder-friendly open main triangle.",
    merge(
        wheels(622, 33, 32),
        tubes("tt", 34.9, "1.2/0.8/1.2", 90), tubes("dt", 44.0, "1.3/0.9/1.3", 100),
        tubes("st", 31.8, "1.4/1.0/1.4", 120),
        ROAD_COCKPIT,
        frame_size_label="56", frame_material="aluminium7005", joint_style="tig",
        head_tube_angle=71.5, seat_tube_angle=73.5, stack=588, reach=385,
        seat_tube_length=540, st_extension=25, tt_ht_offset=18,
        bb_drop=63, chainstay_length=425, rear_hub_spacing=142, front_hub_spacing=100,
        bb_shell_od=42, bb_shell_width=68,
        ht_od_top=48, ht_od_bottom=58, ht_wall=1.8, cs_od_bb=26, cs_od_drop=16, cs_wall=1.0,
        ss_od_top=19, ss_od_drop=14, ss_wall=1.0,
        fork_type="rigid", fork_length=395, fork_offset=50, fork_crown_height=28, fork_crown_width=115,
        fork_blade_od=32, fork_blade_od_tip=16, fork_blade_shape="straight",
        lower_stack=12, upper_stack=8, spacers=20, steerer_od=28.6,
        stem_length=100, saddle_height=730,
        seatpost_od=27.2, seatpost_length=350,
        drive_type="derailleur", crank_length=172.5, chainrings="46, 36",
        cogs="11, 12, 13, 14, 15, 17, 19, 21, 23, 25, 28", front_derailleur=True,
        rim_depth_front=30, rim_depth_rear=30, spokes_front=24, spokes_rear=28,
        brake_front="disc", brake_rear="disc", rotor_front=160, rotor_rear=160,
        bottle_dt=True, bottle_st=False,
        paint_frame="#f2a900", paint_fork="#1a1a1a", paint_head_tube="#1a1a1a", paint_decal="#1a1a1a",
    ))

template(
    "xc_hardtail_29", "XC hardtail 29er M", "mtb",
    "Steel cross-country 29er hardtail, size M: 110 mm suspension fork (511 mm A-C, 44 mm offset), "
    "68° head / 74.5° seat, 432 mm chainstays, 148 mm boost rear, 29x2.3 tires, 1x12 and a flat bar.",
    merge(
        wheels(622, 58, 57),
        tubes("tt", 31.8, "0.9/0.6/0.9", 90), tubes("dt", 38.1, "0.9/0.6/0.9", 100),
        tubes("st", 31.8, "0.9/0.6/0.9", 120),
        FLAT_COCKPIT,
        frame_size_label="M", frame_material="steel", joint_style="tig",
        head_tube_angle=68.0, seat_tube_angle=74.5, stack=620, reach=435,
        seat_tube_length=430, st_extension=80, tt_ht_offset=15, dt_ht_offset=35,
        bb_drop=60, chainstay_length=432, rear_hub_spacing=148, front_hub_spacing=110,
        bb_shell_od=42, bb_shell_width=73, cs_spread_bb=90,
        ht_od_top=44, ht_od_bottom=56, ht_wall=1.5, cs_od_bb=22.2, cs_od_drop=16, cs_wall=0.9,
        ss_od_top=16, ss_od_drop=14, ss_wall=0.8,
        fork_type="suspension", fork_length=511, fork_offset=44, fork_travel=110, fork_sag=0,
        fork_stanchion_od=34, fork_crown_height=35, fork_crown_width=120,
        lower_stack=12, upper_stack=8, spacers=15, steerer_od=28.6,
        stem_length=80, stem_angle=-6, bar_type="flat", bar_rise=0, bar_backsweep=9, bar_width=760,
        saddle_height=740,
        seatpost_od=27.2, seatpost_length=400, seatpost_type="standard",
        drive_type="derailleur", crank_length=175, chainrings="32",
        cogs="10, 12, 14, 16, 18, 21, 24, 28, 32, 36, 42, 52", front_derailleur=False, chainline=52,
        q_factor=168,
        rim_depth_front=22, rim_depth_rear=22, spokes_front=28, spokes_rear=28,
        brake_front="disc", brake_rear="disc", rotor_front=180, rotor_rear=160,
        bottle_dt=True, bottle_st=False, bottle_dt_pos=150,
        paint_frame="#2a6f97", paint_fork="#1a1a1a", paint_head_tube="#2a6f97",
    ))

template(
    "trail_hardtail_275", "Trail hardtail 27.5 M", "mtb",
    "Steel trail hardtail, size M: 140 mm fork (537 mm A-C, 42 mm offset), slack 65° head / steep 75.5° seat, "
    "425 mm chainstays, 27.5x2.4 tires, 150 mm dropper, short stem and wide riser bar.",
    merge(
        wheels(584, 61, 59),
        tubes("tt", 31.8, "0.9/0.6/0.9", 90), tubes("dt", 38.1, "1.0/0.7/1.0", 100),
        tubes("st", 34.9, "1.0/0.7/1.0", 120),
        FLAT_COCKPIT,
        frame_size_label="M", frame_material="steel", joint_style="tig",
        head_tube_angle=65.0, seat_tube_angle=75.5, stack=610, reach=450,
        seat_tube_length=420, st_extension=100, tt_ht_offset=15, dt_ht_offset=35,
        bb_drop=35, chainstay_length=425, rear_hub_spacing=148, front_hub_spacing=110,
        bb_shell_od=42, bb_shell_width=73, cs_spread_bb=90,
        ht_od_top=44, ht_od_bottom=56, ht_wall=1.5, cs_od_bb=22.2, cs_od_drop=16, cs_wall=0.9,
        ss_od_top=16, ss_od_drop=14, ss_wall=0.8,
        fork_type="suspension", fork_length=537, fork_offset=42, fork_travel=140, fork_sag=0,
        fork_stanchion_od=35, fork_crown_height=38, fork_crown_width=125,
        lower_stack=12, upper_stack=8, spacers=15, steerer_od=28.6,
        stem_length=45, stem_angle=0, bar_type="riser", bar_rise=25, bar_backsweep=9, bar_width=780,
        saddle_height=730,
        seatpost_od=31.6, seatpost_length=440, seatpost_type="dropper", dropper_travel=150, dropper_drop=0,
        seatpost_min_insertion=100,
        drive_type="derailleur", crank_length=170, chainrings="30",
        cogs="10, 12, 14, 16, 18, 21, 24, 28, 32, 36, 42, 52", front_derailleur=False, chainline=52,
        pedal_type="flat", q_factor=175,
        rim_depth_front=22, rim_depth_rear=22, spokes_front=32, spokes_rear=32,
        brake_front="disc", brake_rear="disc", rotor_front=200, rotor_rear=180,
        bottle_dt=True, bottle_st=False, bottle_dt_pos=150,
        paint_frame="#e07a1f", paint_fork="#1a1a1a", paint_head_tube="#e07a1f",
    ))

template(
    "city_step_through", "City step-through M", "city",
    "Aluminium step-through city bike, size M: no top tube, a curved low step-over tube from the head tube "
    "to the base of the seat tube, upright swept-back bar, 8-speed hub gear, V-brakes, fenders, rear rack, "
    "kickstand plate and 700x42 tires.",
    merge(
        wheels(622, 42, 40),
        tubes("tt", 31.8, "1.4/1.0/1.4", 80), tubes("dt", 44.0, "1.6/1.2/1.6", 100),
        tubes("st", 34.9, "1.6/1.2/1.6", 120),
        FLAT_COCKPIT,
        frame_size_label="M", frame_material="aluminium", joint_style="tig",
        remove_tubes="tt",
        head_tube_angle=69.5, seat_tube_angle=70.0, stack=645, reach=365,
        seat_tube_length=480, st_extension=25, tt_ht_offset=20, dt_ht_offset=30,
        bb_drop=70, chainstay_length=460, rear_hub_spacing=135, front_hub_spacing=100,
        bb_shell_od=42, bb_shell_width=68,
        ht_od_top=44, ht_od_bottom=44, ht_wall=1.8, cs_od_bb=24, cs_od_drop=16, cs_wall=1.2,
        ss_od_top=19, ss_od_drop=14, ss_wall=1.2,
        fork_type="rigid", fork_length=410, fork_offset=50, fork_crown_height=30, fork_crown_width=115,
        fork_blade_od=30, fork_blade_od_tip=16, fork_blade_shape="straight",
        lower_stack=12, upper_stack=10, spacers=30, steerer_od=28.6,
        stem_length=70, stem_angle=30, bar_type="swept", bar_rise=40, bar_backsweep=45, bar_width=600,
        saddle_height=700, saddle_length=260, saddle_ref_to_nose=125, saddle_stack=60,
        seatpost_od=27.2, seatpost_length=350,
        drive_type="hub_gear", crank_length=170, chainrings="38", cogs="20", front_derailleur=False,
        chainline=43.5, pedal_type="flat", q_factor=160,
        rim_depth_front=20, rim_depth_rear=20, spokes_front=36, spokes_rear=36, cross_front=3, cross_rear=3,
        brake_front="v", brake_rear="v",
        bottle_dt=False, bottle_st=False, kickstand_plate=True,
        fenders=True, fender_clearance=14, fender_width=55, rack_rear=True, rack_height=385,
        paint_frame="#7fb3a6", paint_fork="#7fb3a6", paint_head_tube="#f4f4f4", decal_text="CITY",
    ),
    extras={"extra_tubes": [
        {"name": "step", "label": "Step-through tube", "a": {"tube": "ht", "s": 80},
         "b": {"tube": "st", "s": 110}, "od": 38.0, "wall": 1.4, "bend": 45.0},
    ]})

template(
    "mixte", "Mixte M", "city",
    "Steel mixte, size M: the top tube is replaced by twin lateral tubes running from the head tube past the "
    "seat tube to the rear dropouts; quill stem, swept bar, 2x9 gearing, long-reach calipers, fenders, rear rack.",
    merge(
        wheels(622, 35, 34),
        tubes("tt", 25.4, "0.8/0.5/0.8", 80), tubes("dt", 31.8, "0.9/0.6/0.9", 90),
        tubes("st", 28.6, "0.9/0.6/0.9", 120),
        FLAT_COCKPIT,
        frame_size_label="M", frame_material="steel", joint_style="tig",
        remove_tubes="tt",
        head_tube_angle=70.5, seat_tube_angle=72.0, stack=600, reach=384,
        seat_tube_length=500, st_extension=25, tt_ht_offset=20,
        bb_drop=72, chainstay_length=445, rear_hub_spacing=135, front_hub_spacing=100,
        bb_shell_od=41, bb_shell_width=68,
        ht_od_top=31.7, ht_od_bottom=31.7, ht_wall=1.0, cs_od_bb=22.2, cs_od_drop=14, cs_wall=0.8,
        ss_od_top=14, ss_od_drop=12.7, ss_wall=0.8,
        fork_type="rigid", fork_length=395, fork_offset=50, fork_crown_height=30, fork_crown_width=110,
        fork_blade_od=26, fork_blade_od_tip=13, fork_blade_shape="curved",
        lower_stack=13.5, upper_stack=25, steerer_od=25.4,
        stem_type="quill", quill_height=70, stem_length=70, stem_angle=0, bar_od=25.4,
        bar_type="swept", bar_rise=30, bar_backsweep=35, bar_width=560,
        saddle_height=710, saddle_length=270, saddle_stack=55,
        seatpost_od=27.2, seatpost_length=300,
        drive_type="derailleur", crank_length=170, chainrings="46, 30",
        cogs="11, 13, 15, 17, 19, 21, 24, 28, 32", front_derailleur=True,
        pedal_type="flat", q_factor=155,
        rim_depth_front=18, rim_depth_rear=18, spokes_front=32, spokes_rear=32, cross_front=3, cross_rear=3,
        brake_front="caliper", brake_rear="caliper", brake_reach=57,
        bottle_dt=True, bottle_st=False,
        fenders=True, fender_clearance=12, fender_width=50, rack_rear=True, rack_height=380,
        paint_frame="#3d5a80", paint_fork="#3d5a80", paint_head_tube="#e8e1cf", decal_text="MIXTE",
    ),
    extras={"extra_tubes": [
        {"name": "lateral", "label": "Mixte lateral (pair)", "a": {"tube": "ht", "pos": 0.82},
         "b": "stay_node", "od": 16.0, "wall": 0.9, "za": 9.0, "zb": 70.5, "mirrored": True},
    ]})

template(
    "kids_24", "Kids 24\"", "kids",
    "Aluminium 24\" kids' bike (approx. 8-11 years): 24x1.95 tires on 507 mm rims, 140 mm cranks, short reach, "
    "riser bar, 1x8 and V-brakes.  Toe overlap is normal at this size.",
    merge(
        wheels(507, 50, 47),
        tubes("tt", 31.8, "1.4/1.0/1.4", 60), tubes("dt", 38.0, "1.4/1.0/1.4", 70),
        tubes("st", 31.8, "1.6/1.2/1.6", 80),
        FLAT_COCKPIT,
        frame_size_label="24in", frame_material="aluminium", joint_style="tig",
        head_tube_angle=69.0, seat_tube_angle=72.5, stack=480, reach=340,
        seat_tube_length=330, st_extension=85, tt_ht_offset=50, dt_ht_offset=25,
        bb_drop=20, chainstay_length=390, rear_hub_spacing=135, front_hub_spacing=100,
        bb_shell_od=40, bb_shell_width=68, cs_spread_bb=76,
        ht_od_top=38, ht_od_bottom=38, ht_wall=1.6, cs_od_bb=20, cs_od_drop=14, cs_wall=1.2,
        ss_od_top=16, ss_od_drop=12.7, ss_wall=1.2,
        fork_type="rigid", fork_length=360, fork_offset=38, fork_crown_height=30, fork_crown_width=110,
        fork_blade_od=28, fork_blade_od_tip=16, fork_blade_shape="straight",
        lower_stack=12, upper_stack=8, spacers=20, steerer_od=28.6,
        stem_length=40, stem_angle=10, stem_clamp_height=38, bar_type="riser", bar_rise=25,
        bar_backsweep=9, bar_width=560, bar_od=31.8,
        saddle_height=600, saddle_length=240, saddle_ref_to_nose=120, saddle_stack=45,
        seatpost_od=27.2, seatpost_length=300,
        drive_type="derailleur", crank_length=140, chainrings="32", cogs="11, 13, 15, 18, 21, 24, 28, 34",
        front_derailleur=False, chainline=47.5, pedal_type="flat", q_factor=150, toe_overhang=75,
        rim_depth_front=20, rim_depth_rear=20, spokes_front=28, spokes_rear=28,
        hub_flange_front=38, hub_flange_rear=44,
        brake_front="v", brake_rear="v",
        bottle_dt=True, bottle_st=False, bottle_dt_pos=120, bottle_length=180, bottle_diameter=70,
        paint_frame="#00a7e1", paint_fork="#00a7e1", paint_head_tube="#ffd100", decal_text="FW 24",
    ))

template(
    "time_trial", "Time trial / triathlon M", "tt",
    "Carbon time-trial / triathlon bike, size M: aero-profile top, down and seat tubes, steep 78° seat angle, "
    "low stack and long reach, base bar (bullhorn), deep-section wheels and 54/42 gearing.",
    merge(
        wheels(622, 25, 25),
        tubes("tt", 50.0, "1.4/1.0/1.4", 80, profile="aero", od2=26.0),
        tubes("dt", 62.0, "1.6/1.1/1.6", 90, profile="aero", od2=34.0),
        tubes("st", 48.0, "1.6/1.1/1.6", 100, profile="aero", od2=28.0),
        ROAD_COCKPIT,
        frame_size_label="M", frame_material="carbon", joint_style="bonded",
        head_tube_angle=73.0, seat_tube_angle=78.0, stack=515, reach=415,
        seat_tube_length=500, st_extension=20, tt_ht_offset=15, dt_ht_offset=30,
        bb_drop=70, chainstay_length=405, rear_hub_spacing=130, front_hub_spacing=100,
        bb_shell_od=46, bb_shell_width=86.5,
        ht_od_top=45, ht_od_bottom=56, ht_wall=1.8, cs_od_bb=28, cs_od_drop=16, cs_wall=1.4,
        ss_profile="aero", ss_od_top=22, ss_od_drop=14, ss_wall=1.2,
        fork_type="rigid", fork_length=365, fork_offset=50, fork_crown_height=20, fork_crown_width=105,
        fork_blade_od=38, fork_blade_od_tip=18, fork_blade_shape="straight",
        lower_stack=8, upper_stack=5, spacers=0, steerer_od=28.6,
        stem_length=100, stem_angle=-10, bar_type="bullhorn", bar_reach=80, bar_rise=0, bar_width=420,
        lever_type="none", hand_position="hoods",
        saddle_height=735, saddle_length=250, saddle_ref_to_nose=110,
        seatpost_od=27.2, seatpost_length=330,
        drive_type="derailleur", crank_length=170, chainrings="54, 42",
        cogs="11, 12, 13, 14, 15, 16, 17, 19, 21, 23, 25", front_derailleur=True,
        rim_depth_front=60, rim_depth_rear=80, spokes_front=18, spokes_rear=20, cross_front=0, cross_rear=2,
        brake_front="caliper", brake_rear="caliper", brake_reach=47,
        bottle_dt=True, bottle_st=False, dt_cable_stops=False, cs_bridge=False,
        paint_frame="#141414", paint_fork="#141414", paint_head_tube="#141414", paint_decal="#ff4f00",
        decal_text="FRAMEWRIGHT TT", decal_size=26,
    ))

template(
    "fat_bike", "Fat bike M", "fat",
    "Aluminium fat bike, size M: 26x4.0 tires on 559 mm rims (wheel diameter close to a 29er), 197 mm rear / "
    "150 mm front hubs, 100 mm BB shell, rigid fat fork, 1x11 and a riser bar.",
    merge(
        wheels(559, 101.6, 96),
        tubes("tt", 38.1, "1.4/1.0/1.4", 80), tubes("dt", 44.5, "1.5/1.1/1.5", 90),
        tubes("st", 34.9, "1.6/1.2/1.6", 120),
        FLAT_COCKPIT,
        frame_size_label="M", frame_material="aluminium", joint_style="tig",
        head_tube_angle=69.0, seat_tube_angle=73.5, stack=620, reach=420,
        seat_tube_length=440, st_extension=50, tt_ht_offset=15, dt_ht_offset=35,
        bb_drop=55, chainstay_length=450, rear_hub_spacing=197, front_hub_spacing=150,
        bb_shell_od=44, bb_shell_width=100, cs_spread_bb=100, ss_spread_top=60,
        ht_od_top=44, ht_od_bottom=56, ht_wall=1.8, cs_od_bb=25, cs_od_drop=18, cs_wall=1.2,
        ss_od_top=19, ss_od_drop=16, ss_wall=1.2,
        fork_type="rigid", fork_length=468, fork_offset=51, fork_crown_height=30, fork_crown_width=160,
        fork_blade_od=32, fork_blade_od_tip=20, fork_blade_shape="straight",
        lower_stack=12, upper_stack=8, spacers=20, steerer_od=28.6,
        stem_length=60, stem_angle=0, bar_type="riser", bar_rise=20, bar_backsweep=9, bar_width=760,
        saddle_height=740,
        seatpost_od=31.6, seatpost_length=400,
        drive_type="derailleur", crank_length=175, chainrings="28",
        cogs="11, 13, 15, 17, 19, 21, 24, 28, 32, 37, 46", front_derailleur=False, chainline=66,
        pedal_type="flat", q_factor=206,
        rim_depth_front=20, rim_depth_rear=20, spokes_front=32, spokes_rear=32, cross_front=3, cross_rear=3,
        hub_flange_front=60, hub_flange_rear=60,
        brake_front="disc", brake_rear="disc", rotor_front=180, rotor_rear=160,
        bottle_dt=True, bottle_st=False, bottle_dt_pos=150,
        paint_frame="#5b2c83", paint_fork="#5b2c83", paint_head_tube="#5b2c83", decal_text="FAT",
    ))


template(
    "road_tandem", "Road tandem L/M", "tandem",
    "Steel road tandem, large captain / medium stoker: 740 mm BB-to-BB, marathon tube, oversize boom, "
    "145 mm rear hub, 700x32 tires, disc brakes and an eccentric-free timing drive.",
    merge(
        wheels(622, 32, 31),
        tubes("tt", 35.0, "0.9/0.7/0.9", 80), tubes("dt", 38.1, "0.9/0.7/0.9", 90),
        tubes("st", 31.8, "0.9/0.7/0.9", 120),
        ROAD_COCKPIT,
        frame_type="tandem", tandem_bb_distance=740, tandem_bb_dy=0, stoker_st_angle=73.0, stoker_st_length=500,
        stoker_tt_drop=0, stoker_tt_angle=0, tandem_mid_tube="marathon", tandem_tube_od=38.1,
        stoker_saddle_height=700, stoker_bar_drop=110, stoker_stem_length=110, timing_ring=32,
        frame_size_label="L/M", frame_material="steel", joint_style="tig",
        head_tube_angle=72.0, seat_tube_angle=73.0, stack=600, reach=390,
        seat_tube_length=560, st_extension=25, tt_ht_offset=18, dt_ht_offset=30,
        bb_drop=72, chainstay_length=440, rear_hub_spacing=145, front_hub_spacing=100,
        bb_shell_od=41, bb_shell_width=68,
        ht_od_top=44, ht_od_bottom=44, ht_wall=1.4, cs_od_bb=22.2, cs_od_drop=16, cs_wall=0.9,
        ss_od_top=19, ss_od_drop=16, ss_wall=0.9,
        fork_type="rigid", fork_length=395, fork_offset=50, fork_crown_height=25, fork_crown_width=110,
        fork_blade_od=31.8, fork_blade_od_tip=18, fork_blade_shape="straight",
        lower_stack=12, upper_stack=8, spacers=30, steerer_od=28.6,
        stem_length=100, saddle_height=750,
        drive_type="derailleur", crank_length=172.5, chainrings="48, 34", cogs="11, 12, 13, 15, 17, 19, 22, 25, 28, 32, 36",
        brake_front="disc", brake_rear="disc", rotor_front=203, rotor_rear=180,
        spokes_front=36, spokes_rear=40, cross_front=3, cross_rear=3,
        bottle_dt=True, bottle_st=False, paint_frame="#1b6f8a", paint_fork="#1b6f8a",
        paint_head_tube="#f2f2f2", decal_text="FRAMEWRIGHT TANDEM",
    ))

template(
    "ebike_trekking", "E-trekking (mid-drive) M", "ebike",
    "Aluminium trekking e-bike, size M: mid-drive motor housing at the BB, down-tube battery, 700x47 tires, "
    "fenders and rear rack, 1x10 and a swept city bar.",
    merge(
        wheels(622, 47, 44),
        tubes("tt", 38.1, "1.4/1.1/1.4", 80), tubes("dt", 50.8, "1.6/1.2/1.6", 90),
        tubes("st", 34.9, "1.6/1.2/1.6", 120),
        FLAT_COCKPIT,
        frame_size_label="M", frame_material="aluminium", joint_style="tig",
        bb_housing="mid_motor", housing_length=180, housing_height=150, housing_dx=15, housing_dy=30,
        housing_mass=2900, battery="downtube", battery_length=400, battery_thickness=75, battery_pos=110,
        battery_mass=2600,
        head_tube_angle=70.5, seat_tube_angle=73.5, stack=640, reach=400,
        seat_tube_length=500, st_extension=40, tt_ht_offset=18, dt_ht_offset=35,
        bb_drop=60, chainstay_length=470, rear_hub_spacing=135, front_hub_spacing=100,
        bb_shell_od=44, bb_shell_width=73,
        ht_od_top=44, ht_od_bottom=56, ht_wall=1.8, cs_od_bb=25, cs_od_drop=18, cs_wall=1.2,
        ss_od_top=19, ss_od_drop=16, ss_wall=1.2,
        fork_type="rigid", fork_length=410, fork_offset=50, fork_crown_height=25, fork_crown_width=115,
        fork_blade_od=32, fork_blade_od_tip=18, fork_blade_shape="straight",
        lower_stack=12, upper_stack=8, spacers=30, steerer_od=28.6,
        stem_length=80, stem_angle=15, bar_type="swept", bar_rise=30, bar_backsweep=30, bar_width=620,
        saddle_height=720, saddle_length=260,
        drive_type="derailleur", crank_length=170, chainrings="38", cogs="11, 13, 15, 18, 21, 24, 28, 32, 37, 42",
        front_derailleur=False, pedal_type="flat",
        brake_front="disc", brake_rear="disc", rotor_front=180, rotor_rear=180,
        spokes_front=36, spokes_rear=36, cross_front=3, cross_rear=3,
        fenders=True, fender_clearance=12, rack_rear=True, rack_height=390,
        bottle_dt=False, bottle_st=True, paint_frame="#3c4a3e", paint_fork="#3c4a3e",
        paint_head_tube="#3c4a3e", decal_text="E-TREK",
    ))


# --------------------------------------------------------------------------
# build / check / write
# --------------------------------------------------------------------------
def build(spec: dict, order: int = 0) -> Design:
    d = Design()
    for k, v in spec["values"].items():
        if k not in d:
            raise KeyError(f"{spec['slug']}: unknown parameter {k!r}")
        d.set(k, v)
    for k, v in spec["extras"].items():
        d.extras[k] = json.loads(json.dumps(v))
    d.extras["meta"] = {"description": spec["description"], "category": spec["category"],
                        "template": spec["slug"], "order": order}
    return d


def designs() -> list[tuple[str, Design]]:
    return [(s["slug"], build(s, i)) for i, s in enumerate(TEMPLATES)]


def crown_clearance(d: Design, g) -> float:
    """Gap between the front tire (plus fender) and the underside of the fork crown."""
    ac = g.v["fork_length"]
    fender = (d.f("fender_clearance") + 2.5) if d["fenders"] else 0.0
    return ac - d.f("fork_crown_height") - g.wheels["front"].outer_r - fender


def report(slug: str, d: Design) -> str:
    g = solve(d)
    v = g.v
    ratio = v["stack"] / v["reach"] if v["reach"] else math.nan
    lines = [f"{slug:20s} {d.title}",
             f"  stack {v['stack']:.0f} reach {v['reach']:.0f} ratio {ratio:.2f}  HTL {v['head_tube_length']:.0f}"
             f"  HTA {v['head_tube_angle']:.1f} STA {v['seat_tube_angle']:.1f}  trail {v['trail']:.0f}",
             f"  BB drop {v['bb_drop']:.0f} height {v['bb_height']:.0f}  CS {v['chainstay_length']:.0f}"
             f"  WB {v['wheelbase']:.0f} FC {v['front_center']:.0f}  ETT {v['top_tube_effective']:.0f}"
             f"  ST ext {v['st_extension']:.0f}  standover {v['standover']:.0f}",
             f"  toe {v['toe_clearance']:.0f}  rear tire {v['rear_tire_clearance']:.0f}"
             f"  front tire/DT {v['front_tire_clearance']:.0f}  crown {crown_clearance(d, g):.0f}"
             f"  post insert {v['seatpost_insertion']:.0f} exposed {v['seatpost_exposed']:.0f}"
             f"  saddle-bar drop {v['saddle_bar_drop']:.0f}  pedal clr {v['pedal_clearance']:.0f}"]
    for w in g.warnings:
        lines.append(f"  WARNING: {w}")
    return "\n".join(lines)


def write(d: Design, path: Path) -> None:
    """Save without per-run timestamps so regenerated files only change when the design does."""
    data = d.to_dict()
    meta = data["extras"]["meta"]
    for k in ("created", "modified"):
        meta.pop(k, None)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def render(slug: str, d: Design, out: Path) -> Path:
    from framewright.qt import QtWidgets
    from framewright.render.bike_scene import build_scene
    from framewright.render.qt_render import render_image
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{slug}.png"
    render_image(build_scene(solve(d))).save(str(path))
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="output directory for .fwd files")
    ap.add_argument("--report", action="store_true", help="print key numbers and solver warnings")
    ap.add_argument("--render", type=Path, metavar="DIR", help="also render each template to DIR/<slug>.png")
    ap.add_argument("--dry-run", action="store_true", help="do not write .fwd files")
    args = ap.parse_args(argv)
    if not args.dry_run:
        args.out.mkdir(parents=True, exist_ok=True)
    for slug, d in designs():
        if not args.dry_run:
            write(d, args.out / f"{slug}.fwd")
        if args.report:
            print(report(slug, d))
        if args.render:
            print("rendered", render(slug, d, args.render))
    if not args.dry_run:
        print(f"wrote {len(TEMPLATES)} templates to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
