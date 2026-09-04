"""Field-level, provenance-aware compiler scoring against reviewed specs."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from arbiter.compiler.models import ValidatedAssertion, ValidatedDraft
from arbiter.core.spec import Unresolved, resolve


UNRESOLVED_STATES = {"ambiguous", "missing_source", "not_stated"}
ASSERTED_STATES = {"sourced", "derived", "assumed"}


@dataclass(frozen=True)
class GoldField:
    path: str
    rule_kind: str
    field_name: str
    state: str
    value: Any
    candidates: tuple[Any, ...]
    scope: dict[str, tuple[str, ...]]
    evidence: tuple[tuple[int, int, int], ...]


def _evidence(value: Any) -> tuple[tuple[int, int, int], ...]:
    found: set[tuple[int, int, int]] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if all(key in node for key in ("page_number", "char_start", "char_end")):
                found.add(
                    (int(node["page_number"]), int(node["char_start"]), int(node["char_end"]))
                )
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return tuple(sorted(found))


def _scope(rule: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for name, field in rule.get("scope", {}).items():
        value = resolve(field)
        if isinstance(value, Unresolved):
            flattened = {
                str(item)
                for candidate in value.field.get("candidate_values", [])
                for item in (candidate if isinstance(candidate, list) else [candidate])
            }
            result[name] = tuple(sorted(flattened))
        else:
            values = value if isinstance(value, list) else [value]
            result[name] = tuple(sorted(str(item) for item in values))
    return result


def gold_fields(artifact: dict[str, Any]) -> tuple[GoldField, ...]:
    fields: list[GoldField] = []
    for rule in artifact["spec"]["rules"]:
        scope = _scope(rule)
        candidates = list(rule.get("scope", {}).items()) + [
            (name, field)
            for name, field in rule.items()
            if name not in {"kind", "rule_id", "scope"}
            and isinstance(field, dict)
            and "state" in field
        ]
        for name, field in candidates:
            field_name = f"scope.{name}" if name in rule.get("scope", {}) else name
            state = str(field["state"])
            fields.append(
                GoldField(
                    path=f"rules.{rule['rule_id']}.{field_name}",
                    rule_kind=rule["kind"],
                    field_name=field_name,
                    state=state,
                    value=field.get("value"),
                    candidates=tuple(field.get("candidate_values", [])),
                    scope=scope,
                    evidence=_evidence(field),
                )
            )
    for name in ("rounding_policy", "line_ordering_policy"):
        field = artifact["spec"][name]
        fields.append(
            GoldField(
                path=f"policy.{name}",
                rule_kind="policy",
                field_name=name,
                state=str(field["state"]),
                value=field.get("value"),
                candidates=tuple(field.get("candidate_values", [])),
                scope={},
                evidence=_evidence(field),
            )
        )
    return tuple(fields)


def _draft_scope(item: ValidatedAssertion) -> dict[str, tuple[str, ...]]:
    scope = item.assertion.scope
    return {
        "service_classes": tuple(scope.service_classes),
        "network_states": tuple(scope.network_states),
        "codes": tuple(scope.codes),
    }


def _similarity(gold: GoldField, draft: ValidatedAssertion) -> int:
    proposed = _draft_scope(draft)
    score = 0
    for dimension in ("service_classes", "network_states", "codes"):
        expected = set(gold.scope.get(dimension, ()))
        actual = set(proposed.get(dimension, ()))
        if expected == actual:
            score += 4
        elif expected and actual and expected & actual:
            score += 1
        elif expected or actual:
            score -= 3
    return score


def _json_value(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {"invalid_json": value}


def _citation_agreement(gold: GoldField, draft: ValidatedAssertion) -> bool:
    if not gold.evidence:
        return draft.span_valid
    for citation in draft.resolved_citations:
        if not citation.valid:
            continue
        for page, start, end in gold.evidence:
            if citation.page_number == page and citation.char_start < end and citation.char_end > start:
                return True
    return False


def score_trial(artifact: dict[str, Any], draft: ValidatedDraft) -> dict[str, Any]:
    rows = []
    for gold in gold_fields(artifact):
        candidates = [
            item
            for item in draft.assertions
            if item.assertion.rule_kind == gold.rule_kind
            and item.assertion.field_name == gold.field_name
        ]
        chosen = max(candidates, key=lambda item: _similarity(gold, item), default=None)
        if chosen is None:
            rows.append(
                {
                    "gold_path": gold.path,
                    "gold_state": gold.state,
                    "draft_state": None,
                    "draft_signature": "missing",
                    "attempted": False,
                    "value_agreement": False,
                    "scope_agreement": False,
                    "span_valid": False,
                    "citation_agreement": False,
                    "safe_abstention": False,
                    "unsafe_assertion": False,
                    "covered": False,
                }
            )
            continue
        assertion = chosen.assertion
        value = _json_value(assertion.value_json)
        state_unresolved = assertion.state not in ASSERTED_STATES
        gold_unresolved = gold.state in UNRESOLVED_STATES
        value_agreement = value == gold.value if not gold_unresolved else False
        scope_agreement = all(
            tuple(gold.scope.get(name, ())) == tuple(_draft_scope(chosen).get(name, ()))
            for name in ("service_classes", "network_states", "codes")
        )
        safe_abstention = gold_unresolved and state_unresolved
        unsafe_assertion = gold_unresolved and not state_unresolved
        covered = (
            safe_abstention
            if gold_unresolved
            else value_agreement and scope_agreement and chosen.span_valid
        )
        signature = json.dumps(
            {
                "state": assertion.state,
                "value": value,
                "candidates": list(assertion.candidate_values_json),
                "scope": _draft_scope(chosen),
            },
            sort_keys=True,
        )
        rows.append(
            {
                "gold_path": gold.path,
                "gold_state": gold.state,
                "draft_state": assertion.state,
                "draft_signature": signature,
                "attempted": True,
                "value_agreement": value_agreement,
                "scope_agreement": scope_agreement,
                "span_valid": chosen.span_valid,
                "citation_agreement": _citation_agreement(gold, chosen),
                "safe_abstention": safe_abstention,
                "unsafe_assertion": unsafe_assertion,
                "covered": covered,
            }
        )

    by_state: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        state = row["gold_state"]
        by_state[state]["total"] += 1
        for metric in (
            "attempted",
            "value_agreement",
            "scope_agreement",
            "span_valid",
            "citation_agreement",
            "safe_abstention",
            "unsafe_assertion",
            "covered",
        ):
            by_state[state][metric] += int(row[metric])
    return {
        "score_version": 1,
        "gold_spec_id": artifact["spec"]["spec_id"],
        "field_count": len(rows),
        "metrics": {"fields": len(rows)} | {
            metric: sum(int(row[metric]) for row in rows)
            for metric in (
                "attempted",
                "value_agreement",
                "scope_agreement",
                "span_valid",
                "citation_agreement",
                "safe_abstention",
                "unsafe_assertion",
                "covered",
            )
        },
        "by_gold_state": {state: dict(counts) for state, counts in sorted(by_state.items())},
        "rows": rows,
    }


def aggregate_trials(scores: list[dict[str, Any]]) -> dict[str, Any]:
    if not scores:
        raise ValueError("at least one trial score is required")
    signatures: dict[str, list[str]] = defaultdict(list)
    attempts: dict[str, list[bool]] = defaultdict(list)
    for score in scores:
        for row in score["rows"]:
            signatures[row["gold_path"]].append(row["draft_signature"])
            attempts[row["gold_path"]].append(row["attempted"])
    stability = {
        path: (
            len(scores) > 1
            and len(values) == len(scores)
            and all(attempts[path])
            and len(set(values)) == 1
        )
        for path, values in signatures.items()
    }
    consistently_missing = sorted(
        path for path, values in attempts.items() if len(values) == len(scores) and not any(values)
    )
    by_state: dict[str, Counter[str]] = defaultdict(Counter)
    for score in scores:
        for state, counts in score["by_gold_state"].items():
            by_state[state].update(counts)
    observation_count = sum(score["field_count"] for score in scores)
    attempted_observations = sum(score["metrics"]["attempted"] for score in scores)
    covered_observations = sum(score["metrics"]["covered"] for score in scores)
    return {
        "trial_count": len(scores),
        "field_count": len(stability),
        "stable_fields": sum(stability.values()),
        "consistently_missing_fields": consistently_missing,
        "observation_count": observation_count,
        "attempted_observations": attempted_observations,
        "covered_observations": covered_observations,
        "attempt_rate": (
            round(attempted_observations / observation_count, 4) if observation_count else 0
        ),
        "coverage_rate": (
            round(covered_observations / observation_count, 4) if observation_count else 0
        ),
        "unstable_fields": sorted(path for path, stable in stability.items() if not stable),
        "unsafe_assertions": sum(score["metrics"]["unsafe_assertion"] for score in scores),
        "safe_abstentions": sum(score["metrics"]["safe_abstention"] for score in scores),
        "by_gold_state": {state: dict(counts) for state, counts in sorted(by_state.items())},
        "stability": stability,
    }


def markdown_report(plan_reports: dict[str, dict[str, Any]]) -> str:
    lines = ["# Compiler field evaluation", "", "Gold values were used only after extraction.", ""]
    for plan, report in plan_reports.items():
        lines.extend(
            [
                f"## {plan}",
                "",
                f"- Trials: {report['trial_count']}",
                f"- Stable fields: {report['stable_fields']}/{report['field_count']}",
                f"- Attempted field observations: {report['attempted_observations']}/{report['observation_count']} ({report['attempt_rate']:.1%})",
                f"- Covered field observations: {report['covered_observations']}/{report['observation_count']} ({report['coverage_rate']:.1%})",
                f"- Consistently missing fields: {len(report['consistently_missing_fields'])}",
                f"- Safe abstentions across trials: {report['safe_abstentions']}",
                f"- Unsafe assertions across trials: {report['unsafe_assertions']}",
                f"- Unstable fields: {len(report['unstable_fields'])}",
                "",
            ]
        )
        if report["unstable_fields"]:
            lines.extend(f"  - `{path}`" for path in report["unstable_fields"])
            lines.append("")
        lines.extend(["### By gold provenance state", ""])
        for state, counts in report["by_gold_state"].items():
            lines.append(
                f"- `{state}`: attempted {counts.get('attempted', 0)}/{counts['total']}; "
                f"covered {counts.get('covered', 0)}/{counts['total']}; "
                f"safe abstentions {counts.get('safe_abstention', 0)}; "
                f"unsafe assertions {counts.get('unsafe_assertion', 0)}"
            )
        lines.append("")
    return "\n".join(lines)
