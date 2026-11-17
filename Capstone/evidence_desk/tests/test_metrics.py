"""The metrics report: values, rules for missing and meaningless inputs, display, invariance.

The known growth rates are computed by hand from the answer key in
``test_facts.py`` (published annual-report figures), not from the code.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.core.facts import FactBook
from app.core.metric_models import Metric, MetricsReport
from app.core.metrics import build_report, eps_text, percent_text, usd_text
from tests.test_facts import (
    CIKS,
    FY_END,
    FY_START,
    H1_END,
    KNOWN_ANNUAL_PER_SHARE_AND_MARGIN,
    MILLION,
    N9_END,
    Q1_END,
    Q2_START,
    companyfacts,
    fact,
    load_fixture,
    shuffled,
)

PRIOR_START, PRIOR_END = "2023-01-30", "2024-01-28"


def metric(report: MetricsReport, key: str, period: str, end: str) -> Metric:
    """The one metric with this key, period kind and end date."""
    found = [m for m in report.metrics if m.id == f"{key}:{period}:{end}"]
    assert len(found) == 1, f"{key}:{period}:{end} not in report"
    return found[0]


def two_year_company(**overrides: list[dict[str, Any]]) -> dict[str, Any]:
    """Two fiscal years with every concept the metrics read; overrides replace a concept."""
    concepts: dict[str, list[dict[str, Any]]] = {
        "Revenues": [
            fact(46_743 * MILLION, FY_END, FY_START),
            fact(30_040 * MILLION, PRIOR_END, PRIOR_START),
        ],
        "CostOfRevenue": [fact(20_000 * MILLION, FY_END, FY_START)],
        "GrossProfit": [fact(26_743 * MILLION, FY_END, FY_START)],
        "OperatingIncomeLoss": [fact(10_000 * MILLION, FY_END, FY_START)],
        "NetIncomeLoss": [fact(-2_500 * MILLION, FY_END, FY_START)],
        "EarningsPerShareDiluted": [fact(1.08, FY_END, FY_START)],
        "ResearchAndDevelopmentExpense": [fact(5_000 * MILLION, FY_END, FY_START)],
        "NetCashProvidedByUsedInOperatingActivities": [fact(12_000 * MILLION, FY_END, FY_START)],
        "PaymentsToAcquirePropertyPlantAndEquipment": [fact(812 * MILLION, FY_END, FY_START)],
        "CashAndCashEquivalentsAtCarryingValue": [
            fact(9_000 * MILLION, FY_END),
            fact(6_000 * MILLION, PRIOR_END),
        ],
        "InventoryNet": [fact(3_000 * MILLION, FY_END)],
    }
    concepts.update(overrides)
    return companyfacts({name: facts for name, facts in concepts.items() if facts})


# Display


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (46_743_000_000, "$46.74B"),
        (1_000_000_000, "$1.00B"),
        (812_000_000, "$812.0M"),
        (1_000_000, "$1.0M"),
        (999_999, "$999,999"),
        (12_345.4, "$12,345"),
        (-46_743_000_000, "-$46.74B"),
        (-812_000_000, "-$812.0M"),
        (0, "$0"),
        # Boundaries: a value that would round up to 1000.0M is shown in billions, and one
        # that would round up to 1,000,000 is shown in millions.
        (999_950_000, "$1.00B"),
        (999_949_999, "$999.9M"),
        (-999_950_000, "-$1.00B"),
        (999_999.5, "$1.0M"),
        (999_999.4, "$999,999"),
        (-999_999.5, "-$1.0M"),
    ],
)
def test_usd_display(value: float, text: str) -> None:
    assert usd_text(value) == text


def test_free_cash_flow_says_how_it_is_defined() -> None:
    """A house definition, which can differ from the company's own: the label says which."""
    report = build_report(FactBook(two_year_company()))
    fcf = metric(report, "free_cash_flow", "annual", FY_END)
    margin = metric(report, "fcf_margin", "annual", FY_END)
    definition = (
        "Free cash flow here is operating cash flow less purchases of property and equipment "
        "(PaymentsToAcquirePropertyPlantAndEquipment), a house definition that can differ "
        "from the company's own."
    )
    assert fcf.note == definition
    assert margin.note == f"{definition} The margin divides it by revenue."
    # The label is unchanged: it is part of the model's prompt, which recorded answers key on.
    assert (fcf.label, margin.label) == ("Free cash flow", "Free cash flow margin")
    # A missing value keeps its reason after the definition.
    missing = build_report(
        FactBook(two_year_company(PaymentsToAcquirePropertyPlantAndEquipment=[]))
    )
    note = metric(missing, "free_cash_flow", "annual", FY_END).note
    assert note.startswith(definition) and "No value for" in note


