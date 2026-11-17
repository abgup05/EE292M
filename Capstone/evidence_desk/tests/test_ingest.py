"""Ingest: select, retrieve, parse, deduplicate and record every requested source."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.models import ExtractionStatus, Run, RunStatus, SourceKind, ThesisRequest
from app.core.ports import SourceError
from app.services import ingest as ingest_module
from app.services.ingest import ingest
from app.sources.http import FetchError
from app.store import Store
from tests.fakes import (
    FY_2026,
    NVIDIA,
    Q1_2027,
    Q2_2027,
    RETRIEVED_AT,
    FakeFilings,
    FakePages,
    filing_html,
)

CLAIM = "Data center revenue is still growing year over year."
PAGE = "<html><head><title>Press release</title></head><body><p>{}</p></body></html>"


def make_run(filings: int = 3, extra_urls: list[str] | None = None) -> Run:
    request = ThesisRequest(
        ticker="NVDA",
        decision="Whether to keep the position into the next earnings report",
        claims=[CLAIM],
        filings=filings,
        extra_urls=extra_urls or [],
    )
    return Run(
        id="run-test",
        inputs=request,
        status=RunStatus.running,
        started_at=datetime(2026, 11, 17, tzinfo=UTC),
    )


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "runs.sqlite")


def never() -> bool:
    return False


def test_filings_are_read_newest_first_then_extra_pages(store: Store) -> None:
    run = make_run(filings=1, extra_urls=["https://investor.example.com/q2"])
    pages = FakePages(
        {"https://investor.example.com/q2": ("https://investor.example.com/q2", PAGE.format("x"))}
    )
    result = ingest(
        run,
        NVIDIA,
        store,
        filings=FakeFilings.nvidia(Q2_2027),
        fetch_page=pages,
        out_of_time=never,
    )
    assert [s.id for s in run.sources] == ["s1", "s2"]
    filing, page = run.sources
    assert filing.kind == SourceKind.sec_filing
    assert filing.extraction_status == ExtractionStatus.extracted
    assert (filing.form, filing.accession) == ("10-Q", "0001045810-26-000075")
    assert (filing.period_end, filing.published_date) == ("2026-07-26", "2026-08-26")
    assert filing.retrieved_at == RETRIEVED_AT
    assert filing.title == "NVIDIA CORP 10-Q, period ended 2026-07-26"
    assert filing.sections > 10 and filing.characters == len(result.documents["s1"].text)
    assert page.kind == SourceKind.public_html and page.title == "Press release"
    assert result.requested == 2 and set(result.documents) == {"s1", "s2"}
    assert store.get_source_texts(run.id) == {
        source_id: document.text for source_id, document in result.documents.items()
    }


def test_a_failed_filing_is_recorded_and_the_others_are_still_read(store: Store) -> None:
    run = make_run()
    filings = FakeFilings.nvidia(Q2_2027, Q1_2027, FY_2026)  # Q1 was not recorded: HTTP 404
    result = ingest(
        run, NVIDIA, store, filings=filings, fetch_page=FakePages({}), out_of_time=never
    )
    statuses = [(s.id, s.extraction_status) for s in run.sources]
    assert statuses == [
        ("s1", ExtractionStatus.extracted),
        ("s2", ExtractionStatus.failed),
        ("s3", ExtractionStatus.extracted),
    ]
    assert run.sources[1].error == f"EDGAR answered HTTP 404 for {Q1_2027.url}"
    assert run.sources[1].form == "10-Q" and run.sources[1].accession == Q1_2027.accession
    assert result.requested == 3 and set(result.documents) == {"s1", "s3"}


def test_a_filing_that_cannot_be_parsed_is_recorded_not_fatal(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_parse = ingest_module.parse_filing

    def parse(html: str, **kwargs: object) -> object:
        if "BROKEN" in html:
            raise RecursionError("maximum recursion depth exceeded")
        return real_parse(html, **kwargs)

    monkeypatch.setattr(ingest_module, "parse_filing", parse)
    filings = FakeFilings.synthetic(filing_html("BROKEN"), filing_html("A readable paragraph."))
    run = make_run(filings=2)
    result = ingest(
        run, NVIDIA, store, filings=filings, fetch_page=FakePages({}), out_of_time=never
    )
    assert run.sources[0].extraction_status == ExtractionStatus.failed
    assert run.sources[0].error == "The document could not be parsed (RecursionError)"
    assert set(result.documents) == {"s2"}


def test_an_unreadable_index_still_counts_the_filings_asked_for(store: Store) -> None:
    run = make_run(filings=3, extra_urls=["https://investor.example.com/q2"])
    filings = FakeFilings.nvidia()
    filings.index_error = SourceError("EDGAR could not be reached (ConnectError)")
    pages = FakePages(
        {"https://investor.example.com/q2": ("https://investor.example.com/q2", PAGE.format("x"))}
    )
    result = ingest(run, NVIDIA, store, filings=filings, fetch_page=pages, out_of_time=never)
    assert run.errors == [
        "The filing index could not be read: EDGAR could not be reached (ConnectError)"
    ]
    assert set(result.documents) == {"s1"}
    # Three filings and one page were asked for; one page is not a complete reading.
    assert result.requested == 4


def test_fewer_filings_than_requested_is_a_coverage_limit(store: Store) -> None:
    run = make_run(filings=5)
    result = ingest(
        run,
        NVIDIA,
        store,
        filings=FakeFilings.nvidia(Q2_2027, FY_2026),
        fetch_page=FakePages({}),
        out_of_time=never,
    )
    assert result.requested == 2
    assert run.coverage_limits == [
        "5 filing(s) were requested; EDGAR lists 2 (the latest annual report and the "
        "quarterly reports filed after it)."
    ]


def test_identical_content_is_read_once(store: Store) -> None:
    same = filing_html("Data Center revenue grew 56% from a year ago.")
    run = make_run(filings=2)
    result = ingest(
        run,
        NVIDIA,
        store,
        filings=FakeFilings.synthetic(same, same),
        fetch_page=FakePages({}),
        out_of_time=never,
    )
    assert set(result.documents) == {"s1"}
    assert run.sources[1].error == "Duplicate of s1 (identical content)"
    assert result.duplicates == 1
    assert set(store.get_source_texts(run.id)) == {"s1"}


def test_a_page_redirecting_to_one_already_read_is_a_duplicate(store: Store) -> None:
    urls = ["https://investor.example.com/a", "https://investor.example.com/b"]
    pages = FakePages(
        {
            urls[0]: ("https://investor.example.com/a", PAGE.format("first")),
            urls[1]: ("https://investor.example.com/a/", PAGE.format("second")),
        }
    )
    run = make_run(filings=1, extra_urls=urls)
    result = ingest(
        run,
        NVIDIA,
        store,
        filings=FakeFilings.synthetic(filing_html("Filing text.")),
        fetch_page=pages,
        out_of_time=never,
    )
    assert run.sources[2].error == "Duplicate of s2 (same page)"
    assert set(result.documents) == {"s1", "s2"} and result.duplicates == 1


def test_a_failed_page_is_recorded_with_its_error(store: Store) -> None:
    url = "https://investor.example.com/gone"
    run = make_run(filings=1, extra_urls=[url])
    result = ingest(
        run,
        NVIDIA,
        store,
        filings=FakeFilings.synthetic(filing_html("Filing text.")),
        fetch_page=FakePages({url: FetchError("HTTP 403")}),
        out_of_time=never,
    )
    assert run.sources[1].extraction_status == ExtractionStatus.failed
    assert run.sources[1].error == "HTTP 403"
    assert set(result.documents) == {"s1"}


def test_the_time_limit_stops_fetching_and_says_how_many_were_skipped(store: Store) -> None:
    calls = iter([False, True, True])
    run = make_run(filings=3)
    filings = FakeFilings.synthetic(filing_html("One."), filing_html("Two."), filing_html("Three."))
    result = ingest(
        run,
        NVIDIA,
        store,
        filings=filings,
        fetch_page=FakePages({}),
        out_of_time=lambda: next(calls),
    )
    assert result.time_limit_hit
    assert set(result.documents) == {"s1"}
    assert len(filings.fetched) == 1
    assert run.coverage_limits == ["The run time limit was reached; 2 source(s) were not fetched."]


def test_a_filing_mostly_outside_item_headings_is_a_coverage_limit(store: Store) -> None:
    paragraph = "<p>Paragraph {} of a filing whose Item headings are missing.</p>"
    no_items = "<html><body>" + "".join(paragraph.format(n) for n in range(40)) + "</body></html>"
    run = make_run(filings=2)
    filings = FakeFilings.synthetic(no_items, filing_html("A readable paragraph under an Item."))
    ingest(run, NVIDIA, store, filings=filings, fetch_page=FakePages({}), out_of_time=never)
    title = run.sources[0].title
    assert run.coverage_limits == [
        f"Item headings were not found for most of {title}; "
        "its passages are located by sub-heading only."
    ]


def test_the_recorded_10q_has_no_item_coverage_limit(store: Store) -> None:
    run = make_run(filings=1)
    ingest(
        run,
        NVIDIA,
        store,
        filings=FakeFilings.nvidia(Q2_2027),
        fetch_page=FakePages({}),
        out_of_time=never,
    )
    assert run.coverage_limits == []
