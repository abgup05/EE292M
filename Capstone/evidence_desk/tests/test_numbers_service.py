"""Reported numbers for a run: loading XBRL company facts, and what the engine is shown."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from app.core import limits
from app.core.facts import FactBook
from app.core.metrics import build_report
from app.core.models import ExtractionStatus, SourceKind
from app.core.ports import SourceError
from app.services.numbers import FIGURE_KEYS, load_numbers, select_figures
from app.sources.filing import parse_filing
from app.sources.xbrl import company_facts_url
from tests.fakes import NVIDIA, Q2_2027, FakeFilings, recorded_facts, recorded_html

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def test_load_numbers_builds_the_report_and_an_xbrl_source() -> None:
    result = load_numbers(NVIDIA, FakeFilings.nvidia(), now=lambda: NOW)
    assert result.error is None and result.report is not None
    assert result.report.cik == NVIDIA.cik and result.report.metrics
    source = result.source
    assert source is not None
    assert source.kind == SourceKind.sec_xbrl
    assert source.title == "NVIDIA CORP XBRL company facts"
    assert source.url == company_facts_url(NVIDIA.cik)
    assert source.retrieved_at == NOW
    assert source.extraction_status == ExtractionStatus.extracted
    canonical = json.dumps(recorded_facts(), sort_keys=True, separators=(",", ":"))
    assert source.content_hash == hashlib.sha256(canonical.encode()).hexdigest()
    assert result.notes == result.report.notes


def test_unreadable_facts_become_an_error_not_an_exception() -> None:
    filings = FakeFilings.nvidia()
    filings.facts_error = SourceError("EDGAR answered HTTP 503 for company facts")
    result = load_numbers(NVIDIA, filings, now=lambda: NOW)
    assert result.report is None
    assert result.error == "EDGAR answered HTTP 503 for company facts"
    assert result.source is not None
    assert result.source.extraction_status == ExtractionStatus.failed
    assert result.source.error == result.error


def test_malformed_facts_become_an_error() -> None:
    filings = FakeFilings.nvidia()
    filings.facts = {"cik": 1045810, "entityName": "NVIDIA CORP", "facts": []}
    result = load_numbers(NVIDIA, filings, now=lambda: NOW)
    assert result.report is None
    assert result.error is not None and "facts" in result.error


def test_selected_figures_are_the_newest_periods_of_the_headline_keys() -> None:
    report = build_report(FactBook(recorded_facts()))
    figures = select_figures(report)
    assert 0 < len(figures) <= limits.MAX_FIGURES_OFFERED
    assert all(figure.value is not None for figure in figures)
    ids = {figure.id for figure in figures}
    for key in ("revenue", "revenue_yoy", "gross_margin", "net_margin", "free_cash_flow"):
        assert f"{key}:quarter:2026-07-26" in ids
        assert f"{key}:annual:2026-01-25" in ids
        assert f"{key}:annual:2025-01-26" in ids
    assert "revenue:quarter:2025-10-26" not in ids  # older than the three newest quarters
    assert "revenue:annual:2024-01-28" not in ids  # older than the two newest years
    assert {"cash:instant:2026-07-26", "inventory:instant:2026-07-26"} <= ids
    assert "cash:instant:2026-01-25" not in ids
    assert {f.key for f in figures if f.period != "instant"} <= set(FIGURE_KEYS)
    assert len(ids) == len(figures)


def test_independent_method_xbrl_revenue_is_printed_in_the_recorded_10q() -> None:
    """The XBRL API and the filing's HTML are two separate paths to one number."""
    quarters = FactBook(recorded_facts()).quarters("revenue")
    newest = max(quarters)
    assert newest.isoformat() == Q2_2027.period_end
    in_millions = f"{quarters[newest].value / 1e6:,.0f}"
    document = parse_filing(
        recorded_html("nvda-10q-20260726.htm.gz"),
        url=Q2_2027.url,
        title="NVIDIA CORP 10-Q",
        published_date=Q2_2027.filed_date,
    )
    assert in_millions == "96,221"
    assert f"Revenue ${in_millions}" in document.text
