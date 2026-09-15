"""Load repository artifacts outside the pure adjudication core."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from arbiter.core.models import (
    AccumulatorSnapshot,
    Claim,
    CoreInput,
    MissingSource,
    PriceEntry,
    PricingContext,
    ProcedureHistory,
)
from arbiter.core.spec import ReviewedSpec


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_spec(path: Path) -> ReviewedSpec:
    return ReviewedSpec(json.loads(path.read_text(encoding="utf-8")))


def pricing_amounts(
    schedule: dict[str, Any], overrides: dict[str, Any]
) -> dict[str, int | MissingSource]:
    result: dict[str, int | MissingSource] = {
        entry["code"]: int(entry["amount_cents"]["value"])
        for entry in schedule["entries"]
    }
    for code, value in overrides.items():
        if isinstance(value, dict) and value.get("state") == "missing_source":
            result[code] = MissingSource.model_validate(value)
        else:
            result[code] = int(value)
    return result


def core_input_for_case(
    case: dict[str, Any], plan: str, schedule: dict[str, Any]
) -> CoreInput:
    history_raw = case["history_input"]
    history: tuple[ProcedureHistory, ...] | MissingSource
    if isinstance(history_raw, dict) and history_raw.get("state") == "missing_source":
        history = MissingSource.model_validate(history_raw)
    else:
        history = tuple(ProcedureHistory.model_validate(item) for item in history_raw)
    context = case["pricing_context"]
    return CoreInput(
        claim=Claim.model_validate(case["claim"]),
        history=history,
        pricing=PricingContext(
            kind=context["kind"],
            schedule_id=context["schedule_id"],
            entries=tuple(
                PriceEntry(code=code, amount_cents=value)
                for code, value in sorted(
                    pricing_amounts(schedule, context.get("overrides", {})).items()
                )
            ),
        ),
        accumulators=AccumulatorSnapshot.model_validate(
            case["plan_inputs"][plan]["accumulators"]
        ),
    )
