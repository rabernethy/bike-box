"""Rider anatomy and pose, Fit Advisor (fitting schemes) and centre of mass.

Importing the package registers the "Rider & fit" parameters and adds the
rider and centre-of-mass drawing hooks to ``render.bike_scene.EXTRA_BUILDERS``.
None of these modules import Qt.
"""
from . import expr, rider, com, advisor  # noqa: F401  (registration side effects)
from .advisor import (SCHEMES, Recommendation, apply, evaluate, fit_report, get_scheme, load_schemes, recommend,
                      save_custom_scheme)
from .com import centre_of_mass, component_masses, draw_com
from .rider import Pose, anatomy, draw_rider, estimate_from_basic, solve_pose

__all__ = ["expr", "rider", "com", "advisor", "SCHEMES", "Recommendation", "apply", "evaluate", "fit_report",
           "get_scheme", "load_schemes", "recommend", "save_custom_scheme", "centre_of_mass", "component_masses",
           "draw_com", "Pose", "anatomy", "draw_rider", "estimate_from_basic", "solve_pose"]
