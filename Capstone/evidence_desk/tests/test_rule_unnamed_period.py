"""Rule 3, made after set C: a flow against an amount names its period, or it is not read.

"Revenue is over $100 billion" may mean a quarter's revenue or a year's, which differ about
four times over; the grammar used to read the latest fiscal year, and a model reader of set C
read a quarter (h063). Neither reading is the sentence's. A flow (revenue, an expense, a cash
flow, a per-share amount of one, or a part's revenue) compared with an amount of money is now
refused, by the grammar and by the model readers, unless the sentence names its period: "a
year", "annual", "last quarter", "in fiscal 2026", "trailing twelve months", "now running
at" and the like. Ratios and balances keep the latest quarter by default; the sign of a flow
("free cash flow is positive") is not an amount and keeps the latest fiscal year. Set C's
score was made before this rule and does not reflect it.
"""

from __future__ import annotations

import pytest

from app.core.claim_reading import as_reading
from app.core.claimtest import (
    NO_PERIOD_REASON,
    ClaimTest,
    NotNumeric,
    Number,
    Period,
    Term,
    compile_claim,
    unplaced_amount,
)
from app.engines.claim_reader import READ_SYSTEM, ModelClaimReader
from tests.test_claim_reading import Answers

assert NO_PERIOD_REASON == "names no period: a quarter's amount or a year's?"


@pytest.mark.parametrize(
    "claim",
    [
        "Revenue is over $100 billion.",
        "Free cash flow exceeded $100 billion.",
        "R&D expense exceeded $30 billion.",
        "Diluted EPS is above $3.",
        "The company spent more than $10 billion on buybacks.",
        "The company returned more than $20 billion to shareholders.",
        "Income before income taxes surpassed $120 billion.",
        "Revenue is over $100 billion and gross margin is above 70%.",
    ],
)
def test_a_flow_against_an_amount_with_no_period_is_refused(claim: str) -> None:
    result = compile_claim(claim)
    assert isinstance(result, NotNumeric), result
    assert result.reason == NO_PERIOD_REASON


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("Annual revenue is at least $150 billion.", "revenue[FY] >= $150B"),
        ("Net income is at most $10 billion a year.", "net_income[FY] <= $10B"),
        ("Quarterly revenue is above $50 billion.", "revenue[Q] > $50B"),
        ("Revenue last quarter was above $40 billion.", "revenue[Q] > $40B"),
        ("Revenue in the latest quarter topped $40 billion.", "revenue[Q] > $40B"),
        ("Revenue is now running at more than $40 billion.", "revenue[Q] > $40B"),
        ("Revenue is now running at more than $40 billion a quarter.", "revenue[Q] > $40B"),
        ("Free cash flow exceeded $60 billion in fiscal 2026.", "free_cash_flow[FY2026] > $60B"),
        ("Trailing twelve month revenue exceeds $200 billion.", "revenue[TTM] > $200B"),
        ("Capex was under $5 billion last fiscal year.", "capex[FY] < $5B"),
        (
            "Revenue was above $30 billion in each of the last four quarters.",
            "each(4): revenue[Q] > $30B",
        ),
        ("Annual diluted EPS is above $4.", "eps_diluted[FY] > $4"),
    ],
)
def test_a_flow_against_an_amount_with_its_period_named_is_read(claim: str, expected: str) -> None:
    result = compile_claim(claim)
    assert isinstance(result, ClaimTest), result
    assert result.canonical == expected


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("Cash on hand is more than $40 billion.", "cash[Q] > $40B"),
        ("Inventory is under $20 billion.", "inventory[Q] < $20B"),
        ("Gross margin is above 70%.", "gross_margin[Q] > 70%"),
        ("Free cash flow is positive.", "free_cash_flow[FY] > $0"),
        ("The company has no debt.", "total_debt[Q] <= $0"),
    ],
)
def test_ratios_balances_and_a_sign_keep_their_default(claim: str, expected: str) -> None:
    result = compile_claim(claim)
    assert isinstance(result, ClaimTest), result
    assert result.canonical == expected


def test_an_annualised_run_rate_is_refused_and_not_read_as_a_fiscal_year() -> None:
    for claim in (
        "Revenue is now running at more than $160 billion a year.",
        "Data center revenue has an annualized run rate above $150 billion.",
    ):
        result = compile_claim(claim)
        assert isinstance(result, NotNumeric), claim
        assert "run rate" in result.reason, claim


# The model readers


def test_the_readers_prompt_states_the_rule() -> None:
    assert NO_PERIOD_REASON in READ_SYSTEM
    assert "rule 3" not in READ_SYSTEM  # the prompt says what to do, not the project's history


def _amount_test(period: Period, axis: str = "") -> ClaimTest:
    member = "Data Center" if axis else ""
    left = Term("value", "revenue", period, member=member, axis=axis)
    return ClaimTest("threshold", left, ">", Number(100e9, "USD"))


@pytest.mark.parametrize(
    ("claim", "test", "refused"),
    [
        ("Revenue is over $100 billion.", _amount_test(Period("FY")), True),
        ("Revenue is over $100 billion.", _amount_test(Period("Q")), True),
        ("Annual revenue is over $100 billion.", _amount_test(Period("FY")), False),
        # h003 of set C: the grammar does not read "FY26", but it names the period
        ("Revenue north of $100B in FY26.", _amount_test(Period("FY", fiscal_year=2026)), False),
        (
            "Data center revenue is above $100 billion.",
            _amount_test(Period("filing"), "segment"),
            True,
        ),
        (
            "Data center revenue was above $100 billion in fiscal 2026.",
            _amount_test(Period("FY", fiscal_year=2026), "segment"),
            False,
        ),
    ],
)
def test_a_model_readers_unplaced_amount_is_refused_whatever_period_it_wrote(
    claim: str, test: ClaimTest, refused: bool
) -> None:
    assert (unplaced_amount(claim, test) == NO_PERIOD_REASON) is refused
    reader = ModelClaimReader(transport=Answers({claim: as_reading(test)}))
    result = reader.read(claim)
    if refused:
        assert isinstance(result, NotNumeric) and NO_PERIOD_REASON in result.reason
    else:
        assert isinstance(result, ClaimTest), result
        assert result.canonical == test.canonical
