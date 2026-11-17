"""Reading SEC XBRL company facts: fetching, validation, selection and derivation.

Synthetic company facts test each rule in isolation; the recorded fixtures
(``make fixtures-facts``) test the rules against three real filers. The
known values below were entered by hand from the companies' annual reports
and are the answer key: when the code and the key disagree, the code is wrong.
"""

from __future__ import annotations

import copy
import gzip
import json
import random
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.core.facts import (
    GROUPS,
    FactBook,
    FactsError,
    parse_fact,
    period_length,
)
from app.core.ports import SourceError
from app.sources.xbrl import company_facts_url, fetch_company_facts

EDGAR_FIXTURES = Path(__file__).parent / "fixtures" / "edgar"
CIKS = {"NVDA": 1045810, "AAPL": 320193, "MSFT": 789019}
MILLION = 1_000_000

# Helpers shared with test_metrics.py


def fact(
    val: float,
    end: str,
    start: str | None = None,
    *,
    filed: str = "2025-03-01",
    accn: str = "0000000001-25-000001",
    form: str = "10-K",
    fy: int = 2025,
    fp: str = "FY",
) -> dict[str, Any]:
    """One company-facts entry as EDGAR writes it."""
    entry: dict[str, Any] = {
        "end": end,
        "val": val,
        "accn": accn,
        "fy": fy,
        "fp": fp,
        "form": form,
        "filed": filed,
    }
    if start is not None:
        entry["start"] = start
    return entry


def companyfacts(
    concepts: dict[str, list[dict[str, Any]]], *, cik: int = 1, name: str = "Test Corp"
) -> dict[str, Any]:
    """A company-facts body holding ``concepts`` (EPS in USD/shares, the rest in USD)."""
    gaap = {
        concept: {
            "label": concept,
            "units": {"USD/shares" if concept.startswith("EarningsPerShare") else "USD": facts},
        }
        for concept, facts in concepts.items()
    }
    return {"cik": cik, "entityName": name, "facts": {"us-gaap": gaap}}


def load_fixture(ticker: str) -> dict[str, Any]:
    """The recorded company facts of ``ticker``; skips when not recorded."""
    path = EDGAR_FIXTURES / f"companyfacts-CIK{CIKS[ticker]:010d}.json.gz"
    if not path.exists():
        pytest.skip(f"no recorded company facts for {ticker}; run `make fixtures-facts`")
    return json.loads(gzip.decompress(path.read_bytes()))


def shuffled(payload: dict[str, Any], seed: int) -> dict[str, Any]:
    """A deep copy with every fact list, and the concept order, shuffled."""
    rng = random.Random(seed)
    result = copy.deepcopy(payload)
    gaap = result["facts"]["us-gaap"]
    names = list(gaap)
    rng.shuffle(names)
    result["facts"]["us-gaap"] = {name: gaap[name] for name in names}
    for entry in result["facts"]["us-gaap"].values():
        for facts in entry["units"].values():
            rng.shuffle(facts)
    return result


# A synthetic fiscal year: 2024-01-29 to 2025-01-26 (52 weeks), quarters of 13 weeks.
FY_START, Q1_END, H1_END, N9_END, FY_END = (
    "2024-01-29",
    "2024-04-28",
    "2024-07-28",
    "2024-10-27",
    "2025-01-26",
)
Q2_START, Q3_START, Q4_START = "2024-04-29", "2024-07-29", "2024-10-28"


# Source adapter


def test_company_facts_url_pads_the_cik_to_ten_digits() -> None:
    assert (
        company_facts_url(1045810)
        == "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json"
    )


@pytest.mark.parametrize("cik", [0, -5, 10**10])
def test_company_facts_url_rejects_impossible_ciks(cik: int) -> None:
    with pytest.raises(ValueError, match="CIK"):
        company_facts_url(cik)


def test_fetch_company_facts_parses_the_body_from_the_given_getter() -> None:
    seen: list[str] = []

    def get(url: str) -> bytes:
        seen.append(url)
        return b'{"cik": 320193, "entityName": "Apple Inc.", "facts": {}}'

    payload = fetch_company_facts(get, 320193)
    assert payload["entityName"] == "Apple Inc."
    assert seen == ["https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"]


@pytest.mark.parametrize("body", [b"<html>not json</html>", b"\xff\xfe\x00", b"[1, 2]"])
def test_fetch_company_facts_maps_bad_bodies_to_source_error(body: bytes) -> None:
    with pytest.raises(SourceError, match="company facts"):
        fetch_company_facts(lambda url: body, 320193)


