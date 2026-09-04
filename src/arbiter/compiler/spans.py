"""Exact citation resolution against frozen canonical page text."""

from __future__ import annotations

from typing import Any

from arbiter.compiler.models import (
    CompilerDraft,
    ResolvedCitation,
    ValidatedAssertion,
    ValidatedDraft,
)


def resolve_quote(canonical: dict[str, Any], page_number: int, quote: str) -> ResolvedCitation:
    pages = {int(page["page_number"]): page["text"] for page in canonical["pages"]}
    page = pages.get(page_number)
    if page is None:
        return ResolvedCitation(
            page_number=page_number,
            char_start=-1,
            char_end=-1,
            quoted_text=quote,
            valid=False,
            failure_reason="page_not_found",
        )
    count = page.count(quote)
    if count != 1:
        return ResolvedCitation(
            page_number=page_number,
            char_start=-1,
            char_end=-1,
            quoted_text=quote,
            valid=False,
            failure_reason="quote_not_found" if count == 0 else "quote_not_unique_on_page",
        )
    start = page.index(quote)
    return ResolvedCitation(
        page_number=page_number,
        char_start=start,
        char_end=start + len(quote),
        quoted_text=quote,
        valid=True,
    )


def validate_draft_spans(canonical: dict[str, Any], draft: CompilerDraft) -> ValidatedDraft:
    assertions = []
    for assertion in draft.assertions:
        resolved = tuple(
            resolve_quote(canonical, citation.page_number, citation.quoted_text)
            for citation in assertion.citations
        )
        assertions.append(
            ValidatedAssertion(
                assertion=assertion,
                resolved_citations=resolved,
                span_valid=bool(resolved) and all(item.valid for item in resolved)
                if assertion.citations
                else assertion.state in {"assumed", "missing_source", "not_stated", "compiler_uncertain"},
            )
        )
    return ValidatedDraft(
        draft=draft,
        assertions=tuple(assertions),
        all_spans_valid=all(item.span_valid for item in assertions),
    )
