"""Evaluating a compiled claim against one company's dated facts, and its history.

A synthetic company (calendar fiscal years 2022 to 2025, every quarter tagged as a
three-month fact, a 10-Q for each of the first three quarters and a 10-K for the year)
gives values whose expected results are worked out here by hand; the recorded NVIDIA,
Apple and Microsoft facts prove that nothing filed after the date is seen.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from app.core.breakdown_models import (
    Breakdown,
    BreakdownReport,
    BreakdownRow,
    BreakdownValue,
    FilingInfo,
    PeriodColumn,
)
from app.core.claim_eval import HistoryBooks, claim_history, evaluate
from app.core.claimtest import ClaimTest, NotNumeric, compile_claim
from app.core.facts import FactBook
from app.core.models import Company
from app.core.periods import fiscal_calendar
from tests.lookahead import filing_dates, late_refs, pruned
from tests.test_facts import companyfacts, fact, load_fixture

QUARTER_ENDS = ("03-31", "06-30", "09-30", "12-31")
QUARTER_STARTS = ("01-01", "04-01", "07-01", "10-01")


def _rev(i: int) -> int:
    """Revenue of the i-th quarter: rising by the same amount each quarter, so growth slows."""
    return 100_000_000 + 10_000_000 * i


def _income(i: int) -> int:
    """Operating income: a falling share of revenue, so it grows more slowly than revenue."""
    return round(_rev(i) * (0.25 - 0.002 * i))


def _margin(i: int) -> float:
    return 0.40 + 0.01 * i


def _filed(year: int, quarter: int) -> tuple[str, str, str, int, str]:
    """(filed, accession, form, fy, fp) of the report that first tags a quarter."""
    if quarter < 4:
        end = date.fromisoformat(f"{year}-{QUARTER_ENDS[quarter - 1]}")
        filed = (end + timedelta(days=40)).isoformat()
        return filed, f"q-{year}-{quarter}", "10-Q", year, f"Q{quarter}"
    return f"{year + 1}-02-15", f"k-{year}", "10-K", year, "FY"


def synthetic(years: range = range(2022, 2026), *, gross: bool = True) -> dict[str, Any]:
    revenue: list[dict[str, Any]] = []
    profit: list[dict[str, Any]] = []
    income: list[dict[str, Any]] = []
    for y in years:
        for q in range(1, 5):
            i = (y - 2022) * 4 + (q - 1)
            filed, accn, form, fy, fp = _filed(y, q)
            start, end = f"{y}-{QUARTER_STARTS[q - 1]}", f"{y}-{QUARTER_ENDS[q - 1]}"
            kw = {"filed": filed, "accn": accn, "form": form, "fy": fy, "fp": fp}
            revenue.append(fact(_rev(i), end, start, **kw))
            profit.append(fact(round(_rev(i) * _margin(i)), end, start, **kw))
            income.append(fact(_income(i), end, start, **kw))
        kw = {"filed": f"{y + 1}-02-15", "accn": f"k-{y}", "form": "10-K", "fy": y, "fp": "FY"}
        first = (y - 2022) * 4
        year_revenue = sum(_rev(first + k) for k in range(4))
        year_profit = sum(round(_rev(first + k) * _margin(first + k)) for k in range(4))
        revenue.append(fact(year_revenue, f"{y}-12-31", f"{y}-01-01", **kw))
        profit.append(fact(year_profit, f"{y}-12-31", f"{y}-01-01", **kw))
        year_income = sum(_income(first + k) for k in range(4))
        income.append(fact(year_income, f"{y}-12-31", f"{y}-01-01", **kw))
    concepts = {"Revenues": revenue, "OperatingIncomeLoss": income}
    if gross:
        concepts["GrossProfit"] = profit
    return companyfacts(concepts)


def _evaluate(claim: str, payload: dict[str, Any], as_of: date | None = None, reports=()):
    test = compile_claim(claim)
    assert isinstance(test, ClaimTest), test
    book = FactBook(payload, as_of=as_of)
    return evaluate(test, book, calendar=fiscal_calendar(payload, as_of=as_of), reports=reports)


# One outcome


def test_an_expanding_margin_holds_with_its_operands_arithmetic_and_margin() -> None:
    result = _evaluate("Gross margin is expanding.", synthetic())
    assert result.outcome == "holds" and result.counted_as == "supports"
    assert result.bound == "gross_margin[Q4 FY2025] > gross_margin[Q4 FY2024]"
    assert result.left is not None and result.right is not None
    assert result.left.value == pytest.approx(_margin(15) * 100, abs=1e-6)
    assert result.right.value == pytest.approx(_margin(11) * 100, abs=1e-6)
    assert result.margin == pytest.approx(4.0, abs=1e-6) and result.margin_display == "+4.0 points"
    refs = [ref for side in (result.left, result.right) for ref in side.inputs]
    assert {ref.accession for ref in refs} == {"k-2025", "k-2024"}
    assert all(ref.form == "10-K" and ref.filed for ref in refs)
    assert any("÷" in line for line in result.arithmetic)
    assert result.arithmetic[-1].endswith("holds")


def test_growth_above_a_threshold_fails_when_it_is_lower() -> None:
    result = _evaluate("Revenue grew more than 50% year over year.", synthetic())
    assert result.outcome == "fails" and result.counted_as == "challenges"
    expected = (_rev(15) - _rev(11)) / _rev(11) * 100
    assert result.left is not None and result.left.value == pytest.approx(expected)
    assert result.margin == pytest.approx(expected - 50)
    assert [o.term for o in result.operands] == ["revenue[Q4 FY2025]", "revenue[Q4 FY2024]"]


def test_an_amount_threshold_reads_the_latest_fiscal_year() -> None:
    result = _evaluate("Revenue is over $500 million.", synthetic())
    year = sum(_rev(12 + k) for k in range(4))
    assert result.bound == "revenue[FY2025] > $500M"
    assert result.left is not None and result.left.value == year
    assert result.outcome == ("holds" if year > 500e6 else "fails")


def test_a_named_fiscal_year_and_a_named_quarter() -> None:
    result = _evaluate("Gross profit increased in the second quarter of fiscal 2024.", synthetic())
    assert result.bound == "gross_profit[Q2 FY2024] > gross_profit[Q2 FY2023]"
    assert result.outcome == "holds"
    result = _evaluate("Revenue was at least $9 billion in fiscal 2023.", synthetic())
    assert result.bound == "revenue[FY2023] >= $9B" and result.outcome == "fails"


def test_a_missing_input_cannot_be_computed_and_says_why() -> None:
    result = _evaluate("Gross margin is expanding.", synthetic(gross=False))
    assert result.outcome == "cannot_compute" and result.counted_as == ""
    assert "gross profit" in result.reason.lower()
    assert result.margin is None and result.margin_display == ""


def test_a_period_the_facts_do_not_reach_cannot_be_computed() -> None:
    result = _evaluate("Revenue grew in fiscal 2019.", synthetic())
    assert result.outcome == "cannot_compute" and "FY2019" in result.reason


def test_a_streak_counts_consecutive_rises_against_the_period_before() -> None:
    held = _evaluate("Revenue has grown for eight consecutive quarters.", synthetic())
    assert held.outcome == "holds" and held.left is not None and held.left.value == 15
    too_long = _evaluate("Revenue has grown for 20 consecutive quarters.", synthetic())
    # Fifteen rises are known and the facts reach no further back: not a fail.
    assert too_long.outcome == "cannot_compute" and "15" in too_long.reason


def test_compound_growth_over_three_years() -> None:
    result = _evaluate("Revenue has compounded at over 40% for three years.", synthetic())
    first = sum(_rev(k) for k in range(4))
    last = sum(_rev(12 + k) for k in range(4))
    expected = ((last / first) ** (1 / 3) - 1) * 100
    assert result.left is not None and result.left.value == pytest.approx(expected)
    assert result.outcome == "fails"


def test_two_measures_growing_and_acceleration() -> None:
    faster = _evaluate("Revenue is growing faster than operating income.", synthetic())
    revenue = (_rev(15) - _rev(11)) / _rev(11) * 100
    income = (_income(15) - _income(11)) / _income(11) * 100
    assert faster.outcome == "holds" and faster.margin == pytest.approx(revenue - income)
    accel = _evaluate("Revenue growth is accelerating.", synthetic())
    # The same amount added each quarter is a falling rate of growth.
    assert accel.outcome == "fails" and accel.margin is not None and accel.margin < 0


def test_operating_expenses_are_gross_profit_less_operating_income_and_say_so() -> None:
    result = _evaluate("Operating expenses are falling.", synthetic())
    assert result.left is not None and "gross profit less operating income" in result.left.note
    expected = round(_rev(15) * _margin(15)) - _income(15)
    assert result.left.value == expected


# A share of revenue, from a filing's tagged breakdowns


def _report(rows: dict[str, float], total: float, customers: dict[str, float]) -> BreakdownReport:
    period = PeriodColumn(period_start="2025-10-01", period_end="2025-12-31", label="Quarter")

    def value(v: float, unit: str = "USD") -> BreakdownValue:
        return BreakdownValue(
            period_start="2025-10-01",
            period_end="2025-12-31",
            value=v,
            unit=unit,
            shown="",
            display="",
        )

    product = Breakdown(
        id="revenue_by_product",
        title="Revenue by product or service",
        concept="Revenues",
        axis="srt:ProductOrServiceAxis",
        period_kind="quarter",
        unit_label="USD millions",
        periods=[period],
        rows=[
            BreakdownRow(member=f"t:{k}Member", label=k, values=[value(v)]) for k, v in rows.items()
        ],
        total=[value(total)],
        adds_up=True,
    )
    concentration = Breakdown(
        id="revenue_concentration_by_customer",
        title="Share of revenue by major customer",
        concept="ConcentrationRiskPercentage1",
        axis="srt:MajorCustomersAxis",
        period_kind="quarter",
        unit_label="percent of revenue",
        periods=[period],
        rows=[
            BreakdownRow(member=f"t:{k}Member", label=k, values=[value(v, "pure")])
            for k, v in customers.items()
        ],
    )
    return BreakdownReport(
        company=Company(cik=1, ticker="TEST", name="Test Corp"),
        filing=FilingInfo(
            form="10-K",
            period_end="2025-12-31",
            filed_date="2026-02-15",
            accession="k-2025",
            url="",
        ),
        breakdowns=[product, concentration],
    )


def test_a_share_of_revenue_from_the_newest_filing_has_no_history() -> None:
    report = _report({"Data Center": 900.0, "Gaming": 100.0}, 1000.0, {"Customer A": 0.12})
    result = _evaluate("Data center is more than 80% of revenue.", synthetic(), reports=[report])
    assert result.outcome == "holds" and result.left is not None
    assert result.left.value == pytest.approx(90.0)
    assert result.left.inputs and result.left.inputs[0].accession == "k-2025"
    customer = _evaluate("No customer is over 20% of revenue.", synthetic(), reports=[report])
    assert customer.bound.startswith("max(share(customer))") and customer.outcome == "holds"
    assert customer.left is not None and customer.left.value == pytest.approx(12.0)
    missing = _evaluate("Automotive is under 5% of revenue.", synthetic(), reports=[report])
    assert missing.outcome == "cannot_compute" and "Automotive" in missing.reason
    none = _evaluate("Data center is more than 80% of revenue.", synthetic(), reports=[])
    assert none.outcome == "cannot_compute"
    share = compile_claim("Data center is more than 80% of revenue.")
    assert isinstance(share, ClaimTest)
    points, note = claim_history(share, synthetic())
    assert points == [] and "no history" in note


# History


def test_the_history_has_a_point_per_periodic_filing_and_marks_the_flip() -> None:
    payload = synthetic()
    test = compile_claim("Gross margin is above 50.5%.")
    assert isinstance(test, ClaimTest)
    points, note = claim_history(test, payload, as_of=date(2026, 3, 1))
    days = [p.filed for p in points]
    assert days == sorted(days) and days[-1] == "2026-02-15"
    assert len(points) == len(set(days)) == 16
    # Margin is 40% + 1 point a quarter: 51% in the twelfth quarter (Q4 2024), first
    # reported in the 10-K filed 2025-02-15.
    flips = [p for p in points if p.flipped]
    assert len(flips) == 1 and flips[0].filed == "2025-02-15" and flips[0].form == "10-K"
    assert all(p.outcome == "fails" for p in points if p.filed < "2025-02-15")
    assert all(p.outcome == "holds" for p in points if p.filed >= "2025-02-15")
    assert "5 years" in note or "years" in note


def test_the_history_is_capped_to_the_last_five_years(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import limits

    payload = synthetic(range(2014, 2026))
    test = compile_claim("Revenue is growing.")
    assert isinstance(test, ClaimTest)
    points, _ = claim_history(test, payload)
    assert points[0].filed >= "2021-02-15"
    monkeypatch.setattr(limits, "MAX_HISTORY_POINTS", 3)
    points, note = claim_history(test, payload)
    assert len(points) == 3 and "3" in note


# No lookahead, on the recorded facts

CLAIMS = [
    "Gross margin is expanding.",
    "Revenue grew more than 20% year over year.",
    "Revenue has grown for four consecutive quarters.",
    "Revenue has compounded at over 10% for three years.",
    "Operating income is growing faster than revenue.",
    "Cash and cash equivalents are declining.",
    "Diluted EPS is above $2.",
]


def _lookahead_problems(ticker: str) -> list[str]:
    payload = load_fixture(ticker)
    days = filing_dates(payload)
    chosen = sorted({*days[-6:], *days[::12], *(d - timedelta(days=1) for d in days[-3:])})
    tests = [compile_claim(c) for c in CLAIMS]
    problems: list[str] = []
    for day in chosen:
        book = FactBook(payload, as_of=day)
        calendar = fiscal_calendar(payload, as_of=day)
        trimmed = pruned(payload, day)
        clean = FactBook(trimmed)
        clean_calendar = fiscal_calendar(trimmed)
        for test in tests:
            assert isinstance(test, ClaimTest)
            seen = evaluate(test, book, calendar=calendar)
            late = late_refs(seen, day)
            if late:
                problems.append(f"{ticker} as of {day}: {test.canonical}: {late[0]}")
            expected = evaluate(test, clean, calendar=clean_calendar)
            if seen.model_copy(update={"as_of": ""}) != expected:
                problems.append(f"{ticker} as of {day}: {test.canonical} differs from pruned")
        points, _ = claim_history(tests[0], payload, as_of=day)
        late = late_refs(points, day)
        if late or any(p.filed > day.isoformat() for p in points):
            problems.append(f"{ticker} history as of {day}: {late[:1]}")
    return problems


@pytest.mark.parametrize("ticker", ["NVDA", "AAPL", "MSFT"])
def test_a_claim_as_of_a_date_sees_nothing_filed_later(ticker: str) -> None:
    assert _lookahead_problems(ticker) == []


def _history_mismatches(ticker: str) -> list[str]:
    """Each of the newest history points against the test computed from a pruned payload."""
    payload = load_fixture(ticker)
    test = compile_claim("Gross margin is expanding.")
    assert isinstance(test, ClaimTest)
    points, _ = claim_history(test, payload, books=HistoryBooks(payload))
    problems = [] if len(points) >= 15 else [f"only {len(points)} points"]
    for point in points[-4:]:
        day = date.fromisoformat(point.filed)
        trimmed = pruned(payload, day)
        alone = evaluate(test, FactBook(trimmed), calendar=fiscal_calendar(trimmed))
        if (alone.outcome, alone.bound, alone.left) != (
            point.outcome,
            point.bound,
            alone.left and alone.left.model_copy(update={"value": point.left}),
        ):
            problems.append(f"{point.filed}: {point.bound} {point.outcome} vs {alone.outcome}")
    return problems


def test_each_history_point_is_what_the_test_gives_as_of_that_day() -> None:
    assert _history_mismatches("NVDA") == []


def test_the_checks_catch_a_history_that_reads_facts_filed_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import claim_eval

    def leaky(payload: dict[str, Any], *, as_of: date | None = None) -> FactBook:
        return FactBook(payload)  # ignores the date: every fact, the later ones too

    monkeypatch.setattr(claim_eval, "FactBook", leaky)
    assert _history_mismatches("NVDA") != []


def test_a_claim_that_is_not_numeric_is_not_evaluated() -> None:
    assert isinstance(compile_claim("Growth is priced in."), NotNumeric)