# Rejection


def test_a_list_is_rejected() -> None:
    with pytest.raises(FactsError, match="JSON object"):
        FactBook([])  # type: ignore[arg-type]


def test_a_body_without_facts_is_rejected() -> None:
    with pytest.raises(FactsError, match="'facts'"):
        FactBook({"cik": 1, "entityName": "Test Corp"})


@pytest.mark.parametrize(
    ("payload", "problem"),
    [
        ({"entityName": "X", "facts": {}}, "'cik'"),
        ({"cik": "abc", "entityName": "X", "facts": {}}, "'cik'"),
        ({"cik": 1, "facts": {}}, "'entityName'"),
        ({"cik": 1, "entityName": "X", "facts": {"us-gaap": []}}, "'us-gaap'"),
        (
            {"cik": 1, "entityName": "X", "facts": {"us-gaap": {"Revenues": {"units": []}}}},
            "Revenues",
        ),
        (
            {
                "cik": 1,
                "entityName": "X",
                "facts": {"us-gaap": {"Revenues": {"units": {"USD": {"end": "x"}}}}},
            },
            "Revenues",
        ),
    ],
)
def test_malformed_structure_is_rejected_with_a_message_naming_it(
    payload: dict[str, Any], problem: str
) -> None:
    with pytest.raises(FactsError, match=problem):
        FactBook(payload)


def test_a_fact_without_end_is_rejected_by_name() -> None:
    raw = fact(5.0, FY_END, FY_START)
    del raw["end"]
    with pytest.raises(FactsError, match="'end'"):
        parse_fact("Revenues", "USD", raw)


@pytest.mark.parametrize("val", ["12", None, True, float("nan")])
def test_a_fact_with_a_non_numeric_val_is_rejected_by_name(val: object) -> None:
    with pytest.raises(FactsError, match="'val'"):
        parse_fact("Revenues", "USD", fact(val, FY_END, FY_START))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"end": "2025-13-40"}, "'end'"),
        ({"start": "2026-01-01"}, "after its end"),
        ({"filed": None}, "'filed'"),
        ({"accn": 7}, "'accn'"),
    ],
)
def test_other_malformed_facts_are_rejected_by_name(change: dict[str, Any], problem: str) -> None:
    raw = fact(5.0, FY_END, FY_START) | change
    with pytest.raises(FactsError, match=problem):
        parse_fact("Revenues", "USD", raw)


def test_one_malformed_fact_is_skipped_and_counted_not_fatal() -> None:
    bad = fact(1.0, FY_END, FY_START)
    del bad["end"]
    book = FactBook(
        companyfacts(
            {"Revenues": [fact(100.0, FY_END, FY_START), bad, fact("x", Q1_END, FY_START)]}
        )
    )
    assert book.annuals("revenue")[date(2025, 1, 26)].value == 100.0
    assert len(book.problems) == 2
    assert any("'end'" in note and "Revenues" in note for note in book.problems)
    assert any("'val'" in note for note in book.problems)


def test_empty_facts_give_an_empty_book() -> None:
    book = FactBook({"cik": 7, "entityName": "Empty Co", "facts": {}})
    assert (book.name, book.cik) == ("Empty Co", 7)
    for key in GROUPS:
        assert book.durations(key) == {}
        assert book.instants(key) == {}
        assert book.quarters(key) == {}
        assert book.annuals(key) == {}


# Period placement


@pytest.mark.parametrize(
    ("start", "end", "length"),
    [
        ("2024-01-29", "2025-01-26", "annual"),  # 363 days, a 52-week year
        ("2023-01-30", "2024-01-28", "annual"),  # 363 days
        ("2024-01-01", "2024-12-30", "annual"),  # 364 days
        ("2022-09-25", "2023-09-30", "annual"),  # 370 days, Apple's 53-week fiscal 2023
        ("2024-01-01", "2025-01-06", "annual"),  # 371 days
        ("2024-01-01", "2024-04-01", "quarter"),  # 91 days
        ("2024-01-01", "2024-04-08", "quarter"),  # 98 days
        ("2024-01-01", "2024-07-01", "half_year"),
        ("2024-01-01", "2024-09-30", "nine_months"),
        ("2024-01-01", "2024-05-01", None),  # 121 days: not a reporting period
        ("2024-01-01", "2024-01-31", None),
    ],
)
def test_period_length_is_decided_by_days(start: str, end: str, length: str | None) -> None:
    assert period_length(date.fromisoformat(start), date.fromisoformat(end)) == length


