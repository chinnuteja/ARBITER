"""Immutable accumulator application and reversal helpers."""

from __future__ import annotations

from arbiter.core.models import (
    AccumulatorDelta,
    AccumulatorSnapshot,
    CountPoolBalance,
    CountPoolDelta,
    MoneyPoolBalance,
    MoneyPoolDelta,
)


def negate_delta(delta: AccumulatorDelta) -> AccumulatorDelta:
    """Return the exact reversal of a proposed accumulator delta."""

    return AccumulatorDelta(
        deductible=tuple(
            MoneyPoolDelta(pool_id=item.pool_id, delta_cents=-item.delta_cents)
            for item in delta.deductible
        ),
        maximum=tuple(
            MoneyPoolDelta(pool_id=item.pool_id, delta_cents=-item.delta_cents)
            for item in delta.maximum
        ),
        frequency=tuple(
            CountPoolDelta(pool_id=item.pool_id, delta_count=-item.delta_count)
            for item in delta.frequency
        ),
    )


def _apply_money(
    balances: tuple[MoneyPoolBalance, ...], deltas: tuple[MoneyPoolDelta, ...]
) -> tuple[MoneyPoolBalance, ...]:
    values = {item.pool_id: item.amount_cents for item in balances}
    for item in deltas:
        if item.pool_id not in values:
            raise ValueError(f"unknown money accumulator pool: {item.pool_id}")
        after = values[item.pool_id] + item.delta_cents
        if after < 0:
            raise ValueError(f"negative money accumulator balance: {item.pool_id}")
        values[item.pool_id] = after
    return tuple(
        MoneyPoolBalance(pool_id=key, amount_cents=value)
        for key, value in sorted(values.items())
    )


def _apply_count(
    balances: tuple[CountPoolBalance, ...], deltas: tuple[CountPoolDelta, ...]
) -> tuple[CountPoolBalance, ...]:
    values = {item.pool_id: item.count for item in balances}
    for item in deltas:
        if item.pool_id not in values:
            raise ValueError(f"unknown count accumulator pool: {item.pool_id}")
        after = values[item.pool_id] + item.delta_count
        if after < 0:
            raise ValueError(f"negative count accumulator balance: {item.pool_id}")
        values[item.pool_id] = after
    return tuple(
        CountPoolBalance(pool_id=key, count=value)
        for key, value in sorted(values.items())
    )


def apply_delta(
    snapshot: AccumulatorSnapshot, delta: AccumulatorDelta
) -> AccumulatorSnapshot:
    """Apply a validated delta without creating pools or mutating the input."""

    return AccumulatorSnapshot(
        member_id=snapshot.member_id,
        spec_id=snapshot.spec_id,
        benefit_year=snapshot.benefit_year,
        deductible_met=_apply_money(snapshot.deductible_met, delta.deductible),
        maximum_used=_apply_money(snapshot.maximum_used, delta.maximum),
        frequency_counts=_apply_count(snapshot.frequency_counts, delta.frequency),
    )
