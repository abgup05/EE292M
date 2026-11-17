"""The reported-figures probe, driven by a fake filing source (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app import figures
from app.core.models import Company
from app.core.ports import SourceError
from app.figures import QuarterRow, build_table, probe_company
from tests.fakes import NVIDIA, FakeFilings
from tests.test_facts import costco_revenue

COSTCO = Company(ticker="COST", name="COSTCO WHOLESALE CORP /NEW", cik=909832)
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def costco() -> FakeFilings:
    return FakeFilings(refs=[], documents={}, companies={"COST": COSTCO}, facts=costco_revenue())


def test_a_week_based_year_shows_four_quarters_with_their_lengths() -> None:
    result = probe_company(costco(), "COST")
    assert result.error is None
    rows = {row.quarter_end: row for row in result.rows}
    fourth = rows["2026-08-30"]
    assert fourth == QuarterRow(
        quarter_end="2026-08-30",
        days=112,
        revenue="$95.72B",
        source="derived",
        on_year_earlier="+11.1%",
        on_quarter_before="n/a",
        cash_flow="n/a",
    )
    assert rows["2026-05-10"].days == 84 and rows["2026-05-10"].source == "reported"
    assert rows["2026-05-10"].on_quarter_before == "+1.3%"
    # Newest first, as many quarters as the report holds.
    assert [row.quarter_end for row in result.rows][:2] == ["2026-08-30", "2026-05-10"]


def test_the_metrics_without_a_value_are_counted_with_their_total() -> None:
    result = probe_company(costco(), "COST")
    assert result.figures_offered > 0
    # Revenue is all this fixture holds, so margins and cash flow have no value.
    assert 0 < result.metrics_without_value < result.metrics_total
    assert {"gross_margin", "revenue_yoy"} <= set(result.keys_without_value)


def test_an_unknown_ticker_and_an_edgar_failure_are_rows_not_exceptions() -> None:
    unknown = probe_company(costco(), "NOPE")
    assert unknown.rows == [] and "NOPE" in (unknown.error or "")
    broken = costco()
    broken.facts_error = SourceError("EDGAR answered HTTP 503 for the company facts")
    failed = probe_company(broken, "COST")
    assert failed.rows == [] and "HTTP 503" in (failed.error or "")


def test_the_table_has_one_line_per_quarter_and_names_a_failure() -> None:
    table = build_table([probe_company(costco(), "COST"), probe_company(costco(), "NOPE")])
    assert "| COST | 2026-08-30 | 112 | $95.72B | derived | +11.1% | n/a | n/a |" in table
    assert "| NOPE | could not be read:" in table
    assert "- COST: a run would offer " in table and " metrics have no value" in table
    assert "Without a value in some period: " in table and "gross_margin" in table


def test_main_prints_the_table_and_writes_it(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    source = FakeFilings.nvidia()
    assert figures.main(["NVDA"], source=source, now=NOW, out_dir=tmp_path) == 0
    printed = capsys.readouterr().out
    written = (tmp_path / "figures-20261117T120000Z.md").read_text()
    assert "| NVDA | 2026-07-26 | 91 |" in printed and "| NVDA | 2026-07-26 | 91 |" in written
    assert NVIDIA.ticker in written and "figures: wrote" in printed