def test_fiscal_year_and_period_fields_are_ignored_for_placement() -> None:
    # A fiscal year whose fy and fp say something else: only its dates place it. (Its form
    # is an annual report's: since 17 November 2026 that is what makes a year-long period a
    # fiscal year, see test_twelve_months_to_a_quarter_end_is_not_a_fiscal_year.)
    misleading = fact(70.0, "2024-01-28", "2023-01-30", fy=2010, fp="Q3", form="10-K")
    book = FactBook(companyfacts({"Revenues": [misleading]}))
    assert list(book.annuals("revenue")) == [date(2024, 1, 28)]
    assert book.quarters("revenue") == {}


def test_instants_are_keyed_by_their_date() -> None:
    book = FactBook(
        companyfacts({"CashAndCashEquivalentsAtCarryingValue": [fact(9.0, "2025-01-26")]})
    )
    cash = book.instants("cash")[date(2025, 1, 26)]
    assert cash.value == 9.0 and cash.start is None
    assert book.durations("cash") == {}


# Selection and de-duplication


def test_a_later_filing_with_a_different_value_wins_and_is_flagged_restated() -> None:
    first = fact(100.0, FY_END, FY_START, filed="2025-03-01", accn="A-1")
    later = fact(104.0, FY_END, FY_START, filed="2026-03-01", accn="A-2")
    value = FactBook(companyfacts({"Revenues": [later, first]})).annuals("revenue")[
        date(2025, 1, 26)
    ]
    assert value.value == 104.0
    assert value.refs[0].accession == "A-2"
    assert value.refs[0].restated and value.restated
    assert "100" in value.refs[0].note and "A-1" in value.refs[0].note


def test_a_duplicate_older_filing_of_the_same_value_changes_nothing() -> None:
    base = companyfacts({"Revenues": [fact(100.0, FY_END, FY_START, filed="2026-03-01")]})
    doubled = copy.deepcopy(base)
    doubled["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
        fact(100.0, FY_END, FY_START, filed="2025-03-01", accn="OLD")
    )
    assert FactBook(base).annuals("revenue") == FactBook(doubled).annuals("revenue")
    assert not FactBook(doubled).annuals("revenue")[date(2025, 1, 26)].restated


def test_the_first_concept_with_a_value_for_the_exact_period_is_taken() -> None:
    book = FactBook(
        companyfacts(
            {
                "Revenues": [fact(1.0, FY_END, FY_START), fact(2.0, "2024-01-28", "2023-01-30")],
                "RevenueFromContractWithCustomerExcludingAssessedTax": [
                    fact(10.0, FY_END, FY_START)
                ],
                "SalesRevenueNet": [fact(30.0, "2023-01-29", "2022-01-31")],
            }
        )
    )
    annual = book.annuals("revenue")
    assert annual[date(2025, 1, 26)].value == 10.0
    preferred = "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert annual[date(2025, 1, 26)].concept == preferred
    assert annual[date(2024, 1, 28)].value == 2.0
    assert annual[date(2023, 1, 29)].concept == "SalesRevenueNet"


def test_other_units_of_a_concept_are_ignored() -> None:
    payload = companyfacts({"Revenues": [fact(100.0, FY_END, FY_START)]})
    payload["facts"]["us-gaap"]["Revenues"]["units"]["EUR"] = [fact(90.0, FY_END, FY_START)]
    assert FactBook(payload).annuals("revenue")[date(2025, 1, 26)].value == 100.0


def test_shuffling_fact_lists_changes_nothing_on_a_real_filer() -> None:
    payload = load_fixture("NVDA")
    book, other = FactBook(payload), FactBook(shuffled(payload, seed=3))
    for key in GROUPS:
        assert book.durations(key) == other.durations(key)
        assert book.instants(key) == other.instants(key)
        assert book.quarters(key) == other.quarters(key)


# Standalone quarters


