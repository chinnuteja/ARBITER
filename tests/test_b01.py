from __future__ import annotations

from arbiter.core.engine import adjudicate
from arbiter.evaluation.loaders import core_input_for_case
from arbiter.evaluation.oracle import matches_oracle


def test_b01_is_green_end_to_end(manifest, schedule, specs) -> None:
    case = next(item for item in manifest["cases"] if item["case_id"] == "B01")
    assert [line["tooth"] for line in case["claim"]["lines"]] == ["3", "14"]
    assumption_ids = {
        item["assumption_id"] for item in case["scenario_assumptions"]
    }
    assert assumption_ids == {
        "arbiter-benchmark-schedule-v1",
        "b01-clear-crown-history-v1",
        "b01-clinical-gate-passed-v1",
        "b01-distinct-teeth-v1",
        "b01-prior-maximum-v1",
    }
    for plan in ("delta", "metlife"):
        determination = adjudicate(
            core_input_for_case(case, plan, schedule), specs[plan]
        )
        assert matches_oracle(determination, case["expected"][plan])
