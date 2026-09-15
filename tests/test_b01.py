from __future__ import annotations

from arbiter.core.engine import adjudicate
from arbiter.evaluation.loaders import core_input_for_case
from arbiter.evaluation.oracle import matches_oracle


def test_b01_is_green_end_to_end(manifest, schedule, specs) -> None:
    case = next(item for item in manifest["cases"] if item["case_id"] == "B01")
    for plan in ("delta", "metlife"):
        determination = adjudicate(
            core_input_for_case(case, plan, schedule), specs[plan]
        )
        assert matches_oracle(determination, case["expected"][plan])
