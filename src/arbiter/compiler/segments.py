"""Deterministic canonical-page segmentation and six-family routing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any


FAMILY_TERMS = {
    "eligibility": ("effective date", "calendar year", "coverage effective"),
    "frequency": (
        "frequency",
        "limited to",
        "every 12 months",
        "every 24 months",
        "every 48 months",
        "every 60 months",
        "d0120",
        "d0150",
        "d0180",
        "d0210",
        "d0330",
    ),
    "alternate_benefit": (
        "alternate benefit",
        "less costly",
        "dental review",
        "d2952",
        "d2954",
        "d2510",
        "d2520",
        "d2530",
    ),
    "deductible": ("deductible",),
    "coinsurance": ("coinsurance", "you pay", "plan allowance"),
    "annual_maximum": ("annual benefit maximum", "annual maximum"),
}


@dataclass(frozen=True)
class Segment:
    segment_id: str
    page_number: int
    char_start: int
    char_end: int
    text: str
    families: tuple[str, ...]
    sha256: str


def _blocks(text: str, max_chars: int) -> list[tuple[int, int, str]]:
    paragraphs = [match for match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, re.S)]
    if not paragraphs:
        return []
    chunks: list[tuple[int, int, str]] = []
    start = paragraphs[0].start()
    end = paragraphs[0].end()
    for paragraph in paragraphs[1:]:
        if paragraph.end() - start > max_chars:
            chunks.append((start, end, text[start:end]))
            start = paragraph.start()
        end = paragraph.end()
    chunks.append((start, end, text[start:end]))
    return chunks


def compile_segments(
    canonical: dict[str, Any], *, max_chars: int = 3000
) -> tuple[Segment, ...]:
    segments: list[Segment] = []
    for page in canonical["pages"]:
        page_number = int(page["page_number"])
        for index, (start, end, text) in enumerate(_blocks(page["text"], max_chars), 1):
            lowered = text.lower()
            families = tuple(
                family
                for family, terms in FAMILY_TERMS.items()
                if any(term in lowered for term in terms)
            )
            if not families:
                continue
            segments.append(
                Segment(
                    segment_id=f"p{page_number:03d}-s{index:03d}",
                    page_number=page_number,
                    char_start=start,
                    char_end=end,
                    text=text,
                    families=families,
                    sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )
    return tuple(segments)


def segments_artifact(canonical: dict[str, Any], segments: tuple[Segment, ...]) -> dict[str, Any]:
    return {
        "segment_artifact_version": 1,
        "document_id": canonical["document_id"],
        "document_sha256": canonical["document_sha256"],
        "canonicalization_version": canonical["canonicalization_version"],
        "segments": [asdict(segment) for segment in segments],
    }
