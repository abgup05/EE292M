"""The period check: the years and fiscal labels a statement names, against its evidence.

The fiscal calendars of the three recorded filers are an answer key entered by
hand from their annual reports: NVIDIA's fiscal 2026 ended 2026-01-25, Apple's
2026-09-26, Microsoft's 2026-06-30, and each labels a fiscal year by the
calendar year it ends in.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.facts import FactBook
from app.core.metric_models import Metric
from app.core.metrics import build_report
from app.core.numcheck import quantities
from app.core.periods import (
    FiscalCalendar,
    check_periods,
    fiscal_calendar,
    period_mentions,
    shift_each_year,
    shift_years,
    years_in,
)
from tests.fakes import recorded_facts
from tests.test_facts import companyfacts, fact, load_fixture

NVIDIA_CALENDAR = FiscalCalendar(end_month=1, end_day=25, label_offset=0)
RECORDED_RUN = Path(__file__).parent.parent / "demo" / "recorded-run-v5.json"
NOT_FOUND = "is not in the quotes, the cited figures or the period of a filing quoted"


# The fiscal calendar


def test_nvidias_calendar_places_its_year_end_and_its_second_quarter() -> None:
    calendar = fiscal_calendar(load_fixture("NVDA"))
    assert calendar is not None
    assert (calendar.end_month, calendar.end_day, calendar.label_offset) == (1, 25, 0)
    assert calendar.fiscal_year(date(2026, 1, 25)) == 2026
    assert calendar.fiscal_year(date(2026, 7, 26)) == 2027
    assert calendar.fiscal_year(date(2025, 1, 26)) == 2025  # a year that ended a day later


@pytest.mark.parametrize(
    ("ticker", "year_end", "fy"),
    [("AAPL", date(2026, 9, 26), 2026), ("MSFT", date(2026, 6, 30), 2026)],
)
def test_the_newest_annual_period_is_its_filings_fiscal_year_and_the_next_day_is_the_next(
    ticker: str, year_end: date, fy: int
) -> None:
    calendar = fiscal_calendar(load_fixture(ticker))
    assert calendar is not None
    assert (calendar.end_month, calendar.end_day) == (year_end.month, year_end.day)
    assert calendar.fiscal_year(year_end) == fy
    assert calendar.fiscal_year(year_end + timedelta(days=1)) == fy + 1


def _annual(end: str, start: str, fy: int, *, filed: str, accn: str) -> dict[str, Any]:
    return fact(100.0, end, start, filed=filed, accn=accn, form="10-K", fy=fy)


def test_a_company_that_names_the_year_it_begins_in_has_an_offset_of_minus_one() -> None:
    body = companyfacts(
        {"Revenues": [_annual("2026-02-01", "2025-02-02", 2025, filed="2026-03-20", accn="a-1")]}
    )
    calendar = fiscal_calendar(body)
    assert calendar is not None and calendar.label_offset == -1
    assert calendar.fiscal_year(date(2026, 2, 1)) == 2025
    assert calendar.fiscal_year(date(2026, 5, 3)) == 2026


def test_a_52_53_week_year_end_that_moves_from_the_25th_to_the_31st() -> None:
    body = companyfacts(
        {
            "Revenues": [
                _annual("2026-01-25", "2025-01-27", 2026, filed="2026-02-25", accn="a-1"),
                _annual("2027-01-31", "2026-01-26", 2027, filed="2027-02-24", accn="a-2"),
            ]
        }
    )
    calendar = fiscal_calendar(body)
    assert calendar is not None
    assert (calendar.end_month, calendar.end_day, calendar.label_offset) == (1, 31, 0)
    assert calendar.fiscal_year(date(2026, 1, 25)) == 2026  # ended six days before the 31st
    assert calendar.fiscal_year(date(2027, 1, 31)) == 2027
    assert calendar.fiscal_year(date(2027, 2, 1)) == 2028
    # Read from the earlier year, the later year's end six days after the 25th is still its end.
    assert NVIDIA_CALENDAR.fiscal_year(date(2027, 1, 31)) == 2027
    assert NVIDIA_CALENDAR.fiscal_year(date(2027, 4, 25)) == 2028


def test_a_december_year_end_takes_the_first_days_of_january_as_its_drift() -> None:
    calendar = FiscalCalendar(end_month=12, end_day=31, label_offset=0)
    assert calendar.fiscal_year(date(2027, 1, 2)) == 2026  # a 53-week year ending on a Saturday
    assert calendar.fiscal_year(date(2026, 12, 26)) == 2026
    assert calendar.fiscal_year(date(2027, 3, 31)) == 2027


def test_an_amendment_with_no_year_long_period_does_not_hide_the_annual_report() -> None:
    cover = fact(5.0, "2026-04-15", filed="2026-04-20", accn="a-2", form="10-K/A", fy=2026)
    body = companyfacts(
        {
            "Revenues": [_annual("2026-01-25", "2025-01-27", 2026, filed="2026-02-25", accn="a-1")],
            "CashAndCashEquivalentsAtCarryingValue": [cover],
        }
    )
    calendar = fiscal_calendar(body)
    assert calendar is not None and (calendar.end_month, calendar.end_day) == (1, 25)


def test_no_annual_report_gives_no_calendar() -> None:
    quarterly = fact(1.0, "2026-04-26", "2026-01-26", form="10-Q", fy=2027, fp="Q1")
    assert fiscal_calendar(companyfacts({"Revenues": [quarterly]})) is None


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "facts",
        {"facts": "not an object"},
        {"facts": {"us-gaap": []}},
        {"facts": {"us-gaap": {"Revenues": {"units": "USD"}}}},
        {"facts": {"us-gaap": {"Revenues": {"units": {"USD": "not a list"}}}}},
        {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [None, 3, "x"]}}}}},
        companyfacts(
            {
                "Revenues": [
                    {"start": "2025-01-27", "end": "bad", "form": "10-K", "filed": 5, "fy": "x"},
                    {"start": "2025-01-27", "end": "2026-01-25", "form": 7, "fy": 2026},
                    {"start": "2025-01-27", "end": "2026-01-25", "form": "10-K", "fy": True},
                ]
            }
        ),
        companyfacts(
            {"Revenues": [_annual("2026-01-25", "2025-01-27", 2031, filed="2026-02-25", accn="x")]}
        ),
    ],
)
def test_a_malformed_body_gives_no_calendar_and_no_exception(body: object) -> None:
    assert fiscal_calendar(body) is None


# The years a statement names


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Revenue grew in fiscal 2026.", [(2026, True)]),
        ("Revenue in fiscal year 2026 was a record.", [(2026, True)]),
        ("Fiscal Year 2026 revenue was a record.", [(2026, True)]),
        ("Revenue rose in fiscal years 2025 and 2026.", [(2025, True), (2026, True)]),
        ("Revenue rose in fiscal 2025 and 2026.", [(2025, True), (2026, True)]),
        ("From fiscal 2024 to fiscal 2026 revenue tripled.", [(2024, True), (2026, True)]),
        ("Fiscal years 2024 through 2026 saw growth.", [(2024, True), (2026, True)]),
        ("FY2026 revenue was a record.", [(2026, True)]),
        ("FY 2026 revenue was a record.", [(2026, True)]),
        ("FY26 revenue was a record.", [(2026, True)]),
        ("Revenue in Q4 FY25 was a record.", [(2025, True)]),
        ("Revenue for fiscal '26 was a record.", [(2026, True)]),
        ("Revenue in the first quarter of fiscal 2027 rose.", [(2027, True)]),
        ("Revenue rose in 2025.", [(2025, False)]),
        ("Revenue rose in Q2 2026.", [(2026, False)]),
        ("Revenue rose in July 2026.", [(2026, False)]),
        ("The quarter ended on January 25, 2026.", [(2026, False)]),
        ("The quarter ended on Sep. 28, 2025.", [(2025, False)]),
        ("The quarter ended 2026-01-25.", [(2026, False)]),
        ("Sales in 2024 and 2025 rose.", [(2024, False), (2025, False)]),
        ("Demand has grown since 2020.", [(2020, False)]),
        ("For the year ended December 31, 2025 sales rose.", [(2025, False)]),
        ("The fiscal year ended January 25, 2026 was a record.", [(2026, False)]),
        ("CY2025 shipments rose.", [(2025, False)]),
        ("At fiscal year-end 2026, receivables were concentrated.", [(2026, True)]),
        ("At the fiscal year end 2026, receivables were concentrated.", [(2026, True)]),
        ("At year-end 2026, receivables were concentrated.", [(2026, False)]),
        ("In the fiscal year ended 2026 revenue rose.", [(2026, False)]),
    ],
)
def test_period_mentions_reads_each_form(text: str, expected: list[tuple[int, bool]]) -> None:
    assert [(m.year, m.fiscal) for m in period_mentions(text)] == expected


@pytest.mark.parametrize(
    "text",
    [
        "The company has 2000 employees.",
        "See Note 5 to the statements.",
        "As described in the 10-K, demand rose.",
        "Revenue was $2,026 million.",
        "Sales were made under a Rule 10b5-1 plan.",
        "The RTX 5090 launched.",
        "The company operates 2,026 stores.",
        "The shares trade at 30x earnings.",
        "Revenue was $2025 million.",
        "The 2025 stores were refitted.",
    ],
)
def test_period_mentions_finds_nothing_in_a_quantity_or_a_name(text: str) -> None:
    assert period_mentions(text) == []


def test_mentions_keep_the_words_that_name_them() -> None:
    assert [m.raw for m in period_mentions("In fiscal 2026 and in July 2026, FY27 began.")] == [
        "fiscal 2026",
        "July 2026",
        "FY27",
    ]


def _statements() -> list[str]:
    record = json.loads(RECORDED_RUN.read_text())
    findings = [*record["findings"], *record["unsupported_findings"]]
    return [finding["statement"] for finding in findings]


def test_no_year_period_mentions_finds_is_a_number_the_number_check_checks() -> None:
    found = 0
    for statement in _statements():
        numbers = [q for q in quantities(statement) if q.unit in ("plain", "count", "usd")]
        for mention in period_mentions(statement):
            found += 1
            assert mention.raw in statement
            clash = [q.raw for q in numbers if q.value == mention.year]
            assert not clash, (statement, mention, clash)
    assert found >= 3, "the recorded run names too few years for this test to mean anything"


# The years an excerpt shows


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Revenue for fiscal year 2025 was $130.5 billion", {2025}),
        ("FY26 revenue rose; FY 2027 began", {2026, 2027}),
        ("for fiscal '26", {2026}),
        ("Year Ended Jan 25, 2026 Jan 26, 2025", {2025, 2026}),
        ("2026-01-25", {2026}),
        ("2025 2024 Change", {2024, 2025}),
        ("$2,026 million and 1,995 units", set()),
        ("1899 and 1900 and 2101", {1900}),
        ("up 117% from a year ago", set()),
    ],
)
def test_years_in_is_generous(text: str, expected: set[int]) -> None:
    assert years_in(text) == expected


# The check


REFEREE_QUOTE = "Revenue for fiscal year 2025 was $130.5 billion"
NO_YEAR_QUOTE = "Data Center revenue was $89.0 billion, up 117% from a year ago."
FY2026_10K = date(2026, 1, 25)
Q2_FY2027_10Q = date(2026, 7, 26)


def test_the_referees_case_a_figure_put_in_fiscal_2023_is_unverified() -> None:
    check = check_periods(
        "Revenue was $130,497 million in fiscal 2023.",
        [(REFEREE_QUOTE, FY2026_10K)],
        [],
        NVIDIA_CALENDAR,
    )
    assert check.status == "unverified" and check.checked == 1
    assert check.unverified == ["fiscal 2023"] and check.comparative == []
    assert check.details == [f"fiscal 2023 {NOT_FOUND}"]


def test_the_same_statement_with_the_quoted_year_passes() -> None:
    check = check_periods(
        "Revenue was $130,497 million in fiscal 2025.",
        [(REFEREE_QUOTE, FY2026_10K)],
        [],
        NVIDIA_CALENDAR,
    )
    assert check.status == "passed" and check.details == ["fiscal 2025 is in a quote"]


def test_the_same_statement_with_the_filings_own_year_passes() -> None:
    check = check_periods(
        "Revenue was $130,497 million in fiscal 2026.",
        [(REFEREE_QUOTE, FY2026_10K)],
        [],
        NVIDIA_CALENDAR,
    )
    assert check.status == "passed" and check.unverified == []
    assert check.details == [
        "fiscal 2026 is the fiscal year of a filing quoted (period ended 2026-01-25)"
    ]


def test_the_year_before_a_filings_own_year_is_unverified_and_comparative() -> None:
    check = check_periods(
        "Data Center revenue grew 117% in fiscal 2024.",
        [(NO_YEAR_QUOTE, FY2026_10K)],
        [],
        NVIDIA_CALENDAR,
    )
    assert check.status == "unverified"
    assert check.unverified == ["fiscal 2024"] and check.comparative == ["fiscal 2024"]


@pytest.mark.parametrize(
    ("statement", "status", "comparative"),
    [
        ("Revenue rose in the second quarter of fiscal 2027.", "passed", []),
        ("Revenue rose in the second quarter of fiscal 2026.", "unverified", ["fiscal 2026"]),
        ("Revenue rose in July 2026.", "passed", []),
        ("Revenue rose in 2024.", "unverified", []),
    ],
)
def test_a_quarter_is_placed_by_the_10q_it_is_quoted_from(
    statement: str, status: str, comparative: list[str]
) -> None:
    check = check_periods(statement, [(NO_YEAR_QUOTE, Q2_FY2027_10Q)], [], NVIDIA_CALENDAR)
    assert check.status == status and check.comparative == comparative


def test_a_quote_from_a_page_that_is_not_a_filing_gives_only_its_text() -> None:
    check = check_periods("Revenue rose in fiscal 2026.", [(NO_YEAR_QUOTE, None)], [], None)
    assert check.status == "unverified" and check.comparative == []


def _nvidia_metric(metric_id: str) -> Metric:
    report = build_report(FactBook(recorded_facts()))
    return next(metric for metric in report.metrics if metric.id == metric_id)


def test_the_fiscal_year_of_a_cited_figure_passes_with_no_quote() -> None:
    growth = _nvidia_metric("revenue_yoy:annual:2026-01-25")
    check = check_periods("Revenue grew 65% in fiscal 2026.", [], [growth], NVIDIA_CALENDAR)
    assert check.status == "passed"
    assert check.details == [
        "fiscal 2026 is the fiscal year of a cited figure (period ended 2026-01-25)"
    ]


def test_the_base_year_of_a_year_over_year_figure_passes() -> None:
    growth = _nvidia_metric("revenue_yoy:annual:2026-01-25")
    assert [ref.end for ref in growth.inputs] == ["2026-01-25", "2025-01-26"]
    check = check_periods(
        "Revenue grew 65% from fiscal 2025 to fiscal 2026.", [], [growth], NVIDIA_CALENDAR
    )
    assert check.status == "passed" and check.checked == 2
    wrong_base = check_periods(
        "Revenue grew 65% from fiscal 2022 to fiscal 2026.", [], [growth], NVIDIA_CALENDAR
    )
    assert wrong_base.unverified == ["fiscal 2022"] and wrong_base.comparative == []
    # Two years before the base year is a comparison year of the report that holds the base.
    older = check_periods("Revenue grew 65% from fiscal 2023.", [], [growth], NVIDIA_CALENDAR)
    assert older.comparative == ["fiscal 2023"]


def test_without_a_calendar_a_period_end_may_be_its_own_year_or_the_next() -> None:
    excerpts = [(NO_YEAR_QUOTE, FY2026_10K)]
    check = check_periods("Revenue rose in fiscal 2026 and fiscal 2027.", excerpts, [], None)
    assert check.status == "passed" and check.checked == 2
    assert any("fiscal calendar could not be read" in detail for detail in check.details)
    before = check_periods("Revenue rose in fiscal 2025.", excerpts, [], None)
    assert before.unverified == ["fiscal 2025"] and before.comparative == ["fiscal 2025"]


def test_a_bare_year_may_be_a_fiscal_label_and_a_fiscal_label_is_not_a_calendar_year() -> None:
    excerpts = [(NO_YEAR_QUOTE, Q2_FY2027_10Q)]
    assert check_periods("Revenue rose in 2027.", excerpts, [], NVIDIA_CALENDAR).status == "passed"
    # The 10-Q's period ends in calendar 2026, but its fiscal year is 2027.
    fiscal = check_periods("Revenue rose in fiscal 2026.", excerpts, [], NVIDIA_CALENDAR)
    assert fiscal.status == "unverified"


def test_a_statement_that_names_no_year_is_not_checked() -> None:
    check = check_periods("Revenue rose 56%.", [(NO_YEAR_QUOTE, FY2026_10K)], [], None)
    assert (check.status, check.checked, check.details) == ("none", 0, [])


def test_a_comparative_detail_says_so_and_the_details_give_back_each_year_not_found() -> None:
    check = check_periods(
        "Revenue grew 117% in fiscal 2024, and in fiscal 2026, after fiscal 2023.",
        [(NO_YEAR_QUOTE, FY2026_10K)],
        [],
        NVIDIA_CALENDAR,
    )
    assert check.unverified == ["fiscal 2024", "fiscal 2023"]
    assert check.comparative == ["fiscal 2024"]
    assert check.details[0] == (
        f"fiscal 2024 {NOT_FOUND}; it is a year or two before the fiscal year of a filing "
        "quoted or a cited figure, as a report's comparison year would be"
    )
    assert [(u.raw, u.comparative) for u in check.unplaced] == [
        ("fiscal 2024", True),
        ("fiscal 2023", False),
    ]
    assert [u.detail for u in check.unplaced] == [check.details[0], check.details[2]]


# Planting a wrong year, to measure what the check catches -------------------------------------


SHIFTED: list[tuple[str, int, str]] = [
    ("Revenue was $130.5 billion in fiscal 2025.", -1, "fiscal 2024."),
    ("In fiscal years 2025 and 2026 margin fell.", -3, "fiscal years 2022 and 2023 margin"),
    ("FY26 revenue rose.", -1, "FY25 revenue rose."),
    ("fiscal '26 was strong", 1, "fiscal '27 was strong"),
    ("For the quarter ended 2026-07-26 it was up.", -1, "ended 2025-07-26 it was up."),
    ("As of January 25, 2026 the balance was higher.", -2, "As of January 25, 2024 the balance"),
    ("In Q2 2026 and in 2024 it grew.", -1, "In Q2 2025 and in 2023 it grew."),
    # What is not a year is left alone, and so is everything else.
    ("It has 2000 employees and $2,026 million of debt in fiscal 2026.", -1, "in fiscal 2025."),
    ("No year is named here: revenue grew 56%.", -1, "No year is named here: revenue grew 56%."),
]


@pytest.mark.parametrize(("text", "by", "expected_part"), SHIFTED)
def test_shift_years_moves_every_year_named_and_nothing_else(
    text: str, by: int, expected_part: str
) -> None:
    shifted = shift_years(text, by)
    assert expected_part in shifted
    # Nothing but year digits changed: the same length, and the same text once digits are masked.
    assert len(shifted) == len(text)
    assert re.sub(r"\d", "0", shifted) == re.sub(r"\d", "0", text)
    # The quantities are untouched.
    for quantity in ("2000 employees", "$2,026 million", "56%", "$130.5 billion"):
        assert (quantity in text) == (quantity in shifted)


def test_a_shifted_statement_names_the_shifted_years() -> None:
    statement = "Gross margin was 71.1% in fiscal 2026, down from 75.0% in fiscal 2025."
    shifted = shift_years(statement, -3)
    assert [m.year for m in period_mentions(shifted)] == [2023, 2022]
    assert [m.fiscal for m in period_mentions(shifted)] == [True, True]


# A date is a calendar date (found by planting wrong years, 17 November 2026) ------------------


def test_a_date_does_not_pass_as_a_fiscal_label() -> None:
    """ "July 26, 2027" passed against the 10-Q for the quarter ended 2026-07-26.

    NVIDIA's fiscal year for that quarter is 2027, and a year that is not a fiscal label
    was let through on the fiscal year of the filing, since a bare year may be one. A
    date is not a bare year: it names a calendar year, and July 2027 is a year after
    the quarter. A bare year keeps the benefit of the doubt.
    """
    quarter = [("Dividends paid were $6.0 billion.", date(2026, 7, 26))]
    for dated in ("as of July 26, 2027", "in June 2027", "on 2027-07-26"):
        check = check_periods(f"The balance {dated} was higher.", quarter, [], NVIDIA_CALENDAR)
        assert check.status == "unverified", dated
    for fine in ("as of July 26, 2026", "in June 2026", "in 2027", "in fiscal 2027"):
        check = check_periods(f"The balance {fine} was higher.", quarter, [], NVIDIA_CALENDAR)
        assert check.status == "passed", (fine, check.details)


def test_period_mentions_mark_a_date() -> None:
    mentions = period_mentions("On January 25, 2026 and in March 2026, as in 2025 and fiscal 2026.")
    assert [(m.year, m.fiscal, m.dated) for m in mentions] == [
        (2026, False, True),
        (2026, False, True),
        (2025, False, False),
        (2026, True, False),
    ]


def test_the_comparison_year_after_compared_to_is_a_year() -> None:
    """Planting showed "during 2026 compared to 2025" moved as "during 2025 compared to 2025"."""
    statement = "Greater China net sales increased during 2026 compared to 2025."
    assert [m.year for m in period_mentions(statement)] == [2026, 2025]
    assert shift_years(statement, -1) == (
        "Greater China net sales increased during 2025 compared to 2024."
    )


# A year before 1990 is evidence too (fourth referee, 17 November 2026) -------------------------

INCORPORATED = "The company was incorporated in Delaware in {year}."


@pytest.mark.parametrize("year", [1900, 1919, 1950, 1989])
def test_a_year_before_1990_that_the_quote_prints_is_found(year: int) -> None:
    """The evidence stopped at 1990 while a statement's years start at 1900."""
    quote = INCORPORATED.format(year=year)
    assert years_in(quote) == {year}
    check = check_periods(
        f"The company was incorporated in {year}.", [(quote, FY2026_10K)], [], NVIDIA_CALENDAR
    )
    assert check.status == "passed" and check.details == [f"{year} is in a quote"]


