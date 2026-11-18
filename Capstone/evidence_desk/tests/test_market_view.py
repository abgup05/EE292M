"""The market view's pure parts: prices, shares outstanding, valuation, reverse DCF, reaction.

Expected values are worked by a route that does not call the function under test: a
closed form (a growing perpetuity), arithmetic written out in the comment, or a price
path built so that its returns are known.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from app.core.price_series import Close, PriceSeriesError, closes_until, parse_closes
from app.core.reaction import event_reaction
from app.core.reverse_dcf import DcfAssumptions, implied_growth, present_value, sensitivity
from app.core.valuation import shares_outstanding

# Prices


def test_a_csv_of_daily_closes_is_read_by_its_date_and_close_columns() -> None:
    text = "Date,Open,High,Low,Close,Volume\n2026-01-05,1,1,1,10.5,9\n2026-01-02,1,1,1,10,9\n"
    found = parse_closes(text)
    assert found == [Close(date(2026, 1, 2), 10.0), Close(date(2026, 1, 5), 10.5)]


def test_freds_csv_is_read_and_its_missing_days_skipped() -> None:
    text = "observation_date,SP500\n2026-01-01,\n2026-01-02,6000.5\n2026-01-05,.\n2026-01-06,6010\n"
    assert parse_closes(text) == [Close(date(2026, 1, 2), 6000.5), Close(date(2026, 1, 6), 6010.0)]


@pytest.mark.parametrize(
    "text",
    [
        "Date,Close\n2026-01-02,-5\n",  # not positive
        "Date,Close\n2026-01-02,1\n2026-01-02,2\n",  # a day twice
        "Date,Price\n2026-01-02,1\n",  # no close column
        "Date,Close\nyesterday,1\n",
        "",
    ],
)
def test_a_malformed_price_file_is_refused(text: str) -> None:
    with pytest.raises(PriceSeriesError):
        parse_closes(text)


def test_nothing_after_the_as_of_date_is_kept() -> None:
    closes = [Close(date(2026, 1, d), 1.0) for d in (2, 5, 6)]
    assert closes_until(closes, date(2026, 1, 5)) == closes[:2]


# Shares outstanding


def _dei(*entries: dict[str, object]) -> dict[str, object]:
    return {
        "cik": 1,
        "entityName": "X",
        "facts": {
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": list(entries)}}}
        },
    }


def test_shares_are_the_newest_cover_page_filed_by_the_date_summed_over_classes() -> None:
    facts = _dei(
        {"end": "2026-02-01", "val": 100, "accn": "a-1", "form": "10-K", "filed": "2026-02-20"},
        # The next filing reports two share classes on one date: summed, 70 + 40.
        {"end": "2026-05-01", "val": 70, "accn": "a-2", "form": "10-Q", "filed": "2026-05-20"},
        {"end": "2026-05-01", "val": 40, "accn": "a-2", "form": "10-Q", "filed": "2026-05-20"},
        {"end": "2026-08-01", "val": 999, "accn": "a-3", "form": "10-Q", "filed": "2026-08-20"},
    )
    found = shares_outstanding(facts, date(2026, 6, 30))
    assert not isinstance(found, str)
    assert (found.value, found.day, found.accession, found.classes) == (
        110.0,
        date(2026, 5, 1),
        "a-2",
        2,
    )
    early = shares_outstanding(facts, date(2026, 3, 1))
    assert not isinstance(early, str) and early.value == 100.0
    assert isinstance(shares_outstanding(facts, date(2026, 1, 1)), str)


# Reverse DCF


def test_present_value_of_a_growing_perpetuity_is_the_gordon_formula() -> None:
    # No reinvestment (sales-to-capital so large it is nil) and growth equal to the
    # terminal growth: the cash flows are k × R0 × (1 + g)^t forever, worth
    # k × R0 × (1 + g) ÷ (r − g) = 0.25 × 100 × 1.03 ÷ 0.06 = 429.1667.
    a = DcfAssumptions(
        revenue=100.0,
        operating_margin=25.0,
        tax_rate=0.0,
        sales_to_capital=1e15,
        discount_rate=9.0,
        terminal_growth=3.0,
    )
    gordon = 0.25 * 100 * 1.03 / 0.06
    assert present_value(3.0, a) == pytest.approx(gordon, rel=1e-9)
    solved = implied_growth(gordon, a)
    assert solved.growth == pytest.approx(3.0, abs=1e-6)


def test_present_value_of_a_two_year_model_by_hand() -> None:
    # Revenue 100, growth 10%, margin 10%, no tax, sales-to-capital 1, r 10%, g∞ 0, 2 years.
    # Year 1: revenue 110, NOPAT 11, reinvestment 10, cash 1, ÷ 1.1 = 0.909091.
    # Year 2: revenue 121, NOPAT 12.1, reinvestment 11, cash 1.1, ÷ 1.21 = 0.909091.
    # Terminal: revenue 121, NOPAT 12.1, no reinvestment: 12.1 ÷ 0.10 = 121, ÷ 1.21 = 100.
    a = DcfAssumptions(
        revenue=100.0,
        operating_margin=10.0,
        tax_rate=0.0,
        sales_to_capital=1.0,
        discount_rate=10.0,
        terminal_growth=0.0,
        years=2,
    )
    by_hand = 1 / 1.1 + 1.1 / 1.21 + 121 / 1.21
    assert present_value(10.0, a) == pytest.approx(by_hand, rel=1e-12)
    assert implied_growth(by_hand, a).growth == pytest.approx(10.0, abs=1e-6)


def test_no_growth_is_a_flat_perpetuity() -> None:
    # Margin 20%, tax 25%: k = 0.15. Revenue 1000, r 10%: 150 ÷ 0.10 = 1500, whatever
    # the sales-to-capital, since nothing is reinvested.
    a = DcfAssumptions(1000.0, 20.0, 25.0, 0.7, 10.0, 0.0)
    assert present_value(0.0, a) == pytest.approx(1500.0, rel=1e-12)
    assert implied_growth(1500.0, a).growth == pytest.approx(0.0, abs=1e-6)


def test_a_price_no_growth_can_reach_is_not_solved_and_says_why() -> None:
    a = DcfAssumptions(100.0, 25.0, 0.0, 1e15, 9.0, 3.0)
    found = implied_growth(1e12, a)
    assert found.growth is None
    assert "above" in found.reason


def test_assumptions_are_validated() -> None:
    with pytest.raises(ValueError, match="terminal growth"):
        DcfAssumptions(100.0, 25.0, 21.0, 2.0, 5.0, 5.0)
    with pytest.raises(ValueError, match="sales-to-capital"):
        DcfAssumptions(100.0, 25.0, 21.0, 0.0, 9.0, 3.0)


def test_the_sensitivity_grid_moves_the_way_the_arithmetic_says() -> None:
    # A higher discount rate needs more growth to reach the same value; a higher margin less.
    a = DcfAssumptions(100.0, 25.0, 21.0, 2.0, 9.0, 3.0)
    target = present_value(12.0, a)
    grid = sensitivity(target, a)
    assert len(grid) == 15
    centre = next(c for c in grid if c.discount_rate == 9.0 and c.operating_margin == 25.0)
    assert centre.implied_growth == pytest.approx(12.0, abs=1e-6)
    by = {(c.discount_rate, c.operating_margin): c.implied_growth for c in grid}
    assert by[(11.0, 25.0)] > by[(9.0, 25.0)] > by[(7.0, 25.0)]
    assert by[(9.0, 20.0)] > by[(9.0, 25.0)] > by[(9.0, 30.0)]


# Reaction to an event


def _weekdays(start: date, count: int) -> list[date]:
    days: list[date] = []
    day = start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def test_the_reaction_is_the_move_against_the_index_in_units_of_its_normal_move() -> None:
    # 61 closes alternate +1% and -1% (60 daily returns); the index is flat, so the excess
    # returns alternate +0.01 and -0.01: mean 0, sample standard deviation
    # 0.01 × sqrt(60 ÷ 59). The 8-K is filed the day after the 61st close; the stock
    # falls 5% that day and stays flat. Over 3 days: -5% against 0%, a normal 3-day move
    # of 0.01 × sqrt(60/59) × sqrt(3) × 100 = 1.7466%, ratio -2.863.
    days = _weekdays(date(2026, 1, 5), 70)
    stock: list[Close] = []
    value = 100.0
    for i, day in enumerate(days[:61]):
        if i:
            value *= 1.01 if i % 2 else 0.99
        stock.append(Close(day, value))
    base = value
    stock += [Close(day, base * 0.95) for day in days[61:]]
    index = [Close(day, 1000.0) for day in days]
    filed = days[61]
    found = event_reaction(stock, index, filed, days=3, as_of=days[-1])
    assert not isinstance(found, str), found
    window = found[0]
    assert (window.start, window.end, window.days) == (
        days[60].isoformat(),
        days[63].isoformat(),
        3,
    )
    assert window.stock_return == pytest.approx(-5.0)
    assert window.index_return == pytest.approx(0.0)
    normal = 0.01 * math.sqrt(60 / 59) * math.sqrt(3) * 100
    assert window.normal == pytest.approx(normal)
    assert window.ratio == pytest.approx(-5.0 / normal)
    assert (
        window.line == "-5.0% against the index over 3 trading days, "
        f"{5 / normal:.1f} times its normal 3-day move (down)"
    )
    latest = found[1]
    assert latest.end == days[-1].isoformat()
    assert latest.days == 70 - 61


def test_no_close_after_the_as_of_date_is_read() -> None:
    days = _weekdays(date(2026, 1, 5), 80)
    stock = [Close(d, 100.0 + i) for i, d in enumerate(days)]
    found = event_reaction(stock, None, days[70], days=3, as_of=days[71])
    assert not isinstance(found, str)
    # Only one close after the base is on or before the as-of date: no 3-day window.
    assert [w.name for w in found] == ["to the latest close"]
    assert found[0].end == days[71].isoformat()


def test_too_short_a_history_is_said_not_guessed() -> None:
    days = _weekdays(date(2026, 1, 5), 20)
    stock = [Close(d, 100.0) for d in days]
    found = event_reaction(stock, None, days[10], days=3, as_of=days[-1])
    assert not isinstance(found, str)
    assert found[0].normal is None
    assert "fewer than 60" in found[0].line
