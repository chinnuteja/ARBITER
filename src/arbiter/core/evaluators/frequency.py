"""Frequency stage with accumulator-aware applicability candidate worlds."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any

from arbiter.core.evaluators.common import WorkingState, make_effect
from arbiter.core.models import ClaimLine, Effect, MissingSource, ProcedureHistory
from arbiter.core.spec import ReviewedSpec, Unresolved, pool_candidates, resolve


@dataclass(frozen=True)
class FrequencyResult:
    status: str  # payable | denied | ambiguous | missing
    effects: tuple[Effect, ...]
    ambiguous_rule: dict[str, Any] | None = None
    question: str | None = None


def subtract_months(value: date, months: int) -> date:
    total = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def history_count(
    rule: dict[str, Any],
    line: ClaimLine,
    history: tuple[ProcedureHistory, ...],
    member_id: str,
) -> int:
    codes = set(resolve(rule["scope"]["codes"]))
    basis = resolve(rule["basis"])
    months = resolve(rule["period_months"])
    count = 0
    for event in history:
        if event.member_id != member_id or event.final_status != "paid" or event.code not in codes:
            continue
        if event.date_of_service > line.date_of_service:
            continue
        if basis == "benefit_year":
            if event.date_of_service.year == line.date_of_service.year:
                count += 1
        else:
            threshold = subtract_months(line.date_of_service, int(months))
            if threshold < event.date_of_service <= line.date_of_service:
                count += 1
    return count


def evaluate(
    line: ClaimLine,
    spec: ReviewedSpec,
    history: tuple[ProcedureHistory, ...] | MissingSource,
    state: WorkingState,
    member_id: str,
) -> FrequencyResult:
    rules = sorted(
        spec.matching("frequency", line),
        key=lambda rule: (len(resolve(rule["scope"]["codes"])), rule["rule_id"]),
    )
    if not rules:
        return FrequencyResult("payable", ())
    if isinstance(history, MissingSource):
        rule = rules[0]
        return FrequencyResult(
            "missing",
            (
                make_effect(
                    line.line_id,
                    "frequency",
                    "procedure history is required for this frequency rule",
                    unit="none",
                    before=None,
                    after=None,
                    delta=None,
                    rule=rule,
                ),
            ),
            ambiguous_rule=rule,
            question=(
                "Was D0210 or D0330 already used inside the applicable combined image window?"
                if line.submitted_code in {"D0210", "D0330"}
                else "Was this service already used inside the applicable frequency window?"
            ),
        )

    proposed: list[tuple[str, int]] = []
    effects: list[Effect] = []
    for rule in rules:
        pool = pool_candidates(rule["pool_id"])[0]
        before = history_count(rule, line, history, member_id) + state.frequency.get(pool, 0)
        quantity = int(resolve(rule["quantity"]))
        applicability = resolve(rule["applicability"])
        if isinstance(applicability, Unresolved):
            candidates = set(applicability.field.get("candidate_values", []))
            if candidates == {True, False}:
                present_denies = before >= quantity
                absent_denies = False
                if present_denies != absent_denies:
                    effects.append(
                        make_effect(
                            line.line_id,
                            "frequency",
                            "candidate applicability readings produce different coverage decisions",
                            unit="none",
                            before=None,
                            after=None,
                            delta=None,
                            rule=rule,
                        )
                    )
                    return FrequencyResult(
                        "ambiguous",
                        tuple(effects),
                        ambiguous_rule=rule,
                        question="Does the candidate combined examination pool apply to this third mixed-code exam?",
                    )
                effects.append(
                    make_effect(
                        line.line_id,
                        "frequency",
                        "present and absent applicability worlds agree for this line",
                        unit="count",
                        before=before,
                        after=before + 1,
                        delta=1,
                        rule=rule,
                    )
                )
                proposed.append((pool, 1))
                continue
        if before >= quantity:
            effects.append(
                make_effect(
                    line.line_id,
                    "frequency",
                    "the determined frequency pool is exhausted",
                    unit="count",
                    before=before,
                    after=before,
                    delta=0,
                    rule=rule,
                )
            )
            return FrequencyResult("denied", tuple(effects))
        effects.append(
            make_effect(
                line.line_id,
                "frequency",
                "the service consumes one count in the applicable frequency pool",
                unit="count",
                before=before,
                after=before + 1,
                delta=1,
                rule=rule,
            )
        )
        proposed.append((pool, 1))

    for pool, amount in proposed:
        state.add_frequency(pool, amount)
    return FrequencyResult("payable", tuple(effects))
