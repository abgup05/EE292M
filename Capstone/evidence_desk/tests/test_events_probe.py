"""``python -m app.events_probe``: found over listed items, on the recorded NVIDIA 8-Ks."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.core.ports import SourceError
from app.events_probe import NO_HEADING, main, probe_company
from tests.fakes import FakeFilings, current_report_html, current_report_ref


def test_every_item_nvidia_listed_is_found_in_its_8k() -> None:
    result = probe_company("NVDA", FakeFilings.nvidia_with_events(), "2025-11-18")
    assert (result.filings, result.error) == (11, "")
    assert result.listed == 18
    assert (result.found, result.misses) == (18, [])
    # The 8-Ks of 3 Sep and 17 Aug 2026 head an Item 9.01 the index does not list.
    assert result.unlisted == 2


def test_a_listed_item_with_no_heading_is_a_miss_with_its_reason() -> None:
    filings = FakeFilings.nvidia_with_events()
    ref = current_report_ref(7, "2026-11-13", "5.02", "8.01")
    filings.current = [ref]
    filings.documents[ref.url] = current_report_html(
        ("5.02", "Departure of Directors.", ["A director resigned from the Board today."])
    )
    result = probe_company("NVDA", filings, "2025-11-18")
    assert (result.listed, result.found) == (2, 1)
    [miss] = result.misses
    assert (miss.item, miss.reason, miss.accession) == ("8.01", NO_HEADING, ref.accession)


def test_a_filing_that_cannot_be_fetched_misses_every_item_it_lists() -> None:
    filings = FakeFilings.nvidia_with_events()
    ref = current_report_ref(8, "2026-11-13", "2.02", "9.01")
    filings.current = [ref]
    filings.documents[ref.url] = SourceError("EDGAR answered HTTP 404")
    result = probe_company("NVDA", filings, "2025-11-18")
    assert (result.listed, result.found) == (2, 0)
    assert {m.reason for m in result.misses} == {"EDGAR answered HTTP 404"}


def test_main_writes_the_report_with_its_denominator(tmp_path: Path, capsys) -> None:
    filings = FakeFilings.nvidia_with_events()
    code = main(["NVDA"], source=filings, today=date(2026, 11, 18), out_dir=tmp_path)
    assert code == 0
    out = capsys.readouterr().out
    assert "| NVDA | 11 | 18 | 18/18 (100.0%) | 2 |  |" in out
    assert "Denominator: the items the index lists." in out
    assert len(list(tmp_path.glob("events-probe-*.md"))) == 1
