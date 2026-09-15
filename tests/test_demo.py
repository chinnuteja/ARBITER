from __future__ import annotations

from arbiter.demo.service import (
    benchmark_payload,
    case_payload,
    case_summaries,
    load_demo_data,
)

from conftest import ROOT


def test_demo_lead_case_runs_through_both_reviewed_specs() -> None:
    data = load_demo_data(ROOT)
    payload = case_payload(data, "B01")
    assert payload["case"]["case_id"] == "B01"
    assert payload["outcomes"]["delta"]["result_kind"] == "COMPLETE"
    assert payload["outcomes"]["metlife"]["result_kind"] == "COMPLETE"
    assert [line["plan_pays_cents"] for line in payload["outcomes"]["delta"]["lines"]] == [
        35000,
        5000,
    ]
    assert [line["plan_pays_cents"] for line in payload["outcomes"]["metlife"]["lines"]] == [
        35000,
        35000,
    ]
    assert payload["evidence"]["delta"]
    assert payload["evidence"]["metlife"]


def test_demo_exposes_a_scoped_abstention_without_suppressing_the_case() -> None:
    data = load_demo_data(ROOT)
    payload = case_payload(data, "A06")
    metlife = payload["outcomes"]["metlife"]
    assert metlife["result_kind"] == "INCOMPLETE"
    assert metlife["lines"][1]["kind"] == "ambiguous_language"
    assert any(item["demo_lead"] for item in case_summaries(data))


def test_demo_exposes_frozen_compiler_benchmark_without_gold_leakage() -> None:
    benchmark = benchmark_payload(load_demo_data(ROOT))
    assert benchmark["status"] == "complete"
    assert benchmark["model"] == "gemini-3.5-flash"
    assert benchmark["completed_calls"] == benchmark["requested_calls"] == 6
    assert benchmark["gold_excluded_from_prompt"] is True
    assert benchmark["unsafe_assertion_count"] == 4
    assert {item["gold_state"] for item in benchmark["unsafe_examples"]} == {
        "ambiguous",
        "missing_source",
    }
