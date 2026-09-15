"""Strict structured-output and validated-span models for compiler trials."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DraftScope(StrictModel):
    service_classes: tuple[Literal["A", "B", "C", "D"], ...] = ()
    network_states: tuple[Literal["in_network", "out_of_network"], ...] = ()
    codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def canonical(self) -> "DraftScope":
        for name in ("service_classes", "network_states", "codes"):
            values = getattr(self, name)
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"{name} must be sorted and unique")
        return self


class CitationCandidate(StrictModel):
    page_number: int = Field(ge=1)
    quoted_text: str = Field(min_length=1)


CompilerFieldName = Literal[
    "plan_effective_from",
    "plan_effective_to",
    "scope.service_classes",
    "scope.network_states",
    "scope.codes",
    "applicability",
    "pool_id",
    "quantity",
    "basis",
    "period_months",
    "unit",
    "benefited_code",
    "difference_treatment",
    "requires_clinical_review",
    "amount_cents",
    "coverage_level",
    "plan_share_basis_points",
    "rounding_policy",
    "line_ordering_policy",
]


FIELDS_BY_RULE_KIND = {
    "eligibility": {"plan_effective_from", "plan_effective_to"},
    "frequency": {
        "scope.codes",
        "applicability",
        "pool_id",
        "quantity",
        "basis",
        "period_months",
        "unit",
    },
    "alternate_benefit": {
        "scope.codes",
        "applicability",
        "benefited_code",
        "difference_treatment",
        "requires_clinical_review",
    },
    "deductible": {
        "scope.service_classes",
        "scope.network_states",
        "pool_id",
        "amount_cents",
        "coverage_level",
    },
    "coinsurance": {
        "scope.service_classes",
        "scope.network_states",
        "plan_share_basis_points",
    },
    "annual_maximum": {
        "scope.service_classes",
        "scope.network_states",
        "pool_id",
        "amount_cents",
        "coverage_level",
    },
    "policy": {"rounding_policy", "line_ordering_policy"},
}


class ExtractedAssertion(StrictModel):
    rule_kind: Literal[
        "eligibility",
        "frequency",
        "alternate_benefit",
        "deductible",
        "coinsurance",
        "annual_maximum",
        "policy",
    ]
    scope: DraftScope
    field_name: CompilerFieldName
    state: Literal[
        "sourced",
        "derived",
        "assumed",
        "ambiguous",
        "missing_source",
        "not_stated",
        "compiler_uncertain",
    ]
    value_json: str | None
    candidate_values_json: tuple[str, ...] = ()
    required_document_kind: str | None = None
    reasoning: str
    citations: tuple[CitationCandidate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def state_shape(self) -> "ExtractedAssertion":
        if self.field_name not in FIELDS_BY_RULE_KIND[self.rule_kind]:
            raise ValueError(
                f"{self.field_name} is not valid for rule kind {self.rule_kind}"
            )
        resolved = self.state in {"sourced", "derived", "assumed"}
        if resolved != (self.value_json is not None):
            raise ValueError("resolved states require value_json; unresolved states forbid it")
        if self.state == "ambiguous" and len(self.candidate_values_json) < 2:
            raise ValueError("ambiguous assertions require at least two candidate values")
        return self


class UnmappedClause(StrictModel):
    page_number: int = Field(ge=1)
    quoted_text: str = Field(min_length=1)
    reason: str


class CompilerDraft(StrictModel):
    plan_label: str
    assertions: tuple[ExtractedAssertion, ...]
    unmapped_relevant_clauses: tuple[UnmappedClause, ...] = ()


class ResolvedCitation(StrictModel):
    page_number: int
    char_start: int
    char_end: int
    quoted_text: str
    valid: bool
    failure_reason: str | None = None


class ValidatedAssertion(StrictModel):
    assertion: ExtractedAssertion
    resolved_citations: tuple[ResolvedCitation, ...]
    span_valid: bool


class ValidatedDraft(StrictModel):
    draft: CompilerDraft
    assertions: tuple[ValidatedAssertion, ...]
    all_spans_valid: bool
