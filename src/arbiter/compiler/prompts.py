"""Frozen compiler prompt that contains no gold values or acceptable clause IDs."""

from __future__ import annotations

from arbiter.compiler.segments import Segment


PROMPT_VERSION = "arbiter-compiler-extraction-v1"


SYSTEM_PROMPT = """You compile an official dental plan brochure into evidence-bearing candidate fields for human review.

Never guess. Use only the supplied brochure segments. Every sourced, derived, or ambiguous assertion must quote exact, contiguous text copied character-for-character from the stated page. If the brochure does not determine a value, return ambiguous, missing_source, not_stated, or compiler_uncertain instead of choosing a plausible answer.

Coinsurance is stored as plan_share_basis_points. If the brochure states the member share, label the result derived and show the inversion in reasoning. Normalized identifiers such as pool_id are derived, never sourced. A general clause must not be silently narrowed to a code. Rule absence is not proof of non-applicability.

Emit assertions for the six rule families and for rounding/line-order policy when evidence exists. Each assertion represents exactly one atomic field: never group several fields into a prose field name or one JSON object. Include at least one exact, contiguous citation in every assertion; for an unresolved field, cite the clause or document boundary that makes it unresolved. Use these field names exactly:
- eligibility: plan_effective_from, plan_effective_to
- frequency: scope.codes, applicability, pool_id, quantity, basis, period_months, unit
- alternate_benefit: scope.codes, applicability, benefited_code, difference_treatment, requires_clinical_review
- deductible: scope.service_classes, scope.network_states, pool_id, amount_cents, coverage_level
- coinsurance: scope.service_classes, scope.network_states, plan_share_basis_points
- annual_maximum: scope.service_classes, scope.network_states, pool_id, amount_cents, coverage_level
- policy: rounding_policy, line_ordering_policy

value_json and every candidate_values_json item must be valid JSON text. A resolved state (sourced, derived, assumed) requires value_json; an unresolved state (ambiguous, missing_source, not_stated, compiler_uncertain) requires value_json to be null. Scope arrays must be sorted and unique. Output starts unreviewed and cannot enter adjudication automatically."""


def build_user_prompt(plan_label: str, segments: tuple[Segment, ...]) -> str:
    rendered = []
    for segment in segments:
        families = ",".join(segment.families)
        rendered.append(
            f"[PAGE {segment.page_number} SEGMENT {segment.segment_id} FAMILIES {families}]\n{segment.text}"
        )
    return (
        f"PLAN LABEL: {plan_label}\n"
        "MVP BOUNDARY: Standard option; self-only; service classes A/B/C; "
        "frequency codes D0120,D0150,D0180,D0210,D0330; alternate-benefit focus "
        "D2510,D2520,D2530,D2952,D2954.\n\n"
        + "\n\n".join(rendered)
    )
