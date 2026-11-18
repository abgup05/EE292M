"""Analytics from dated facts: every expected value is worked out here from the definitions.

A synthetic company (calendar fiscal years 2023 to 2025, every quarter tagged as a
three-month fact, a 10-Q for each of the first three quarters and a 10-K for the fourth)
has values that are simple functions of the quarter's index ``i`` (0 for Q1 2023 to 11 for
Q4 2025), so each expected number below is computed straight from those functions, not
from the code under test.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import pytest

from app.core.analytics import (
    AnalyticsRequest,
    FactsProvider,
    bridge_analytics,
    earnings_quality,
    measure_analytics,
    computed_test_analytics,
)
from app.core.claim_eval import HistoryBooks, Measures, claim_history, evaluate
from app.core.claimtest import ClaimTest, compile_claim
from app.core.facts import FactBook
from app.core.periods import fiscal_calendar
from tests.test_facts import companyfacts, fact

ENDS = ("03-31", "06-30", "09-30", "12-31")
STARTS = ("01-01", "04-01", "07-01", "10-01")
M = 1_000_000
LAST = 11


def revenue(i: int) -> float:
    return (100 + 10 * i) * M


def gross_margin(i: int) -> float:
    return 0.50 + 0.01 * i


def operating_margin(i: int) -> float:
    return 0.20 + 0.005 * i


def net_income(i: int) -> float:
    return 0.8 * revenue(i) * operating_margin(i)


def cost(i: int) -> float:
    return revenue(i) * (1 - gross_margin(i))


FLOWS = {
    "Revenues": revenue,
    "CostOfRevenue": cost,
    "GrossProfit": lambda i: revenue(i) * gross_margin(i),
    "OperatingIncomeLoss": lambda i: revenue(i) * operating_margin(i),
    "ResearchAndDevelopmentExpense": lambda i: 0.10 * revenue(i),
    "NetIncomeLoss": net_income,
    "NetCashProvidedByUsedInOperatingActivities": lambda i: net_income(i) + 5 * M,
    "PaymentsToAcquirePropertyPlantAndEquipment": lambda i: 3 * M,
    "ShareBasedCompensation": lambda i: 2 * M,
    "DepreciationDepletionAndAmortization": lambda i: 1 * M,
}
BALANCES = {
    "AccountsReceivableNetCurrent": lambda i: (50 + 2 * i) * M,
    "InventoryNet": lambda i: (30 + i) * M,
    "Assets": lambda i: (1000 + 20 * i) * M,
    "StockholdersEquity": lambda i: (600 + 10 * i) * M,
    "ContractWithCustomerLiabilityCurrent": lambda i: (40 + i) * M,
}


def _filed(year: int, quarter: int) -> dict[str, Any]:
    if quarter < 4:
        end = date.fromisoformat(f"{year}-{ENDS[quarter - 1]}")
        filed = (end + timedelta(days=40)).isoformat()
        return {"filed": filed, "accn": f"q-{year}-{quarter}", "form": "10-Q", "fy": year,
                "fp": f"Q{quarter}"}
    return {"filed": f"{year + 1}-02-15", "accn": f"k-{year}", "form": "10-K", "fy": year,
            "fp": "FY"}


def synthetic() -> dict[str, Any]:
    concepts: dict[str, list[dict[str, Any]]] = {name: [] for name in (*FLOWS, *BALANCES)}
    for year in (2023, 2024, 2025):
        for quarter in range(1, 5):
            i = (year - 2023) * 4 + quarter - 1
            kw = _filed(year, quarter)
            start, end = f"{year}-{STARTS[quarter - 1]}", f"{year}-{ENDS[quarter - 1]}"
            for name, value in FLOWS.items():
                concepts[name].append(fact(round(value(i)), end, start, **kw))
            for name, value in BALANCES.items():
                concepts[name].append(fact(round(value(i)), end, **kw))
    return companyfacts(concepts)


@pytest.fixture(scope="module")
def payload() -> dict[str, Any]:
    return synthetic()


@pytest.fixture(scope="module")
def measures(payload: dict[str, Any]) -> Measures:
    return Measures(FactBook(payload), fiscal_calendar(payload))


def _by_id(items: list[Any]) -> dict[str, Any]:
    return {item.id: item for item in items}


def test_a_measures_level_changes_trends_acceleration_range_and_typical_move(
    measures: Measures,
) -> None:
    got = _by_id(measure_analytics(measures, "revenue", ["c1"]))
    r = revenue
    assert got["an:revenue:level"].value == pytest.approx(r(LAST))
    assert got["an:revenue:yoy"].value == pytest.approx((r(11) / r(7) - 1) * 100)
    assert got["an:revenue:qoq"].value == pytest.approx((r(11) / r(10) - 1) * 100)
    assert got["an:revenue:trend4"].value == pytest.approx(((r(11) / r(7)) ** 0.25 - 1) * 100)
    assert got["an:revenue:trend8"].value == pytest.approx(((r(11) / r(3)) ** 0.125 - 1) * 100)
    growth_now, growth_before = r(11) / r(7) - 1, r(10) / r(6) - 1
    assert got["an:revenue:acceleration"].value == pytest.approx(
        (growth_now - growth_before) * 100
    )
    assert "slowing" in got["an:revenue:acceleration"].reading
    assert got["an:revenue:range8"].value == pytest.approx(100.0)  # rising: at the high
    assert "at the high" in got["an:revenue:range8"].reading
    moves = sorted(abs(r(i) / r(i - 1) - 1) for i in range(4, 12))
    assert got["an:revenue:typical_move"].value == pytest.approx(
        (moves[3] + moves[4]) / 2 * 100
    )
    assert all(item.claim_ids == ["c1"] for item in got.values())
    assert all(item.reading_origin == "code" and item.reading for item in got.values())


def test_a_ratio_moves_in_points(measures: Measures) -> None:
    got = _by_id(measure_analytics(measures, "gross_margin"))
    assert got["an:gross_margin:level"].value == pytest.approx(gross_margin(11) * 100)
    assert got["an:gross_margin:yoy"].unit == "points"
    assert got["an:gross_margin:yoy"].value == pytest.approx(4.0)
    assert got["an:gross_margin:trend8"].value == pytest.approx(8.0)
    assert got["an:gross_margin:typical_move"].value == pytest.approx(1.0)
    assert got["an:gross_margin:yoy"].display == "+4.0 percentage points"
    assert "an:gross_margin:acceleration" not in got


def _computed(claim: str, payload: dict[str, Any]) -> tuple[ClaimTest, Any]:
    test = compile_claim(claim)
    assert isinstance(test, ClaimTest), test
    book = FactBook(payload)
    result = evaluate(test, book, calendar=fiscal_calendar(payload))
    history, note = claim_history(test, payload, books=HistoryBooks(payload))
    return test, result.model_copy(update={"history": history, "history_note": note})


def test_a_threshold_tests_headroom_flip_and_record(payload: dict[str, Any]) -> None:
    test, computed = _computed("Gross margin is above 55.5%.", payload)
    got = _by_id(computed_test_analytics("c2", test, computed, None))
    margin_now = gross_margin(11) * 100
    assert got["an:c2:headroom"].value == pytest.approx(margin_now - 55.5)
    # The margin rises one point a filing, so the room is (61 - 55.5) / 1 typical moves.
    assert got["an:c2:headroom_moves"].value == pytest.approx(margin_now - 55.5)
    assert got["an:c2:flip"].value == pytest.approx(55.5)
    # Above 55.5% from i = 6 (56%) on: 6 of the 12 quarters, in one run; the flip at i = 6.
    record = got["an:c2:history"]
    held = 6
    computed_points = [p for p in computed.history if p.outcome != "cannot_compute"]
    assert record.display == f"{held} of {len(computed_points)}"
    assert "longest run holding was 6" in record.reading
    assert _filed(2024, 3)["filed"] in record.reading
    assert "an:c2:needed" not in got


def test_a_failing_growth_test_says_what_was_needed(payload: dict[str, Any]) -> None:
    test, computed = _computed("Revenue grew more than 30% year over year.", payload)
    assert computed.outcome == "fails"
    got = _by_id(computed_test_analytics("c3", test, computed, None))
    needed = revenue(7) * 1.30
    assert got["an:c3:flip"].value == pytest.approx(needed)
    assert got["an:c3:needed"].value == pytest.approx(needed - revenue(11))
    assert got["an:c3:headroom"].value == pytest.approx((revenue(11) / revenue(7) - 1) * 100 - 30)


def _ttm(fn: Any) -> float:
    return sum(fn(i) for i in range(8, 12))


def test_bridges_split_cash_flow_and_the_operating_margin(measures: Measures) -> None:
    got = _by_id(bridge_analytics(measures, date(2025, 12, 31), "Q4 FY2025", {}))
    ocf = _ttm(lambda i: net_income(i) + 5 * M)
    assert got["an:bridge:fcf"].value == pytest.approx(ocf - 12 * M)
    assert got["an:bridge:ni_to_ocf"].value == pytest.approx(ocf - _ttm(net_income))
    # 20 M of the gap: SBC 8 M and D&A 4 M added back, 8 M of working capital and other.
    assert "$8.0M of working capital" in got["an:bridge:ni_to_ocf"].reading
    split = got["an:bridge:op_margin"]
    assert split.value == pytest.approx((operating_margin(11) - operating_margin(7)) * 100)
    assert "gross margin +4.0 percentage points" in split.reading
    assert "R&D +0.0 percentage points" in split.reading
    assert "other operating expenses -2.0 percentage points" in split.reading


def test_earnings_quality_and_dupont(measures: Measures) -> None:
    got = _by_id(earnings_quality(measures, date(2025, 12, 31), "Q4 FY2025", {}))
    income, ocf = _ttm(net_income), _ttm(lambda i: net_income(i) + 5 * M)
    assert got["an:eq:cash_conversion"].value == pytest.approx(ocf / income)
    assert got["an:eq:accrual_share"].value == pytest.approx((income - ocf) / income * 100)
    days = (date(2025, 12, 31) - date(2025, 10, 1)).days + 1
    assert got["an:eq:dso"].value == pytest.approx(72 * M / revenue(11) * days)
    assert got["an:eq:dio"].value == pytest.approx(41 * M / cost(11) * days)
    sales = _ttm(revenue)
    assert got["an:eq:sbc_ratio"].value == pytest.approx(8 * M / sales * 100)
    assert got["an:eq:capex_ratio"].value == pytest.approx(12 * M / sales * 100)
    assert got["an:eq:deferred_revenue"].value == pytest.approx(51 * M)
    # Return on average equity, worked directly: net income over the average of the two ends.
    equity = ((600 + 10 * 11) + (600 + 10 * 7)) / 2 * M
    assert got["an:eq:roe"].value == pytest.approx(income / equity * 100)
    assets = ((1000 + 20 * 11) + (1000 + 20 * 7)) / 2 * M
    assert got["an:eq:asset_turnover"].value == pytest.approx(sales / assets)
    assert got["an:eq:equity_multiplier"].value == pytest.approx(assets / equity)
    product = (
        got["an:eq:dupont_margin"].value
        * got["an:eq:asset_turnover"].value
        * got["an:eq:equity_multiplier"].value
    )
    assert product == pytest.approx(got["an:eq:roe"].value)


def test_what_the_facts_lack_is_returned_unavailable_with_why() -> None:
    sparse = companyfacts(
        {
            "Revenues": [
                fact(100 * M, "2025-03-31", "2025-01-01", filed="2025-05-10", form="10-Q",
                     accn="q", fy=2025, fp="Q1")
            ]
        }
    )
    book = FactBook(sparse)
    request = AnalyticsRequest(book, fiscal_calendar(sparse), {"c1": ["revenue"]})
    got = _by_id(FactsProvider().provide(request))
    assert got["an:revenue:level"].available
    assert not got["an:revenue:yoy"].available and got["an:revenue:yoy"].note
    assert not got["an:eq:dso"].available and "receivable" in got["an:eq:dso"].note.lower()
    assert not got["an:eq:roe"].available and got["an:eq:roe"].note


def test_no_facts_is_one_unavailable_analytic_that_says_why() -> None:
    got = FactsProvider().provide(AnalyticsRequest(None, None, error="EDGAR was down"))
    assert len(got) == 1 and not got[0].available and "EDGAR was down" in got[0].note


def test_an_analytic_never_reads_a_fact_filed_after_the_book_date(payload: dict[str, Any]) -> None:
    as_of = date(2025, 6, 1)  # Q1 2025 (i = 8) filed 2025-05-10 is the newest seen
    book = FactBook(payload, as_of=as_of)
    measures = Measures(book, fiscal_calendar(payload, as_of=as_of))
    got = _by_id(measure_analytics(measures, "revenue"))
    assert got["an:revenue:level"].value == pytest.approx(revenue(8))
    assert all(
        not item.filed or item.filed <= as_of.isoformat()
        for analytic in got.values()
        for item in analytic.inputs
    )
    assert math.isfinite(got["an:revenue:yoy"].value)
