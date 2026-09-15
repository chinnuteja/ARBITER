"""Pure, deterministic adjudication pipeline for the case-bounded MVP."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from arbiter.core.evaluators import alternate_benefit, eligibility, frequency, money
from arbiter.core.evaluators.common import WorkingState
from arbiter.core.models import (
    AbstentionLine,
    AccumulatorDelta,
    CoreInput,
    CountPoolDelta,
    Determination,
    Effect,
    ModeledLine,
    MoneyPoolDelta,
)
from arbiter.core.spec import ReviewedSpec, assumptions, clauses, pool_candidates, resolve


ENGINE_VERSION = "arbiter-core-0.1.0"
ORDER_ASSUMPTION = "arbiter-canonical-line-order-v1"
ROUNDING_ASSUMPTION = "arbiter-default-rounding-v1"


def _ordered_lines(core_input: CoreInput, spec: ReviewedSpec):
    policy = resolve(spec.data["line_ordering_policy"])
    keys = tuple(policy["keys"])

    def key(line: Any) -> tuple[Any, ...]:
        return tuple(getattr(line, name) for name in keys)

    return tuple(sorted(core_input.claim.lines, key=key))


def _all_line_abstention(
    core_input: CoreInput,
    spec: ReviewedSpec,
    *,
    kind: str,
    question: str,
) -> Determination:
    lines = tuple(
        AbstentionLine(
            line_id=line.line_id,
            kind=kind,
            stage="entry_guard",
            question=question,
        )
        for line in sorted(
            core_input.claim.lines,
            key=lambda item: (item.date_of_service, item.source_sequence, item.line_id),
        )
    )
    return Determination(
        claim_id=core_input.claim.claim_id,
        spec_id=spec.spec_id,
        engine_version=ENGINE_VERSION,
        result_kind="INCOMPLETE",
        committable=False,
        lines=lines,
        proposed_accumulator_delta=None,
        expected_assumption_ids=(),
    )


def _entry_guard(core_input: CoreInput, spec: ReviewedSpec) -> Determination | None:
    claim = core_input.claim
    snapshot = core_input.accumulators
    if claim.coverage_tier != "self_only":
        return _all_line_abstention(
            core_input,
            spec,
            kind="out_of_scope",
            question="Family and subscriber-level accumulation are outside the MVP.",
        )
    if snapshot.member_id != claim.member_id:
        return _all_line_abstention(
            core_input,
            spec,
            kind="invalid_input",
            question="Accumulator member does not match the claim member.",
        )
    if snapshot.spec_id != spec.spec_id:
        return _all_line_abstention(
            core_input,
            spec,
            kind="invalid_input",
            question="Accumulator spec does not match the selected benefit spec.",
        )
    if snapshot.benefit_year != int(str(spec.data["effective_from"])[:4]):
        return _all_line_abstention(
            core_input,
            spec,
            kind="invalid_input",
            question="Accumulator benefit year does not match the claim service year.",
        )
    pools_by_kind = {
        "deductible": {item.pool_id for item in snapshot.deductible_met},
        "annual_maximum": {item.pool_id for item in snapshot.maximum_used},
        "frequency": {item.pool_id for item in snapshot.frequency_counts},
    }
    for kind, present in pools_by_kind.items():
        required = {
            pool
            for rule in spec.rules_of_kind(kind)
            for pool in pool_candidates(rule["pool_id"])
        }
        missing = sorted(required - present)
        if missing:
            return _all_line_abstention(
                core_input,
                spec,
                kind="invalid_input",
                question=f"Accumulator snapshot is missing required {kind} pools: {', '.join(missing)}.",
            )
    return None


def _abstention(
    line: Any,
    *,
    kind: str,
    stage: str,
    question: str,
    effects: tuple[Effect, ...],
    rule: dict[str, Any] | None = None,
    required_document_kind: str | None = None,
    candidate_outcomes: tuple[dict[str, Any], ...] = (),
) -> AbstentionLine:
    return AbstentionLine(
        line_id=line.line_id,
        kind=kind,
        stage=stage,
        question=question,
        required_document_kind=required_document_kind,
        acceptable_rule_ids=() if rule is None else (rule["rule_id"],),
        acceptable_clause_ids=() if rule is None else clauses(rule),
        candidate_outcomes=candidate_outcomes,
        effects=effects,
    )


def _candidate_modeled(
    line: Any,
    spec: ReviewedSpec,
    state: WorkingState,
    *,
    reading: str,
    benefited_code: str,
    allowed: int,
    post_deductible: int,
    treatment: str | None,
) -> dict[str, Any]:
    plan_before_maximum, _, _ = money.coinsurance(line, post_deductible, spec)
    plan_payment, _, _ = money.maximum(
        line, plan_before_maximum, spec, state, commit=False
    )
    if treatment == "submitted_charge_minus_plan_payment":
        basis = "submitted_charge"
        member = int(line.submitted_cents) - plan_payment
        adjustment = 0
    else:
        basis = "benchmark_allowed"
        member = allowed - plan_payment
        adjustment = None
    return {
        "reading": reading,
        "result_kind": "MODELED",
        "coverage_decision": "payable",
        "line_id": line.line_id,
        "submitted_code": line.submitted_code,
        "submitted_cents": line.submitted_cents,
        "benefited_code": benefited_code,
        "benchmark_allowed_cents": allowed,
        "plan_pays_cents": plan_payment,
        "member_cost_share_cents": member,
        "contractual_adjustment_cents": adjustment,
        "reconciliation_basis": basis,
        "effects": [],
    }


def _frequency_candidates(
    line: Any,
    core_input: CoreInput,
    spec: ReviewedSpec,
    state: WorkingState,
) -> tuple[dict[str, Any], ...]:
    priced = money.price(line, line.submitted_code, core_input.pricing)
    if priced.amount is None:
        return ()
    allowed = priced.amount
    denied = {
        "reading": "combined_pool_applies",
        "result_kind": "MODELED",
        "coverage_decision": "frequency_denied",
        "line_id": line.line_id,
        "submitted_code": line.submitted_code,
        "submitted_cents": line.submitted_cents,
        "benefited_code": line.submitted_code,
        "benchmark_allowed_cents": allowed,
        "plan_pays_cents": 0,
        "member_cost_share_cents": allowed,
        "contractual_adjustment_cents": None,
        "reconciliation_basis": "benchmark_allowed",
        "effects": [],
    }
    candidate_state = deepcopy(state)
    deduct = money.deductible(line, allowed, spec, candidate_state)
    if deduct.status != "resolved":
        return ()
    payable = _candidate_modeled(
        line,
        spec,
        candidate_state,
        reading="individual_limits_only",
        benefited_code=line.submitted_code,
        allowed=allowed,
        post_deductible=int(deduct.post_deductible),
        treatment=None,
    )
    return denied, payable


def _deductible_reading(pool: str) -> str:
    if "abc-combined" in pool:
        return "abc_combined"
    if "class-" in pool:
        return "class_specific"
    return pool


def _denied_line(line: Any, allowed: int, effects: list[Effect]) -> ModeledLine:
    effects.append(money.final_effect(line, basis_amount=allowed, member=allowed, denied=True))
    return ModeledLine(
        coverage_decision="frequency_denied",
        line_id=line.line_id,
        submitted_code=line.submitted_code,
        submitted_cents=line.submitted_cents,
        benefited_code=line.submitted_code,
        benchmark_allowed_cents=allowed,
        plan_pays_cents=0,
        member_cost_share_cents=allowed,
        contractual_adjustment_cents=None,
        reconciliation_basis="benchmark_allowed",
        effects=tuple(effects),
    )


def _modeled_line(
    line: Any,
    *,
    benefited_code: str,
    allowed: int,
    plan_payment: int,
    treatment: str | None,
    effects: list[Effect],
) -> ModeledLine:
    if treatment == "submitted_charge_minus_plan_payment":
        basis = "submitted_charge"
        member = int(line.submitted_cents) - plan_payment
        adjustment = 0
        split_basis = int(line.submitted_cents)
    else:
        basis = "benchmark_allowed"
        member = allowed - plan_payment
        adjustment = None
        split_basis = allowed
    effects.append(money.final_effect(line, basis_amount=split_basis, member=member))
    return ModeledLine(
        coverage_decision="payable",
        line_id=line.line_id,
        submitted_code=line.submitted_code,
        submitted_cents=line.submitted_cents,
        benefited_code=benefited_code,
        benchmark_allowed_cents=allowed,
        plan_pays_cents=plan_payment,
        member_cost_share_cents=member,
        contractual_adjustment_cents=adjustment,
        reconciliation_basis=basis,
        effects=tuple(effects),
    )


def _deltas(state: WorkingState) -> AccumulatorDelta:
    return AccumulatorDelta(
        deductible=tuple(
            MoneyPoolDelta(pool_id=key, delta_cents=value)
            for key, value in sorted(state.deductible_delta.items())
        ),
        maximum=tuple(
            MoneyPoolDelta(pool_id=key, delta_cents=value)
            for key, value in sorted(state.maximum_delta.items())
        ),
        frequency=tuple(
            CountPoolDelta(pool_id=key, delta_count=value)
            for key, value in sorted(state.frequency_delta.items())
        ),
    )


def _expected_assumptions(
    lines: tuple[Any, ...], spec: ReviewedSpec
) -> tuple[str, ...]:
    found = set(assumptions(spec.data["line_ordering_policy"])) or {ORDER_ASSUMPTION}
    monetary = False
    for line in lines:
        if isinstance(line, ModeledLine) or line.candidate_outcomes:
            monetary = True
        for effect in line.effects:
            found.update(effect.assumption_ids)
    if monetary:
        found.update(assumptions(spec.data["rounding_policy"]) or (ROUNDING_ASSUMPTION,))
    return tuple(sorted(found))


def adjudicate(core_input: CoreInput, spec: ReviewedSpec) -> Determination:
    """Adjudicate one immutable input with one reviewed, case-bounded spec."""

    guarded = _entry_guard(core_input, spec)
    if guarded is not None:
        return guarded

    state = WorkingState.from_snapshot(core_input.accumulators)
    results: list[ModeledLine | AbstentionLine] = []

    for line in _ordered_lines(core_input, spec):
        effects: list[Effect] = []
        eligible, eligibility_effect = eligibility.evaluate(
            line,
            spec,
            core_input.claim.coverage_start,
            core_input.claim.coverage_end,
        )
        effects.append(eligibility_effect)
        if not eligible:
            results.append(
                _abstention(
                    line,
                    kind="out_of_scope",
                    stage="eligibility",
                    question="The service date is outside this plan's effective period.",
                    effects=tuple(effects),
                )
            )
            continue

        frequency_result = frequency.evaluate(
            line, spec, core_input.history, state, core_input.claim.member_id
        )
        effects.extend(frequency_result.effects)
        if frequency_result.status == "missing":
            results.append(
                _abstention(
                    line,
                    kind="missing_document",
                    stage="frequency",
                    question=str(frequency_result.question),
                    required_document_kind="claim_history",
                    rule=frequency_result.ambiguous_rule,
                    effects=tuple(effects),
                )
            )
            continue
        if frequency_result.status == "ambiguous":
            results.append(
                _abstention(
                    line,
                    kind="ambiguous_language",
                    stage="frequency",
                    question=str(frequency_result.question),
                    rule=frequency_result.ambiguous_rule,
                    candidate_outcomes=_frequency_candidates(
                        line, core_input, spec, state
                    ),
                    effects=tuple(effects),
                )
            )
            continue
        if frequency_result.status == "denied":
            priced = money.price(line, line.submitted_code, core_input.pricing)
            effects.append(priced.effect)
            if priced.amount is None:
                results.append(
                    _abstention(
                        line,
                        kind="missing_document",
                        stage="benchmark_price",
                        question=f"What benchmark allowance applies to {line.submitted_code}?",
                        required_document_kind=priced.missing.required_kind,
                        effects=tuple(effects),
                    )
                )
            else:
                results.append(_denied_line(line, priced.amount, effects))
            continue

        alternate = alternate_benefit.evaluate(line, spec)
        if alternate.effect is not None:
            effects.append(alternate.effect)
        if alternate.status in {"missing", "ambiguous"}:
            results.append(
                _abstention(
                    line,
                    kind=(
                        "missing_document" if alternate.status == "missing" else "ambiguous_language"
                    ),
                    stage="alternate_benefit",
                    question=str(alternate.question),
                    required_document_kind=alternate.required_document_kind,
                    rule=alternate.rule,
                    effects=tuple(effects),
                )
            )
            continue

        priced = money.price(line, alternate.benefited_code, core_input.pricing)
        effects.append(priced.effect)
        if priced.amount is None:
            results.append(
                _abstention(
                    line,
                    kind="missing_document",
                    stage="benchmark_price",
                    question=f"What benchmark allowance applies to {alternate.benefited_code}?",
                    required_document_kind=priced.missing.required_kind,
                    effects=tuple(effects),
                )
            )
            continue

        deduct = money.deductible(line, priced.amount, spec, state)
        effects.append(deduct.effect)
        if deduct.status == "ambiguous":
            candidates = tuple(
                _candidate_modeled(
                    line,
                    spec,
                    deepcopy(state),
                    reading=_deductible_reading(pool),
                    benefited_code=alternate.benefited_code,
                    allowed=priced.amount,
                    post_deductible=post,
                    treatment=alternate.treatment,
                )
                for pool, post in deduct.candidates
            )
            results.append(
                _abstention(
                    line,
                    kind="ambiguous_language",
                    stage="deductible",
                    question="Did line L1 exhaust a combined ABC deductible or only the Class A deductible?",
                    rule=deduct.rule,
                    candidate_outcomes=candidates,
                    effects=tuple(effects),
                )
            )
            continue

        plan_before_maximum, coin_effect, _ = money.coinsurance(
            line, int(deduct.post_deductible), spec
        )
        effects.append(coin_effect)
        plan_payment, maximum_effect, _ = money.maximum(
            line, plan_before_maximum, spec, state
        )
        effects.append(maximum_effect)
        results.append(
            _modeled_line(
                line,
                benefited_code=alternate.benefited_code,
                allowed=priced.amount,
                plan_payment=plan_payment,
                treatment=alternate.treatment,
                effects=effects,
            )
        )

    line_results = tuple(results)
    complete = all(isinstance(item, ModeledLine) for item in line_results)
    return Determination(
        claim_id=core_input.claim.claim_id,
        spec_id=spec.spec_id,
        engine_version=ENGINE_VERSION,
        result_kind="COMPLETE" if complete else "INCOMPLETE",
        committable=complete,
        lines=line_results,
        proposed_accumulator_delta=_deltas(state) if complete else None,
        expected_assumption_ids=_expected_assumptions(line_results, spec),
    )


adjudicate_case = adjudicate
