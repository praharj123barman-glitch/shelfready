"""Deterministic checks. Importing this package registers every check in REGISTRY.

Module order is the order checks run in (it only affects finding ids):
nutrition, label, claims, approved copy, print readiness, India.
"""

from . import claims_checks, fssai_checks, label_checks, match_checks, nutrition_checks, print_checks
from .registry import REGISTRY, CheckSpec, check

# importing a module is what registers its checks; this tuple also fixes the run order
CHECK_MODULES = (nutrition_checks, label_checks, claims_checks, match_checks, print_checks, fssai_checks)
_ORDER = [m.__name__.rsplit(".", 1)[-1] for m in CHECK_MODULES]
REGISTRY._specs.sort(key=lambda spec: _ORDER.index(spec.module))

__all__ = ["REGISTRY", "CheckSpec", "check"]
