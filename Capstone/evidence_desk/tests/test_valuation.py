"""Valuation from a price and the facts: balances of the newest balance sheet only, by hand.

A synthetic company (``tests.test_claim_eval.synthetic``: calendar years 2022 to 2025,
revenue of the i-th quarter 100 + 10·i million) with a balance sheet added here. Every
expected value is arithmetic written out in the comments.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.core.claim_eval import Measures
from app.core.facts import FactBook
from app.core.periods import fiscal_calendar
from app.core.valuation import (
    Price,
    Shares,
    cash_and_securities,
    money,
    share_count_caution,
    shares_outstanding,
    total_debt,
    trailing_growth,
    valuation,
)
from tests.test_claim_eval import synthetic
from tests.test_facts import fact

M = 1_000_000
AS_OF = date(2026, 3, 1)
K2025 = {"filed": "2026-02-15", "accn": "k-2025", "form": "10-K", "fy": 2025, "fp": "FY"}
K2024 = {"filed": "2025-02-15", "accn": "k-2024", "form": "10-K", "fy": 2024, "fp": "FY"}


def company(balances: dict[str, list[dict[str, Any]]], shares: float = 100 * M) -> dict[str, Any]:
    """The synthetic company with ``balances`` (us-gaap concept to facts) and a cover page."""
    payload = synthetic()
    for concept, facts in {"Assets": [fact(5000 * M, "2025-12-31", **K2025)], **balances}.items():
        payload["facts"]["us-gaap"][concept] = {"label": concept, "units": {"USD": facts}}
    payload["facts"]["dei"] = {
        "EntityCommonStockSharesOutstanding": {
            "units": {"shares": [{"end": "2026-02-10", "val": shares, **K2025}]}
        }
    }
    return payload


FULL = {
    "LongTermDebtNoncurrent": [fact(300 * M, "2025-12-31", **K2025)],
    "LongTermDebtCurrent": [fact(50 * M, "2025-12-31", **K2025)],
    "CashAndCashEquivalentsAtCarryingValue": [fact(120 * M, "2025-12-31", **K2025)],
    "MarketableSecuritiesCurrent": [fact(30 * M, "2025-12-31", **K2025)],
    "StockholdersEquity": [fact(700 * M, "2025-12-31", **K2025)],
}


def valued(payload: dict[str, Any], price: float = 10.0, **more: Any):
    measures = Measures(FactBook(payload, as_of=AS_OF), fiscal_calendar(payload, as_of=AS_OF))
    return valuation(
        "TEST",
        Price(price, date(2026, 2, 27), "a test price"),
        shares_outstanding(payload, AS_OF),
        measures,
        AS_OF.isoformat(),
        companyfacts=payload,
        **more,
    )


def by_kind(found: Any) -> dict[str, Any]:
    return {result.kind: result for result in found.results}


def test_market_and_enterprise_value_and_the_sales_multiple_by_hand() -> None:
    found = valued(company(FULL))
    results = by_kind(found)
    # 10 dollars × 100M shares = 1,000M.
    assert results["market_value"].value == pytest.approx(1000 * M)
    # Debt 300M + 50M = 350M; cash 120M + securities 30M = 150M; 1,000 + 350 − 150 = 1,200M.
    assert results["enterprise_value"].value == pytest.approx(1200 * M)
    assert results["enterprise_value"].formula == "$1.00B + $350.0M − $150.0M"
    # The four quarters of 2025 are i = 12..15: 220 + 230 + 240 + 250 = 940M. 1,200 ÷ 940.
    assert results["ev_sales"].value == pytest.approx(1200 / 940)
    assert results["ev_sales"].display == "1.3×"
    # No net income is tagged: no multiple, and the reason says which figure is missing.
    assert results["pe"].outcome == "cannot_compute" and "Net income" in results["pe"].reason
    filed = {i.filed for r in found.results for i in r.inputs if i.filed}
    assert "2026-02-15" in filed and max(filed) <= AS_OF.isoformat()


def test_a_balance_last_reported_for_an_older_date_is_not_carried_forward() -> None:
    # Debt was tagged for 2024 and not for 2025 (as Tesla's non-current debt stops in 2018):
    # using the 2024 figure would give an enterprise value; none is given.
    stale = {**FULL, "LongTermDebtNoncurrent": [fact(300 * M, "2024-12-31", **K2024)]}
    del stale["LongTermDebtCurrent"]
    found = valued(company(stale))
    result = by_kind(found)["enterprise_value"]
    assert found.enterprise_value is None and result.outcome == "cannot_compute"
    assert "Not reported on the newest balance sheet (2025-12-31)" in result.reason
    assert "last reported for 2024-12-31" in result.reason
    assert by_kind(found)["ev_sales"].outcome == "cannot_compute"
    assert by_kind(found)["market_value"].value == pytest.approx(1000 * M)


def test_a_tagged_total_of_debt_is_used_when_the_parts_are_not_there_and_named() -> None:
    other = {k: v for k, v in FULL.items() if not k.startswith("LongTermDebt")}
    other["DebtInstrumentCarryingAmount"] = [fact(400 * M, "2025-12-31", **K2025)]
    other["LongTermDebt"] = [fact(390 * M, "2025-12-31", **K2025)]  # later in the order
    payload = company(other)
    measures = Measures(FactBook(payload, as_of=AS_OF), fiscal_calendar(payload, as_of=AS_OF))
    debt = total_debt(measures, payload, AS_OF)
    assert debt.value == 400 * M and "DebtInstrumentCarryingAmount" in debt.note
    # 1,000 + 400 − 150 = 1,250M.
    assert valued(payload).enterprise_value == pytest.approx(1250 * M)
    # Filed after the date: not read, and then there is no debt at all.
    assert total_debt(measures, payload, date(2026, 2, 14)).value is None


def test_securities_under_another_tag_are_added_and_none_is_said_to_be_zero() -> None:
    other = {k: v for k, v in FULL.items() if k != "MarketableSecuritiesCurrent"}
    payload = company({**other, "DebtSecuritiesCurrent": [fact(80 * M, "2025-12-31", **K2025)]})
    measures = Measures(FactBook(payload, as_of=AS_OF), fiscal_calendar(payload, as_of=AS_OF))
    cash = cash_and_securities(measures, payload, AS_OF)
    # 120M of cash + 80M under DebtSecuritiesCurrent = 200M, read by the measure itself.
    assert cash.value == 200 * M and cash.note == ""
    assert any("DebtSecuritiesCurrent" in i.label for i in cash.inputs)
    bare = company(other)
    measures = Measures(FactBook(bare, as_of=AS_OF), fiscal_calendar(bare, as_of=AS_OF))
    cash = cash_and_securities(measures, bare, AS_OF)
    assert cash.value == 120 * M and cash.note.endswith("counted as zero.")


def test_a_share_count_that_jumped_is_a_caution_on_the_market_value() -> None:
    payload = company(FULL)
    used = shares_outstanding(payload, AS_OF)
    assert not isinstance(used, str)
    later = Shares(1000 * M, date(2026, 5, 10), date(2026, 5, 15), "q-2026-1", "10-Q", "x", 1)
    assert "moved by a factor of 10.00" in share_count_caution(used, later)
    # Buybacks and grants move a count a little: 110M after 100M is no caution.
    near = Shares(110 * M, date(2026, 5, 10), date(2026, 5, 15), "q-2026-1", "10-Q", "x", 1)
    assert share_count_caution(used, near) == ""
    assert share_count_caution(used, used) == "" and share_count_caution(used, None) == ""
    note = by_kind(valued(payload, later_shares=later))["market_value"].note
    assert "a split or a large issue" in note


def test_the_companys_own_growth_is_compound_and_needs_consecutive_years() -> None:
    payload = company(FULL)
    one, three = trailing_growth(FactBook(payload, as_of=AS_OF), as_of=AS_OF.isoformat())
    # 2025: 940M. 2024 (i = 8..11): 180 + 190 + 200 + 210 = 780M. 940 ÷ 780 − 1 = 20.5%.
    assert one.value == pytest.approx((940 / 780 - 1) * 100)
    # 2022 (i = 0..3): 100 + 110 + 120 + 130 = 460M. (940 ÷ 460)^(1/3) − 1 = 26.9%.
    assert three.value == pytest.approx(((940 / 460) ** (1 / 3) - 1) * 100)
    assert three.display == "+26.9%"
    # With 2023 missing, three steps back is not three years back: no rate.
    gap = company(FULL)
    for concept in ("Revenues", "OperatingIncomeLoss", "GrossProfit"):
        rows = gap["facts"]["us-gaap"][concept]["units"]["USD"]
        gap["facts"]["us-gaap"][concept]["units"]["USD"] = [
            r for r in rows if not r["end"].startswith("2023")
        ]
    _, three = trailing_growth(FactBook(gap, as_of=AS_OF), years=2, as_of=AS_OF.isoformat())
    assert three.outcome == "cannot_compute" and "not consecutive" in three.reason


def test_money_prints_trillions() -> None:
    assert money(5.5038e12) == "$5.50T" and money(-1.2e12) == "-$1.20T"
    assert money(33.37e9) == "$33.37B"
