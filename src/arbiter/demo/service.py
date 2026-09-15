"""Read-only presentation adapter around the deterministic adjudication core."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arbiter.core.engine import adjudicate
from arbiter.evaluation.loaders import core_input_for_case, load_spec, load_yaml


PLAN_LABELS = {
    "delta": "Delta Dental · Standard",
    "metlife": "MetLife · Standard",
}


def _evidence_index(value: Any, index: dict[str, dict[str, Any]]) -> None:
    if isinstance(value, dict):
        for item in value.get("evidence", []):
            clause_id = item.get("clause_id")
            if isinstance(clause_id, str) and clause_id not in index:
                index[clause_id] = {
                    "clause_id": clause_id,
                    "page_number": item.get("page_number"),
                    "quoted_text": item.get("quoted_text"),
                }
        for child in value.values():
            _evidence_index(child, index)
    elif isinstance(value, list):
        for child in value:
            _evidence_index(child, index)


@dataclass(frozen=True)
class DemoData:
    manifest: dict[str, Any]
    schedule: dict[str, Any]
    specs: dict[str, Any]
    evidence: dict[str, dict[str, dict[str, Any]]]
    benchmark: dict[str, Any]

    @property
    def cases(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.manifest["cases"])


def load_demo_data(root: Path) -> DemoData:
    manifest = load_yaml(root / "data/cases/manifest.yaml")
    schedule = load_yaml(root / "data/cases/benchmark-schedule.yaml")
    specs = {
        "delta": load_spec(root / "data/specs/delta-standard-2026.gold.json"),
        "metlife": load_spec(root / "data/specs/metlife-standard-2026.gold.json"),
    }
    evidence: dict[str, dict[str, dict[str, Any]]] = {}
    for plan, spec in specs.items():
        plan_index: dict[str, dict[str, Any]] = {}
        _evidence_index(spec.artifact, plan_index)
        evidence[plan] = plan_index
    return DemoData(
        manifest=manifest,
        schedule=schedule,
        specs=specs,
        evidence=evidence,
        benchmark=_load_benchmark(root),
    )


def _load_benchmark(root: Path) -> dict[str, Any]:
    """Read the compact, reviewable benchmark summary used by the demo.

    Raw prompts, responses, and trial logs belong to the private research
    workspace. The public demo carries only the frozen result needed to audit
    its UI claims.
    """
    path = root / "data" / "demo" / "compiler-benchmark.json"
    return json.loads(path.read_text(encoding="utf-8"))


def benchmark_payload(data: DemoData) -> dict[str, Any]:
    return data.benchmark


def case_summaries(data: DemoData) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case["case_id"],
            "title": case["title"],
            "category": case["category"],
            "tags": case["tags"],
            "thesis": case["thesis"],
            "demo_lead": case.get("demo_lead", False),
        }
        for case in data.cases
    ]


def _case(data: DemoData, case_id: str) -> dict[str, Any]:
    for case in data.cases:
        if case["case_id"] == case_id:
            return case
    raise KeyError(case_id)


def case_payload(data: DemoData, case_id: str) -> dict[str, Any]:
    case = _case(data, case_id)
    outcomes: dict[str, dict[str, Any]] = {}
    plan_meta: dict[str, dict[str, Any]] = {}
    evidence: dict[str, dict[str, dict[str, Any]]] = {}
    for plan, spec in data.specs.items():
        determination = adjudicate(core_input_for_case(case, plan, data.schedule), spec)
        outcomes[plan] = determination.model_dump(mode="json")
        plan_meta[plan] = {
            "label": PLAN_LABELS[plan],
            "carrier": spec.carrier,
            "plan_name": spec.data["plan_name"],
            "option": spec.data["option"],
            "spec_id": spec.spec_id,
        }
        used_clause_ids = {
            clause_id
            for line in outcomes[plan]["lines"]
            for effect in line.get("effects", [])
            for clause_id in effect.get("acceptable_clause_ids", [])
        }
        evidence[plan] = {
            clause_id: data.evidence[plan][clause_id]
            for clause_id in sorted(used_clause_ids)
            if clause_id in data.evidence[plan]
        }
    return {
        "mvp_notice": (
            "MODELED outcome using a frozen synthetic benchmark allowance. "
            "This is not a carrier payment guarantee."
        ),
        "case": {
            key: case[key]
            for key in ("case_id", "category", "title", "tags", "thesis", "claim")
        },
        "plans": plan_meta,
        "outcomes": outcomes,
        "evidence": evidence,
    }
