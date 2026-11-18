"""Facts as of a date: a FactBook sees only what had been filed by then.

Synthetic facts test the rule; the recorded fixtures of NVIDIA, Apple and Microsoft
carry the no-lookahead proof for the metrics report: as of every date on which one of
them filed a 10-K or 10-Q, and the day before each, (a) no fact reference in the
report was filed after the date, and (b) the report equals the one built from the
payload with every later fact deleted (:mod:`tests.lookahead`). The same two checks
are run against a deliberately leaky filter to show that they catch it.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from app.core import facts as facts_module
from app.core.facts import FactBook
from app.core.metrics import build_report
from app.core.periods import fiscal_calendar
from tests.lookahead import filing_dates, late_refs, pruned
from tests.test_facts import companyfacts, fact, load_fixture

TICKERS = ("NVDA", "AAPL", "MSFT")


def _restated_revenue() -> dict[str, Any]:
    """FY2024 revenue first reported as 100, then restated to 90 in a later 10-K."""
    return companyfacts(
        {
            "Revenues": [
                fact(100.0, "2024-12-31", "2024-01-01", filed="2025-02-01", accn="a-1"),
                fact(90.0, "2024-12-31", "2024-01-01", filed="2026-02-01", accn="a-2"),
                fact(120.0, "2025-12-31", "2025-01-01", filed="2026-02-01", accn="a-2"),
            ]
        }
    )


def test_without_a_date_every_fact_is_seen() -> None:
    book = FactBook(_restated_revenue())
    assert book.as_of is None
    values = {end.isoformat(): v.value for end, v in book.annuals("revenue").items()}
    assert values == {"2024-12-31": 90.0, "2025-12-31": 120.0}
    assert book.annuals("revenue")[date(2024, 12, 31)].restated


def test_as_of_a_date_a_later_filing_is_not_seen() -> None:
    book = FactBook(_restated_revenue(), as_of=date(2025, 6, 30))
    values = {end.isoformat(): v.value for end, v in book.annuals("revenue").items()}
    assert values == {"2024-12-31": 100.0}
    assert not book.annuals("revenue")[date(2024, 12, 31)].restated


def test_a_fact_filed_on_the_date_is_seen() -> None:
    book = FactBook(_restated_revenue(), as_of=date(2026, 2, 1))
    assert book.annuals("revenue")[date(2024, 12, 31)].value == 90.0


def test_a_payload_with_nothing_filed_by_the_date_gives_an_empty_book() -> None:
    book = FactBook(_restated_revenue(), as_of=date(2020, 1, 1))
    assert book.annuals("revenue") == {}
    assert build_report(book).metrics == []


def test_the_fiscal_calendar_as_of_a_date_reads_the_newest_annual_report_by_then() -> None:
    payload = companyfacts(
        {
            "Revenues": [
                fact(1.0, "2024-01-28", "2023-01-30", filed="2024-02-21", accn="k-1", fy=2024),
                # A later report labels its year one off: the calendar as of 2024 must not see it.
                fact(2.0, "2025-01-26", "2024-01-29", filed="2025-02-26", accn="k-2", fy=2026),
            ]
        }
    )
    early = fiscal_calendar(payload, as_of=date(2024, 6, 1))
    late = fiscal_calendar(payload)
    assert early is not None and early.label_offset == 0 and early.year_end == date(2024, 1, 28)
    assert late is not None and late.label_offset == 1


# The proof on the recorded fixtures


def _dates(payload: dict[str, Any]) -> list[date]:
    """Every periodic filing date and the day before each."""
    days = filing_dates(payload)
    return sorted({*days, *(day - timedelta(days=1) for day in days)})


def lookahead_problems(ticker: str) -> list[str]:
    """Every date on which the metrics report as of it fails check (a) or (b), with why."""
    payload = load_fixture(ticker)
    problems: list[str] = []
    for day in _dates(payload):
        report = build_report(FactBook(payload, as_of=day))
        late = late_refs(report, day)
        if late:
            problems.append(f"{ticker} as of {day}: {len(late)} late reference(s), e.g. {late[0]}")
        independent = build_report(FactBook(pruned(payload, day)))
        if report != independent:
            problems.append(f"{ticker} as of {day}: differs from the pruned payload's report")
    return problems


@pytest.mark.parametrize("ticker", TICKERS)
def test_no_fact_filed_after_the_date_reaches_the_metrics_report(ticker: str) -> None:
    assert lookahead_problems(ticker) == []


@pytest.mark.parametrize("ticker", TICKERS)
def test_the_dates_checked_are_many(ticker: str) -> None:
    assert len(_dates(load_fixture(ticker))) >= 120


def test_the_checks_catch_a_filter_that_reads_the_period_end_instead_of_the_filing_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def leaky(raw: object, as_of: date | None) -> bool:
        # A fact whose period has ended counts as known: the 10-K that reports it is filed
        # weeks later, so this lets the future in.
        if as_of is None or not isinstance(raw, dict):
            return True
        return date.fromisoformat(str(raw["end"])) <= as_of

    monkeypatch.setattr(facts_module, "filed_by", leaky)
    problems = lookahead_problems("NVDA")
    assert any("late reference" in line for line in problems)
    assert any("differs from the pruned" in line for line in problems)