def test_a_year_before_1990_that_the_quote_does_not_print_is_still_unverified() -> None:
    check = check_periods(
        "The company was incorporated in 1925.",
        [(INCORPORATED.format(year=1919), FY2026_10K)],
        [],
        NVIDIA_CALENDAR,
    )
    assert check.status == "unverified" and check.unverified == ["1925"]


def test_the_years_an_excerpt_shows_are_the_years_a_statement_can_name() -> None:
    assert years_in("1899 and 1900 and 2100 and 2101") == {1900, 2100}


# A year used as an adjective is a year the period check reads (fourth referee) -----------------


def test_a_year_before_a_financial_noun_is_a_mention() -> None:
    assert [(m.raw, m.year, m.fiscal) for m in period_mentions("2025 revenue was a record.")] == [
        ("2025", 2025, False)
    ]
    assert [m.year for m in period_mentions("2026 net income and 2025 sales rose.")] == [2026, 2025]


def test_a_wrong_year_before_revenue_is_unverified_and_the_right_one_passes() -> None:
    wrong = check_periods(
        "2023 revenue was $130.5 billion.", [(REFEREE_QUOTE, FY2026_10K)], [], NVIDIA_CALENDAR
    )
    assert wrong.status == "unverified" and wrong.unverified == ["2023"]
    right = check_periods(
        "2025 revenue was $130.5 billion.", [(REFEREE_QUOTE, FY2026_10K)], [], NVIDIA_CALENDAR
    )
    assert right.status == "passed" and right.details == ["2025 is in a quote"]