@pytest.mark.parametrize(("ticker", "end", "eps", "margin"), KNOWN_ANNUAL_PER_SHARE_AND_MARGIN)
def test_reported_eps_and_gross_margin_match_the_answer_key(
    ticker: str, end: str, eps: float, margin: float
) -> None:
    """The figures as shown, against the hand-typed key in ``test_facts.py``."""
    report = build_report(FactBook(load_fixture(ticker)), years=10)
    assert metric(report, "eps_diluted", "annual", end).display == f"${eps:.2f}"
    assert metric(report, "gross_margin", "annual", end).display == f"{margin:.1f}%"


@pytest.mark.parametrize(
    ("value", "signed", "text"),
    [
        (55.6, False, "55.6%"),
        (55.649, False, "55.6%"),
        (-2.8, False, "-2.8%"),
        (2.02, True, "+2.0%"),
        (-2.8, True, "-2.8%"),
        (-0.04, False, "0.0%"),
    ],
)
def test_percent_display(value: float, signed: bool, text: str) -> None:
    assert percent_text(value, signed=signed) == text


@pytest.mark.parametrize(("value", "text"), [(1.08, "$1.08"), (-0.255, "-$0.26"), (12.0, "$12.00")])
def test_eps_display(value: float, text: str) -> None:
    assert eps_text(value) == text


# One constructed company


def test_annual_metrics_of_a_constructed_company() -> None:
    report = build_report(FactBook(two_year_company()))
    end = "2025-01-26"
    growth = metric(report, "revenue_yoy", "annual", end)
    assert growth.value == pytest.approx((46_743 - 30_040) / 30_040 * 100)
    assert growth.display == "+55.6%"
    assert growth.formula == "(46,743 − 30,040) ÷ 30,040; USD millions"
    assert growth.unit == "percent"
    assert growth.period_label == "Fiscal year ended 2025-01-26"
    revenue = metric(report, "revenue", "annual", end)
    assert (revenue.value, revenue.display, revenue.formula) == (46_743e6, "$46.74B", "")
    assert metric(report, "gross_margin", "annual", end).value == pytest.approx(
        26_743 / 46_743 * 100
    )
    net = metric(report, "net_margin", "annual", end)
    assert net.value == pytest.approx(-2_500 / 46_743 * 100) and net.display == "-5.3%"
    eps = metric(report, "eps_diluted", "annual", end)
    assert (eps.value, eps.display, eps.unit) == (1.08, "$1.08", "USD_per_share")
    assert metric(report, "capex", "annual", end).display == "$812.0M"
    fcf = metric(report, "free_cash_flow", "annual", end)
    assert fcf.value == (12_000 - 812) * MILLION
    assert fcf.formula == "12,000 − 812; USD millions"
    assert {ref.concept for ref in fcf.inputs} == {
        "NetCashProvidedByUsedInOperatingActivities",
        "PaymentsToAcquirePropertyPlantAndEquipment",
    }
    assert metric(report, "fcf_margin", "annual", end).value == pytest.approx(11_188 / 46_743 * 100)
    assert metric(report, "rnd_ratio", "annual", end).value == pytest.approx(5_000 / 46_743 * 100)


