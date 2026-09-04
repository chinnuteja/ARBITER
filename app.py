"""Vercel entrypoint for the ARBITER claim-review demonstration.

The local ``scripts/run_demo.py`` server is deliberately dependency-free. This
adapter exposes the same read-only API and static interface as a FastAPI app so
Vercel can run it as one Python Function.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from arbiter.demo.service import (  # noqa: E402
    benchmark_payload,
    case_payload,
    case_summaries,
    load_demo_data,
)


STATIC_ROOT = ROOT / "src" / "arbiter" / "demo" / "static"

app = FastAPI(title="ARBITER", docs_url=None, redoc_url=None)


@lru_cache(maxsize=1)
def demo_data():
    """Load the frozen demo artifacts once per warm function instance."""
    return load_demo_data(ROOT)


@app.get("/api/cases")
def get_cases() -> dict[str, object]:
    return {"cases": case_summaries(demo_data())}


@app.get("/api/benchmark")
def get_benchmark() -> dict[str, object]:
    return benchmark_payload(demo_data())


@app.get("/api/case/{case_id}")
def get_case(case_id: str) -> dict[str, object]:
    try:
        return case_payload(demo_data(), case_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Unknown case") from error


@app.get("/{requested_path:path}")
def get_static_file(requested_path: str):
    """Serve the existing single-page UI without exposing arbitrary files."""
    relative_path = requested_path or "index.html"
    candidate = (STATIC_ROOT / relative_path).resolve()
    if candidate == STATIC_ROOT / "index.html" or (
        STATIC_ROOT.resolve() in candidate.parents and candidate.is_file()
    ):
        return FileResponse(candidate, headers={"Cache-Control": "no-store"})
    return JSONResponse(status_code=404, content={"error": "Not found"})