@pytest.mark.parametrize(
    "text",
    ["The company has 2025 employees.", "It operates 2,025 stores.", "It shipped 2025 units."],
)
def test_a_count_before_any_other_noun_is_not_a_mention(text: str) -> None:
    assert period_mentions(text) == []


# Planting one wrong year beside right ones (fourth referee) ------------------------------------


def test_shift_each_year_moves_one_year_at_a_time_and_leaves_the_others() -> None:
    statement = "Gross margin was 71.1% in fiscal 2026, down from 75.0% in fiscal 2025."
    planted = shift_each_year(statement, -1)
    assert [(mention.raw, text) for mention, text in planted] == [
        ("fiscal 2026", "Gross margin was 71.1% in fiscal 2025, down from 75.0% in fiscal 2025."),
        ("fiscal 2025", "Gross margin was 71.1% in fiscal 2026, down from 75.0% in fiscal 2024."),
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "In fiscal years 2025 and 2026 margin fell.",
            [
                "In fiscal years 2024 and 2026 margin fell.",
                "In fiscal years 2025 and 2025 margin fell.",
            ],
        ),
        ("FY26 and FY25 revenue.", ["FY25 and FY25 revenue.", "FY26 and FY24 revenue."]),
        (
            "As of January 25, 2026, up from 2025 revenue.",
            [
                "As of January 25, 2025, up from 2025 revenue.",
                "As of January 25, 2026, up from 2024 revenue.",
            ],
        ),
        ("Revenue rose in fiscal 2026.", ["Revenue rose in fiscal 2025."]),
        ("It has 2000 employees and no year.", []),
    ],
)
def test_shift_each_year_plants_one_statement_per_year_named(
    text: str, expected: list[str]
) -> None:
    planted = [moved for _, moved in shift_each_year(text, -1)]
    assert planted == expected
    for moved in planted:
        # One year moved, nothing else: the same text once digits are masked.
        assert re.sub(r"\d", "0", moved) == re.sub(r"\d", "0", text)


def test_each_planted_year_is_flagged_where_the_evidence_holds_only_the_right_ones() -> None:
    statement = "Revenue was $130.5 billion in fiscal 2025 and grew in fiscal 2026."
    excerpts = [(REFEREE_QUOTE, FY2026_10K)]
    assert check_periods(statement, excerpts, [], NVIDIA_CALENDAR).status == "passed"
    flagged = [
        check_periods(moved, excerpts, [], NVIDIA_CALENDAR).unverified
        for _, moved in shift_each_year(statement, -1)
    ]
    # fiscal 2025 -> 2024 is nowhere; fiscal 2026 -> 2025 is in the quote, so it passes.
    assert flagged == [["fiscal 2024"], []]