def _year_to_date_company() -> dict[str, Any]:
    """Operating cash flow as a 10-Q reports it: year to date only, plus the annual value."""
    return companyfacts(
        {
            "NetCashProvidedByUsedInOperatingActivities": [
                fact(10.0, Q1_END, FY_START, form="10-Q", accn="Q1"),
                fact(25.0, H1_END, FY_START, form="10-Q", accn="H1"),
                fact(45.0, N9_END, FY_START, form="10-Q", accn="N9"),
                fact(70.0, FY_END, FY_START, form="10-K", accn="FY"),
                # A six-month period with another start is not this year's year to date.
                fact(999.0, "2024-07-28", "2024-02-05", form="10-Q", accn="ODD"),
            ]
        }
    )


def test_quarters_are_derived_from_year_to_date_values_with_the_same_start() -> None:
    quarters = FactBook(_year_to_date_company()).quarters("operating_cash_flow")
    assert {end.isoformat(): q.value for end, q in quarters.items()} == {
        Q1_END: 10.0,
        H1_END: 15.0,
        N9_END: 20.0,
        FY_END: 25.0,
    }
    assert not quarters[date(2024, 4, 28)].derived
    q2 = quarters[date(2024, 7, 28)]
    assert q2.derived and q2.start == date(2024, 4, 29)
    assert [ref.accession for ref in q2.refs[1:]] == ["H1", "Q1"]
    q4 = quarters[date(2025, 1, 26)]
    assert q4.derived and q4.start == date(2024, 10, 28)
    assert [ref.accession for ref in q4.refs[1:]] == ["FY", "N9"]
    assert q4.refs[0].derived and "70" in q4.refs[0].note and "45" in q4.refs[0].note


def costco_revenue() -> dict[str, Any]:
    """Costco's revenue facts for fiscal 2025 and 2026, as EDGAR's company facts gave them.

    Copied on 17 November 2026 (CIK 909832). Its year is three 12-week quarters and one of
    16 weeks, so its year-to-date periods are 24 and 36 weeks: 167 and 251 days from start
    to end, outside the six- and nine-month lengths this module first allowed.
    """
    rows = [
        # value in USD millions, start, end, form, accession, filed
        (62151, "2024-09-02", "2024-11-24", "10-Q", "0000909832-24-000079", "2024-12-19"),
        (125874, "2024-09-02", "2025-02-16", "10-Q", "0000909832-25-000015", "2025-03-13"),
        (63723, "2024-11-25", "2025-02-16", "10-Q", "0000909832-25-000015", "2025-03-13"),
        (189079, "2024-09-02", "2025-05-11", "10-Q", "0000909832-25-000033", "2025-06-05"),
        (63205, "2025-02-17", "2025-05-11", "10-Q", "0000909832-25-000033", "2025-06-05"),
        (275235, "2024-09-02", "2025-08-31", "10-K", "0000909832-25-000101", "2025-10-08"),
        (67307, "2025-09-01", "2025-11-23", "10-Q", "0000909832-25-000169", "2025-12-17"),
        (136904, "2025-09-01", "2026-02-15", "10-Q", "0000909832-26-000029", "2026-03-11"),
        (69597, "2025-11-24", "2026-02-15", "10-Q", "0000909832-26-000029", "2026-03-11"),
        (207431, "2025-09-01", "2026-05-10", "10-Q", "0000909832-26-000051", "2026-06-03"),
        (70527, "2026-02-16", "2026-05-10", "10-Q", "0000909832-26-000051", "2026-06-03"),
        (303154, "2025-09-01", "2026-08-30", "10-K", "0000909832-26-000093", "2026-10-07"),
    ]
    return companyfacts(
        {
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                fact(millions * 1e6, end, start, form=form, accn=accession, filed=filed)
                for millions, start, end, form, accession, filed in rows
            ]
        },
        cik=909832,
        name="COSTCO WHOLESALE CORP /NEW",
    )


def test_a_52_week_retailer_gets_its_sixteen_week_fourth_quarter() -> None:
    """The third referee, finding 8: Costco's fourth quarter was never derived.

    The fiscal year less the 36 weeks to date is the 16-week fourth quarter; the four
    quarters then add up to the year.
    """
    quarters = FactBook(costco_revenue()).quarters("revenue")
    year = {end: q for end, q in quarters.items() if end > date(2025, 8, 31)}
    assert {end.isoformat(): q.value for end, q in year.items()} == {
        "2025-11-23": 67307e6,
        "2026-02-15": 69597e6,
        "2026-05-10": 70527e6,
        "2026-08-30": 95723e6,
    }
    fourth = year[date(2026, 8, 30)]
    assert fourth.derived and fourth.start == date(2026, 5, 11)
    assert [ref.accession for ref in fourth.refs[1:]] == [
        "0000909832-26-000093",
        "0000909832-26-000051",
    ]
    assert sum(q.value for q in year.values()) == 303154e6
    # The year before, so that the newest quarter has a quarter to be compared with.
    assert quarters[date(2025, 8, 31)].value == 275235e6 - 189079e6
    # What the note calls each input is what it is: 36 weeks is not "nine months".
    assert "36 weeks" in fourth.refs[0].note and "nine months" not in fourth.refs[0].note


