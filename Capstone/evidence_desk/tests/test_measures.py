"""The measure catalogue: what a claim test can name, how each is computed, and what stays put.

A synthetic company (calendar fiscal years 2022 to 2025, from ``tests.test_claim_eval``)
is given buybacks tagged year to date (so a fourth quarter is a difference), dividends,
debt with no commercial paper, cash and current marketable securities, income tax and
pre-tax income, a diluted share count, and sales and marketing and G&A without an SG&A
line. Every expected value below is worked out here by hand.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.core import metrics
from app.core.claim_eval import evaluate
from app.core.claimtest import METRICS, ClaimTest, NotNumeric, compile_claim
from app.core.facts import ALL_CONCEPTS, BOOK_GROUPS, CLAIM_GROUPS, GROUPS, FactBook
from app.core.measures import ADDED, CATALOGUE, PANEL, RATIO_OF
from app.core.periods import fiscal_calendar
from tests.test_claim_eval import QUARTER_ENDS, QUARTER_STARTS, _filed, synthetic
from tests.test_facts import fact

M = 1_000_000


def _buyback(i: int) -> int:
    return 10 * M * (i + 1)


def _shares(i: int) -> int:
    return 1_000 * M - 5 * M * i


def _pretax(i: int) -> int:
    return 100 * M + 10 * M * i


def with_catalogue() -> dict[str, Any]:
    """The synthetic company, with the facts only the catalogue reads."""
    payload = synthetic()
    gaap = payload["facts"]["us-gaap"]
    added: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in (
            "PaymentsForRepurchaseOfCommonStock",
            "PaymentsOfDividends",
            "LongTermDebtNoncurrent",
            "LongTermDebtCurrent",
            "CashAndCashEquivalentsAtCarryingValue",
            "MarketableSecuritiesCurrent",
            "IncomeTaxExpenseBenefit",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "SellingAndMarketingExpense",
            "GeneralAndAdministrativeExpense",
        )
    }
    shares: list[dict[str, Any]] = []
    for y in range(2022, 2026):
        for q in range(1, 5):
            i = (y - 2022) * 4 + (q - 1)
            filed, accn, form, fy, fp = _filed(y, q)
            kw = {"filed": filed, "accn": accn, "form": form, "fy": fy, "fp": fp}
            start, end = f"{y}-{QUARTER_STARTS[q - 1]}", f"{y}-{QUARTER_ENDS[q - 1]}"
            # Buybacks: year to date only, as cash flows are tagged in a 10-Q and a 10-K.
            to_date = sum(_buyback((y - 2022) * 4 + k) for k in range(q))
            added["PaymentsForRepurchaseOfCommonStock"].append(
                fact(to_date, end, f"{y}-01-01", **kw)
            )
            added["PaymentsOfDividends"].append(fact(5 * M, end, start, **kw))
            added["LongTermDebtNoncurrent"].append(fact(500 * M - 10 * M * i, end, **kw))
            added["LongTermDebtCurrent"].append(fact(50 * M, end, **kw))
            added["CashAndCashEquivalentsAtCarryingValue"].append(fact(200 * M, end, **kw))
            added["MarketableSecuritiesCurrent"].append(fact(100 * M, end, **kw))
            added[
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
            ].append(fact(_pretax(i), end, start, **kw))
            tax = round(_pretax(i) * 0.15)
            added["IncomeTaxExpenseBenefit"].append(fact(tax, end, start, **kw))
            added["SellingAndMarketingExpense"].append(fact(20 * M, end, start, **kw))
            added["GeneralAndAdministrativeExpense"].append(fact(10 * M, end, start, **kw))
            shares.append(fact(_shares(i), end, start, **kw))
        kw = {"filed": f"{y + 1}-02-15", "accn": f"k-{y}", "form": "10-K", "fy": y, "fp": "FY"}
        first = (y - 2022) * 4
        shares.append(
            fact(sum(_shares(first + k) for k in range(4)) // 4, f"{y}-12-31", f"{y}-01-01", **kw)
        )
    for name, facts in added.items():
        gaap[name] = {"label": name, "units": {"USD": facts}}
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = {
        "label": "shares",
        "units": {"shares": shares},
    }
    return payload


def _evaluate(claim: str, as_of: date | None = None):
    payload = with_catalogue()
    test = compile_claim(claim)
    assert isinstance(test, ClaimTest), test
    book = FactBook(payload, as_of=as_of)
    return evaluate(test, book, calendar=fiscal_calendar(payload, as_of=as_of))


# The catalogue itself


def test_every_measure_is_computed_from_what_exists() -> None:
    for measure in CATALOGUE.values():
        if measure.computed == "group":
            assert measure.group in BOOK_GROUPS, measure.key
        for part in (*measure.plus, *measure.minus, *measure.fallback):
            assert part in CATALOGUE, (measure.key, part)
        assert set(measure.optional) <= set(measure.plus) | set(measure.minus), measure.key
        if measure.computed == "ratio":
            assert len(measure.plus) == 1 and measure.over in CATALOGUE, measure.key
        if measure.computed != "metrics":
            assert measure.definition or measure.note or measure.computed == "group"
    assert all(key in CATALOGUE for pair in RATIO_OF.items() for key in pair)
    assert set(METRICS) == set(CATALOGUE)


def test_the_panel_its_figures_and_its_recordings_are_not_widened() -> None:
    assert not set(CLAIM_GROUPS) & set(GROUPS)
    assert {m.key for m in PANEL} >= set(metrics.SPECS) - {
        key for key in metrics.SPECS if key.endswith(("_yoy", "_qoq"))
    }
    assert not {m.key for m in ADDED} & set(metrics.SPECS)
    payload = with_catalogue()
    payload["facts"]["us-gaap"]["PaymentsOfDividends"]["units"]["USD"].append({"end": "bad"})
    book = FactBook(payload)
    assert book.problems == FactBook(synthetic()).problems
    [problem] = book.claim_problems
    assert "PaymentsOfDividends" in problem
    panel_only = with_catalogue()
    gaap = panel_only["facts"]["us-gaap"]
    panel_only["facts"]["us-gaap"] = {k: v for k, v in gaap.items() if k in ALL_CONCEPTS}
    assert metrics.build_report(book) == metrics.build_report(FactBook(panel_only))


# The compiler names them


@pytest.mark.parametrize(
    ("claim", "canonical"),
    [
        ("Share buybacks are increasing.", "share_repurchases[Q] > share_repurchases[Q-4]"),
        ("Dividends are growing.", "dividends_paid[Q] > dividends_paid[Q-4]"),
        (
            "The company returned more than $20 billion to shareholders.",
            "shareholder_returns[FY] > $20B",
        ),
        ("The company spent more than $10 billion on buybacks.", "share_repurchases[FY] > $10B"),
        ("Total debt fell below $10 billion.", "total_debt[Q] < $10B"),
        ("The company has no debt.", "total_debt[Q] <= $0"),
        ("Long-term debt is declining.", "long_term_debt[Q] < long_term_debt[Q-4]"),
        ("Net cash is above $50 billion.", "net_cash[Q] > $50B"),
        ("Cash and marketable securities exceeded $20 billion.", "cash_and_securities[Q] > $20B"),
        (
            "Cash and short-term investments are above $10 billion.",
            "cash_and_securities[Q] > $10B",
        ),
        ("The diluted share count is declining.", "diluted_shares[Q] < diluted_shares[Q-4]"),
        ("SG&A as a share of revenue fell.", "sga_ratio[Q] < sga_ratio[Q-4]"),
        ("Stock-based compensation is less than 10% of revenue.", "sbc_ratio[Q] < 10%"),
        ("Operating expenses are less than 30% of revenue.", "opex_ratio[Q] < 30%"),
        ("The effective tax rate is below 15%.", "effective_tax_rate[Q] < 15%"),
        ("Taxes are lower than last year.", "income_tax[FY] < income_tax[FY-1]"),
        ("Interest expense rose year over year.", "interest_expense[Q] > interest_expense[Q-4]"),
        ("Deferred revenue is rising.", "deferred_revenue[Q] > deferred_revenue[Q-4]"),
        ("Unearned revenue grew sequentially.", "deferred_revenue[Q] > deferred_revenue[Q-1]"),
        ("Total assets exceed $100 billion.", "total_assets[Q] > $100B"),
        ("Accounts payable are rising.", "accounts_payable[Q] > accounts_payable[Q-4]"),
        ("Cost of revenue grew faster than revenue.", "yoy(cost_of_revenue)[Q] > yoy(revenue)[Q]"),
    ],
)
def test_a_catalogue_measure_compiles(claim: str, canonical: str) -> None:
    result = compile_claim(claim)
    assert not isinstance(result, NotNumeric), result.reason
    assert result.canonical == canonical


@pytest.mark.parametrize(
    ("claim", "words"),
    [
        ("Shares outstanding are declining.", "metric set"),
        ("Goodwill is more than 10% of assets.", "percent threshold on an amount"),
        ("Debt is manageable.", "no direction"),
        ("Stock-based compensation is diluting shareholders.", "metric set"),
        ("Data Center revenue grew more than 50% year over year.", "part of the company"),
    ],
)
def test_what_the_catalogue_does_not_make_numeric_is_still_refused(claim: str, words: str) -> None:
    result = compile_claim(claim)
    assert isinstance(result, NotNumeric), result.canonical
    assert words in result.reason


# The evaluator computes them


def test_a_fourth_quarter_of_buybacks_is_the_year_less_nine_months() -> None:
    result = _evaluate("Share buybacks are increasing.")

    assert result.outcome == "holds"
    assert (result.left.value, result.right.value) == (_buyback(15), _buyback(11))
    assert result.left.formula  # derived: the year less the nine months
    assert "Cash paid for repurchases" in result.left.note


def test_total_debt_adds_its_parts_and_counts_a_part_not_reported_as_zero() -> None:
    result = _evaluate("Total debt is at most $400 million.")

    assert result.outcome == "holds"
    assert result.left.value == 350 * M + 50 * M
    assert "0 (commercial paper: none reported)" in result.left.formula
    assert "Leases are left out" in result.left.note


def test_net_cash_is_cash_and_securities_less_total_debt() -> None:
    result = _evaluate("Net cash is above $0.")

    assert result.outcome == "fails"
    assert result.left.value == 300 * M - 400 * M


def test_the_effective_tax_rate_divides_tax_by_pretax_income_also_over_four_quarters() -> None:
    quarter = _evaluate("The effective tax rate is below 16%.")
    trailing = _evaluate("The effective tax rate is below 16% on a trailing twelve month basis.")

    assert quarter.outcome == trailing.outcome == "holds"
    assert quarter.left.value == pytest.approx(15.0, abs=0.01)
    assert trailing.left.value == pytest.approx(15.0, abs=0.01)


def test_sga_falls_back_to_its_parts_when_no_sga_line_is_tagged() -> None:
    result = _evaluate("SG&A is less than 10% of revenue.")

    assert result.left.value == pytest.approx(30 * M / (100 * M + 150 * M) * 100)
    assert result.outcome == "fails"


def test_a_share_count_is_read_as_reported_and_has_no_four_quarter_total() -> None:
    falling = _evaluate("The diluted share count is declining.")
    trailing = _evaluate("The trailing twelve month diluted share count is declining.")

    assert falling.outcome == "holds"
    assert (falling.left.value, falling.right.value) == (_shares(15), _shares(11))
    assert falling.left.display == "925M shares"
    assert trailing.outcome == "cannot_compute"
    assert "share count" in trailing.reason


def test_as_of_a_date_a_catalogue_measure_reads_nothing_filed_after_it() -> None:
    day = date(2026, 1, 1)
    result = _evaluate("Share buybacks are increasing.", as_of=day)

    assert result.left.value == _buyback(14)  # Q3 2025: the 10-K of 2025 is not yet filed
    for operand in result.operands:
        for ref in operand.inputs:
            assert date.fromisoformat(ref.filed) <= day


# Rules the catalogue's measures needed, from the metric refusals of sets A and B


@pytest.mark.parametrize(
    ("claim", "canonical"),
    [
        # "stock" is what was repurchased, not a share price
        (
            "Apple repurchased more than $90 billion of its stock last fiscal year.",
            "share_repurchases[FY] > $90B",
        ),
        (
            "Common stock repurchased exceeded $15 billion last fiscal year.",
            "share_repurchases[FY] > $15B",
        ),
        # a company named before its verb
        (
            "Microsoft returned over $30 billion to shareholders through buybacks and dividends.",
            "shareholder_returns[FY] > $30B",
        ),
        # "over the trailing twelve months"
        (
            "Share repurchases exceeded $20 billion over the trailing twelve months.",
            "share_repurchases[TTM] > $20B",
        ),
        # a percent of a named denominator is the ratio
        (
            "Operating expenses were under 15% of revenue in the most recent quarter.",
            "opex_ratio[Q] < 15%",
        ),
        (
            "The income tax provision was above 13% of pre-tax income last year.",
            "effective_tax_rate[FY] > 13%",
        ),
        # "rose above 16%" is a level, not a change
        ("The effective tax rate rose above 16% last fiscal year.", "effective_tax_rate[FY] > 16%"),
        # surpassed, passed
        ("Income before income taxes surpassed $120 billion.", "pretax_income[FY] > $120B"),
        ("Total assets passed $500 billion in fiscal 2025.", "total_assets[FY2025] > $500B"),
        # negative and positive are thresholds at zero
        (
            "Other income and expense, net, was negative in fiscal 2025.",
            "other_income[FY2025] < $0",
        ),
        ("Net cash is positive.", "net_cash[Q] > $0"),
        (
            "Commercial paper outstanding is down from a year ago.",
            "commercial_paper[Q] < commercial_paper[Q-4]",
        ),
    ],
)
def test_a_rule_for_the_catalogue_from_sets_a_and_b(claim: str, canonical: str) -> None:
    result = compile_claim(claim)
    assert not isinstance(result, NotNumeric), result.reason
    assert result.canonical == canonical


@pytest.mark.parametrize(
    ("claim", "words"),
    [
        ("LinkedIn revenue grew by 9% or more.", ""),
        ("The stock price is above $200.", "valuation"),
        ("Gross margin rose 2% last year.", "exact figure"),
    ],
)
def test_those_rules_do_not_widen_what_is_refused(claim: str, words: str) -> None:
    result = compile_claim(claim)
    assert isinstance(result, NotNumeric), result.canonical
    assert words in result.reason
