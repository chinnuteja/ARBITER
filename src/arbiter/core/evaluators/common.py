"""Shared stage result and effect helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from arbiter.core.models import Effect
from arbiter.core.spec import assumptions, clauses


@dataclass
class WorkingState:
    deductible: dict[str, int]
    maximum: dict[str, int]
    frequency: dict[str, int]
    deductible_delta: dict[str, int] = field(default_factory=dict)
    maximum_delta: dict[str, int] = field(default_factory=dict)
    frequency_delta: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> "WorkingState":
        return cls(
            deductible={item.pool_id: item.amount_cents for item in snapshot.deductible_met},
            maximum={item.pool_id: item.amount_cents for item in snapshot.maximum_used},
            frequency={item.pool_id: item.count for item in snapshot.frequency_counts},
        )

    @staticmethod
    def _advance(target: dict[str, int], delta: dict[str, int], key: str, amount: int) -> None:
        if key not in target:
            raise ValueError(f"accumulator snapshot is missing required pool: {key}")
        target[key] += amount
        if amount:
            delta[key] = delta.get(key, 0) + amount

    def add_deductible(self, pool: str, amount: int) -> None:
        self._advance(self.deductible, self.deductible_delta, pool, amount)

    def add_maximum(self, pool: str, amount: int) -> None:
        self._advance(self.maximum, self.maximum_delta, pool, amount)

    def add_frequency(self, pool: str, amount: int) -> None:
        self._advance(self.frequency, self.frequency_delta, pool, amount)


def make_effect(
    line_id: str,
    stage: str,
    description: str,
    *,
    unit: str,
    before: int | str | bool | None,
    after: int | str | bool | None,
    delta: int | None,
    rule: dict[str, Any] | None = None,
    extra_assumptions: tuple[str, ...] = (),
) -> Effect:
    rule_id = None if rule is None else rule["rule_id"]
    rule_assumptions = () if rule is None else assumptions(rule)
    return Effect(
        effect_id=f"{line_id}:{stage}:{rule_id or 'none'}",
        stage=stage,
        rule_id=rule_id,
        description=description,
        value_unit=unit,
        before_value=before,
        after_value=after,
        delta_value=delta,
        acceptable_clause_ids=() if rule is None else clauses(rule),
        assumption_ids=tuple(sorted(set(rule_assumptions) | set(extra_assumptions))),
    )
