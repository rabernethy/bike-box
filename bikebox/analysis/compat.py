"""Component-compatibility checks.

Flags standards mismatches that would make a frame hard or impossible to build
or assemble — seatpost fit, thru-axle vs hub spacing, front derailleur vs
chainrings, belt drive without a frame break, disc/rotor consistency, mismatched
wheel sizes and an out-of-range chainline. Conservative: physically-impossible
combinations are ``fail``, likely mistakes ``warn``, intentional-but-notable
``info``.
"""
from __future__ import annotations

from .report import Section
from ..geometry.solver import Geometry

THRU_STANDARDS = {142.0, 148.0, 157.0, 177.0, 197.0}      # common rear thru-axle OLD
BB_STANDARDS = {68.0, 70.0, 73.0, 83.0, 100.0, 120.0}


def _rings(d) -> int:
    return len([x for x in str(d.get("chainrings", "")).replace(",", " ").split() if x.strip().replace(".", "").isdigit()])


def check(g: Geometry) -> list[tuple[str, str, str]]:
    """List of (status, label, message); status in ok/warn/fail/info."""
    d = g.design
    out: list[tuple[str, str, str]] = []

    # seatpost into the seat tube
    st_id = d.f("st_od") - 2 * max(d.f("st_wall_end"), d.f("st_wall_mid"))
    post = d.f("seatpost_od")
    if post and st_id > 0:
        if post > st_id + 0.2:
            out.append(("fail", "Seatpost", f"Ø{post:.1f} post won't fit the seat-tube bore (~Ø{st_id:.1f})"))
        elif post < st_id - 0.8:
            out.append(("warn", "Seatpost", f"Ø{post:.1f} post is loose in the ~Ø{st_id:.1f} bore (needs a shim)"))
        else:
            out.append(("ok", "Seatpost", f"Ø{post:.1f} post fits the ~Ø{st_id:.1f} seat-tube bore"))

    # thru-axle dropout vs rear spacing
    if d["dropout_type"] == "thru" and d.f("rear_hub_spacing") not in THRU_STANDARDS:
        out.append(("warn", "Rear axle", f"Thru-axle dropouts with {d.f('rear_hub_spacing'):.0f} mm spacing "
                    "(expected 142/148/157)"))

    # front derailleur vs chainrings / drive type
    nring = _rings(d)
    if d.get("front_derailleur") and nring <= 1:
        out.append(("warn", "Front derailleur", "A front derailleur is set but there is only one chainring"))
    if d["drive_type"] == "singlespeed" and nring > 1:
        out.append(("warn", "Drivetrain", f"Single-speed drive with {nring} chainrings"))

    # rear derailleur capacity vs the drivetrain range
    if d["drive_type"] == "derailleur":
        from .gearing import drivetrain_range
        dr = drivetrain_range(d)
        cap = d.get("rd_capacity") or 0
        mx = d.get("rd_max_cog") or 0
        if dr and cap and dr["required_capacity"] > cap:
            out.append(("fail", "Derailleur capacity", f"Drivetrain needs {dr['required_capacity']:.0f} T of "
                        f"wrap but the rear derailleur is rated for {cap} T"))
        if dr and mx and dr["max_cog"] > mx:
            out.append(("fail", "Derailleur max cog", f"{dr['max_cog']:.0f} T largest cog exceeds the rear "
                        f"derailleur's {mx} T limit"))

    # belt drive needs a frame break
    if d["drive_type"] == "belt" and d["dropout_type"] not in ("sliding", "track") and not d.get("couplers"):
        out.append(("warn", "Belt drive", "Belt drive needs a frame break (split seat stay, sliding dropout or "
                    "coupler) to install the belt"))

    # disc / rotor consistency
    for end in ("front", "rear"):
        brake = d[f"brake_{end}"]
        rotor = d.f(f"rotor_{end}")
        if brake == "disc" and rotor <= 0:
            out.append(("warn", f"{end.capitalize()} brake", "Disc brake with no rotor size set"))
        if brake != "disc" and rotor > 0:
            out.append(("info", f"{end.capitalize()} brake", f"Rotor size set but the brake is '{brake}'"))

    # wheel sizes
    if abs(d.f("front_bsd") - d.f("rear_bsd")) > 1:
        out.append(("info", "Wheels", f"Mixed wheel sizes (front BSD {d.f('front_bsd'):.0f}, "
                    f"rear {d.f('rear_bsd'):.0f}) — mullet/650b-front, intentional?"))

    # chainline sanity vs rear spacing
    cl = d.f("chainline")
    half = d.f("rear_hub_spacing") / 2
    if cl and (cl > half + 12 or cl < half - 25):
        out.append(("warn", "Chainline", f"Chainline {cl:.1f} mm is unusual for {d.f('rear_hub_spacing'):.0f} mm "
                    f"spacing (~{half:.0f} mm centre)"))

    # BB shell width
    if d.f("bb_shell_width") not in BB_STANDARDS:
        out.append(("info", "BB shell", f"{d.f('bb_shell_width'):.0f} mm shell is not a common width "
                    "(68/73/83/100…)"))

    if not out:
        out.append(("ok", "Compatibility", "No component standards conflicts found"))
    return out


def section(g: Geometry) -> Section:
    # report rows are (label, value, status)
    return Section("Compatibility", [(label, msg, status) for status, label, msg in check(g)])
