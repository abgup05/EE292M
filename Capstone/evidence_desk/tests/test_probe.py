"""The live segmentation probe, driven by a fake filing source (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import probe
from app.core.documents import FetchedFiling, FilingRef
from app.core.models import Company
from app.core.ports import SourceError, UnknownTicker
from app.probe import ProbeRow, build_table, probe_company, verdict

SEGMENTED = (
    "<html><body><div><b>Item 1. Business</b></div><div>We make things and sell them widely.</div>"
    "<div><b>Item 7. Discussion</b></div><div>Revenue grew in every quarter of the year.</div>"
    "</body></html>"
)
UNSEGMENTED = "<html><body><div>A filing that cross-references Items to pages.</div></body></html>"


def ref(form: str, period: str, accession: str) -> FilingRef:
    return FilingRef(
        cik=1,
        accession=accession,
        form=form,
        period_end=period,
        filed_date=period,
        primary_document="doc.htm",
        url=f"https://www.sec.gov/Archives/edgar/data/1/{accession}/doc.htm",
    )


class FakeSource:
    """A FilingSource with canned companies, filings and documents."""

    def __init__(self) -> None:
        self.companies = {
            "GOOD": Company(cik=1, ticker="GOOD", name="Good Co"),
            "BANK": Company(cik=2, ticker="BANK", name="Bank Co"),
            "NOK": Company(cik=3, ticker="NOK", name="Foreign Co"),
        }
        self.filings = {
            "GOOD": [ref("10-Q", "2026-07-31", "q-good"), ref("10-K", "2026-01-31", "k-good")],
            "BANK": [ref("10-Q", "2026-06-30", "q-bank"), ref("10-K", "2025-12-31", "k-bank")],
        }
        self.html = {"q-good": SEGMENTED, "k-good": SEGMENTED, "k-bank": UNSEGMENTED}
        self.limits: list[int] = []

    def company(self, ticker: str) -> Company:
        if ticker.upper() not in self.companies:
            raise UnknownTicker(f"Ticker {ticker.upper()} is not in SEC's company list")
        return self.companies[ticker.upper()]

    def periodic_filings(self, company: Company, limit: int) -> list[FilingRef]:
        self.limits.append(limit)
        if company.ticker not in self.filings:
            raise SourceError(f"No annual report (10-K) found for {company.name}")
        return self.filings[company.ticker][:limit]

    def fetch(self, filing: FilingRef) -> FetchedFiling:
        if filing.accession not in self.html:
            raise SourceError("EDGAR answered HTTP 404")
        retrieved = datetime(2026, 11, 17, tzinfo=UTC)
        return FetchedFiling(filing, self.html[filing.accession], retrieved)


@pytest.mark.parametrize(
    ("coverage", "expected"),
    [(1.0, "segmented"), (0.8, "segmented"), (0.79, "partly segmented"), (0.5, "partly segmented")]
    + [(0.49, "not segmented"), (0.0, "not segmented")],
)
def test_verdict_thresholds(coverage: float, expected: str) -> None:
    assert verdict(coverage) == expected


def test_probe_reads_the_annual_report_first_then_the_newest_quarterly() -> None:
    source = FakeSource()
    rows = probe_company(source, "good")
    assert source.limits == [2]
    assert [(row.ticker, row.form, row.period_end) for row in rows] == [
        ("GOOD", "10-K", "2026-01-31"),
        ("GOOD", "10-Q", "2026-07-31"),
    ]
    first = rows[0]
    assert first.error is None
    assert first.items == 2
    assert first.coverage == pytest.approx(1.0)
    assert first.html_bytes == len(SEGMENTED.encode())
    assert first.text_chars and first.sections == 2
    assert first.parse_seconds is not None


def test_failures_become_rows_and_the_other_companies_still_run() -> None:
    rows = probe.probe_all(FakeSource(), ["NOPE", "NOK", "BANK", "GOOD"])
    by_ticker = [(row.ticker, row.form, row.error) for row in rows]
    assert by_ticker[0] == ("NOPE", "", "Ticker NOPE is not in SEC's company list")
    assert by_ticker[1] == ("NOK", "", "No annual report (10-K) found for Foreign Co")
    assert by_ticker[2] == ("BANK", "10-K", None)
    assert by_ticker[3] == ("BANK", "10-Q", "EDGAR answered HTTP 404")
    assert [row.ticker for row in rows[4:]] == ["GOOD", "GOOD"]
    assert rows[2].coverage == 0.0


def test_table_has_every_column_and_one_row_per_filing() -> None:
    rows = [
        ProbeRow(
            ticker="GOOD",
            form="10-K",
            period_end="2026-01-31",
            accession="k-good",
            html_bytes=1_517_522,
            text_chars=151_303,
            sections=73,
            items=14,
            coverage=0.9612,
            parse_seconds=0.123,
        ),
        ProbeRow(ticker="NOPE", error="Ticker NOPE is not in SEC's company list"),
    ]
    lines = build_table(rows).splitlines()
    assert lines[0] == (
        "| Ticker | Form | Period end | Accession | HTML size | Text size | Sections "
        "| Items found | Item coverage | Parse time | Verdict |"
    )
    assert lines[1].count("|") == lines[0].count("|")
    assert lines[2] == (
        "| GOOD | 10-K | 2026-01-31 | k-good | 1,517,522 B | 151,303 chars | 73 | 14 "
        "| 96.1% | 0.12 s | segmented |"
    )
    assert lines[3] == (
        "| NOPE | | | | | | | | | | error: Ticker NOPE is not in SEC's company list |"
    )
    assert len(lines) == 4


def test_table_cells_cannot_break_the_markdown() -> None:
    table = build_table([ProbeRow(ticker="X", error="bad | pipe\nand newline")])
    assert table.splitlines()[2].endswith("| error: bad \\| pipe and newline |")


def test_main_prints_and_writes_the_table(tmp_path: Path, capsys) -> None:
    now = datetime(2026, 11, 17, 12, 30, 5, tzinfo=UTC)
    status = probe.main(["good", "nope"], source=FakeSource(), now=now, out_dir=tmp_path)
    assert status == 0
    written = (tmp_path / "probe-20261117T123005Z.md").read_text()
    printed = capsys.readouterr().out
    assert "| GOOD | 10-K |" in written
    assert "error: Ticker NOPE" in written
    assert build_table(probe.probe_all(FakeSource(), ["good", "nope"])) in printed


def test_outline_lists_each_filing_section_with_its_size() -> None:
    rows = probe_company(FakeSource(), "good", outline=True)
    assert rows[0].outline == (
        ("Item 1. Business", len("We make things and sell them widely.")),
        ("Item 7. Discussion", len("Revenue grew in every quarter of the year.")),
    )
    text = probe.build_outline(rows)
    assert text.startswith("### GOOD 10-K 2026-01-31 (k-good)\n")
    assert "     36  Item 1. Business\n" in text
    assert probe_company(FakeSource(), "good")[0].outline == ()


def test_main_appends_outlines_when_asked(tmp_path: Path, capsys) -> None:
    now = datetime(2026, 11, 17, 12, 30, 5, tzinfo=UTC)
    probe.main(["--outline", "good"], source=FakeSource(), now=now, out_dir=tmp_path)
    assert "### GOOD 10-Q" in (tmp_path / "probe-20261117T123005Z.md").read_text()
    assert "Item 7. Discussion" in capsys.readouterr().out