@pytest.mark.parametrize(
    ("start", "end", "length"),
    [
        ("2025-09-01", "2025-11-23", "quarter"),  # 12 weeks
        ("2026-05-11", "2026-08-30", "quarter"),  # 16 weeks
        ("2025-09-01", "2026-02-15", "half_year"),  # 24 weeks
        ("2025-09-01", "2026-05-10", "nine_months"),  # 36 weeks
        ("2025-02-02", "2025-05-24", "quarter"),  # 16 weeks, a first quarter
        ("2025-02-02", "2025-08-16", "half_year"),  # 28 weeks
        ("2025-02-02", "2025-11-08", "nine_months"),  # 40 weeks
        ("2024-01-01", "2024-05-01", None),  # 121 days is still not a reporting period
        ("2024-01-01", "2024-05-31", None),
        ("2024-01-01", "2024-08-20", None),
    ],
)
def test_the_period_lengths_of_companies_that_report_in_weeks(
    start: str, end: str, length: str | None
) -> None:
    assert period_length(date.fromisoformat(start), date.fromisoformat(end)) == length


def trailing_twelve_months() -> dict[str, Any]:
    """A company shaped like Amazon: cash flows also tagged for the twelve months to each quarter.

    The amounts are invented. What is real is the shape, seen with ``make figures`` on
    17 November 2026: Amazon's 10-Qs tag operating cash flow for the twelve months ended
    each quarter, and those periods are as long as a fiscal year.
    """
    k, q = "10-K", "10-Q"
    return companyfacts(
        {
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                fact(600e9, "2024-12-31", "2024-01-01", form=k, accn="K24", filed="2025-02-07"),
                fact(700e9, "2025-12-31", "2025-01-01", form=k, accn="K25", filed="2026-02-06"),
                fact(180e9, "2026-03-31", "2026-01-01", form=q, accn="Q1", filed="2026-05-01"),
                fact(200e9, "2026-06-30", "2026-04-01", form=q, accn="Q2", filed="2026-08-01"),
            ],
            "NetCashProvidedByUsedInOperatingActivities": [
                fact(100e9, "2024-12-31", "2024-01-01", form=k, accn="K24", filed="2025-02-07"),
                fact(120e9, "2025-12-31", "2025-01-01", form=k, accn="K25", filed="2026-02-06"),
                fact(20e9, "2026-03-31", "2026-01-01", form=q, accn="Q1", filed="2026-05-01"),
                fact(125e9, "2026-03-31", "2025-04-01", form=q, accn="Q1", filed="2026-05-01"),
                fact(50e9, "2026-06-30", "2026-01-01", form=q, accn="Q2", filed="2026-08-01"),
                fact(135e9, "2026-06-30", "2025-07-01", form=q, accn="Q2", filed="2026-08-01"),
            ],
        },
        name="Trailing Corp",
    )


def test_twelve_months_to_a_quarter_end_is_not_a_fiscal_year() -> None:
    """A fiscal year is a year-long period that an annual report reported.

    With length alone, the two newest "fiscal years" of this company ended on 30 June
    and 31 March 2026 and held a cash flow and nothing else.
    """
    book = FactBook(trailing_twelve_months())
    cash = book.annuals("operating_cash_flow")
    assert [end.isoformat() for end in sorted(cash)] == ["2024-12-31", "2025-12-31"]
    assert cash[date(2025, 12, 31)].value == 120e9
    assert sorted(book.annuals("revenue")) == [date(2024, 12, 31), date(2025, 12, 31)]
    # The quarter is still the half year less the first quarter, not touched by the long periods.
    assert book.quarters("operating_cash_flow")[date(2026, 6, 30)].value == 30e9


