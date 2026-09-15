"""Semantic comparison between engine output and the frozen case oracle."""

from __future__ import annotations

from typing import Any


def semantic_projection(value: Any) -> Any:
    """Remove prose-only fields while retaining IDs, values, evidence, and ordering."""

    if isinstance(value, dict):
        return {
            key: semantic_projection(child)
            for key, child in value.items()
            if key not in {"description", "reasoning_note", "authored_at"}
        }
    if isinstance(value, list):
        return [semantic_projection(child) for child in value]
    return value


def actual_oracle_shape(determination: Any) -> dict[str, Any]:
    value = determination.model_dump(mode="json")
    return {
        key: value[key]
        for key in (
            "spec_id",
            "result_kind",
            "committable",
            "lines",
            "proposed_accumulator_delta",
            "expected_assumption_ids",
        )
    }


def matches_oracle(determination: Any, expected: dict[str, Any]) -> bool:
    return semantic_projection(actual_oracle_shape(determination)) == semantic_projection(
        expected
    )
