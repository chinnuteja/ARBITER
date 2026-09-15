"""Read-only helpers for reviewed gold specs and evidence-bearing values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


RESOLVED_STATES = frozenset({"sourced", "derived", "assumed"})


@dataclass(frozen=True)
class Unresolved:
    state: str
    field: dict[str, Any]


def resolve(field: dict[str, Any]) -> Any | Unresolved:
    state = field.get("state")
    if state in RESOLVED_STATES:
        return field.get("value")
    return Unresolved(str(state), field)


def clauses(value: Any) -> tuple[str, ...]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            clause_id = node.get("clause_id")
            if isinstance(clause_id, str):
                found.add(clause_id)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return tuple(sorted(found))


def assumptions(value: Any) -> tuple[str, ...]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            assumption_id = node.get("assumption_id")
            if isinstance(assumption_id, str):
                found.add(assumption_id)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return tuple(sorted(found))


class ReviewedSpec:
    def __init__(self, artifact: dict[str, Any]) -> None:
        self.artifact = artifact
        self.data = artifact["spec"]
        self.spec_id = self.data["spec_id"]
        self.carrier = self.data["carrier"]
        self.rules = tuple(self.data["rules"])
        self.by_id = {rule["rule_id"]: rule for rule in self.rules}

    def rules_of_kind(self, kind: str) -> tuple[dict[str, Any], ...]:
        return tuple(rule for rule in self.rules if rule["kind"] == kind)

    @staticmethod
    def scope_matches(rule: dict[str, Any], line: Any) -> bool:
        scope = rule.get("scope", {})
        dimensions = {
            "service_classes": line.service_class,
            "network_states": line.network_state,
            "codes": line.submitted_code,
        }
        for key, actual in dimensions.items():
            field = scope.get(key)
            if field is None:
                continue
            value = resolve(field)
            if isinstance(value, Unresolved):
                candidates = value.field.get("candidate_values", [])
                if candidates and not any(actual in candidate for candidate in candidates):
                    return False
                continue
            if actual not in value:
                return False
        return True

    def matching(self, kind: str, line: Any) -> tuple[dict[str, Any], ...]:
        return tuple(
            rule for rule in self.rules_of_kind(kind) if self.scope_matches(rule, line)
        )


def pool_candidates(field: dict[str, Any]) -> tuple[str, ...]:
    value = resolve(field)
    if isinstance(value, Unresolved):
        return tuple(str(item) for item in value.field.get("candidate_values", []))
    return (str(value),)


def only(items: Iterable[Any], message: str) -> Any:
    values = tuple(items)
    if len(values) != 1:
        raise ValueError(f"{message}: expected one, found {len(values)}")
    return values[0]
