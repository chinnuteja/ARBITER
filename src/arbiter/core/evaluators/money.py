"""Benchmark price, deductible, coinsurance, maximum, and reconciliation stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from arbiter.core.evaluators.common import WorkingState, make_effect
from arbiter.core.models import ClaimLine, Effect, MissingSource, PricingContext
from arbiter.core.spec import ReviewedSpec, pool_candidates, resolve


def round_basis_points(
    amount: int,
    basis_points: int,
    *,
    mode: str = "half_up",
    increment_cents: int = 1,
) -> int:
    if increment_cents <= 0:
        raise ValueError("rounding increment must be positive")
    denominator = 10000 * increment_cents
    units, remainder = divmod(amount * basis_points, denominator)
    if mode == "down":
        rounded_units = units
    elif mode == "half_up":
        rounded_units = units + int(remainder * 2 >= denominator)
    elif mode == "half_even":
        rounded_units = units + int(
            remainder * 2 > denominator
            or (remainder * 2 == denominator and units % 2 == 1)
        )
    else:
        raise ValueError(f"unsupported rounding mode: {mode}")
    return rounded_units * increment_cents


@dataclass(frozen=True)
class PriceResult:
    amount: int | None
    effect: Effect
    missing: MissingSource | None = None


def price(line: ClaimLine, benefited_code: str, pricing: PricingContext) -> PriceResult:
    value = next(
        (entry.amount_cents for entry in pricing.entries if entry.code == benefited_code),
        None,
    )
    if isinstance(value, MissingSource) or value is None:
        missing = value or MissingSource(
            required_kind="fee_schedule",
            reason=f"No benchmark entry exists for {benefited_code}",
        )
        return PriceResult(
            None,
            make_effect(
                line.line_id,
                "benchmark_price",
                "the benchmark allowance is unavailable",
                unit="none",
                before=None,
                after=None,
                delta=None,
            ),
            missing,
        )
    return PriceResult(
        int(value),
        make_effect(
            line.line_id,
            "benchmark_price",
            "select the frozen benchmark allowance",
            unit="cents",
            before=None,
            after=int(value),
            delta=None,
            extra_assumptions=(pricing.schedule_id,),
        ),
    )


@dataclass(frozen=True)
class DeductibleResult:
    status: str  # resolved | ambiguous
    post_deductible: int | None
    effect: Effect
    rule: dict[str, Any]
    candidates: tuple[tuple[str, int], ...] = ()  # pool, post-deductible


def deductible(
    line: ClaimLine, allowed: int, spec: ReviewedSpec, state: WorkingState
) -> DeductibleResult:
    rule = spec.matching("deductible", line)[0]
    amount = int(resolve(rule["amount_cents"]))
    pools = pool_candidates(rule["pool_id"])
    outcomes = []
    applied_by_pool: dict[str, int] = {}
    for pool in pools:
        remaining = max(0, amount - state.deductible.get(pool, 0))
        applied = min(allowed, remaining)
        outcomes.append((pool, allowed - applied))
        applied_by_pool[pool] = applied
    posts = {post for _, post in outcomes}
    if len(posts) > 1:
        return DeductibleResult(
            "ambiguous",
            None,
            make_effect(
                line.line_id,
                "deductible",
                "candidate deductible pools produce different post-deductible amounts",
                unit="none",
                before=None,
                after=None,
                delta=None,
                rule=rule,
            ),
            rule,
            tuple(outcomes),
        )
    post = outcomes[0][1]
    applied = allowed - post
    for pool in pools:
        state.add_deductible(pool, applied_by_pool[pool])
    return DeductibleResult(
        "resolved",
        post,
        make_effect(
            line.line_id,
            "deductible",
            "apply the applicable deductible pool",
            unit="cents",
            before=allowed,
            after=post,
            delta=post - allowed,
            rule=rule,
        ),
        rule,
    )


def coinsurance(
    line: ClaimLine, post_deductible: int, spec: ReviewedSpec
) -> tuple[int, Effect, dict[str, Any]]:
    rule = spec.matching("coinsurance", line)[0]
    plan_share = int(resolve(rule["plan_share_basis_points"]))
    policy = resolve(spec.data["rounding_policy"])
    amount = round_basis_points(
        post_deductible,
        plan_share,
        mode=str(policy["mode"]),
        increment_cents=int(policy["increment_cents"]),
    )
    return amount, make_effect(
        line.line_id,
        "coinsurance",
        "apply plan share to the post-deductible allowance",
        unit="cents",
        before=post_deductible,
        after=amount,
        delta=amount - post_deductible,
        rule=rule,
    ), rule


def maximum(
    line: ClaimLine,
    before_maximum: int,
    spec: ReviewedSpec,
    state: WorkingState,
    *,
    commit: bool = True,
) -> tuple[int, Effect, dict[str, Any]]:
    rule = spec.matching("annual_maximum", line)[0]
    cap = int(resolve(rule["amount_cents"]))
    pool = pool_candidates(rule["pool_id"])[0]
    remaining = max(0, cap - state.maximum.get(pool, 0))
    payment = min(before_maximum, remaining)
    if commit:
        state.add_maximum(pool, payment)
    return payment, make_effect(
        line.line_id,
        "annual_maximum",
        "cap plan payment at the remaining annual maximum",
        unit="cents",
        before=before_maximum,
        after=payment,
        delta=payment - before_maximum,
        rule=rule,
    ), rule


def final_effect(
    line: ClaimLine,
    *,
    basis_amount: int,
    member: int,
    denied: bool = False,
) -> Effect:
    return make_effect(
        line.line_id,
        "final_split",
        (
            "frequency limit assigns the benchmark allowance to member cost share"
            if denied
            else "reconcile plan payment and member cost share"
        ),
        unit="cents",
        before=basis_amount,
        after=member,
        delta=member - basis_amount if denied else None,
    )