def test_a_bank_reports_its_revenue_net_of_interest_expense() -> None:
    """JPMorgan tags no Revenues: its total net revenue is RevenuesNetOfInterestExpense.

    Seen with ``make figures`` on 17 November 2026: every revenue figure of JPMorgan was
    missing. The concept is the last of the revenue group, so a company that reports one
    of the others is not affected. The amounts here are invented.
    """
    body = companyfacts(
        {
            "RevenuesNetOfInterestExpense": [
                fact(45e9, "2026-03-31", "2026-01-01", form="10-Q", accn="Q1"),
                fact(180e9, "2025-12-31", "2025-01-01", form="10-K", accn="K25"),
            ]
        }
    )
    book = FactBook(body)
    assert book.quarters("revenue")[date(2026, 3, 31)].concept == "RevenuesNetOfInterestExpense"
    assert book.annuals("revenue")[date(2025, 12, 31)].value == 180e9
    both = companyfacts(
        {
            "Revenues": [fact(50e9, "2026-03-31", "2026-01-01", form="10-Q", accn="Q1")],
            "RevenuesNetOfInterestExpense": [
                fact(45e9, "2026-03-31", "2026-01-01", form="10-Q", accn="Q1")
            ],
        }
    )
    assert FactBook(both).quarters("revenue")[date(2026, 3, 31)].value == 50e9


def test_a_three_month_fact_is_preferred_over_a_derived_quarter() -> None:
    payload = _year_to_date_company()
    payload["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]["units"][
        "USD"
    ].append(fact(16.0, H1_END, Q2_START, form="10-Q", accn="Q2-DIRECT"))
    q2 = FactBook(payload).quarters("operating_cash_flow")[date(2024, 7, 28)]
    assert (q2.value, q2.derived, q2.refs[0].accession) == (16.0, False, "Q2-DIRECT")


def test_eps_is_never_differenced() -> None:
    book = FactBook(
        companyfacts(
            {
                "EarningsPerShareDiluted": [
                    fact(0.5, Q1_END, FY_START, form="10-Q"),
                    fact(1.1, H1_END, FY_START, form="10-Q"),
                    fact(2.4, FY_END, FY_START),
                ]
            }
        )
    )
    assert list(book.quarters("eps_diluted")) == [date(2024, 4, 28)]
    assert book.differenced_quarters("eps_diluted") == {}
    assert book.annuals("eps_diluted")[date(2025, 1, 26)].value == 2.4


def test_gross_profit_falls_back_to_revenue_minus_cost_marked_derived() -> None:
    book = FactBook(
        companyfacts(
            {
                "Revenues": [fact(100.0, FY_END, FY_START), fact(80.0, "2024-01-28", "2023-01-30")],
                "CostOfRevenue": [
                    fact(40.0, FY_END, FY_START),
                    fact(30.0, "2024-01-28", "2023-01-30"),
                ],
                "GrossProfit": [fact(51.0, "2024-01-28", "2023-01-30")],
            }
        )
    )
    annual = book.annuals("gross_profit")
    assert annual[date(2025, 1, 26)].value == 60.0 and annual[date(2025, 1, 26)].derived
    assert {ref.concept for ref in annual[date(2025, 1, 26)].refs[1:]} == {
        "Revenues",
        "CostOfRevenue",
    }
    # Where GrossProfit is reported, it is read, not recomputed.
    assert annual[date(2024, 1, 28)].value == 51.0 and not annual[date(2024, 1, 28)].derived


def test_no_gross_profit_without_cost_of_revenue() -> None:
    book = FactBook(companyfacts({"Revenues": [fact(100.0, FY_END, FY_START)]}))
    assert book.annuals("gross_profit") == {}


# Recorded filers: the answer key, typed in by hand from each company's Form 10-K. Never edit
# a value here to make a test pass: when the recorded data and the key disagree, find out from
# the filing which is wrong.

# Revenue and net income, USD millions.
KNOWN_ANNUAL = [
    # Apple Form 10-K, consolidated statements of operations, fiscal years 2022 to 2024
    # (total net sales; net income).
    ("AAPL", "2022-09-24", 394_328, 99_803),
    ("AAPL", "2023-09-30", 383_285, 96_995),
    ("AAPL", "2024-09-28", 391_035, 93_736),
    # Microsoft Form 10-K, income statements, fiscal years 2023 and 2024
    # (total revenue; net income).
    ("MSFT", "2023-06-30", 211_915, 72_361),
    ("MSFT", "2024-06-30", 245_122, 88_136),
    # NVIDIA Form 10-K, consolidated statements of income, fiscal years 2024 and 2025
    # (revenue; net income).
    ("NVDA", "2024-01-28", 60_922, 29_760),
    ("NVDA", "2025-01-26", 130_497, 72_880),
]


