"""The analytics on two real companies, against numbers copied by hand from their raw facts.

Every expected value below is arithmetic on figures read off the recorded SEC company-facts
bodies (``tests/fixtures/edgar/companyfacts-CIK*.json.gz``), in USD millions, each named by
its concept and period. Nothing here calls the code under test to get an expectation, and
none of it goes through :class:`~app.core.facts.FactBook`: a wrong period placement, a wrong
quarter derived from year-to-date facts or a wrong formula fails here.

NVIDIA's fiscal year 2026 ended 2026-01-25 and its newest quarter, Q2 FY2027, 2026-07-26.
Apple's fiscal year 2026 ended 2026-09-26, which is also its newest quarter's end.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.core.analytics import (
    balance_days,
    cash_conversion,
    cash_walk,
    computed_test_analytics,
    fiscal_year_analytics,
    quarter_analytics,
)
from app.core.claim_eval import HistoryBooks, Measures, claim_history, evaluate
from app.core.claimtest import ClaimTest, compile_claim
from app.core.facts import FactBook
from app.core.periods import fiscal_calendar
from tests.fakes import recorded_facts

NVDA, AAPL = 1045810, 320193


def _measures(cik: int, as_of: date | None = None) -> Measures:
    payload = recorded_facts(cik)
    return Measures(FactBook(payload, as_of=as_of), fiscal_calendar(payload, as_of=as_of))


def _by_id(items: list[Any]) -> dict[str, Any]:
    return {item.id: item for item in items}


def test_nvidia_cash_conversion_from_year_to_date_cash_flows() -> None:
    # NetCashProvidedByUsedInOperatingActivities: FY2026 102,718; first half of FY2026 42,779;
    # first quarter of FY2027 50,344; first half of FY2027 74,421.
    # NetIncomeLoss, quarter by quarter: Q3 FY2026 31,910 (tagged); Q4 FY2026 = FY2026 120,067
    # less nine months 77,107; Q1 FY2027 58,321 and Q2 FY2027 59,688 (both tagged). The two
    # tagged quarters of FY2027 add to 118,009, one less than the half year the filing tags
    # (118,010): the filing's own rounding, and the sum of quarters is what is computed.
    ocf_ttm = 102_718 - 42_779 + 74_421
    income_ttm = 31_910 + (120_067 - 77_107) + 58_321 + 59_688
    got = cash_conversion(_measures(NVDA), date(2026, 7, 26), ["c1"])
    assert got.value == pytest.approx(ocf_ttm / income_ttm)
    assert got.display == "0.70x"
    quarter = (74_421 - 50_344) / 59_688
    assert f"alone it was {quarter:.2f}x" in got.reading and f"{quarter:.2f}" == "0.40"


def test_nvidia_receivable_and_inventory_days() -> None:
    # AccountsReceivableNetCurrent 63,059 at 2026-07-26 and 27,808 at 2025-07-27; Revenues
    # 96,221 (2026-04-27 to 2026-07-26, 91 days) and 46,743 a year before. InventoryNet 31,575
    # and 14,962; CostOfRevenue 24,079 and 12,890.
    measures = _measures(NVDA)
    dso = balance_days(measures, date(2026, 7, 26), "dso", [])
    assert dso.value == pytest.approx(63_059 / 96_221 * 91)
    assert f"against {27_808 / 46_743 * 91:.1f} days a year before" in dso.reading
    dio = balance_days(measures, date(2026, 7, 26), "dio", [])
    assert dio.value == pytest.approx(31_575 / 24_079 * 91)
    assert f"against {14_962 / 12_890 * 91:.1f} days a year before" in dio.reading


def test_nvidia_fiscal_2026_cash_walk_and_revenue_path() -> None:
    # FY2026: NetIncomeLoss 120,067; operating cash flow 102,718;
    # PaymentsToAcquireProductiveAssets 6,042. Receivables 38,466 at 2026-01-25 and 23,065 at
    # 2025-01-26; inventory 21,403 and 10,080. Revenues 215,938 (FY2026), 130,497 (FY2025).
    measures = _measures(NVDA)
    year = measures.slot("annual", date(2026, 1, 25))
    walk = cash_walk(measures, year, ["c4"])
    assert walk.value == pytest.approx((102_718 - 6_042 - 120_067) * 1e6)
    assert "accounts receivable rose $15.40B" in walk.reading  # 38,466 - 23,065 = 15,401
    assert "inventory rose $11.32B" in walk.reading  # 21,403 - 10,080 = 11,323
    path = _by_id(fiscal_year_analytics(measures, "revenue", year))["an:revenue:fy2026:path"]
    assert path.value == pytest.approx((215_938 / 130_497 - 1) * 100)
    since = _by_id(fiscal_year_analytics(measures, "revenue", year))["an:revenue:fy2026:since"]
    assert since.value == pytest.approx((96_221 / 46_743 - 1) * 100)


def test_nvidia_free_cash_flow_as_a_share_of_net_income_reading_by_reading() -> None:
    payload = recorded_facts(NVDA)
    test = compile_claim("Free cash flow was above net income last fiscal year")
    assert isinstance(test, ClaimTest)
    computed = evaluate(test, FactBook(payload), calendar=fiscal_calendar(payload))
    history, note = claim_history(test, payload, books=HistoryBooks(payload))
    computed = computed.model_copy(update={"history": history, "history_note": note})
    sides = _by_id(computed_test_analytics("c4", test, computed))["an:c4:sides"]
    # FY2026: (102,718 - 6,042) / 120,067. FY2025: (64,089 - 3,236) / 72,880.
    assert sides.value == pytest.approx((102_718 - 6_042) / 120_067 * 100)
    assert f"{(64_089 - 3_236) / 72_880 * 100:.1f}%" in sides.reading
    assert "fallen at every reading" in sides.reading


def test_apple_newest_quarter_is_the_year_less_nine_months() -> None:
    # RevenueFromContractWithCustomerExcludingAssessedTax: FY2026 478,834 and nine months
    # 364,357; FY2025 416,161 and nine months 313,695. Apple tags no fourth quarter.
    q4, q4_before = 478_834 - 364_357, 416_161 - 313_695
    got = _by_id(quarter_analytics(_measures(AAPL), "revenue"))
    assert got["an:revenue:yoy"].value == pytest.approx((q4 / q4_before - 1) * 100)
    assert got["an:revenue:yoy"].period == "Q4 FY2026"


def test_apple_cash_conversion_and_days() -> None:
    # Operating cash flow: FY2026 145,097, nine months 116,996; FY2025 111,482. NetIncomeLoss:
    # FY2026 132,175, nine months 101,464; FY2025 112,010. Receivables 43,817 at 2026-09-26 and
    # 39,777 at 2025-09-27. CostOfGoodsAndServicesSold FY2026 245,232, nine months 185,575;
    # InventoryNet 14,541. The quarter 2026-06-28 to 2026-09-26 is 91 days.
    measures = _measures(AAPL)
    end = date(2026, 9, 26)
    conversion = cash_conversion(measures, end, [])
    assert conversion.value == pytest.approx(145_097 / 132_175)
    alone = (145_097 - 116_996) / (132_175 - 101_464)
    assert f"alone it was {alone:.2f}x" in conversion.reading
    assert f"{111_482 / 112_010:.2f}x over the four quarters a year before" in conversion.reading
    q4, q4_before = 478_834 - 364_357, 416_161 - 313_695
    dso = balance_days(measures, end, "dso", [])
    assert dso.value == pytest.approx(43_817 / q4 * 91)
    assert f"against {39_777 / q4_before * 91:.1f} days a year before" in dso.reading
    dio = balance_days(measures, end, "dio", [])
    assert dio.value == pytest.approx(14_541 / (245_232 - 185_575) * 91)
    # The walk over FY2026: capital expenditure 9,041; receivables up 4,040, inventory 8,823.
    walk = cash_walk(measures, measures.slot("annual", end), [])
    assert walk.value == pytest.approx((145_097 - 9_041 - 132_175) * 1e6)
    assert "accounts receivable rose $4.04B" in walk.reading
    assert "inventory rose $8.82B" in walk.reading


def test_apple_as_of_a_date_sees_only_what_was_filed_by_then() -> None:
    # As of 2026-06-01 the newest filing is the 10-Q of 2026-05-01 (quarter ended 2026-03-28):
    # revenue 111,184; the same quarter a year before is not in the pruned facts printed
    # above, so the check here is the period and the filings read.
    as_of = date(2026, 6, 1)
    got = quarter_analytics(_measures(AAPL, as_of), "revenue")
    assert got[0].period == "Q2 FY2026"
    assert got[0].inputs[0].value == pytest.approx(111_184e6)
    filed = [item.filed for analytic in got for item in analytic.inputs if item.filed]
    assert filed and max(filed) <= as_of.isoformat()
