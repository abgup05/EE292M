"""Runs as of a past date: only what had been filed by then is read.

The request takes an optional ``as_of``; with it, the run reads the newest 10-K filed
on or before that day and the 10-Qs filed after it up to that day, the 8-Ks filed
between that 10-K and the day, and the XBRL facts filed by the day. Without it, a run
asks EDGAR and the engine exactly what it asked before (the replay and the tripwire
pin that). EDGAR's recent index may not reach back far enough: the older pages are
read, and a date they cannot reach is a clear error.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.models import ThesisRequest
from app.core.ports import SourceError
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import FY_2026, NVIDIA, Q1_2027, Q2_2027, FakePages, ScriptedAnalyst
from tests.lookahead import late_refs
from tests.replay_run import recorded_filings
from tests.test_edgar import (
    MAIN_INDEX,
    NVDA,
    forms_and_dates,
    older_page,
    page_entry,
    page_name,
    paged_client,
)

CLAIMS = ["Gross margin is expanding.", "Revenue grew more than 50% year over year."]


def _request(**changes: object) -> ThesisRequest:
    base: dict[str, object] = {
        "ticker": "NVDA",
        "decision": "Whether to keep an overweight position in NVIDIA",
        "claims": CLAIMS,
    }
    return ThesisRequest.model_validate(base | changes)


# The request


def test_a_request_without_a_date_is_as_before() -> None:
    request = _request()
    assert request.as_of is None


def test_a_past_date_is_accepted() -> None:
    assert _request(as_of="2026-06-01").as_of == date(2026, 6, 1)


@pytest.mark.parametrize(
    ("value", "words"),
    [
        ("2999-01-01", "must not be in the future"),
        ("2008-12-31", "on or after 2009-01-01"),
        ("June 2026", "valid date"),
    ],
)
def test_a_date_that_cannot_be_used_is_refused(value: str, words: str) -> None:
    with pytest.raises(ValidationError, match=words):
        _request(as_of=value)


def test_extra_pages_cannot_be_read_as_of_a_past_date() -> None:
    with pytest.raises(ValidationError, match="extra pages"):
        _request(as_of="2026-06-01", extra_urls=["https://example.com/a"])


# EDGAR's index, as of a date


def test_as_of_a_date_the_newest_10k_by_then_and_the_10qs_after_it_are_chosen() -> None:
    seen: list[str] = []
    recent = [
        ("10-Q", "2026-08-26"),
        ("10-Q", "2026-05-20"),
        ("8-K", "2026-03-10"),
        ("10-K", "2026-02-25"),
        ("10-Q", "2025-11-19"),
        ("10-K", "2025-02-26"),
    ]
    client = paged_client(recent, [], {}, seen)
    refs = client.periodic_filings(NVDA, 5, as_of="2026-06-01")
    assert forms_and_dates(refs) == [("10-Q", "2026-05-20"), ("10-K", "2026-02-25")]
    refs = client.periodic_filings(NVDA, 5, as_of="2026-02-24")
    assert forms_and_dates(refs) == [("10-Q", "2025-11-19"), ("10-K", "2025-02-26")]


def test_the_older_pages_are_read_when_the_recent_index_does_not_reach_back() -> None:
    seen: list[str] = []
    recent = [("424B2", "2026-11-10"), ("10-Q", "2026-11-01"), ("10-K", "2026-02-25")]
    files = [page_entry(1, "2025-06-01", "2025-11-30"), page_entry(2, "2024-12-01", "2025-05-31")]
    pages = {
        1: older_page(1, [("10-Q", "2025-11-30"), ("8-K", "2025-09-01"), ("10-Q", "2025-08-05")]),
        2: older_page(2, [("10-Q", "2025-05-31"), ("10-K", "2025-02-26")]),
    }
    client = paged_client(recent, files, pages, seen)
    refs = client.periodic_filings(NVDA, 5, as_of="2025-10-01")
    assert forms_and_dates(refs) == [
        ("10-Q", "2025-08-05"),
        ("10-Q", "2025-05-31"),
        ("10-K", "2025-02-26"),
    ]
    assert seen == [MAIN_INDEX, page_name(1), page_name(2)]
    current = client.current_reports(NVDA, "2025-02-26", filed_until="2025-10-01")
    assert forms_and_dates(current) == [("8-K", "2025-09-01")]
    # The pages just read are reused: listing the 8-Ks asked for nothing more.
    assert seen == [MAIN_INDEX, page_name(1), page_name(2)]


def test_a_date_the_index_cannot_reach_is_a_clear_error() -> None:
    seen: list[str] = []
    recent = [("10-Q", "2026-11-01"), ("10-K", "2026-02-25")]
    with pytest.raises(SourceError, match=r"No annual report \(10-K\) filed on or before 2020"):
        paged_client(recent, [], {}, seen).periodic_filings(NVDA, 3, as_of="2020-01-01")


def test_without_a_date_the_index_is_read_as_before() -> None:
    seen: list[str] = []
    files = [page_entry(1, "2025-06-01", "2025-11-30")]
    recent = [("10-Q", "2026-11-01"), ("10-K", "2026-02-25")]
    refs = paged_client(recent, files, {}, seen).periodic_filings(NVDA, 3)
    assert forms_and_dates(refs) == [("10-Q", "2026-11-01"), ("10-K", "2026-02-25")]
    assert seen == [MAIN_INDEX]


# A run as of a date, on the recorded filings


def _run(tmp_path: Path, request: ThesisRequest):
    analyst = ScriptedAnalyst()
    run = execute_run(
        new_run(request),
        Store(tmp_path / "record.sqlite"),
        filings=recorded_filings(),
        analyst=analyst,
        fetch_page=FakePages({}),
        cache=FilingCache(),
    )
    return run, analyst


def test_a_run_as_of_a_date_reads_only_what_had_been_filed_by_then(tmp_path: Path) -> None:
    day = date(2026, 6, 1)
    run, analyst = _run(tmp_path, _request(as_of="2026-06-01"))
    filings = [s for s in run.sources if s.form in ("10-K", "10-Q")]
    assert [s.accession for s in filings] == [Q1_2027.accession, FY_2026.accession]
    assert Q2_2027.accession not in {s.accession for s in run.sources}
    assert run.timeline and all(e.filed_date <= "2026-06-01" for e in run.timeline)
    assert all(e.filed_date > FY_2026.filed_date for e in run.timeline)
    assert all((s.published_date or "") <= "2026-06-01" for s in run.sources)
    assert late_refs(run, day) == []
    newest_quarter = max(m.period_end for m in run.metrics if m.period == "quarter")
    assert newest_quarter == "2026-04-26"
    offered = analyst.figures[CLAIMS[0]]
    assert offered and all(fact.filed <= "2026-06-01" for f in offered for fact in f.inputs)
    assert run.as_of is not None and run.as_of.requested == "2026-06-01"
    assert run.as_of.newest_filed == max(e.filed_date for e in run.timeline)
    assert "2026-06-01" in run.as_of.requested_note or "1 Jun 2026" in run.as_of.requested_note


def test_a_run_as_of_the_day_after_the_annual_report_reads_it_alone(tmp_path: Path) -> None:
    run, _ = _run(tmp_path, _request(as_of="2026-03-01"))
    filings = [s for s in run.sources if s.form in ("10-K", "10-Q")]
    assert [s.accession for s in filings] == [FY_2026.accession]
    assert max(m.period_end for m in run.metrics if m.period == "annual") == "2026-01-25"
    assert late_refs(run, date(2026, 3, 1)) == []


def test_a_run_without_a_date_is_unchanged(tmp_path: Path) -> None:
    run, _ = _run(tmp_path, _request())
    filings = [s for s in run.sources if s.form in ("10-K", "10-Q")]
    assert [s.accession for s in filings] == [
        Q2_2027.accession,
        Q1_2027.accession,
        FY_2026.accession,
    ]
    assert run.as_of is not None and run.as_of.requested is None
    assert run.as_of.requested_note == ""


def test_a_date_before_the_recorded_annual_report_fails_the_run_with_the_reason(
    tmp_path: Path,
) -> None:
    run, _ = _run(tmp_path, _request(as_of="2026-01-15"))
    assert run.status == "failed"
    assert any("filed on or before 2026-01-15" in error for error in run.errors)


def test_the_started_time_is_not_the_as_of_date(tmp_path: Path) -> None:
    run, _ = _run(tmp_path, _request(as_of="2026-06-01"))
    assert run.started_at.date() == datetime.now(UTC).date()
    assert run.as_of is not None and run.as_of.days_since_newest is not None
    assert (
        run.as_of.days_since_newest
        == (date(2026, 6, 1) - date.fromisoformat(run.as_of.newest_filed or "2026-06-01")).days
    )


def test_the_fake_lists_as_edgar_would(tmp_path: Path) -> None:
    filings = recorded_filings()
    assert [r.accession for r in filings.periodic_filings(NVIDIA, 3, as_of="2026-05-20")] == [
        Q1_2027.accession,
        FY_2026.accession,
    ]
    with pytest.raises(SourceError, match="filed on or before 2025-12-31"):
        filings.periodic_filings(NVIDIA, 3, as_of="2025-12-31")