def test_instants_and_their_change_over_one_year() -> None:
    report = build_report(FactBook(two_year_company()))
    cash = metric(report, "cash", "instant", "2025-01-26")
    assert (cash.value, cash.period_label) == (9_000e6, "As of 2025-01-26")
    change = metric(report, "cash_yoy", "instant", "2025-01-26")
    assert change.value == pytest.approx(50.0) and change.display == "+50.0%"
    no_prior = metric(report, "inventory_yoy", "instant", "2025-01-26")
    assert no_prior.value is None and no_prior.display == "n/a"
    assert "one year earlier" in no_prior.note
    missing = metric(report, "receivables", "instant", "2025-01-26")
    assert missing.value is None and "AccountsReceivableNetCurrent" in missing.note


def test_metrics_are_newest_first_within_a_key_and_series_oldest_first() -> None:
    report = build_report(FactBook(two_year_company()))
    ends = [m.period_end for m in report.metrics if m.key == "revenue" and m.period == "annual"]
    assert ends == ["2025-01-26", "2024-01-28"]
    series = [s for s in report.series if s.key == "revenue" and s.period == "annual"]
    assert len(series) == 1
    assert [p.period_end for p in series[0].points] == ["2024-01-28", "2025-01-26"]
    assert [p.display for p in series[0].points] == ["$30.04B", "$46.74B"]
    assert len({(s.key, s.period) for s in report.series}) == len(report.series)
    assert {s.period for s in report.series} <= {"quarter", "annual"}


def test_metric_ids_are_stable_and_unique() -> None:
    report = build_report(FactBook(two_year_company()))
    assert len({m.id for m in report.metrics}) == len(report.metrics)
    assert all(m.id == f"{m.key}:{m.period}:{m.period_end}" for m in report.metrics)


# Limiting cases


@pytest.mark.parametrize(("base", "reason"), [(0.0, "zero"), (-5 * MILLION, "negative")])
def test_growth_needs_a_positive_base(base: float, reason: str) -> None:
    payload = two_year_company(
        Revenues=[fact(46_743 * MILLION, FY_END, FY_START), fact(base, PRIOR_END, PRIOR_START)]
    )
    growth = metric(build_report(FactBook(payload)), "revenue_yoy", "annual", "2025-01-26")
    assert (growth.value, growth.display) == (None, "n/a")
    assert reason in growth.note


@pytest.mark.parametrize("revenue", [0.0, -1 * MILLION])
def test_margins_need_positive_revenue(revenue: float) -> None:
    payload = two_year_company(Revenues=[fact(revenue, FY_END, FY_START)])
    report = build_report(FactBook(payload))
    for key in ("gross_margin", "operating_margin", "net_margin", "rnd_ratio", "fcf_margin"):
        item = metric(report, key, "annual", "2025-01-26")
        assert (item.value, item.display) == (None, "n/a")
        assert "revenue" in item.note.lower()


def test_a_company_without_cost_of_revenue_has_no_gross_margin_and_nothing_else_breaks() -> None:
    payload = two_year_company(CostOfRevenue=[], GrossProfit=[])
    report = build_report(FactBook(payload))
    gross = metric(report, "gross_margin", "annual", "2025-01-26")
    assert gross.value is None and gross.display == "n/a"
    assert "GrossProfit" in gross.note and "CostOfRevenue" in gross.note
    assert metric(report, "operating_margin", "annual", "2025-01-26").value is not None


def test_a_missing_input_is_never_replaced_by_zero() -> None:
    payload = two_year_company(PaymentsToAcquirePropertyPlantAndEquipment=[])
    report = build_report(FactBook(payload))
    for key in ("capex", "free_cash_flow", "fcf_margin"):
        item = metric(report, key, "annual", "2025-01-26")
        assert item.value is None and item.display == "n/a"
        assert "PaymentsToAcquirePropertyPlantAndEquipment" in item.note


