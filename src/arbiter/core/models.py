"""Immutable runtime inputs and outputs for the deterministic core."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MissingSource(FrozenModel):
    state: Literal["missing_source"] = "missing_source"
    required_kind: str
    reason: str


class ClaimLine(FrozenModel):
    line_id: str
    source_sequence: int = Field(ge=0)
    submitted_code: str
    service_class: Literal["A", "B", "C", "D"]
    date_of_service: date
    network_state: Literal["in_network", "out_of_network"]
    submitted_cents: int | None = Field(default=None, ge=0)
    tooth: str | None = None
    quadrant: str | None = None
    arch: str | None = None


class Claim(FrozenModel):
    claim_id: str
    member_id: str
    coverage_tier: Literal["self_only", "self_plus_one", "self_and_family"]
    coverage_start: date
    coverage_end: date | None
    lines: tuple[ClaimLine, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_lines(self) -> "Claim":
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ValueError("duplicate line_id")
        if len({line.source_sequence for line in self.lines}) != len(self.lines):
            raise ValueError("duplicate source_sequence")
        return self


class ProcedureHistory(FrozenModel):
    member_id: str
    code: str
    date_of_service: date
    tooth: str | None
    quadrant: str | None
    arch: str | None
    final_status: Literal["paid", "denied", "reversed", "pending"]


class MoneyPoolBalance(FrozenModel):
    pool_id: str
    amount_cents: int = Field(ge=0)


class CountPoolBalance(FrozenModel):
    pool_id: str
    count: int = Field(ge=0)


class AccumulatorSnapshot(FrozenModel):
    member_id: str
    spec_id: str
    benefit_year: int
    deductible_met: tuple[MoneyPoolBalance, ...] = ()
    maximum_used: tuple[MoneyPoolBalance, ...] = ()
    frequency_counts: tuple[CountPoolBalance, ...] = ()

    @model_validator(mode="after")
    def canonical_pools(self) -> "AccumulatorSnapshot":
        for name in ("deductible_met", "maximum_used", "frequency_counts"):
            values = [item.pool_id for item in getattr(self, name)]
            if values != sorted(values) or len(values) != len(set(values)):
                raise ValueError(f"{name} must be strictly sorted and unique")
        return self


class PriceEntry(FrozenModel):
    code: str
    amount_cents: int | MissingSource


class PricingContext(FrozenModel):
    kind: Literal["benchmark"]
    schedule_id: str
    entries: tuple[PriceEntry, ...]

    @model_validator(mode="after")
    def canonical_entries(self) -> "PricingContext":
        codes = [entry.code for entry in self.entries]
        if codes != sorted(codes) or len(codes) != len(set(codes)):
            raise ValueError("pricing entries must be strictly sorted and unique")
        return self


class Effect(FrozenModel):
    effect_id: str
    stage: Literal[
        "eligibility",
        "frequency",
        "alternate_benefit",
        "benchmark_price",
        "deductible",
        "coinsurance",
        "annual_maximum",
        "final_split",
    ]
    rule_id: str | None
    description: str
    value_unit: Literal["none", "cents", "count", "code", "date", "boolean"]
    before_value: int | str | bool | None
    after_value: int | str | bool | None
    delta_value: int | None
    acceptable_clause_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()


class ModeledLine(FrozenModel):
    result_kind: Literal["MODELED"] = "MODELED"
    coverage_decision: Literal["payable", "frequency_denied"]
    line_id: str
    submitted_code: str
    submitted_cents: int | None
    benefited_code: str
    benchmark_allowed_cents: int = Field(ge=0)
    plan_pays_cents: int = Field(ge=0)
    member_cost_share_cents: int = Field(ge=0)
    contractual_adjustment_cents: int | None
    reconciliation_basis: Literal["benchmark_allowed", "submitted_charge"]
    effects: tuple[Effect, ...]

    @model_validator(mode="after")
    def reconciles(self) -> "ModeledLine":
        if self.reconciliation_basis == "benchmark_allowed":
            if self.benchmark_allowed_cents != self.plan_pays_cents + self.member_cost_share_cents:
                raise ValueError("benchmark line does not reconcile")
        else:
            adjustment = self.contractual_adjustment_cents or 0
            if self.submitted_cents != self.plan_pays_cents + self.member_cost_share_cents + adjustment:
                raise ValueError("submitted-charge line does not reconcile")
        return self


class CandidateOutcome(ModeledLine):
    reading: str


class AbstentionLine(FrozenModel):
    result_kind: Literal["ABSTENTION"] = "ABSTENTION"
    line_id: str
    kind: Literal[
        "ambiguous_language",
        "not_stated",
        "missing_document",
        "compiler_uncertain",
        "out_of_scope",
        "invalid_input",
    ]
    stage: str
    question: str
    required_document_kind: str | None = None
    acceptable_rule_ids: tuple[str, ...] = ()
    acceptable_clause_ids: tuple[str, ...] = ()
    candidate_outcomes: tuple[CandidateOutcome, ...] = ()
    effects: tuple[Effect, ...] = ()


LineResult = ModeledLine | AbstentionLine


class MoneyPoolDelta(FrozenModel):
    pool_id: str
    delta_cents: int


class CountPoolDelta(FrozenModel):
    pool_id: str
    delta_count: int


class AccumulatorDelta(FrozenModel):
    deductible: tuple[MoneyPoolDelta, ...] = ()
    maximum: tuple[MoneyPoolDelta, ...] = ()
    frequency: tuple[CountPoolDelta, ...] = ()

    @model_validator(mode="after")
    def canonical_deltas(self) -> "AccumulatorDelta":
        for name in ("deductible", "maximum", "frequency"):
            values = [item.pool_id for item in getattr(self, name)]
            if values != sorted(values) or len(values) != len(set(values)):
                raise ValueError(f"{name} deltas must be strictly sorted and unique")
        return self


class Determination(FrozenModel):
    claim_id: str
    spec_id: str
    engine_version: str
    result_kind: Literal["COMPLETE", "INCOMPLETE"]
    committable: bool
    lines: tuple[LineResult, ...]
    proposed_accumulator_delta: AccumulatorDelta | None
    expected_assumption_ids: tuple[str, ...]

    @model_validator(mode="after")
    def claim_result_is_coherent(self) -> "Determination":
        complete = self.result_kind == "COMPLETE"
        if complete != self.committable:
            raise ValueError("only a complete determination is committable")
        if complete != (self.proposed_accumulator_delta is not None):
            raise ValueError("only a complete determination has an accumulator delta")
        if complete and not all(isinstance(line, ModeledLine) for line in self.lines):
            raise ValueError("a complete determination cannot contain an abstention")
        if not complete and not any(isinstance(line, AbstentionLine) for line in self.lines):
            raise ValueError("an incomplete determination must contain an abstention")
        if list(self.expected_assumption_ids) != sorted(set(self.expected_assumption_ids)):
            raise ValueError("expected assumption ids must be strictly sorted and unique")
        return self


class CoreInput(FrozenModel):
    claim: Claim
    history: tuple[ProcedureHistory, ...] | MissingSource
    pricing: PricingContext
    accumulators: AccumulatorSnapshot
