"""Fit Advisor: fitting schemes with customisable formulas.

A *fitting scheme* is a plain dict (so it round-trips through JSON)::

    {"name": "Classic road",
     "description": "...",
     "inputs": {"flexibility": {"label": "...", "default": 3, "min": 1, "max": 5,
                                "param": "fit_flexibility"}},
     "formulas": {                       # evaluated in order
        "saddle_height": {"label": "Saddle height", "expr": "0.883 * inseam",
                          "range": ["0.875 * inseam", "0.893 * inseam"],
                          "unit": "mm", "param": "saddle_height"},
        "saddle_y": {"expr": "...", "hidden": true},     # helper, not reported
        ...}}

Formulas are evaluated with :mod:`framewright.fit.expr` (a whitelisted
evaluator, never ``eval``).  Each formula can use the result of any earlier
formula by its key; range expressions can also use ``value`` (the formula's own
result).  Available variables (see :func:`scheme_variables`):

* rider: ``height inseam torso arm shoulder foot thigh lower_leg upper_arm
  forearm hand forearm_grip head_neck torso_seg mass ankle_height hip_height
  elbow_bend arm_eff hip_dx hip_dy cleat_offset``
* scheme inputs, e.g. ``flexibility`` (1-5), ``style`` (1 recreational,
  2 fitness, 3 competitive), ``uci`` (time trial)
* current design: ``cur_<value>`` for every solved value (``cur_stack``,
  ``cur_saddle_height``, ``cur_hand_x`` ...), current pose angles
  (``cur_knee_extension_bdc``, ``cur_torso_angle``, ``cur_kops`` ...),
  ``cockpit_dx``/``cockpit_dy`` (hands relative to the head-tube top),
  ``hand_bar_dx``/``hand_bar_dy`` (hands relative to the bar clamp),
  ``saddle_ref_to_nose``
* model functions (rider model, current cleat/foot settings):
  ``kops_setback(h)`` saddle setback that puts the knee over the pedal spindle
  at 3 o'clock for saddle height h; ``knee_ext(h, setback)`` knee angle at BDC;
  ``saddle_for_knee(angle, setback)`` saddle height giving that knee angle at BDC.

Custom schemes come from ``design.extras["fit_formulas"]`` (``{name: scheme}``
or a list) and from JSON files in ``~/.config/framewright/fit_schemes/``.  A
custom scheme whose name matches an existing one is merged into it formula by
formula (so a design can, for example, just override the saddle-height
expression of "Classic road"); a formula set to ``null`` removes it.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from ..geometry.solver import Geometry, solve
from ..geometry.vec import V, cosd, sind
from ..model import params as P
from ..model.design import Design
from ..model.units import fmt_angle, fmt_len
from . import expr as X
from .rider import GROUP, _arm_span, _position, anatomy, hip_point, leg_pose, leg_sweep, solve_pose

_ADV = "Fit advisor"
STYLE_VALUES = {"recreational": 1.0, "fitness": 2.0, "competitive": 3.0}

P.register([
    P.ParamDef("fit_scheme", "Fitting scheme", GROUP, _ADV, P.STR, "Classic road", morph=False,
               help="Name of the fitting scheme used by the Fit Advisor"),
    P.ParamDef("fit_flexibility", "Flexibility", GROUP, _ADV, P.INT, 3, "", 1, 5, 1,
               help="1 = stiff (cannot touch toes) … 5 = very flexible (palms on the floor)"),
    P.ParamDef("fit_style", "Riding style", GROUP, _ADV, P.CHOICE, "fitness",
               choices=(("recreational", "Recreational / comfort"), ("fitness", "Fitness / sportive"),
                        ("competitive", "Competitive / racing")), morph=False),
])


@dataclass
class Recommendation:
    key: str
    label: str
    value: float
    low: float
    high: float
    unit: str
    param: str | None
    current: float | None = None

    @property
    def in_range(self) -> bool | None:
        if self.current is None or self.current != self.current:
            return None
        return self.low - 1e-9 <= self.current <= self.high + 1e-9


# --------------------------------------------------------------------------
# built-in schemes
# --------------------------------------------------------------------------
_INPUTS = {
    "flexibility": {"label": "Flexibility (1 stiff … 5 very flexible)", "default": 3, "min": 1, "max": 5,
                    "param": "fit_flexibility"},
    "style": {"label": "Riding style (1 recreational, 2 fitness, 3 competitive)", "default": 2, "min": 1, "max": 3,
              "param": "fit_style", "map": STYLE_VALUES},
}


def _f(label, expr, rng=None, unit="mm", param=None, hidden=False) -> dict:
    out: dict[str, Any] = {"label": label, "expr": expr, "unit": unit, "param": param}
    if rng:
        out["range"] = list(rng)
    if hidden:
        out["hidden"] = True
    return out


def _saddle_block(height_expr, height_rng, setback_expr) -> dict:
    return {
        "saddle_height": _f("Saddle height (BB to saddle top)", height_expr, height_rng, param="saddle_height"),
        "saddle_setback": _f("Saddle setback (reference point behind BB)", setback_expr,
                             ("value - 10", "value + 15"), param="saddle_setback"),
        "seat_angle_eff": _f("Effective seat angle", "acos(clamp(saddle_setback / saddle_height, -1, 1))",
                             ("acos(clamp((saddle_setback + 15) / saddle_height, -1, 1))",
                              "acos(clamp((saddle_setback - 10) / saddle_height, -1, 1))"), "deg"),
        "knee_extension": _f("Knee angle at bottom of stroke (rider model)",
                             "knee_ext(saddle_height, saddle_setback)", ("145", "155"), "deg"),
        "saddle_x": _f("Saddle X", "-saddle_setback", hidden=True),
        "saddle_y": _f("Saddle Y", "sqrt(max(saddle_height ** 2 - saddle_setback ** 2, 0))", hidden=True),
    }


def _upper_block(torso_expr, shoulder_expr, elbow_expr="180 - elbow_bend") -> dict:
    return {
        "torso_angle": _f("Torso angle (hip to shoulder, from horizontal)", torso_expr,
                          ("value - 5", "value + 5"), "deg"),
        "shoulder_angle": _f("Shoulder angle (torso to upper arm)", shoulder_expr, ("value - 5", "value + 5"), "deg"),
        "elbow_angle": _f("Elbow angle", elbow_expr, ("value - 10", "min(value + 10, 180)"), "deg"),
        "shoulder_x": _f("Shoulder X", "saddle_x + hip_dx + torso_seg * cos(torso_angle)", hidden=True),
        "shoulder_y": _f("Shoulder Y", "saddle_y + hip_dy + torso_seg * sin(torso_angle)", hidden=True),
        "upper_arm_dir": _f("Upper arm direction", "torso_angle + 180 + shoulder_angle", unit="deg", hidden=True),
        "hand_x": _f("Hand position X (from BB)",
                     "shoulder_x + upper_arm * cos(upper_arm_dir)"
                     " + forearm_grip * cos(upper_arm_dir + 180 - elbow_angle)", ("value - 15", "value + 15")),
        "hand_y": _f("Hand position Y (from BB)",
                     "shoulder_y + upper_arm * sin(upper_arm_dir)"
                     " + forearm_grip * sin(upper_arm_dir + 180 - elbow_angle)", ("value - 15", "value + 15")),
        "stack": _f("Frame stack (with the current cockpit)", "hand_y - cockpit_dy", ("value - 10", "value + 10"),
                    param="stack"),
        "reach": _f("Frame reach (with the current cockpit)", "hand_x - cockpit_dx", ("value - 10", "value + 10"),
                    param="reach"),
        "saddle_hand_drop": _f("Saddle to hand drop", "saddle_y - hand_y", ("value - 15", "value + 15")),
        "saddle_bar_drop": _f("Saddle to bar drop", "saddle_y - (hand_y - hand_bar_dy)", ("value - 15", "value + 15")),
        "nose_to_bar": _f("Saddle nose to bar",
                          "sqrt((hand_x - hand_bar_dx - saddle_x - saddle_ref_to_nose) ** 2"
                          " + (hand_y - hand_bar_dy - saddle_y) ** 2)", ("value - 15", "value + 15")),
    }


def _frame_block(crank_expr, st_k, standover_clear, bar_expr) -> dict:
    return {
        "crank_length": _f("Crank length", crank_expr, ("value - 5", "value + 2.5"), param="crank_length"),
        "seat_tube_length": _f("Seat tube length (centre to top)", f"{st_k} * inseam", ("value - 20", "value + 20"),
                               param="seat_tube_length"),
        "max_standover": _f("Standover height (maximum)", f"inseam - {standover_clear}",
                            ("value - 60", "value")),
        "bar_width": _f("Handlebar width", bar_expr, ("value - 20", "value + 20"), param="bar_width"),
    }


def _scheme(name, description, saddle, upper, frame, inputs=None) -> dict:
    formulas: dict[str, Any] = {}
    for block in (saddle, upper, frame):
        formulas.update(block)
    return {"name": name, "description": description, "builtin": True,
            "inputs": copy.deepcopy(inputs or _INPUTS), "formulas": formulas}


_ROAD_CRANK = "clamp(round(0.205 * inseam / 2.5) * 2.5, 150, 180)"
BUILTIN_SCHEMES: list[dict] = [
    _scheme("Classic road",
            "Classic road (LeMond saddle height = 0.883 × inseam, knee over pedal spindle, "
            "seat tube 0.65 × inseam)",
            _saddle_block("0.883 * inseam", ("0.875 * inseam", "0.893 * inseam"), "kops_setback(saddle_height)"),
            _upper_block("clamp(47 - 4 * (flexibility - 3) - 3 * (style - 2), 28, 62)", "75"),
            _frame_block(_ROAD_CRANK, 0.65, 25, "clamp(round(shoulder / 20) * 20, 360, 480)")),
    _scheme("Endurance / comfort",
            "Endurance and comfort: slightly lower saddle (0.875 × inseam), more upright torso, "
            "shorter cranks, taller front end",
            _saddle_block("0.875 * inseam", ("0.865 * inseam", "0.885 * inseam"), "kops_setback(saddle_height) + 5"),
            _upper_block("clamp(52 - 3 * (flexibility - 3) - 2 * (style - 2), 38, 70)", "74"),
            _frame_block("clamp(round(0.200 * inseam / 2.5) * 2.5, 150, 177.5)", 0.66, 30,
                         "clamp(round((shoulder + 20) / 20) * 20, 380, 500)")),
    _scheme("Gravel & touring",
            "Gravel and touring: stable, upright position, wider (flared) bars, more standover clearance",
            _saddle_block("0.877 * inseam", ("0.865 * inseam", "0.887 * inseam"), "kops_setback(saddle_height) + 5"),
            _upper_block("clamp(51 - 3 * (flexibility - 3) - 2 * (style - 2), 35, 68)", "74"),
            _frame_block("clamp(round(0.200 * inseam / 2.5) * 2.5, 150, 177.5)", 0.63, 50,
                         "clamp(round((shoulder + 40) / 20) * 20, 400, 540)")),
    _scheme("Mountain",
            "Mountain bike: pedalling saddle height 0.877 × inseam, steeper effective seat angle, "
            "wide riser bar, short seat tube for a dropper post",
            _saddle_block("0.877 * inseam", ("0.865 * inseam", "0.887 * inseam"), "kops_setback(saddle_height) - 10"),
            _upper_block("clamp(50 - 2 * (flexibility - 3) - 2 * (style - 2), 38, 65)", "68"),
            _frame_block("clamp(round(0.200 * inseam / 2.5) * 2.5, 150, 175)", 0.55, 80,
                         "clamp(round(shoulder * 1.85 / 10) * 10, 680, 800)")),
    _scheme("Time trial",
            "Time trial / triathlon: saddle rotated forward and up (0.89 × inseam), flat torso on the aero "
            "extensions with elbows at ≈ 95°, shorter cranks. 'uci' = 1 keeps the saddle nose 50 mm behind the BB",
            _saddle_block("0.890 * inseam", ("0.880 * inseam", "0.900 * inseam"),
                          "max(kops_setback(saddle_height) - 50, uci * (50 + saddle_ref_to_nose))"),
            _upper_block("clamp(15 - 3 * (flexibility - 3) - 2 * (style - 2), 3, 30)", "90", "95"),
            _frame_block("clamp(round(0.195 * inseam / 2.5) * 2.5, 145, 175)", 0.64, 25,
                         "clamp(round(shoulder / 20) * 20, 360, 440)"),
            inputs={**_INPUTS, "uci": {"label": "Follow UCI saddle setback rule (1 = yes, 0 = no)", "default": 1,
                                       "min": 0, "max": 1}}),
    _scheme("Knee angle (Holmes)",
            "Saddle height from knee flexion: 25-35° (knee angle 145-155°) at the bottom of the stroke, "
            "computed with the rider model and current cleat / foot settings",
            {"saddle_setback": _f("Saddle setback (reference point behind BB)",
                                  "kops_setback(saddle_for_knee(150, kops_setback(0.883 * inseam)))",
                                  ("value - 10", "value + 15"), param="saddle_setback"),
             **{k: v for k, v in _saddle_block("saddle_for_knee(150, saddle_setback)",
                                               ("saddle_for_knee(145, saddle_setback)",
                                                "saddle_for_knee(155, saddle_setback)"),
                                               "saddle_setback").items() if k != "saddle_setback"}},
            _upper_block("clamp(47 - 4 * (flexibility - 3) - 3 * (style - 2), 28, 62)", "75"),
            _frame_block(_ROAD_CRANK, 0.65, 25, "clamp(round(shoulder / 20) * 20, 360, 480)")),
]
SCHEMES: dict[str, dict] = {s["name"]: s for s in BUILTIN_SCHEMES}


# --------------------------------------------------------------------------
# loading / saving custom schemes
# --------------------------------------------------------------------------
def user_scheme_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "framewright" / "fit_schemes"


def validate_scheme(scheme: Any) -> list[str]:
    """Problems with a scheme dict (empty list = usable)."""
    errs: list[str] = []
    if not isinstance(scheme, dict):
        return ["scheme must be an object"]
    if not str(scheme.get("name", "")).strip():
        errs.append("scheme has no name")
    formulas = scheme.get("formulas")
    if not isinstance(formulas, dict) or not formulas:
        return errs + ["scheme has no formulas"]
    for key, spec in formulas.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key) or "__" in key:
            errs.append(f"invalid formula key {key!r}")
            continue
        if spec is None:
            continue
        if not isinstance(spec, dict) or not isinstance(spec.get("expr"), str):
            errs.append(f"{key}: missing 'expr'")
            continue
        for e in X.validate(spec["expr"], functions=_FUNC_NAMES):
            errs.append(f"{key}: {e}")
        rng = spec.get("range")
        if rng is not None:
            if not isinstance(rng, (list, tuple)) or len(rng) != 2:
                errs.append(f"{key}: 'range' must be [low, high]")
            else:
                for r in rng:
                    for e in X.validate(str(r), functions=_FUNC_NAMES):
                        errs.append(f"{key} range: {e}")
        param = spec.get("param")
        if param is not None and not isinstance(param, str):
            errs.append(f"{key}: 'param' must be a parameter key or null")
    inputs = scheme.get("inputs", {})
    if not isinstance(inputs, dict):
        errs.append("'inputs' must be an object")
    return errs


def _merge(base: dict, custom: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in custom.items():
        if k in ("formulas", "inputs") and isinstance(v, dict):
            target = out.setdefault(k, {})
            for fk, fv in v.items():
                if fv is None:
                    target.pop(fk, None)
                elif isinstance(fv, dict) and isinstance(target.get(fk), dict):
                    target[fk] = {**target[fk], **copy.deepcopy(fv)}
                else:
                    target[fk] = copy.deepcopy(fv)
        else:
            out[k] = copy.deepcopy(v)
    out["builtin"] = False
    return out


def _iter_custom(obj: Any) -> Iterable[dict]:
    if isinstance(obj, list):
        for s in obj:
            if isinstance(s, dict):
                yield s
    elif isinstance(obj, dict):
        if "formulas" in obj and "name" in obj:
            yield obj
        else:                                   # {name: scheme}
            for name, s in obj.items():
                if isinstance(s, dict):
                    yield {"name": name, **s} if "name" not in s else s


def load_schemes(design: Design | None = None, directory: str | Path | None = None) -> dict[str, dict]:
    """Built-in schemes merged with JSON files in the user scheme directory and
    the design's ``extras["fit_formulas"]`` (later sources win).  Invalid
    custom schemes are skipped.  Nothing is created on disk."""
    schemes = {name: copy.deepcopy(s) for name, s in SCHEMES.items()}
    sources: list[Any] = []
    folder = Path(directory) if directory is not None else user_scheme_dir()
    try:
        files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    except OSError:
        files = []
    for f in files:
        try:
            sources.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    if design is not None:
        sources.append(design.extras.get("fit_formulas") or {})
    for src in sources:
        for custom in _iter_custom(src):
            name = str(custom.get("name", "")).strip()
            if not name:
                continue
            merged = _merge(schemes[name], custom) if name in schemes else _merge({}, custom)
            if not validate_scheme(merged):
                schemes[name] = merged
    return schemes


def save_custom_scheme(scheme: dict, path: str | Path | None = None) -> Path:
    """Validate and write ``scheme`` as JSON.  Default location:
    ``<user scheme dir>/<name>.json`` (the directory is created on demand)."""
    errs = validate_scheme(scheme)
    if errs:
        raise ValueError("invalid fit scheme: " + "; ".join(errs))
    if path is None:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", str(scheme["name"])).strip("_").lower() or "scheme"
        path = user_scheme_dir() / f"{slug}.json"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in scheme.items() if k != "builtin"}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def get_scheme(design: Design, name: str | None = None) -> dict:
    """The scheme called ``name`` (default: the design's ``fit_scheme``)."""
    schemes = load_schemes(design)
    name = name or str(design.get("fit_scheme", "") or "")
    return schemes.get(name) or schemes["Classic road"]


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------
_FUNC_NAMES = {"kops_setback": None, "knee_ext": None, "saddle_for_knee": None}


def _bisect(f: Callable[[float], float], lo: float, hi: float, iters: int = 40) -> float:
    flo, fhi = f(lo), f(hi)
    if flo == 0:
        return lo
    if fhi == 0 or (flo > 0) == (fhi > 0):        # no sign change: closest end
        return lo if abs(flo) < abs(fhi) else hi
    for _ in range(iters):
        mid = (lo + hi) / 2
        fm = f(mid)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
        if hi - lo < 0.01:
            break
    return (lo + hi) / 2


def model_functions(design: Design) -> dict[str, Callable[..., float]]:
    """Trusted rider-model helpers exposed to formulas."""
    a = anatomy(design)
    pos = _position(design)

    def hip_for(h: float, setback: float) -> V:
        y = math.sqrt(max(h * h - setback * setback, 1.0))
        return hip_point(V(-setback, y), design, a)

    def knee_ext(h: float, setback: float) -> float:
        return leg_sweep(hip_for(h, setback), a, pos, step=5.0)["knee_max"]

    def kops(h: float, setback: float) -> float:
        j, _ = leg_pose(hip_for(h, setback), 0.0, a, pos)
        return j["knee"].x - j["pedal"].x

    def kops_setback(h: float) -> float:
        return _bisect(lambda s: kops(h, s), -0.3 * h, 0.6 * h)

    def saddle_for_knee(angle: float, setback: float) -> float:
        return _bisect(lambda h: knee_ext(h, setback) - angle, 0.55 * a["inseam"], 1.15 * a["inseam"])

    return {"kops_setback": kops_setback, "knee_ext": knee_ext, "saddle_for_knee": saddle_for_knee}


def _input_value(design: Design, key: str, spec: dict) -> float:
    fi = design.extras.get("fit_inputs") or {}
    if isinstance(fi, dict) and key in fi:
        try:
            return float(fi[key])
        except (TypeError, ValueError):
            pass
    pkey = spec.get("param")
    if pkey and P.has(pkey):
        v = design[pkey]
        mapping = spec.get("map")
        if isinstance(mapping, dict) and v in mapping:
            return float(mapping[v])
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    try:
        return float(spec.get("default", 0.0))
    except (TypeError, ValueError):
        return 0.0


def scheme_variables(design: Design, g: Geometry | None = None, scheme: dict | None = None,
                     pose=None) -> dict[str, float]:
    """Variables available to fit formulas (see the module docstring)."""
    g = g or solve(design)
    a = anatomy(design)
    pose = pose or solve_pose(g)
    v: dict[str, float] = {}
    for k in ("height", "inseam", "torso", "arm", "shoulder", "foot", "thigh", "lower_leg", "upper_arm", "forearm",
              "hand", "head_neck", "torso_seg", "mass", "ankle_height", "hip_height", "hip_above_saddle"):
        v[k] = float(a[k])
    v["forearm_grip"] = a["forearm"] + a["hand"]
    v["elbow_bend"] = design.f("elbow_bend")
    v["arm_eff"] = _arm_span(a["upper_arm"], v["forearm_grip"], 180.0 - v["elbow_bend"])
    v["cleat_offset"] = design.f("cleat_offset")
    tilt = design.f("saddle_tilt")
    off = V(cosd(tilt), sind(tilt)) * design.f("hip_forward") + V(-sind(tilt), cosd(tilt)) * a["hip_above_saddle"]
    v["hip_dx"], v["hip_dy"] = off.x, off.y
    v["saddle_ref_to_nose"] = design.f("saddle_ref_to_nose")
    for k, val in g.v.items():
        if isinstance(val, (int, float)) and math.isfinite(val):
            v["cur_" + k] = float(val)
    for k, val in pose.angles.items():
        v["cur_" + k] = float(val)
    v["cockpit_dx"] = g.v["hand_x"] - g.v["reach"]
    v["cockpit_dy"] = g.v["hand_y"] - g.v["stack"]
    v["hand_bar_dx"] = g.v["hand_x"] - g.v["bar_x"]
    v["hand_bar_dy"] = g.v["hand_y"] - g.v["bar_y"]
    inputs = dict(_INPUTS)
    if scheme:
        inputs.update(scheme.get("inputs") or {})
    for key, spec in inputs.items():
        if isinstance(spec, dict):
            v[key] = _input_value(design, key, spec)
    return v


_CURRENT_ALIAS = {"seat_tube_length": "seat_tube_ct", "max_standover": "standover",
                  "knee_extension": "knee_extension_bdc"}


def _current(key: str, spec: dict, g: Geometry, pose, variables: dict) -> float | None:
    if isinstance(spec.get("current"), str):
        try:
            return X.evaluate(spec["current"], variables)
        except X.ExprError:
            return None
    k = _CURRENT_ALIAS.get(key, key)
    if k in g.v:
        return float(g.v[k])
    if k in pose.angles:
        return float(pose.angles[k])
    param = spec.get("param") or key
    if P.has(param) and P.get(param).kind in (P.FLOAT, P.INT):
        return float(g.design[param])
    return None


def evaluate(scheme: dict, design: Design, errors: list[str] | None = None) -> list[Recommendation]:
    """Evaluate a scheme's formulas for ``design``; failing formulas are skipped
    (their messages are appended to ``errors`` when given)."""
    g = solve(design)
    pose = solve_pose(g)
    variables = scheme_variables(design, g, scheme, pose)
    funcs = model_functions(design)
    recs: list[Recommendation] = []
    for key, spec in (scheme.get("formulas") or {}).items():
        if not isinstance(spec, dict) or "expr" not in spec:
            continue
        try:
            value = X.evaluate(str(spec["expr"]), variables, funcs)
        except X.ExprError as exc:
            if errors is not None:
                errors.append(f"{key}: {exc}")
            continue
        variables[key] = value
        lo = hi = value
        rng = spec.get("range")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            local = {**variables, "value": value}
            try:
                lo = X.evaluate(str(rng[0]), local, funcs)
                hi = X.evaluate(str(rng[1]), local, funcs)
            except X.ExprError as exc:
                if errors is not None:
                    errors.append(f"{key} range: {exc}")
                lo = hi = value
            if lo > hi:
                lo, hi = hi, lo
        if spec.get("hidden"):
            continue
        recs.append(Recommendation(key, str(spec.get("label") or key), value, lo, hi, str(spec.get("unit", "")),
                                   spec.get("param"), _current(key, spec, g, pose, variables)))
    return recs


def recommend(design: Design, name: str | None = None, errors: list[str] | None = None) -> list[Recommendation]:
    """Evaluate the design's selected fitting scheme (or ``name``)."""
    return evaluate(get_scheme(design, name), design, errors)


# --------------------------------------------------------------------------
# applying recommendations
# --------------------------------------------------------------------------
def _set(design: Design, key: str, value: Any, changed: list[str]) -> None:
    before = design.get(key)
    after = design.set(key, value)
    if before != after and key not in changed:
        changed.append(key)


def _apply_saddle_height(design: Design, h: float, changed: list[str]) -> None:
    if design["saddle_mode"] == "xy":
        S = solve(design).p["saddle"]
        ang = math.atan2(S.y, -S.x) if S.length() > 1 else math.radians(design.f("seat_tube_angle"))
        _set(design, "saddle_x", -h * math.cos(ang), changed)
        _set(design, "saddle_y", h * math.sin(ang), changed)
    else:
        _set(design, "saddle_height", h, changed)


def _apply_saddle_setback(design: Design, s: float, changed: list[str]) -> None:
    if design["saddle_mode"] == "xy":
        h = solve(design).p["saddle"].length()
        _set(design, "saddle_x", -s, changed)
        _set(design, "saddle_y", math.sqrt(max(h * h - s * s, 1.0)), changed)
        return
    h = design.f("saddle_height")
    angle = math.degrees(math.acos(max(-1.0, min(1.0, s / h))))
    if design["seat_angle_source"] == "seat_tube" and abs(angle - design.f("seat_tube_angle")) < 1e-3:
        return
    _set(design, "seat_angle_source", "custom", changed)
    _set(design, "seat_angle_eff", angle, changed)


def _apply_front(design: Design, which: str, target: float, changed: list[str]) -> None:
    """Hit a target stack or reach whatever the front-end input modes are."""
    for _ in range(6):
        g = solve(design)
        delta = target - g.v[which]
        if abs(delta) < 0.05:
            return
        if which == "stack":
            mode = design["front_v_mode"]
            if mode == "stack":
                _set(design, "stack", target, changed)
            elif mode == "bar_y":
                _set(design, "bar_y", design.f("bar_y") + delta, changed)
            else:
                _set(design, "head_tube_length", design.f("head_tube_length") + delta / max(g.u.y, 0.2), changed)
        else:
            mode = design["front_h_mode"]
            if mode == "reach":
                _set(design, "reach", target, changed)
            elif mode == "front_center":
                fa = g.p["front_axle"]
                _set(design, "front_center", math.hypot(fa.x + delta, fa.y), changed)
            elif mode == "ett":
                _set(design, "top_tube_effective", design.f("top_tube_effective") + delta, changed)
            elif mode == "wheelbase":
                _set(design, "wheelbase", design.f("wheelbase") + delta, changed)
            elif mode == "bar_x":
                _set(design, "bar_x", design.f("bar_x") + delta, changed)
            else:
                return


def _apply_seat_tube(design: Design, ct: float, changed: list[str]) -> None:
    if design["st_length_mode"] == "cc":
        g = solve(design)
        ct -= g.v["seat_tube_ct"] - g.v["seat_tube_cc"]
    _set(design, "seat_tube_length", ct, changed)


_APPLY_ORDER = ("saddle_height", "saddle_setback", "stack", "reach")


def apply(recs: Iterable[Recommendation], design: Design, keys: Iterable[str] | None = None) -> list[str]:
    """Write recommendations that map to design parameters into ``design``.

    ``keys`` limits which recommendations (by ``Recommendation.key``) are
    applied.  Front-end and saddle targets are converted to whatever input
    mode the design uses (e.g. a stack target changes the head-tube length
    when the front end is defined by head-tube length).  Returns the
    parameter keys that changed."""
    wanted = set(keys) if keys is not None else None
    todo = [r for r in recs if r.param and (wanted is None or r.key in wanted) and r.value == r.value]
    todo.sort(key=lambda r: _APPLY_ORDER.index(r.param) if r.param in _APPLY_ORDER else len(_APPLY_ORDER))
    changed: list[str] = []
    for r in todo:
        p = r.param
        if p == "saddle_height":
            _apply_saddle_height(design, r.value, changed)
        elif p == "saddle_setback":
            _apply_saddle_setback(design, r.value, changed)
        elif p in ("stack", "reach"):
            _apply_front(design, p, r.value, changed)
        elif p == "seat_tube_length":
            _apply_seat_tube(design, r.value, changed)
        elif p == "seat_angle_eff":
            _set(design, "seat_angle_source", "custom", changed)
            _set(design, "seat_angle_eff", r.value, changed)
        elif P.has(p) and P.get(p).kind in (P.FLOAT, P.INT):
            _set(design, p, r.value, changed)
    return changed


# --------------------------------------------------------------------------
# report of the current fit
# --------------------------------------------------------------------------
def fit_report(g: Geometry) -> list[tuple[str, str]]:
    """Current fit numbers as (label, formatted value) rows."""
    d = g.design
    u = d.get("units", "mm")
    a = anatomy(d)
    pose = solve_pose(g)
    A = pose.angles
    v = g.v
    L = lambda x: fmt_len(x, u, suffix=True)
    rows = [
        ("Rider height", L(a["height"])),
        ("Inseam", L(a["inseam"])),
        ("Rider mass", f"{a['mass']:.1f} kg"),
        ("Saddle height (BB to top)", L(v["saddle_height"])),
        ("Saddle height / inseam", f"{v['saddle_height'] / a['inseam']:.3f} (LeMond 0.883)"),
        ("Saddle setback", L(v["saddle_setback"])),
        ("Saddle nose behind BB", L(v["saddle_nose_setback"])),
        ("Effective seat angle", fmt_angle(v["seat_angle_eff"])),
        ("Saddle to bar drop", L(v["saddle_bar_drop"])),
        ("Saddle to hand drop", L(v["saddle_hand_drop"])),
        ("Saddle nose to bar", L(v["nose_to_bar"])),
        ("Saddle nose to hands", L(v["nose_to_hand"])),
        ("Saddle to hands", L(A["saddle_to_hand_reach"])),
        ("Hand position X / Y", f"{fmt_len(v['hand_x'], u)} / {fmt_len(v['hand_y'], u)}"),
        ("Stack / reach", f"{fmt_len(v['stack'], u)} / {fmt_len(v['reach'], u)}"),
        ("Crank length", L(v["crank_length"])),
        ("Knee angle at bottom of stroke", f"{fmt_angle(A['knee_extension_bdc'])} "
                                           f"(flexion {fmt_angle(A['knee_flexion_bdc'])})"),
        ("Knee angle at top of stroke", fmt_angle(A["knee_flexion_tdc"])),
        ("Knee angle (shown crank position)", fmt_angle(A["knee_angle"])),
        ("Minimum hip angle", fmt_angle(A["hip_angle_min"])),
        ("Torso angle", fmt_angle(A["torso_angle"])),
        ("Shoulder angle", fmt_angle(A["shoulder_angle"])),
        ("Elbow angle", fmt_angle(A["elbow_angle"])),
        ("Knee ahead of pedal spindle (KOPS)", L(A["kops"])),
    ]
    so = v.get("standover", float("nan"))
    if so == so:
        rows.append(("Standover clearance", L(a["inseam"] - so)))
    try:
        from .com import centre_of_mass
        c, total, front = centre_of_mass(g, True)
        rows.append(("Bike + rider mass", f"{total / 1000.0:.1f} kg"))
        rows.append(("Weight on front / rear wheel", f"{front * 100:.0f} % / {(1 - front) * 100:.0f} %"))
    except (KeyError, ValueError, ZeroDivisionError):
        pass
    rows += [("Warning", w) for w in pose.warnings]
    return rows


def recommendations_table(recs: Iterable[Recommendation]) -> list[dict[str, Any]]:
    """Plain dicts (for JSON / CSV / GUI tables)."""
    return [asdict(r) for r in recs]