def test_empty_facts_give_an_empty_report_that_says_so() -> None:
    report = build_report(FactBook({"cik": 7, "entityName": "Empty Co", "facts": {}}))
    assert (report.company, report.cik, report.metrics, report.series) == ("Empty Co", 7, [], [])
    assert any("No reported values" in note for note in report.notes)


def test_a_single_period() -> None:
    report = build_report(
        FactBook(companyfacts({"Revenues": [fact(5 * MILLION, FY_END, FY_START)]}))
    )
    assert metric(report, "revenue", "annual", "2025-01-26").value == 5 * MILLION
    growth = metric(report, "revenue_yoy", "annual", "2025-01-26")
    assert growth.value is None and "one year earlier" in growth.note
    assert not [m for m in report.metrics if m.period == "quarter"]


def test_malformed_facts_are_counted_in_the_report_notes() -> None:
    payload = two_year_company()
    payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
        fact("lots", Q1_END, FY_START)  # type: ignore[arg-type]
    )
    report = build_report(FactBook(payload))
    assert any("Skipped 1 malformed fact(s) of Revenues" in note for note in report.notes)


def test_period_window_arguments_are_validated() -> None:
    with pytest.raises(ValueError, match="quarters"):
        build_report(FactBook(two_year_company()), quarters=-1)


# Quarters


def _quarterly_company() -> dict[str, Any]:
    """Revenue as 10-Qs report it, cash flow year to date only, EPS for Q1 only."""
    return companyfacts(
        {
            "Revenues": [
                fact(100.0 * MILLION, Q1_END, FY_START, form="10-Q"),
                fact(120.0 * MILLION, H1_END, Q2_START, form="10-Q"),
                fact(220.0 * MILLION, H1_END, FY_START, form="10-Q"),
                fact(350.0 * MILLION, N9_END, FY_START, form="10-Q"),
                fact(500.0 * MILLION, FY_END, FY_START),
            ],
            "NetCashProvidedByUsedInOperatingActivities": [
                fact(10.0 * MILLION, Q1_END, FY_START, form="10-Q"),
                fact(25.0 * MILLION, H1_END, FY_START, form="10-Q"),
            ],
            "EarningsPerShareDiluted": [
                fact(0.5, Q1_END, FY_START, form="10-Q"),
                fact(1.1, H1_END, FY_START, form="10-Q"),
            ],
        }
    )


def test_quarter_metrics_use_standalone_and_derived_quarters() -> None:
    report = build_report(FactBook(_quarterly_company()))
    q4 = metric(report, "revenue", "quarter", "2025-01-26")
    assert q4.value == 150.0 * MILLION
    assert q4.formula == "500 − 350; USD millions"
    assert "Derived" in q4.note
    assert any(ref.derived for ref in q4.inputs) and len(q4.inputs) == 3
    assert q4.period_label == "Quarter ended 2025-01-26"
    qoq = metric(report, "revenue_qoq", "quarter", "2024-07-28")
    assert qoq.value == pytest.approx(20.0) and qoq.formula == "(120 − 100) ÷ 100; USD millions"
    assert metric(report, "operating_cash_flow", "quarter", "2024-07-28").value == 15 * MILLION


def test_quarter_eps_without_a_three_month_fact_is_unavailable_not_differenced() -> None:
    report = build_report(FactBook(_quarterly_company()))
    assert metric(report, "eps_diluted", "quarter", "2024-04-28").value == 0.5
    q2 = metric(report, "eps_diluted", "quarter", "2024-07-28")
    assert (q2.value, q2.display) == (None, "n/a")
    assert "3-month" in q2.note and "differenc" in q2.note


def test_quarter_window_keeps_the_latest_quarters() -> None:
    report = build_report(FactBook(_quarterly_company()), quarters=2, years=0)
    ends = [m.period_end for m in report.metrics if m.key == "revenue"]
    assert ends == ["2025-01-26", "2024-10-27"]
    assert not [m for m in report.metrics if m.period == "annual"]


