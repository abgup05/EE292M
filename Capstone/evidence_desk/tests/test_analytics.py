"""Analytics from dated facts: every expected value is worked out here from the definitions.

A synthetic company (calendar fiscal years 2023 to 2025, every quarter tagged as a
three-month fact, a 10-Q for each of the first three quarters and a 10-K for the fourth,
which also tags the year) has values that are simple functions of the quarter's index ``i``
(0 for Q1 2023 to 11 for Q4 2025), so each expected number below is computed straight from
those functions, not from the code under test. ``tests/test_analytics_recorded.py`` checks
the same analytics on two real companies against numbers copied from their raw facts.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import pytest

from app.core.analytics import (
    AnalyticsRequest,
    FactsProvider,
    balance_days,
    cash_conversion,
    cash_walk,
    claim_basis,
    computed_test_analytics,
    deferred_revenue,
    fiscal_year_analytics,
    growth_drivers,
    margin_split,
    part_analytics,
    partition,
    quarter_analytics,
    return_on_equity,
    revenue_share,
)
from app.core.breakdown_models import (
    Breakdown,
    BreakdownReport,
    BreakdownRow,
    BreakdownValue,
    FilingInfo,
)
from app.core.claim_eval import HistoryBooks, Measures, claim_history, evaluate
from app.core.claimtest import ClaimTest, compile_claim
from app.core.facts import FactBook
from app.core.models import Company
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
        return {
            "filed": filed,
            "accn": f"q-{year}-{quarter}",
            "form": "10-Q",
            "fy": year,
            "fp": f"Q{quarter}",
        }
    return {
        "filed": f"{year + 1}-02-15",
        "accn": f"k-{year}",
        "form": "10-K",
        "fy": year,
        "fp": "FY",
    }


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
            if quarter == 4:  # the annual report also tags the fiscal year
                for name, value in FLOWS.items():
                    year_total = sum(value(j) for j in range(i - 3, i + 1))
                    concepts[name].append(fact(round(year_total), end, f"{year}-01-01", **kw))
    return companyfacts(concepts)


@pytest.fixture(scope="module")
def payload() -> dict[str, Any]:
    return synthetic()


@pytest.fixture(scope="module")
def measures(payload: dict[str, Any]) -> Measures:
    return Measures(FactBook(payload), fiscal_calendar(payload))


def _by_id(items: list[Any]) -> dict[str, Any]:
    return {item.id: item for item in items}


END = date(2025, 12, 31)


def _year(fn: Any, year: int) -> float:
    first = (year - 2023) * 4
    return sum(fn(i) for i in range(first, first + 4))


def _ttm(fn: Any) -> float:
    return _year(fn, 2025)


def test_a_measures_newest_quarter_its_pace_and_its_two_years(measures: Measures) -> None:
    got = _by_id(quarter_analytics(measures, "revenue", ["c1"]))
    r = revenue
    assert set(got) == {"an:revenue:yoy", "an:revenue:acceleration", "an:revenue:trend8"}
    assert got["an:revenue:yoy"].value == pytest.approx((r(11) / r(7) - 1) * 100)
    growth_now, growth_before = r(11) / r(7) - 1, r(10) / r(6) - 1
    assert got["an:revenue:acceleration"].value == pytest.approx((growth_now - growth_before) * 100)
    assert "slowing" in got["an:revenue:acceleration"].reading
    assert got["an:revenue:trend8"].value == pytest.approx(((r(11) / r(3)) ** 0.125 - 1) * 100)
    assert "rose in each of the 8 quarters" in got["an:revenue:trend8"].reading
    assert all(item.claim_ids == ["c1"] for item in got.values())
    assert all(item.reading_origin == "code" and item.reading for item in got.values())
    assert all(item.question.endswith("?") for item in got.values())


def test_a_ratio_moves_in_points_and_has_no_growth_to_speed_up(measures: Measures) -> None:
    got = _by_id(quarter_analytics(measures, "gross_margin"))
    assert set(got) == {"an:gross_margin:yoy", "an:gross_margin:trend8"}
    assert got["an:gross_margin:yoy"].unit == "points"
    assert got["an:gross_margin:yoy"].value == pytest.approx(4.0)
    assert got["an:gross_margin:yoy"].display == "+4.0 percentage points"
    assert got["an:gross_margin:trend8"].value == pytest.approx(8.0)


def test_a_fiscal_year_claim_gets_the_fiscal_years_and_what_came_since(
    payload: dict[str, Any],
) -> None:
    test = compile_claim("Revenue more than doubled in fiscal 2024.")
    assert isinstance(test, ClaimTest), test
    measures = Measures(FactBook(payload), fiscal_calendar(payload))
    basis = claim_basis(test, measures)
    assert basis.kind == "annual" and basis.slot is not None and basis.slot.label == "FY2024"
    got = _by_id(fiscal_year_analytics(measures, "revenue", basis.slot, ["c1"]))
    path = got["an:revenue:fy2024:path"]
    assert path.value == pytest.approx((_year(revenue, 2024) / _year(revenue, 2023) - 1) * 100)
    assert "FY2023" in path.reading and "FY2025" not in path.reading
    # Since FY2024 ended: the newest quarter (Q4 2025) on the same quarter a year earlier.
    since = got["an:revenue:fy2024:since"]
    assert since.value == pytest.approx((revenue(11) / revenue(7) - 1) * 100)
    assert since.reading.startswith("Since FY2024 ended:")
    # The newest fiscal year has no quarter after it: nothing is said to have come since.
    last = measures.slot("annual", END)
    assert [item.kind for item in fiscal_year_analytics(measures, "revenue", last)] == [
        "fiscal_path"
    ]
    quarterly = compile_claim("Gross margin is above 55.5%.")
    assert isinstance(quarterly, ClaimTest)
    assert claim_basis(quarterly, measures).kind == "quarter"
    assert claim_basis(None, measures).kind == "quarter"


def test_growth_by_fiscal_year_says_when_it_slowed(measures: Measures) -> None:
    slot = measures.slot("annual", END)
    path = fiscal_year_analytics(measures, "revenue", slot)[0]
    growth = [(_year(revenue, year) / _year(revenue, year - 1) - 1) * 100 for year in (2024, 2025)]
    assert path.value == pytest.approx(growth[1])
    assert growth[1] < growth[0] and "Growth slowed in FY2025" in path.reading
    assert f"{growth[0] - growth[1]:.1f} percentage points" in path.reading


def _computed(claim: str, payload: dict[str, Any]) -> tuple[ClaimTest, Any]:
    test = compile_claim(claim)
    assert isinstance(test, ClaimTest), test
    book = FactBook(payload)
    result = evaluate(test, book, calendar=fiscal_calendar(payload))
    history, note = claim_history(test, payload, books=HistoryBooks(payload))
    return test, result.model_copy(update={"history": history, "history_note": note})


def test_a_threshold_tests_room_in_typical_moves_and_its_record(payload: dict[str, Any]) -> None:
    test, computed = _computed("Gross margin is above 55.5%.", payload)
    got = _by_id(computed_test_analytics("c2", test, computed))
    margin_now = gross_margin(11) * 100
    room = got["an:c2:headroom"]
    assert room.value == pytest.approx(margin_now - 55.5)
    # The margin rises one point a filing, so the room is (61 - 55.5) / 1 typical moves.
    assert "typically moved 1.0 percentage points" in room.reading
    assert f"{margin_now - 55.5:.2f}x a typical move" in room.reading
    # Above 55.5% from i = 6 (56%) on: 6 of the 12 readings, in one run; the flip at i = 6.
    record = got["an:c2:history"]
    assert record.display == "6 of 12" and record.value == pytest.approx(50.0)
    assert "longest run holding was 6" in record.reading
    assert _filed(2024, 3)["filed"] in record.reading
    assert set(got) == {"an:c2:headroom", "an:c2:history"}


def test_a_growth_test_says_what_it_needed_or_could_have_given_up(
    payload: dict[str, Any],
) -> None:
    test, computed = _computed("Revenue grew more than 30% year over year.", payload)
    assert computed.outcome == "fails"
    got = _by_id(computed_test_analytics("c3", test, computed))
    needed = revenue(7) * 1.30
    assert got["an:c3:needed"].value == pytest.approx(revenue(11) - needed)
    assert "short" in got["an:c3:needed"].reading and "an:c3:cushion" not in got
    test, computed = _computed("Revenue grew more than 10% year over year.", payload)
    assert computed.outcome == "holds"
    got = _by_id(computed_test_analytics("c3", test, computed))
    assert got["an:c3:cushion"].value == pytest.approx(revenue(11) - revenue(7) * 1.10)
    assert "more than needed" in got["an:c3:cushion"].reading


def test_one_measure_against_another_says_which_way_the_gap_is_going(
    payload: dict[str, Any],
) -> None:
    claim = "Operating cash flow was above net income in the latest fiscal year."
    test, computed = _computed(claim, payload)
    assert computed.outcome == "holds"
    got = _by_id(computed_test_analytics("c4", test, computed))
    sides = got["an:c4:sides"]
    # Operating cash flow is net income plus 5 M a quarter, and net income grows: the share
    # falls every year.
    shares = [
        (_year(net_income, year) + 20 * M) / _year(net_income, year) * 100
        for year in (2023, 2024, 2025)
    ]
    assert sides.value == pytest.approx(shares[-1])
    assert shares[0] > shares[1] > shares[2] and "fallen at every reading" in sides.reading
    assert [i.value for i in sides.inputs[1:]] == pytest.approx(shares)
    # Three fiscal years are three readings, all shown by the sides: no separate record.
    assert "an:c4:history" not in got


def test_the_cash_walk_runs_from_net_income_to_free_cash_flow(measures: Measures) -> None:
    ocf = _ttm(lambda i: net_income(i) + 5 * M)
    for slot in (measures.slot("ttm", END), measures.slot("annual", END)):
        walk = cash_walk(measures, slot, ["c4"])
        assert walk.value == pytest.approx((ocf - 12 * M) - _ttm(net_income))  # +8 M
        assert "$8.0M above net income" in walk.reading
        assert "stock-based compensation of $8.0M" in walk.reading
        assert "depreciation and amortization of $4.0M" in walk.reading
        # Receivables 50 + 2i and inventory 30 + i, from i = 7 to i = 11.
        assert "accounts receivable rose $8.0M (to $72.0M)" in walk.reading
        assert "inventory rose $4.0M (to $41.0M)" in walk.reading
    assert cash_walk(measures, measures.slot("annual", END), []).id == "an:bridge:cash:fy2025"
    assert cash_walk(measures, measures.slot("ttm", END), []).id == "an:bridge:cash:ttm"


def test_the_operating_margin_change_splits_into_its_parts(measures: Measures) -> None:
    split = margin_split(measures, END, ["c1"])
    assert split.value == pytest.approx((operating_margin(11) - operating_margin(7)) * 100)
    assert "gross margin +4.0 percentage points" in split.reading
    assert "R&D as a share of revenue +0.0 percentage points" in split.reading
    assert "other operating expenses as a share of revenue -2.0 percentage points" in split.reading


def test_earnings_quality(measures: Measures) -> None:
    income, ocf = _ttm(net_income), _ttm(lambda i: net_income(i) + 5 * M)
    conversion = cash_conversion(measures, END, ["c1"])
    assert conversion.value == pytest.approx(ocf / income)
    alone = (net_income(11) + 5 * M) / net_income(11)
    before = (_year(net_income, 2024) + 20 * M) / _year(net_income, 2024)
    assert f"alone it was {alone:.2f}x" in conversion.reading
    assert f"{before:.2f}x over the four quarters a year before" in conversion.reading
    days = (date(2025, 12, 31) - date(2025, 10, 1)).days + 1
    dso = balance_days(measures, END, "dso", [])
    assert dso.value == pytest.approx(72 * M / revenue(11) * days)
    assert f"against {64 * M / revenue(7) * days:.1f} days a year before" in dso.reading
    assert balance_days(measures, END, "dio", []).value == pytest.approx(41 * M / cost(11) * days)
    sales = _ttm(revenue)
    assert revenue_share(measures, END, "sbc_ratio", []).value == pytest.approx(8 * M / sales * 100)
    capex = revenue_share(measures, END, "capex_ratio", [])
    assert capex.value == pytest.approx(12 * M / sales * 100)
    assert f"{12 * M / _year(revenue, 2024) * 100:.1f}%" in capex.reading
    deferred = deferred_revenue(measures, END, [])
    assert deferred.value == pytest.approx((51 - 47) / 47 * 100)
    # Return on average equity, worked directly: net income over the average of the two ends.
    equity = ((600 + 10 * 11) + (600 + 10 * 7)) / 2 * M
    assets = ((1000 + 20 * 11) + (1000 + 20 * 7)) / 2 * M
    roe = return_on_equity(measures, END, [])
    assert roe.value == pytest.approx(income / equity * 100)
    assert f"{sales / assets:.2f}x average total assets" in roe.reading
    assert f"{assets / equity:.2f}x average equity" in roe.reading


def _value(start: str, end: str, millions: float) -> BreakdownValue:
    return BreakdownValue(
        period_start=start,
        period_end=end,
        value=millions * M,
        unit="USD",
        shown=str(millions),
        display=str(millions),
    )


YEARS = (("2025-01-01", "2025-12-31"), ("2024-01-01", "2024-12-31"), ("2023-01-01", "2023-12-31"))


def _row(label: str, *millions: float) -> BreakdownRow:
    values = [_value(*span, m) for span, m in zip(YEARS, millions, strict=False)]
    return BreakdownRow(member=f"x:{label}", label=label, values=values)


def _report() -> BreakdownReport:
    """A 10-K that tags Cloud (with its two sub-parts) and Devices: 3 fiscal years."""
    item = Breakdown(
        id="revenue_by_product",
        title="Revenue by product or service",
        concept="Revenues",
        axis="x",
        period_kind="fiscal year",
        unit_label="USD millions",
        rows=[
            _row("Cloud", 600, 400, 200),
            _row("Cloud Compute", 450, 300, 150),
            _row("Cloud Storage", 150, 100, 50),
            _row("Devices", 180, 220, 260),
        ],
        total=[_value(*span, m) for span, m in zip(YEARS, (780, 620, 460), strict=True)],
    )
    return BreakdownReport(
        company=Company(ticker="TEST", cik=1, name="Test Corp"),
        filing=FilingInfo(
            form="10-K", period_end="2025-12-31", filed_date="2026-02-15", accession="k", url="u"
        ),
        breakdowns=[item],
    )


def test_a_named_part_against_the_company_and_its_own_pace() -> None:
    key = 'revenue(segment "Cloud")'
    got = _by_id(part_analytics([_report()], "cloud", key, ["c5"]))
    growth = got["an:part:cloud:fy:growth"]
    assert growth.value == pytest.approx(50.0)  # 400 to 600
    assert "the company's revenue grew +25.8%" in growth.reading  # 620 to 780
    assert "76.9% of revenue, against 64.5% a year earlier" in growth.reading
    pace = got["an:part:cloud:fy:pace"]
    assert pace.value == pytest.approx(50.0 - 100.0)  # +50% after +100%
    assert "slowing, by 50.0 percentage points" in pace.reading
    assert growth.data_origin == "sec_tagged_breakdowns" and growth.measure == key
    assert part_analytics([_report()], "Gaming", key, ["c5"]) == []


def test_growth_drivers_split_the_total_without_counting_a_sub_part_twice() -> None:
    report = _report()
    rows = [(row, row.values[0], row.values[1]) for row in report.breakdowns[0].rows]
    assert [row.label for row, _, _ in partition(rows, 780 * M)] == ["Cloud", "Devices"]
    drivers = growth_drivers([report], [], ["c3"], annual=True)
    assert drivers is not None and drivers.id == "an:bridge:growth:revenue_by_product:fy"
    # Cloud added (600 - 400) / 620, Devices (180 - 220) / 620: together the total's growth.
    assert drivers.value == pytest.approx(200 / 620 * 100)
    assert "Cloud +32.3 percentage points; Devices -6.5 percentage points" in drivers.reading
    assert "Compute" not in drivers.reading
    assert 200 / 620 * 100 - 40 / 620 * 100 == pytest.approx((780 / 620 - 1) * 100)
    # A quarterly claim is not answered from a filing that tags fiscal years only.
    assert growth_drivers([report], [], ["c3"], annual=False) is None


def _provided(payload: dict[str, Any], claims: dict[str, str], **kw: Any) -> dict[str, Any]:
    tests = {}
    keys: dict[str, list[str]] = {}
    for claim_id, text in claims.items():
        test, computed = _computed(text, payload)
        tests[claim_id] = (test, computed)
        keys[claim_id] = list(
            dict.fromkeys(t.subject for t in test.terms if t.subject in FLOW_KEYS)
        )
    book = FactBook(payload)
    request = AnalyticsRequest(book, fiscal_calendar(payload), keys, tests, **kw)
    return _by_id(FactsProvider().provide(request))


FLOW_KEYS = ("revenue", "gross_margin", "operating_cash_flow", "net_income", "free_cash_flow")


def test_every_analytic_is_tied_to_a_claim_and_follows_its_basis(payload: dict[str, Any]) -> None:
    got = _provided(
        payload,
        {
            "c1": "Gross margin is above 55.5%.",
            "c2": "Revenue more than doubled in fiscal 2025.",
            "c3": "Operating cash flow was above net income in the latest fiscal year.",
        },
    )
    assert all(item.claim_ids for item in got.values()), "no analytic for the thesis at large"
    assert all(item.question for item in got.values())
    by_claim = {
        claim: sorted(item.id for item in got.values() if claim in item.claim_ids)
        for claim in ("c1", "c2", "c3")
    }
    # A quarterly claim about a margin: its quarters, its test, and inventory behind the margin.
    assert by_claim["c1"] == [
        "an:c1:headroom",
        "an:c1:history",
        "an:eq:dio",
        "an:gross_margin:trend8",
        "an:gross_margin:yoy",
    ]
    # A fiscal-year claim about revenue: the fiscal years, not the newest quarters.
    assert "an:revenue:fy2025:path" in by_claim["c2"] and "an:revenue:yoy" not in by_claim["c2"]
    assert "an:c2:needed" in by_claim["c2"]
    # One measure against another: the gap and where the cash went, for that year and since;
    # neither side's own path.
    assert by_claim["c3"] == [
        "an:bridge:cash:fy2025",
        "an:bridge:cash:ttm",
        "an:c3:sides",
        "an:eq:cash_conversion",
    ]


def test_a_claim_with_no_measure_gets_no_analytic(payload: dict[str, Any]) -> None:
    book = FactBook(payload)
    request = AnalyticsRequest(book, fiscal_calendar(payload), {"c1": []})
    assert FactsProvider().provide(request) == []


def test_what_the_facts_lack_is_returned_unavailable_with_why() -> None:
    sparse = companyfacts(
        {
            "Revenues": [
                fact(
                    100 * M,
                    "2025-03-31",
                    "2025-01-01",
                    filed="2025-05-10",
                    form="10-Q",
                    accn="q",
                    fy=2025,
                    fp="Q1",
                )
            ]
        }
    )
    book = FactBook(sparse)
    request = AnalyticsRequest(book, fiscal_calendar(sparse), {"c1": ["revenue", "equity"]})
    got = _by_id(FactsProvider().provide(request))
    assert not got["an:revenue:yoy"].available and got["an:revenue:yoy"].note
    assert not got["an:eq:dso"].available and "receivable" in got["an:eq:dso"].note.lower()
    assert not got["an:eq:roe"].available and got["an:eq:roe"].note
    assert all(item.claim_ids == ["c1"] for item in got.values())


def test_no_facts_is_one_unavailable_analytic_that_says_why() -> None:
    request = AnalyticsRequest(None, None, {"c1": ["revenue"]}, error="EDGAR was down")
    got = FactsProvider().provide(request)
    assert len(got) == 1 and not got[0].available and "EDGAR was down" in got[0].note
    assert got[0].claim_ids == ["c1"]
    assert FactsProvider().provide(AnalyticsRequest(None, None, {"c1": []})) == []


def test_no_analytic_reads_a_fact_filed_after_the_book_date(payload: dict[str, Any]) -> None:
    as_of = date(2025, 6, 1)  # Q1 2025 (i = 8), filed 2025-05-10, is the newest seen
    book = FactBook(payload, as_of=as_of)
    measures = Measures(book, fiscal_calendar(payload, as_of=as_of))
    end = date(2025, 3, 31)
    got = [
        *quarter_analytics(measures, "revenue"),
        *fiscal_year_analytics(measures, "revenue", measures.slot("annual", date(2024, 12, 31))),
        cash_walk(measures, measures.slot("ttm", end), []),
        margin_split(measures, end, []),
        cash_conversion(measures, end, []),
        balance_days(measures, end, "dso", []),
        balance_days(measures, end, "dio", []),
        revenue_share(measures, end, "capex_ratio", []),
        deferred_revenue(measures, end, []),
        return_on_equity(measures, end, []),
    ]
    assert all(item.available for item in got), [i.id for i in got if not i.available]
    by_id = _by_id(got)
    assert by_id["an:revenue:yoy"].value == pytest.approx((revenue(8) / revenue(4) - 1) * 100)
    # The newest quarter the book admits is Q1 2025; the walk is the four quarters to it.
    ocf = sum(net_income(i) + 5 * M for i in range(5, 9))
    assert by_id["an:bridge:cash:ttm"].value == pytest.approx(
        ocf - 12 * M - sum(net_income(i) for i in range(5, 9))
    )
    filed = [item.filed for analytic in got for item in analytic.inputs if item.filed]
    assert filed and max(filed) <= as_of.isoformat()
    assert all(math.isfinite(item.value) for item in got)
    # And the same call on the whole book does see the later quarters.
    later = quarter_analytics(Measures(FactBook(payload), fiscal_calendar(payload)), "revenue")
    assert later[0].value == pytest.approx((revenue(11) / revenue(7) - 1) * 100)
