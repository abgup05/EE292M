"""The live header-cut check, driven by the recorded filings (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tests import header_cut_check
from tests.fakes import FY_2026, Q2_2027, FakeFilings
from tests.header_cut_check import CutRow, build_table, check_company

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def test_the_recorded_filings_parse_to_the_same_document_both_ways() -> None:
    rows = check_company(FakeFilings.nvidia(FY_2026, Q2_2027), "NVDA")
    assert [row.form for row in rows] == ["10-K", "10-Q"]
    assert all(row.error is None and row.has_header and row.same for row in rows)
    assert all(len(row.content_hash) == 64 and row.text_chars > 100_000 for row in rows)


def test_a_difference_is_seen_and_fails_the_command(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """If the uncut parse gave another document, the row says NO and the exit code is 1."""
    monkeypatch.setattr(header_cut_check, "_no_cut", lambda html: (html + "<p>More text.</p>", ""))
    source = FakeFilings.nvidia()
    rows = check_company(source, "NVDA")
    assert rows and not any(row.same for row in rows)
    assert header_cut_check.main(["NVDA"], source=source, now=NOW, out_dir=tmp_path) == 1
    assert "| NO |" in (tmp_path / "header-cut-20261117T120000Z.md").read_text()


def test_an_unknown_ticker_is_a_row_and_fails_the_command(tmp_path: Path) -> None:
    source = FakeFilings.nvidia()
    assert header_cut_check.main(["NOPE"], source=source, now=NOW, out_dir=tmp_path) == 1
    table = build_table([CutRow(ticker="NOPE", error="Ticker NOPE is not in SEC's company list")])
    assert "could not be compared" in table and "0 of 0 filings" in table
