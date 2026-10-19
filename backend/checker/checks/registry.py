"""The list of all deterministic checks, built by a decorator.

Writing a check::

    @check("FDA-101.5")                      # the rule(s) this check implements
    def check_manufacturer(ctx: CheckContext) -> list[Finding]:
        ...

``@check`` adds the function to ``REGISTRY``. The engine runs a check only when
one of its rules (or an equivalent, see ``RuleSet.resolve``) is loaded, so the
same carton gets US checks under the FDA pack and India checks under the FSSAI
pack without any if-statements about markets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..models import Finding
from ..rules import RuleSet
from .base import CheckContext

CheckFunction = Callable[[CheckContext], list[Finding]]


@dataclass(frozen=True)
class CheckSpec:
    function: CheckFunction
    rule_ids: tuple[str, ...]

    @property
    def name(self) -> str:
        return self.function.__name__

    @property
    def module(self) -> str:
        return self.function.__module__.rsplit(".", 1)[-1]

    def applies_to(self, rules: RuleSet) -> bool:
        return any(rules.get(rules.resolve(rule_id) or "") for rule_id in self.rule_ids)

    def run(self, ctx: CheckContext) -> list[Finding]:
        return self.function(ctx)


class CheckRegistry:
    def __init__(self) -> None:
        self._specs: list[CheckSpec] = []

    def register(self, *rule_ids: str) -> Callable[[CheckFunction], CheckFunction]:
        if not rule_ids:
            raise ValueError("a check must name at least one rule it implements")

        def add(function: CheckFunction) -> CheckFunction:
            self._specs.append(CheckSpec(function, rule_ids))
            return function  # the plain function stays callable (and testable) on its own

        return add

    def all(self) -> list[CheckSpec]:
        return list(self._specs)

    def applicable(self, rules: RuleSet) -> list[CheckSpec]:
        return [spec for spec in self._specs if spec.applies_to(rules)]


REGISTRY = CheckRegistry()
check = REGISTRY.register
