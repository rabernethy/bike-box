"""Rider anatomy, pose and drawing.

Body model
----------
The rider is built from six basic measurements (height, inseam, torso length,
arm length, shoulder width, foot length).  Any of them can be left at 0 and is
then estimated from height with the segment-length ratios of Drillis & Contini
(1966) as tabulated by Winter, *Biomechanics and Motor Control of Human
Movement* (4th ed., fig. 4.1).  Individual segments (thigh, lower leg, upper
arm, forearm, head/neck) can be overridden directly.

Pose
----
``solve_pose`` places the hip joint at an offset from the saddle reference
point, puts the ball of the foot on the pedal (pedal + cleat stack, cleat
offset, foot angle that varies through the stroke), solves the knee with a
two-link IK (thigh / lower leg), then finds the torso angle at which the arms
reach the hand position with the preferred elbow bend and solves the elbow the
same way.  Configurations that cannot be reached are clamped and reported in
``Pose.warnings`` instead of raising.

All lengths in mm, angles in degrees, origin at the BB, +X forward, +Y up.
The drive side (+Z) is the near side in the side view.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..geometry.solver import Geometry
from ..geometry.vec import V, circle_circle_intersections, cosd, sind
from ..model import params as P
from ..model.design import Design
from ..render.scene import Z_BACK, Z_RIDER, Scene, Style
from ..render.theme import Theme

# --------------------------------------------------------------------------
# parameters
# --------------------------------------------------------------------------
GROUP = "Rider & fit"
_BODY, _SEG, _POS, _DISP = "Body measurements", "Body segments", "Position", "Rider display"


def _mm(key, label, section, default, lo, hi, step=1.0, help=""):
    return P.ParamDef(key, label, GROUP, section, P.FLOAT, float(default), "mm", lo, hi, step, (), help)


def _deg(key, label, section, default, lo, hi, step=0.5, help=""):
    return P.ParamDef(key, label, GROUP, section, P.FLOAT, float(default), "deg", lo, hi, step, (), help)


HELMETS = (("none", "None"), ("road", "Road helmet"), ("aero", "Aero (time trial) helmet"), ("cap", "Cycling cap"))
RIDER_STYLES = (("silhouette", "Silhouette"), ("outline", "Outline"), ("skeleton", "Skeleton (stick figure)"))

P.register([
    _mm("rider_height", "Rider height", _BODY, 1780, 900, 2300, help="Standing height, barefoot"),
    _mm("inseam", "Inseam (floor to pubic bone)", _BODY, 0, 0, 1300,
        help="Barefoot, with firm upward pressure as for saddle-height formulas. 0 = estimate (0.47 × height)"),
    _mm("torso_length", "Torso length", _BODY, 0, 0, 1000,
        help="Pubic bone to sternal notch. 0 = estimate (0.818 × height − inseam)"),
    _mm("arm_length", "Arm length", _BODY, 0, 0, 1100,
        help="Shoulder joint (acromion) to the centre of a clenched fist. 0 = estimate (0.375 × height)"),
    _mm("shoulder_width", "Shoulder width", _BODY, 0, 0, 700,
        help="Acromion to acromion. 0 = estimate (0.23 × height)"),
    _mm("foot_length", "Foot length", _BODY, 0, 0, 400, help="Heel to longest toe. 0 = estimate (0.152 × height)"),
    P.ParamDef("rider_mass", "Rider mass", GROUP, _BODY, P.FLOAT, 0.0, "kg", 0, 250, 0.5, (),
               "Including clothing. 0 = estimate from height (BMI 22.5)"),
    _mm("thigh_length", "Thigh (hip joint to knee)", _SEG, 0, 0, 800, help="0 = derive from height and inseam"),
    _mm("lower_leg_length", "Lower leg (knee to ankle)", _SEG, 0, 0, 800, help="0 = derive from height and inseam"),
    _mm("upper_arm_length", "Upper arm (shoulder to elbow)", _SEG, 0, 0, 600, help="0 = derive from arm length"),
    _mm("forearm_length", "Forearm (elbow to wrist)", _SEG, 0, 0, 500, help="0 = derive from arm length"),
    _mm("head_neck_length", "Head & neck (shoulder to head centre)", _SEG, 0, 0, 400,
        help="0 = estimate (0.115 × height)"),
    _mm("hip_above_saddle", "Hip joint above saddle top", _POS, 0, 0, 250,
        help="Height of the hip joint centre above the saddle reference point. 0 = estimate (0.095 × inseam)"),
    _mm("hip_forward", "Hip joint forward of saddle reference", _POS, 20, -150, 150,
        help="Along the saddle; negative = hip behind the saddle reference point.  With the pelvis tilted "
             "forward the hip joint sits ahead of the sit bones (default 20 mm)"),
    _mm("cleat_offset", "Ball of foot ahead of pedal spindle", _POS, 0, -60, 80,
        help="Cleat position: + = ball of the foot in front of the spindle (mid-foot cleats are +20 to +40)"),
    _deg("ankle_angle", "Foot angle at bottom of stroke", _POS, 15, -20, 60,
         help="Sole angle below horizontal at bottom dead centre (+ = heel up, toes down)"),
    _deg("ankling", "Ankling range", _POS, 15, 0, 45,
         help="How much flatter the foot is at the top of the stroke than at the bottom"),
    _deg("elbow_bend", "Preferred elbow bend", _POS, 15, 0, 120,
         help="Elbow flexion from straight; the torso angle is solved so the hands reach the bars with this bend"),
    _deg("head_tilt", "Head lift", _POS, 25, -30, 90, help="Neck angle above the torso line"),
    P.ParamDef("helmet", "Helmet", GROUP, _DISP, P.CHOICE, "road", choices=HELMETS, morph=False),
    P.ParamDef("rider_style", "Rider drawing style", GROUP, _DISP, P.CHOICE, "silhouette", choices=RIDER_STYLES,
               morph=False),
])

# --------------------------------------------------------------------------
# anthropometry (fractions of standing height H; Drillis & Contini / Winter)
# --------------------------------------------------------------------------
DEFAULT_HEIGHT = 1780.0
R_INSEAM = 0.470          # floor to pubic bone (cycling inseam, firm pressure)
R_HIP = 0.530             # greater trochanter / hip joint height
R_ANKLE = 0.039           # lateral malleolus height
R_THIGH = 0.245
R_SHANK = 0.246
R_SHOULDER = 0.818        # glenohumeral joint / sternal notch height
R_UPPER_ARM = 0.186
R_FOREARM = 0.146
R_HAND = 0.108            # wrist to fingertip
R_GRIP = 0.043            # wrist to the centre of the grip (≈ 0.4 hand length)
R_ARM = R_UPPER_ARM + R_FOREARM + R_GRIP
R_SHOULDER_W = 0.230      # biacromial breadth
R_FOOT = 0.152
R_HEAD_NECK = 0.115       # shoulder joint to head centre (ear canal)
R_HEAD_RX = 0.055         # half head length (front-back)
R_HEAD_RY = 0.065         # half head height
BMI_DEFAULT = 22.5
HIP_ABOVE_SADDLE_K = 0.095   # × inseam; calibrated so LeMond height gives ~148° knee extension
FOOT_HEEL_TO_BALL = 0.73     # × foot length, heel to 1st metatarsal head
FOOT_ANKLE_TO_BALL = 0.53    # × foot length, ankle joint to 1st metatarsal head (along the sole)
SHOE_SOLE = 8.0              # outer sole to the plantar skin (mm)


def estimate_from_basic(height: float, inseam: float = 0.0, torso: float = 0.0, arm: float = 0.0,
                        shoulder: float = 0.0, foot: float = 0.0) -> dict[str, float]:
    """Full set of segment lengths from the six basic dimensions (0 = estimate).

    Returned keys: ``height inseam torso arm shoulder foot thigh lower_leg
    upper_arm forearm hand head_neck ankle_height hip_height crotch_to_hip
    torso_seg heel_to_ball ankle_to_ball ball_to_toe head_rx head_ry mass``
    (``hand`` = wrist to grip centre, ``torso_seg`` = hip joint to shoulder joint,
    ``mass`` in kg)."""
    H = float(height) if height and height > 0 else DEFAULT_HEIGHT
    inseam = float(inseam) if inseam and inseam > 0 else R_INSEAM * H
    ankle_h = R_ANKLE * H
    crotch_to_hip = (R_HIP - R_INSEAM) * H
    hip_h = inseam + crotch_to_hip
    leg = max(hip_h - ankle_h, 0.2 * H)
    thigh = leg * R_THIGH / (R_THIGH + R_SHANK)
    torso = float(torso) if torso and torso > 0 else max(R_SHOULDER * H - inseam, 0.2 * H)
    arm = float(arm) if arm and arm > 0 else R_ARM * H
    k = arm / R_ARM
    foot = float(foot) if foot and foot > 0 else R_FOOT * H
    return {
        "height": H, "inseam": inseam, "torso": torso, "arm": arm,
        "shoulder": float(shoulder) if shoulder and shoulder > 0 else R_SHOULDER_W * H,
        "foot": foot,
        "thigh": thigh, "lower_leg": leg - thigh,
        "upper_arm": R_UPPER_ARM * k, "forearm": R_FOREARM * k, "hand": R_GRIP * k,
        "head_neck": R_HEAD_NECK * H,
        "ankle_height": ankle_h, "hip_height": hip_h, "crotch_to_hip": crotch_to_hip,
        "torso_seg": max(torso - crotch_to_hip, 0.12 * H),
        "heel_to_ball": FOOT_HEEL_TO_BALL * foot, "ankle_to_ball": FOOT_ANKLE_TO_BALL * foot,
        "ball_to_toe": (1.0 - FOOT_HEEL_TO_BALL) * foot,
        "head_rx": R_HEAD_RX * H, "head_ry": R_HEAD_RY * H,
        "mass": BMI_DEFAULT * (H / 1000.0) ** 2,
    }


def anatomy(design: Design) -> dict[str, float]:
    """Segment lengths for the design's rider (basic dimensions + overrides).

    Adds ``hip_above_saddle`` (resolved auto value) to the keys of
    :func:`estimate_from_basic`."""
    d = design
    a = estimate_from_basic(d.f("rider_height"), d.f("inseam"), d.f("torso_length"), d.f("arm_length"),
                            d.f("shoulder_width"), d.f("foot_length"))
    for key, pkey in (("thigh", "thigh_length"), ("lower_leg", "lower_leg_length"),
                      ("upper_arm", "upper_arm_length"), ("forearm", "forearm_length"),
                      ("head_neck", "head_neck_length")):
        v = d.f(pkey)
        if v > 0:
            a[key] = v
    a["hip_height"] = a["thigh"] + a["lower_leg"] + a["ankle_height"]
    a["arm"] = a["upper_arm"] + a["forearm"] + a["hand"]
    if d.f("rider_mass") > 0:
        a["mass"] = d.f("rider_mass")
    hs = d.f("hip_above_saddle")
    a["hip_above_saddle"] = hs if hs > 0 else HIP_ABOVE_SADDLE_K * a["inseam"]
    return a


# --------------------------------------------------------------------------
# pose
# --------------------------------------------------------------------------
@dataclass
class Pose:
    joints: dict[str, V] = field(default_factory=dict)
    angles: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)


@dataclass
class _Position:
    hip_fwd: float
    cleat: float
    ankle: float
    ankling: float
    stack: float
    elbow_bend: float
    head_tilt: float
    crank_length: float


def _position(d: Design) -> _Position:
    return _Position(d.f("hip_forward"), d.f("cleat_offset"), d.f("ankle_angle"), d.f("ankling"),
                     d.f("pedal_stack") if d.get("pedal_type", "clipless") != "none" else 0.0,
                     d.f("elbow_bend"), d.f("head_tilt"), d.f("crank_length"))


def hip_point(saddle: V, design: Design, a: dict[str, float] | None = None) -> V:
    """Hip joint centre for a saddle reference point (offset in the saddle's frame)."""
    a = a or anatomy(design)
    tilt = design.f("saddle_tilt")
    sx = V(cosd(tilt), sind(tilt))
    return saddle + sx * design.f("hip_forward") + sx.perp() * a["hip_above_saddle"]


def two_link(a: V, b: V, l1: float, l2: float, side: float = 1.0) -> tuple[V, float]:
    """Joint of the chain a–j–b with |a j| = l1, |j b| = l2.

    ``side`` +1 puts the joint left of a→b, -1 right.  Returns ``(joint, err)``
    where ``err`` > 0 is how far b is beyond reach (chain straightened towards
    b) and ``err`` < 0 how much too close it is (chain folded); 0 when exact."""
    dv = b - a
    dist = dv.length()
    u = dv / dist if dist > 1e-9 else V(0.0, -1.0)
    if dist >= l1 + l2:
        return a + u * l1, dist - (l1 + l2)
    err = 0.0
    if dist <= abs(l1 - l2):
        err = dist - abs(l1 - l2) - 1e-12
    c = (l1 * l1 + dist * dist - l2 * l2) / (2 * l1 * max(dist, 1e-9))
    ang = math.degrees(math.acos(max(-1.0, min(1.0, c))))
    return a + u.rot(side * ang) * l1, err


def _interior(vertex: V, p: V, q: V) -> float:
    a, b = (p - vertex).norm(), (q - vertex).norm()
    return math.degrees(math.acos(max(-1.0, min(1.0, a.dot(b)))))


def _foot_angle(pos: _Position, crank: float, bdc: float) -> float:
    """Sole angle below horizontal; ``ankle_angle`` at BDC, flatter by ``ankling`` at TDC."""
    phi = math.radians(crank - bdc)
    return pos.ankle - pos.ankling * (1.0 - math.cos(phi)) / 2.0


def leg_pose(hip: V, crank: float, a: dict[str, float], pos: _Position) -> tuple[dict[str, V], float]:
    """Joints of one leg with the pedal at ``crank`` degrees.  Returns
    (joints {pedal, ball, ankle, heel, toe, knee}, reach error from :func:`two_link`)."""
    pedal = V.polar(pos.crank_length, crank)
    bdc = math.degrees(math.atan2(-hip.y, -hip.x))
    fa = _foot_angle(pos, crank, bdc)
    s = V(cosd(fa), -sind(fa))          # along the sole, heel -> toe
    n = s.perp()                         # out of the sole, into the foot
    ball = pedal + n * pos.stack + s * pos.cleat
    ankle = ball + n * (SHOE_SOLE + a["ankle_height"]) - s * a["ankle_to_ball"]
    knee, err = two_link(hip, ankle, a["thigh"], a["lower_leg"], 1.0)
    if err > 0:                          # cannot reach: straight leg, foot follows the shin
        ankle = knee + (ankle - hip).norm() * a["lower_leg"]
        shift = ankle - (ball + n * (SHOE_SOLE + a["ankle_height"]) - s * a["ankle_to_ball"])
        ball = ball + shift
    heel = ball - s * (a["heel_to_ball"] + 10.0)
    toe = ball + s * (a["ball_to_toe"] + 15.0)
    return {"pedal": pedal, "ball": ball, "ankle": ankle, "heel": heel, "toe": toe, "knee": knee}, err


def leg_sweep(hip: V, a: dict[str, float], pos: _Position, shoulder: V | None = None,
              step: float = 5.0) -> dict[str, float]:
    """Knee (and hip) angles over a full crank revolution.

    Returns ``knee_max`` (extension, ≈ BDC), ``knee_min`` (flexion, ≈ TDC),
    ``hip_min`` (if ``shoulder`` is given), ``reach_err`` (worst over-reach, mm,
    > 0 when the foot cannot reach the pedal), ``fold_err`` (< 0 when the knee
    folds completely) and ``kops`` (knee ahead of the spindle at 3 o'clock)."""
    kmax, kmin, hmin = -1.0, 999.0, 999.0
    reach_err, fold_err = 0.0, 0.0
    n = max(int(round(360.0 / step)), 8)
    for i in range(n):
        c = 360.0 * i / n
        j, err = leg_pose(hip, c, a, pos)
        k = _interior(j["knee"], hip, j["ankle"])
        kmax, kmin = max(kmax, k), min(kmin, k)
        reach_err = max(reach_err, err)
        fold_err = min(fold_err, err)
        if shoulder is not None:
            hmin = min(hmin, _interior(hip, shoulder, j["knee"]))
    j0, _ = leg_pose(hip, 0.0, a, pos)
    out = {"knee_max": kmax, "knee_min": kmin, "reach_err": reach_err, "fold_err": fold_err,
           "kops": j0["knee"].x - j0["pedal"].x}
    if shoulder is not None:
        out["hip_min"] = hmin
    return out


def _arm_span(ua: float, fa: float, elbow: float) -> float:
    """Shoulder to grip distance for an interior elbow angle (degrees)."""
    return math.sqrt(max(ua * ua + fa * fa - 2 * ua * fa * cosd(elbow), 0.0))


def solve_pose(g: Geometry, crank_angle: float | None = None) -> Pose:
    """Rider joints and fit angles on solved geometry ``g``.

    ``crank_angle`` (drive-side crank, degrees CCW from forward) defaults to the
    design's display crank angle.  Joints: hip knee ankle heel ball toe pedal
    (near/drive side), the same with ``_far`` for the other leg, shoulder elbow
    wrist hand neck head head_top.  Angles (degrees unless noted): knee_angle,
    knee_extension_bdc, knee_flexion_bdc, knee_flexion_tdc, hip_angle,
    hip_angle_min, ankle_angle, torso_angle, shoulder_angle, elbow_angle,
    neck_angle, kops (mm), saddle_to_hand_reach (mm), crank_angle."""
    d = g.design
    a = anatomy(d)
    pos = _position(d)
    pose = Pose()
    J, ang = pose.joints, pose.angles
    crank = d.f("crank_angle") if crank_angle is None else float(crank_angle)
    hip = hip_point(g.p["saddle"], d, a)
    J["hip"] = hip

    # -- upper body: torso angle so the arms reach the hands with the preferred bend
    W = g.p["hand"]
    t = a["torso_seg"]
    ua, fa = a["upper_arm"], a["forearm"] + a["hand"]
    span_pref = _arm_span(ua, fa, 180.0 - pos.elbow_bend)
    span_max = ua + fa
    span_min = _arm_span(ua, fa, 30.0)
    dHW = hip.dist(W)
    u_hw = (W - hip).norm()
    if abs(t - span_pref) <= dHW <= t + span_pref:
        sols = circle_circle_intersections(hip, t, W, span_pref)
        shoulder = max(sols, key=lambda q: (W - hip).cross(q - hip)) if sols else hip + u_hw * t
    elif dHW > t + span_pref:
        shoulder = hip + u_hw * t          # lean towards the hands, straighten the arms
        if dHW > t + span_max + 0.5:
            pose.warn(f"Hands out of reach by {dHW - t - span_max:.0f} mm (arms fully extended)")
    else:
        shoulder = hip + V.polar(t, 80.0)  # hands very close: sit up
    elbow, err = two_link(shoulder, W, ua, fa, -1.0)
    if err > 0:
        u = (W - shoulder).norm()
        wrist = shoulder + u * (ua + a["forearm"])
        hand = shoulder + u * span_max
    else:
        if shoulder.dist(W) < span_min:
            pose.warn("Hands too close to the saddle: elbows folded")
        wrist = elbow + (W - elbow).norm() * a["forearm"]
        hand = W
    torso_angle = (shoulder - hip).angle()
    neck_angle = torso_angle + pos.head_tilt
    head = shoulder + V.polar(a["head_neck"], neck_angle)
    head_up = 90.0 + (neck_angle - 90.0) * 0.5
    J.update({"shoulder": shoulder, "elbow": elbow, "wrist": wrist, "hand": hand,
              "neck": shoulder.lerp(head, 0.45), "head": head,
              "head_top": head + V.polar(a["head_ry"], head_up)})

    # -- legs
    near, err_n = leg_pose(hip, crank, a, pos)
    far, _ = leg_pose(hip, crank + 180.0, a, pos)
    J.update(near)
    J.update({k + "_far": v for k, v in far.items()})
    sweep = leg_sweep(hip, a, pos, shoulder)
    if sweep["reach_err"] > 0.5:
        pose.warn(f"Leg cannot reach the pedal at the bottom of the stroke (short by {sweep['reach_err']:.0f} mm); "
                  "saddle too high for this rider")
    if sweep["fold_err"] < -0.5:
        pose.warn("Knee fully folded at the top of the stroke; saddle too low for this rider")

    ang.update({
        "crank_angle": crank,
        "knee_angle": _interior(near["knee"], hip, near["ankle"]),
        "knee_extension_bdc": sweep["knee_max"],
        "knee_flexion_bdc": 180.0 - sweep["knee_max"],
        "knee_flexion_tdc": sweep["knee_min"],
        "hip_angle": _interior(hip, shoulder, near["knee"]),
        "hip_angle_min": sweep["hip_min"],
        "ankle_angle": _interior(near["ankle"], near["knee"], near["ball"]),
        "torso_angle": torso_angle,
        "shoulder_angle": _interior(shoulder, hip, elbow),
        "elbow_angle": _interior(elbow, shoulder, wrist),
        "neck_angle": neck_angle,
        "head_up_angle": head_up,
        "kops": sweep["kops"],
        "saddle_to_hand_reach": g.p["saddle"].dist(W),
    })
    return pose


# --------------------------------------------------------------------------
# drawing
# --------------------------------------------------------------------------
def _rgb(c: str) -> tuple[int, int, int]:
    c = c.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except (ValueError, IndexError):
        return (127, 159, 191)


def _mix(c1: str, c2: str, t: float) -> str:
    """Blend colour c1 towards c2 by t (0..1)."""
    a, b = _rgb(c1), _rgb(c2)
    return "#%02x%02x%02x" % tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def _hull(points: list[V]) -> list[V]:
    pts = sorted({(round(p.x, 6), round(p.y, 6)) for p in points})
    if len(pts) <= 2:
        return [V(*p) for p in pts]

    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    lower: list = []
    upper: list = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return [V(*p) for p in lower[:-1] + upper[:-1]]


def _blob(circles: list[tuple[V, float]], n: int = 24) -> list[V]:
    """Convex outline around a set of circles (rounded limb / body shapes)."""
    pts = []
    for c, r in circles:
        pts += [c + V.polar(r, 360.0 * i / n) for i in range(n)]
    return _hull(pts)


def capsule(a: V, b: V, ra: float, rb: float, n: int = 12) -> list[V]:
    """Outline of a tapered capsule: circles of radius ra at a and rb at b joined by tangents."""
    L = a.dist(b)
    if L <= abs(ra - rb) + 1e-6:
        c, r = (a, ra) if ra >= rb else (b, rb)
        return [c + V.polar(r, 360.0 * i / (2 * n)) for i in range(2 * n)]
    base = (b - a).angle()
    th = math.degrees(math.acos(max(-1.0, min(1.0, (ra - rb) / L))))
    pts = [b + V.polar(rb, base - th + 2 * th * i / n) for i in range(n + 1)]
    pts += [a + V.polar(ra, base + th + (360 - 2 * th) * i / n) for i in range(n + 1)]
    return pts


def _ellipse(c: V, fwd: V, up: V, rx: float, ry: float, a0: float, a1: float, n: int = 24) -> list[V]:
    return [c + fwd * (rx * cosd(a0 + (a1 - a0) * i / n)) + up * (ry * sind(a0 + (a1 - a0) * i / n))
            for i in range(n + 1)]


def _shoe(J: dict[str, V], a: dict[str, float], suffix: str = "") -> list[V]:
    ball, heel, toe = J["ball" + suffix], J["heel" + suffix], J["toe" + suffix]
    s = (toe - heel).norm()
    n = s.perp()
    k = a["foot"] / 271.0
    hx = (heel - ball).dot(s)
    tx = (toe - ball).dot(s)
    ax = -a["ankle_to_ball"]
    ah = a["ankle_height"] + SHOE_SOLE
    loc = [(hx, 4 * k), (hx + 8 * k, 0), (tx - 16 * k, 0), (tx, 7 * k), (tx - 5 * k, 20 * k), (tx - 32 * k, 32 * k),
           (ax * 0.35, 52 * k), (ax + 30 * k, ah + 22 * k), (ax - 22 * k, ah + 18 * k), (hx, ah * 0.6)]
    return [ball + s * x + n * y for x, y in loc]


def _head_outline(c: V, fwd: V, up: V, rx: float, ry: float) -> list[V]:
    pts = []
    for i in range(36):
        th = i * 10.0
        r = 1.0
        if th in (340.0, 350.0):          # nose
            r = 1.12 if th == 350.0 else 1.06
        elif th in (300.0, 310.0, 320.0):  # chin / jaw
            r = 1.04
        pts.append(c + fwd * (rx * r * cosd(th)) + up * (ry * r * sind(th)))
    return pts


def _helmet(kind: str, c: V, fwd: V, up: V, rx: float, ry: float, H: float) -> list[list[V]]:
    if kind == "road":
        t = 0.014 * H
        outer = _ellipse(c, fwd, up, rx + t, ry + t * 1.2, 15, 200, 28)
        inner = _ellipse(c, fwd, up, rx * 0.97, ry * 0.97, 200, 15, 28)
        return [outer + inner]
    if kind == "aero":
        t = 0.012 * H
        outer = _ellipse(c, fwd, up, rx + t, ry + t, 15, 150, 20)
        tail = c - fwd * (rx + 0.10 * H) - up * (0.015 * H)
        inner = _ellipse(c, fwd, up, rx * 0.97, ry * 0.97, 215, 15, 24)
        visor = _ellipse(c, fwd, up, rx + t * 0.6, ry * 0.95, -25, 15, 6)
        return [outer + [tail] + inner, visor + [c + fwd * (rx * 0.9)]]
    if kind == "cap":
        t = 0.004 * H
        dome = _ellipse(c, fwd, up, rx + t, ry + t, 20, 175, 20) + _ellipse(c, fwd, up, rx, ry, 175, 20, 20)
        p0 = c + fwd * (rx * cosd(22)) + up * (ry * sind(22))
        bdir = fwd.rot(20)
        brim = [p0 + up * 4, p0 + bdir * (0.035 * H) + up * 3, p0 + bdir * (0.035 * H) - up * 2, p0 - up * 4]
        return [dome, brim]
    return []


def draw_rider(scene: Scene, g: Geometry, theme: Theme) -> None:
    """Draw the rider (if ``show_rider``) on layer ``rider``."""
    d = g.design
    if not d.get("show_rider", False):
        return
    pose = solve_pose(g)
    for w in pose.warnings:
        g.warn(f"Rider: {w}")
    a = anatomy(d)
    J = pose.joints
    H = a["height"]
    style = d.get("rider_style", "silhouette")
    base = theme.rider or "#7f9fbf"
    bg = theme.bg or "#ffffff"
    far_col = _mix(base, bg, 0.45)
    layer = "rider"
    z_far, z_body, z_leg, z_arm, z_helmet = Z_BACK, Z_RIDER, Z_RIDER + 1, Z_RIDER + 2, Z_RIDER + 3

    if style == "skeleton":
        w = max(theme.width * 2.0, 0.5)
        for suffix, col, z in (("_far", far_col, z_far), ("", base, z_leg)):
            st = Style(col, w, None)
            scene.poly([J["hip"], J["knee" + suffix], J["ankle" + suffix], J["ball" + suffix], J["toe" + suffix]],
                       st, layer, z, tag="rider:leg" + suffix)
            scene.line(J["ankle" + suffix], J["heel" + suffix], st, layer, z, "rider:foot" + suffix)
            scene.line(J["heel" + suffix], J["ball" + suffix], st, layer, z, "rider:foot" + suffix)
            for k in ("knee", "ankle", "ball"):
                scene.circle(J[k + suffix], 0.006 * H, Style(col, w * 0.5, col), layer, z, "rider:joint")
        st = Style(base, w, None)
        scene.line(J["hip"], J["shoulder"], st, layer, z_body, "rider:torso")
        scene.line(J["shoulder"], J["head"], st, layer, z_body, "rider:neck")
        scene.poly([J["shoulder"], J["elbow"], J["wrist"], J["hand"]], st, layer, z_arm, tag="rider:arm")
        scene.circle(J["head"], a["head_ry"] * 0.9, Style(base, w, None), layer, z_body, "rider:head")
        for k in ("hip", "shoulder", "elbow", "wrist"):
            scene.circle(J[k], 0.007 * H, Style(base, w * 0.5, base), layer, z_arm, "rider:joint")
        return

    filled = style != "outline"
    edge = _mix(base, "#000000", 0.35) if filled else base
    wk = theme.width * (0.7 if filled else 1.0)
    near = Style(edge, wk, base if filled else None)
    far = Style(_mix(edge, bg, 0.45), wk, far_col if filled else None)

    def leg(suffix: str, st: Style, z: int):
        hip, knee, ankle = J["hip"], J["knee" + suffix], J["ankle" + suffix]
        scene.poly(capsule(hip, knee, 0.050 * H, 0.030 * H), st, layer, z, True, "rider:thigh" + suffix)
        sd = (ankle - knee).norm()
        calf = knee + (ankle - knee) * 0.32 - sd.perp() * (0.009 * H)
        scene.poly(_blob([(knee, 0.029 * H), (calf, 0.030 * H), (ankle, 0.018 * H)]), st, layer, z, True,
                   "rider:shank" + suffix)
        shoe_st = st.with_(fill=_mix("#202020", bg, 0.45 if suffix else 0.0)) if filled else st
        scene.poly(_shoe(J, a, suffix), shoe_st, layer, z, True, "rider:shoe" + suffix)

    leg("_far", far, z_far)

    hip, sh = J["hip"], J["shoulder"]
    td = (sh - hip).norm()
    tn = td.perp()                        # towards the rider's back
    tl = hip.dist(sh)
    torso = _blob([(hip + tn * (0.012 * H) - td * (0.010 * H), 0.056 * H),
                   (hip + td * (0.45 * tl) + tn * (0.012 * H), 0.050 * H),
                   (hip + td * (0.78 * tl) - tn * (0.004 * H), 0.060 * H),
                   (sh + td * (0.010 * H) + tn * (0.006 * H), 0.042 * H)])
    scene.poly(torso, near, layer, z_body, True, "rider:torso")
    head = J["head"]
    hu = V.dir(pose.angles["head_up_angle"])
    hf = hu.rot(-90.0)
    neck_base = sh + td * (0.02 * H) + tn * (0.01 * H)
    scene.poly(capsule(neck_base, head - hu * (0.02 * H), 0.027 * H, 0.024 * H), near, layer, z_body, True,
               "rider:neck")
    rx, ry = a["head_rx"], a["head_ry"]
    scene.poly(_head_outline(head, hf, hu, rx, ry), near, layer, z_body, True, "rider:head")
    leg("", near, z_leg)
    scene.poly(capsule(sh, J["elbow"], 0.030 * H, 0.022 * H), near, layer, z_arm, True, "rider:upper_arm")
    scene.poly(capsule(J["elbow"], J["wrist"], 0.021 * H, 0.016 * H), near, layer, z_arm, True, "rider:forearm")
    scene.poly(capsule(J["wrist"], J["hand"], 0.016 * H, 0.020 * H), near, layer, z_arm, True, "rider:hand")
    kind = d.get("helmet", "road")
    if kind != "none":
        hcol = _mix(base, "#ffffff", 0.55) if filled else None
        hst = Style(edge, wk, hcol)
        for poly in _helmet(kind, head, hf, hu, rx, ry, H):
            scene.poly(poly, hst, layer, z_helmet, True, f"rider:helmet:{kind}")


def _register() -> None:
    from ..render import bike_scene
    hooks = bike_scene.EXTRA_BUILDERS
    hooks[:] = [f for f in hooks if (getattr(f, "__module__", None), getattr(f, "__name__", None))
                != (__name__, "draw_rider")]           # idempotent across reloads
    hooks.append(draw_rider)


_register()