def test_quarters_and_years_of_unusual_length_are_placed_by_days() -> None:
    payload = companyfacts(
        {
            "Revenues": [
                fact(1.0 * MILLION, "2025-01-06", "2024-01-01"),  # 371 days
                fact(2.0 * MILLION, "2024-04-08", "2024-01-01", form="10-Q"),  # 98 days
            ]
        }
    )
    report = build_report(FactBook(payload))
    assert metric(report, "revenue", "annual", "2025-01-06").value == 1.0 * MILLION
    assert metric(report, "revenue", "quarter", "2024-04-08").value == 2.0 * MILLION


# Recorded filers


@pytest.mark.parametrize(
    ("ticker", "end", "display"),
    [
        ("AAPL", "2023-09-30", "-2.8%"),
        ("AAPL", "2024-09-28", "+2.0%"),
        ("NVDA", "2025-01-26", "+114.2%"),
    ],
)
def test_known_annual_revenue_growth(ticker: str, end: str, display: str) -> None:
    report = build_report(FactBook(load_fixture(ticker)), years=10)
    assert metric(report, "revenue_yoy", "annual", end).display == display


@pytest.mark.parametrize("ticker", list(CIKS))
def test_free_cash_flow_is_operating_cash_flow_less_capex_exactly(ticker: str) -> None:
    report = build_report(FactBook(load_fixture(ticker)))
    checked = 0
    for item in report.metrics:
        if item.key != "free_cash_flow" or item.value is None:
            continue
        ocf = metric(report, "operating_cash_flow", item.period, item.period_end).value
        capex = metric(report, "capex", item.period, item.period_end).value
        assert ocf is not None and capex is not None
        assert item.value == ocf - capex
        checked += 1
    assert checked >= 8


@pytest.mark.parametrize("ticker", list(CIKS))
def test_a_real_report_is_complete_for_the_latest_periods(ticker: str) -> None:
    report = build_report(FactBook(load_fixture(ticker)))
    quarters = [m for m in report.metrics if m.key == "revenue" and m.period == "quarter"]
    years = [m for m in report.metrics if m.key == "revenue" and m.period == "annual"]
    assert len(quarters) == 8 and len(years) == 4
    assert all(m.value is not None and m.value > 0 for m in quarters + years)


# Invariance


@pytest.mark.parametrize("ticker", list(CIKS))
def test_shuffling_fact_lists_changes_nothing_in_the_report(ticker: str) -> None:
    payload = load_fixture(ticker)
    expected = build_report(FactBook(payload)).model_dump()
    for seed in (1, 2):
        assert build_report(FactBook(shuffled(payload, seed))).model_dump() == expected


@pytest.mark.parametrize("ticker", list(CIKS))
def test_a_duplicate_older_filing_changes_nothing_in_the_report(ticker: str) -> None:
    payload = load_fixture(ticker)
    expected = build_report(FactBook(payload)).model_dump()
    doubled = copy.deepcopy(payload)
    for entry in doubled["facts"]["us-gaap"].values():
        for facts in entry["units"].values():
            older = {"filed": "2000-01-01", "accn": "0000000000-00-000000"}
            facts.extend([{**item, **older} for item in facts])
    assert build_report(FactBook(doubled)).model_dump() == expected


def test_a_later_filing_with_a_different_value_wins_and_is_flagged_restated() -> None:
    payload = two_year_company(
        Revenues=[
            fact(46_743 * MILLION, FY_END, FY_START, filed="2025-03-01", accn="ORIGINAL"),
            fact(47_000 * MILLION, FY_END, FY_START, filed="2026-03-01", accn="RESTATED"),
            fact(30_040 * MILLION, PRIOR_END, PRIOR_START),
        ]
    )
    revenue = metric(build_report(FactBook(payload)), "revenue", "annual", "2025-01-26")
    assert revenue.value == 47_000 * MILLION
    assert revenue.inputs[0].accession == "RESTATED" and revenue.inputs[0].restated
    assert "restated" in revenue.note.lower()