@pytest.mark.parametrize(("ticker", "end", "revenue", "net_income"), KNOWN_ANNUAL)
def test_known_annual_revenue_and_net_income(
    ticker: str, end: str, revenue: int, net_income: int
) -> None:
    book = FactBook(load_fixture(ticker))
    year_end = date.fromisoformat(end)
    assert book.annuals("revenue")[year_end].value == revenue * MILLION
    assert book.annuals("net_income")[year_end].value == net_income * MILLION


# Diluted earnings per share, USD; and gross margin as a percent of revenue, one decimal.
KNOWN_ANNUAL_PER_SHARE_AND_MARGIN = [
    # Apple Form 10-K, consolidated statements of operations, fiscal years 2022 to 2024
    # (diluted earnings per share; gross margin ÷ total net sales).
    ("AAPL", "2022-09-24", 6.11, 43.3),
    ("AAPL", "2023-09-30", 6.13, 44.1),
    ("AAPL", "2024-09-28", 6.08, 46.2),
    # Microsoft Form 10-K, income statements, fiscal years 2023 and 2024
    # (diluted earnings per share; gross margin ÷ total revenue).
    ("MSFT", "2023-06-30", 9.68, 68.9),
    ("MSFT", "2024-06-30", 11.80, 69.8),
    # NVIDIA Form 10-K, consolidated statements of income, fiscal years 2024 and 2025
    # (net income per share, diluted; gross profit ÷ revenue). Fiscal 2024 EPS is $1.19 as
    # restated in the fiscal 2025 10-K for the ten-for-one split of June 2024; the fiscal 2024
    # 10-K first reported $11.93.
    ("NVDA", "2024-01-28", 1.19, 72.7),
    ("NVDA", "2025-01-26", 2.94, 75.0),
]


@pytest.mark.parametrize(("ticker", "end", "eps", "_margin"), KNOWN_ANNUAL_PER_SHARE_AND_MARGIN)
def test_known_annual_diluted_eps(ticker: str, end: str, eps: float, _margin: float) -> None:
    book = FactBook(load_fixture(ticker))
    assert book.annuals("eps_diluted")[date.fromisoformat(end)].value == eps


@pytest.mark.parametrize(("ticker", "end", "_eps", "margin"), KNOWN_ANNUAL_PER_SHARE_AND_MARGIN)
def test_known_annual_gross_margin(ticker: str, end: str, _eps: float, margin: float) -> None:
    book = FactBook(load_fixture(ticker))
    year_end = date.fromisoformat(end)
    gross = book.annuals("gross_profit")[year_end].value
    revenue = book.annuals("revenue")[year_end].value
    assert round(gross / revenue * 100, 1) == margin


@pytest.mark.parametrize("ticker", list(CIKS))
def test_differenced_quarters_equal_the_reported_three_month_values(ticker: str) -> None:
    """Independent method: year-to-date differencing reproduces each 3-month fact.

    Exact, except where the filing itself rounded each figure to millions on its
    own: NVIDIA's 10-Q for the quarter ended 2026-07-26 reports the quarter as
    96,221 and the half year as 177,837, and its previous 10-Q reports the first
    quarter as 81,615 (177,837 - 81,615 = 96,222). Such a gap is at most one
    USD million; anything larger is a bug.
    """
    book = FactBook(load_fixture(ticker))
    direct = book.direct_quarters("revenue")
    differenced = book.differenced_quarters("revenue")
    both = sorted(direct.keys() & differenced.keys())
    assert both, f"{ticker}: no quarter has both a 3-month fact and two year-to-date facts"
    gaps = {end: differenced[end].value - direct[end].value for end in both}
    assert {end: gap for end, gap in gaps.items() if abs(gap) > MILLION} == {}
    rounded = {end.isoformat(): gap for end, gap in gaps.items() if gap != 0}
    expected_rounding = {"NVDA": {"2026-07-26": MILLION}}.get(ticker, {})
    assert rounded == expected_rounding


