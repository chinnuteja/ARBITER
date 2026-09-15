"""Eligibility stage."""

from __future__ import annotations

from datetime import date

from arbiter.core.evaluators.common import make_effect
from arbiter.core.models import ClaimLine, Effect
from arbiter.core.spec import ReviewedSpec, only, resolve


def evaluate(
    line: ClaimLine,
    spec: ReviewedSpec,
    coverage_start: date,
    coverage_end: date | None,
) -> tuple[bool, Effect]:
    rule = only(spec.rules_of_kind("eligibility"), "eligibility rule")
    start = date.fromisoformat(str(resolve(rule["plan_effective_from"])))
    end = date.fromisoformat(str(resolve(rule["plan_effective_to"])))
    member_end = coverage_end or date.max
    eligible = (
        start <= line.date_of_service <= end
        and coverage_start <= line.date_of_service <= member_end
    )
    return eligible, make_effect(
        line.line_id,
        "eligibility",
        "service date is inside the 2026 plan year" if eligible else "service date is outside the plan year",
        unit="boolean",
        before=None,
        after=eligible,
        delta=None,
        rule=rule,
    )
