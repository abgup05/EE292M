"""Listing and reading a company's 8-Ks (app.services.events), on the recorded NVIDIA 8-Ks."""

from __future__ import annotations

from datetime import date

from app.core import limits
from app.core.event_models import EventStatus
from app.core.ports import SourceError
from app.services import events as service
from app.store import FilingCache
from tests.fakes import FY_2026, NVIDIA, Q2_2027, FakeFilings, recorded_current_reports

ANNUAL = FY_2026.filed_date  # 2026-02-25
PERIODIC = Q2_2027.filed_date  # 2026-08-26
RESIGNATION = "ev-0001045810-26-000082"  # 12 Nov 2026, Items 5.02 and 9.01


def read(filings: FakeFilings, cache: FilingCache | None = None, **kwargs):
    return service.read_timeline(
        NVIDIA,
        filings,
        cache or FilingCache(),
        annual_filed=kwargs.pop("annual_filed", ANNUAL),
        periodic_filed=kwargs.pop("periodic_filed", PERIODIC),
        **kwargs,
    )


def test_every_8k_since_the_annual_report_is_listed_newest_first() -> None:
    timeline = read(FakeFilings.nvidia_with_events())
    assert len(timeline.events) == 11
    dates = [event.filed_date for event in timeline.events]
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == "2026-11-12"
    assert all(date_filed > ANNUAL for date_filed in dates)


def test_the_8ks_after_the_quarter_and_the_substantive_ones_are_read() -> None:
    timeline = read(FakeFilings.nvidia_with_events())
    read_dates = [e.filed_date for e in timeline.events if e.status == EventStatus.read]
    assert read_dates == [
        "2026-11-12",  # 5.02, 9.01 (after the 10-Q)
        "2026-09-03",  # 8.01 (after the 10-Q, routine)
        "2026-08-17",  # 1.01, 2.03, 7.01
        "2026-07-02",  # 5.02
        "2026-05-08",  # 5.02
        "2026-04-27",  # 5.02
        "2026-03-06",  # 5.02, 9.01
    ]
    index_only = [e.filed_date for e in timeline.events if e.status == EventStatus.index_only]
    assert index_only == ["2026-08-26", "2026-06-30", "2026-06-18", "2026-05-20"]
    assert sorted(timeline.documents) == sorted(
        e.id for e in timeline.events if e.status == EventStatus.read
    )


def test_the_counts_add_up_and_say_so() -> None:
    counts = read(FakeFilings.nvidia_with_events()).counts
    assert (counts.listed, counts.wanted, counts.read, counts.failed) == (11, 7, 7, 0)
    assert (counts.capped, counts.out_of_time, counts.index_only) == (0, 0, 4)
    assert counts.cap == limits.MAX_EVENTS_READ
    assert counts.line.startswith("11 8-K(s) filed since the annual report of 25 Feb 2026: 7 read")


def test_the_resignation_is_read_into_its_items_with_roles_and_opening() -> None:
    timeline = read(FakeFilings.nvidia_with_events())
    resignation = next(e for e in timeline.events if e.id == RESIGNATION)
    assert resignation.categories == ["leadership", "exhibits"]
    assert resignation.substantive and resignation.after_periodic
    departure, exhibits = resignation.items
    assert departure.number == "5.02" and departure.found
    assert departure.opening[0].startswith(
        "On November 11, 2026, the Board of Directors, or the Board, of NVIDIA Corporation "
        "accepted the resignation of Jen-Hsun Huang"
    )
    assert departure.roles[:2] == ["President", "Chief Executive Officer"]
    assert exhibits.number == "9.01" and exhibits.roles == []
    document = timeline.documents[RESIGNATION]
    assert all(sentence in document.text for sentence in departure.opening)


