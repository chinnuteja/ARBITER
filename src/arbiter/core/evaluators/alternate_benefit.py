"""Alternate-benefit stage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from arbiter.core.evaluators.common import make_effect
from arbiter.core.models import ClaimLine, Effect
from arbiter.core.spec import ReviewedSpec, Unresolved, resolve


@dataclass(frozen=True)
class AlternateResult:
    status: str  # unchanged | mapped | missing | ambiguous
    benefited_code: str
    treatment: str | None
    effect: Effect | None
    rule: dict[str, Any] | None
    required_document_kind: str | None = None
    question: str | None = None


def evaluate(line: ClaimLine, spec: ReviewedSpec) -> AlternateResult:
    rules = spec.matching("alternate_benefit", line)
    if not rules:
        return AlternateResult("unchanged", line.submitted_code, None, None, None)
    rule = rules[0]
    applicability = resolve(rule["applicability"])
    if isinstance(applicability, Unresolved):
        return AlternateResult(
            "missing",
            line.submitted_code,
            None,
            make_effect(
                line.line_id,
                "alternate_benefit",
                "clinical policy is required to decide whether alternate-benefit review applies",
                unit="none",
                before=None,
                after=None,
                delta=None,
                rule=rule,
            ),
            rule,
            required_document_kind="clinical_policy",
            question=(
                "Does MetLife clinical review apply an alternate benefit to D2952, and if so which benefited code and reconciliation basis apply?"
            ),
        )
    if not applicability:
        return AlternateResult("unchanged", line.submitted_code, None, None, None)
    benefited = resolve(rule["benefited_code"])
    treatment = resolve(rule["difference_treatment"])
    review = resolve(rule["requires_clinical_review"])
    unresolved = [item for item in (benefited, treatment, review) if isinstance(item, Unresolved)]
    if unresolved:
        first = unresolved[0]
        required = first.field.get("required_kind")
        return AlternateResult(
            "missing" if first.state == "missing_source" else "ambiguous",
            line.submitted_code,
            None,
            make_effect(
                line.line_id,
                "alternate_benefit",
                "the benefited code or reconciliation basis requires unavailable evidence",
                unit="none",
                before=None,
                after=None,
                delta=None,
                rule=rule,
            ),
            rule,
            required_document_kind=required,
            question="Which professionally acceptable less-costly code and reconciliation basis apply to this inlay?",
        )
    return AlternateResult(
        "mapped",
        str(benefited),
        str(treatment),
        make_effect(
            line.line_id,
            "alternate_benefit",
            "replace the submitted code with the explicit benefited code",
            unit="code",
            before=line.submitted_code,
            after=str(benefited),
            delta=None,
            rule=rule,
        ),
        rule,
    )
