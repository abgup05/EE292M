"""The breakdowns command line, driven by the recorded NVIDIA filings (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import breakdowns
from app.core.breakdown_models import BreakdownReport
from app.core.ports import SourceError
from app.services.breakdowns import filing_breakdowns
from tests.test_breakdowns import FormFilings, nvidia

NOW = datetime(2026, 11, 17, 12, 30, 5, tzinfo=UTC)
STEM = "breakdowns-NVDA-10-K-20261117T123005Z"


def run(tmp_path: Path, *argv: str, filings: FormFilings | None = None) -> int:
    return breakdowns.main(list(argv), source=filings or nvidia(), now=NOW, out_dir=tmp_path)


def test_main_prints_and_writes_the_markdown_and_the_record(tmp_path: Path, capsys) -> None:
    assert run(tmp_path, "nvda", "--form", "10-K") == 0
    markdown = (tmp_path / f"{STEM}.md").read_text()
    record = BreakdownReport.model_validate_json((tmp_path / f"{STEM}.json").read_text())
    assert record == filing_breakdowns("NVDA", "10-K", filings=nvidia())
    printed = capsys.readouterr().out
    assert markdown in printed
    assert f"breakdowns: wrote {tmp_path / STEM}.md and .json" in printed


def test_the_form_defaults_to_the_annual_report(tmp_path: Path) -> None:
    assert run(tmp_path, "NVDA") == 0
    assert (tmp_path / f"{STEM}.json").exists()


def test_the_quarterly_report_is_named_in_the_files(tmp_path: Path) -> None:
    assert run(tmp_path, "NVDA", "--form", "10-Q") == 0
    assert (tmp_path / "breakdowns-NVDA-10-Q-20261117T123005Z.md").exists()


def test_the_markdown_has_the_filing_then_one_table_per_breakdown(tmp_path: Path) -> None:
    run(tmp_path, "NVDA")
    markdown = (tmp_path / f"{STEM}.md").read_text()
    assert markdown.startswith("# Tagged breakdowns: NVIDIA CORP, 10-K\n")
    assert "| Accession | 0001045810-26-000021 |" in markdown
    assert "## Revenue by product or service" in markdown
    header = (
        "| Member | Fiscal year ended 2026-01-25 | Fiscal year ended 2025-01-26 "
        "| Fiscal year ended 2024-01-28 |"
    )
    assert header in markdown
    assert "| Data Center | 193,737 (+68.2%) | 115,186 (+142.4%) | 47,525 |" in markdown
    assert "| Total (tagged, no dimension) | 215,938 (+65.5%) |" in markdown
    assert "| Customer One · Compute and Networking Segment | 22.0% |" in markdown
    assert "us-gaap:Revenues" in markdown
    assert "(current − earlier) ÷ earlier" in markdown


def _tables(markdown: str) -> dict[str, list[list[str]]]:
    """Each breakdown's table, by its "## " heading: rows of cells, separator line dropped."""
    tables: dict[str, list[list[str]]] = {}
    heading = ""
    for line in markdown.splitlines():
        if line.startswith("## "):
            heading = line[3:]
        elif line.startswith("| Member |") or (heading in tables and line.startswith("|")):
            if not line.startswith("|---"):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                tables.setdefault(heading, []).append(cells)
    return tables


@pytest.mark.parametrize("form", ["10-K", "10-Q"])
def test_every_table_cell_is_a_string_from_the_record(tmp_path: Path, form: str) -> None:
    assert run(tmp_path, "NVDA", "--form", form) == 0
    stem = tmp_path / f"breakdowns-NVDA-{form}-20261117T123005Z"
    record = BreakdownReport.model_validate_json(stem.with_suffix(".json").read_text())
    tables = _tables(stem.with_suffix(".md").read_text())
    assert len(tables) == len(record.breakdowns)
    for item in record.breakdowns:
        expected = [["Member", *(period.label for period in item.periods)]]
        for label, values in [(r.label, r.values) for r in item.rows] + [
            (breakdowns.TOTAL_LABEL, item.total)
        ] * bool(item.total):
            by_end = {v.period_end: v for v in values}
            cells = [label]
            for period in item.periods:
                value = by_end.get(period.period_end)
                if value is None:
                    cells.append("")
                elif value.change_display:
                    cells.append(f"{value.display} ({value.change_display})")
                else:
                    cells.append(value.display)
            expected.append(cells)
        assert tables[item.title] == expected, item.id
        assert f"; {item.unit_label}." in stem.with_suffix(".md").read_text()


def test_an_unknown_ticker_exits_2_and_writes_nothing(tmp_path: Path, capsys) -> None:
    assert run(tmp_path, "NOPE") == 2
    assert "ticker:" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("where", ["index", "document"])
def test_an_edgar_failure_exits_1_and_writes_nothing(tmp_path: Path, capsys, where: str) -> None:
    filings = nvidia()
    if where == "index":
        filings.index_error = SourceError("EDGAR answered HTTP 503")
    else:
        filings.documents = {}
    assert run(tmp_path, "NVDA", filings=filings) == 1
    assert "SEC EDGAR:" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_an_unknown_form_is_refused_by_the_argument_parser(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exited:
        run(tmp_path, "NVDA", "--form", "8-K")
    assert exited.value.code == 2