def test_a_document_that_cannot_be_fetched_is_a_reason_on_its_event_only() -> None:
    filings = FakeFilings.nvidia_with_events()
    newest = recorded_current_reports()[0]
    filings.documents[newest.url] = SourceError("EDGAR answered HTTP 503 for the 8-K")
    timeline = read(filings)
    failed = [e for e in timeline.events if e.status == EventStatus.failed]
    assert [(e.filed_date, e.reason) for e in failed] == [
        ("2026-11-12", "EDGAR answered HTTP 503 for the 8-K")
    ]
    assert (timeline.counts.read, timeline.counts.failed, timeline.counts.listed) == (6, 1, 11)
    assert RESIGNATION not in timeline.documents
    assert timeline.index_error == ""


def test_the_cap_reads_the_newest_and_counts_the_rest() -> None:
    timeline = read(FakeFilings.nvidia_with_events(), cap=3)
    counts = timeline.counts
    assert (counts.read, counts.capped, counts.index_only, counts.listed) == (3, 4, 4, 11)
    assert counts.read + counts.capped + counts.index_only == counts.listed
    assert "not read because of the cap of 3 per run" in counts.line


def test_once_out_of_time_no_more_documents_are_read() -> None:
    calls = iter([False, False, True, True, True, True, True])
    timeline = read(FakeFilings.nvidia_with_events(), out_of_time=lambda: next(calls))
    counts = timeline.counts
    assert (counts.read, counts.out_of_time) == (2, 5)
    assert "5 not read because the run time limit came first." in counts.line


def test_an_unreadable_index_gives_an_empty_timeline_and_the_reason() -> None:
    filings = FakeFilings.nvidia_with_events()
    filings.current_error = SourceError("EDGAR answered HTTP 503 for the index")
    timeline = read(filings)
    assert timeline.events == []
    assert timeline.index_error == "EDGAR answered HTTP 503 for the index"
    assert timeline.counts.listed == 0
    assert timeline.counts.line == (
        "EDGAR's list of 8-Ks could not be read (EDGAR answered HTTP 503 for the index)."
    )


def test_no_annual_report_means_no_list() -> None:
    filings = FakeFilings.nvidia_with_events()
    timeline = read(filings, annual_filed=None)
    assert timeline.index_error == service.NO_ANNUAL
    assert filings.current_calls == []
    assert timeline.counts.line == "No annual report was read, so no 8-K was listed."


def test_every_status_an_event_can_have_has_its_words() -> None:
    from app.core import policy

    assert set(policy.EVENT_STATUS_LABELS) == {status.value for status in EventStatus}


def test_a_second_read_comes_from_the_cache_and_fetches_nothing() -> None:
    cache = FilingCache()
    read(FakeFilings.nvidia_with_events(), cache)
    again = FakeFilings.nvidia_with_events()
    timeline = read(again, cache)
    assert again.fetched == []
    assert timeline.counts.read == 7
    resignation = next(e for e in timeline.events if e.id == RESIGNATION)
    assert resignation.items[0].roles[:2] == ["President", "Chief Executive Officer"]


def test_an_offered_passage_is_an_exact_slice_marked_with_its_form_and_date() -> None:
    timeline = read(FakeFilings.nvidia_with_events())
    resignation = next(e for e in timeline.events if e.id == RESIGNATION)
    passages = service.event_passages(
        [(resignation, resignation.items[0])], timeline.documents, {RESIGNATION: "s9"}
    )
    assert len(passages) == 1
    passage = passages[0]
    document = timeline.documents[RESIGNATION]
    assert document.text[passage.start : passage.start + len(passage.text)] == passage.text
    assert (passage.source_id, passage.form, passage.filed) == ("s9", "8-K", "2026-11-12")
    assert passage.text.startswith("On November 11, 2026")
    assert passage.locator == resignation.items[0].locator


def test_outside_a_run_the_list_starts_after_the_newest_10k() -> None:
    filings = FakeFilings.nvidia_with_events()
    timeline, as_of = service.company_events(
        NVIDIA, filings, FilingCache(), today=date(2026, 11, 18)
    )
    assert filings.current_calls == [ANNUAL]
    assert timeline.counts.read == 7
    assert as_of.line == (
        "Evidence as of 12 Nov 2026 (8-K), 6 days before today. "
        "Newest periodic report: 10-Q filed 26 Aug 2026."
    )
