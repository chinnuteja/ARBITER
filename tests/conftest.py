from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from arbiter.evaluation.loaders import load_spec, load_yaml


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def manifest() -> dict[str, Any]:
    return load_yaml(ROOT / "data/cases/manifest.yaml")


@pytest.fixture(scope="session")
def schedule() -> dict[str, Any]:
    return load_yaml(ROOT / "data/cases/benchmark-schedule.yaml")


@pytest.fixture(scope="session")
def specs():
    return {
        "delta": load_spec(ROOT / "data/specs/delta-standard-2026.gold.json"),
        "metlife": load_spec(ROOT / "data/specs/metlife-standard-2026.gold.json"),
    }