@pytest.mark.parametrize("ticker", list(CIKS))
def test_revenue_less_cost_equals_gross_profit_each_fiscal_year(ticker: str) -> None:
    book = FactBook(load_fixture(ticker))
    revenue, cost = book.annuals("revenue"), book.annuals("cost_of_revenue")
    gross = {end: v for end, v in book.annuals("gross_profit").items() if not v.derived}
    years = sorted(revenue.keys() & cost.keys() & gross.keys())
    assert years, f"{ticker}: no fiscal year reports revenue, cost and gross profit"
    for end in years:
        gap = revenue[end].value - cost[end].value - gross[end].value
        assert abs(gap) <= MILLION, f"{ticker} {end}: off by {gap:,.0f}"


@pytest.mark.parametrize("ticker", list(CIKS))
def test_four_standalone_quarters_sum_to_the_annual_revenue(ticker: str) -> None:
    """The quarters of a fiscal year sum to the annual revenue, within rounding.

    Compared with the latest annual value where the quarters are on its basis,
    and otherwise with a value the company reported for that year: Microsoft's
    fiscal 2018 10-K restated fiscal 2016 revenue for ASC 606 (85,320 to 91,154)
    without restating its quarters, so those quarters sum to 85,320. That year
    is listed explicitly so that no other year can slip through the same way.
    """
    book = FactBook(load_fixture(ticker))
    quarters = book.quarters("revenue")
    checked, on_earlier_basis = 0, []
    for end, annual in book.annuals("revenue").items():
        assert annual.start is not None
        inside = [q for q_end, q in quarters.items() if annual.start < q_end <= end]
        if len(inside) != 4 or min(q.start for q in inside if q.start) != annual.start:
            continue
        total = sum(q.value for q in inside)
        checked += 1
        if abs(total - annual.value) <= MILLION:
            continue
        reported = [ref.value for ref in book.reports("revenue", annual.start, end)]
        assert any(abs(total - value) <= MILLION for value in reported), (
            f"{ticker} {end}: quarters sum to {total:,.0f}; reported {reported}"
        )
        on_earlier_basis.append(end.isoformat())
    assert checked >= 3, f"{ticker}: only {checked} complete fiscal years"
    assert on_earlier_basis == {"MSFT": ["2016-06-30"]}.get(ticker, [])


def test_a_difference_uses_reports_on_the_same_basis() -> None:
    """A later restatement of the year alone must not leak into the fourth quarter."""
    book = FactBook(
        companyfacts(
            {
                "Revenues": [
                    fact(45.0, N9_END, FY_START, form="10-Q", filed="2024-11-20", accn="N9"),
                    fact(70.0, FY_END, FY_START, filed="2025-03-01", accn="FY-ORIG"),
                    fact(76.0, FY_END, FY_START, filed="2027-03-01", accn="FY-RESTATED"),
                ]
            }
        )
    )
    assert book.annuals("revenue")[date(2025, 1, 26)].value == 76.0
    q4 = book.quarters("revenue")[date(2025, 1, 26)]
    assert q4.value == 25.0 and q4.derived and q4.restated
    used = q4.refs[1]
    assert (used.accession, used.value, used.restated) == ("FY-ORIG", 70.0, True)
    assert "FY-RESTATED" in used.note and "76" in used.note


def test_a_restatement_under_a_new_concept_is_also_kept_out_of_the_difference() -> None:
    """Microsoft's pattern: the restated year is tagged with the newer revenue concept."""
    book = FactBook(
        companyfacts(
            {
                "SalesRevenueNet": [
                    fact(45.0, N9_END, FY_START, form="10-Q", filed="2024-11-20", accn="N9"),
                    fact(70.0, FY_END, FY_START, filed="2025-03-01", accn="FY-ORIG"),
                ],
                "RevenueFromContractWithCustomerExcludingAssessedTax": [
                    fact(76.0, FY_END, FY_START, filed="2026-03-01", accn="FY-NEW-CONCEPT")
                ],
            }
        )
    )
    assert book.annuals("revenue")[date(2025, 1, 26)].value == 76.0
    assert book.quarters("revenue")[date(2025, 1, 26)].value == 25.0
    assert [r.value for r in book.reports("revenue", date(2024, 1, 29), date(2025, 1, 26))] == [
        70.0,
        76.0,
    ]


@pytest.mark.parametrize("ticker", list(CIKS))
def test_no_recorded_eps_quarter_is_derived(ticker: str) -> None:
    book = FactBook(load_fixture(ticker))
    assert all(not q.derived for q in book.quarters("eps_diluted").values())
