"""The whole-sentence rule: a claim compiles only when the parse explains every content word.

Each word of a claim must be accounted for by the test it compiled to (its measures, its
comparison and threshold, its periods and span, the words of its form) or be on the short
list of words that carry no meaning for a test (:data:`app.core.claimtest.NO_MEANING`).
Anything left over refuses the claim, and the refusal names the words. The sentences
here are new, written for the four ways a claim was read wrongly on the foreign set: a
part read as the whole, an unknown measure read as a known one, a named period ignored,
half a claim dropped.
"""

from __future__ import annotations

import pytest

from app.core.claimtest import NotNumeric, compile_claim

PART_AS_WHOLE = [
    ("Gaming operating income rose year over year.", "gaming"),
    ("Azure revenue grew more than 30% year over year.", "azure"),
    ("Services gross margin is above 70%.", "services"),
    ("Accessories revenue declined in fiscal 2025.", "accessories"),
]
UNKNOWN_MEASURE = [
    ("Unbilled receivables grew year over year.", "unbilled"),
    ("Advertising expense as a percent of sales fell.", "advertising expense"),
    ("Selling and administrative costs grew more slowly than revenue.", "administrative costs"),
    ("Cash and restricted cash topped $10 billion.", "restricted"),
]
NAMED_PERIOD_IGNORED = [
    ("Revenue grew in the December quarter.", "december"),
    ("Net income rose in the second half of the year.", "second half"),
    ("Operating cash flow was above $50 billion in the first half.", "first half"),
    ("Capex more than doubled between fiscal 2022 and fiscal 2024.", "between"),
    ("Revenue grew more than 50% in fiscal 2025 and fiscal 2026.", "fiscal 2026"),
]
HALF_DROPPED = [
    ("Gross margin expanded by more than 3 points.", "points"),
    ("Inventory fell sharply.", "sharply"),
    ("Receivables grew roughly in line with revenue.", "roughly in line with"),
    ("Cash is above $5 billion and has hardly changed in two years.", "hardly changed"),
]


@pytest.mark.parametrize(
    ("claim", "words"), PART_AS_WHOLE + UNKNOWN_MEASURE + NAMED_PERIOD_IGNORED + HALF_DROPPED
)
def test_a_word_the_parse_does_not_explain_refuses_the_claim(claim: str, words: str) -> None:
    result = compile_claim(claim)
    assert isinstance(result, NotNumeric), f"compiled to {result.canonical}"
    assert words in result.reason


def test_the_refusal_names_every_unexplained_phrase() -> None:
    claim = "Receivables plus vendor non-trade receivables grew faster than revenue."
    result = compile_claim(claim)
    assert isinstance(result, NotNumeric)
    assert result.reason.startswith("not compiled: ")
    assert "'plus vendor non-trade'" in result.reason and "not understood" in result.reason


EXPLAINED = [
    ("Gross margin is expanding.", "gross_margin[Q] > gross_margin[Q-4]"),
    ("NVIDIA's revenue more than doubled in fiscal 2024.", "yoy(revenue)[FY2024] > 100%"),
    ("Apple's total net sales were above $390 billion in fiscal 2024.", "revenue[FY2024] > $390B"),
    ("Net income was down in fiscal 2023 versus 2022.", "net_income[FY2023] < net_income[FY2022]"),
    ("Operating margin was above 44% last fiscal year.", "operating_margin[FY] > 44%"),
    (
        "The company's diluted EPS rose by more than 10% in fiscal 2025.",
        "yoy(eps_diluted)[FY2025] > 10%",
    ),
    ("Revenue has grown for eight consecutive quarters.", "streak(revenue)[Q] >= 8"),
    ("Revenue has compounded at over 20% for five years.", "cagr(revenue, 5y)[FY] > 20%"),
    (
        "Operating expenses grew slower than revenue.",
        "yoy(operating_expenses)[Q] < yoy(revenue)[Q]",
    ),
    ("Data center is more than 80% of revenue.", 'share(segment "Data Center")[filing] > 80%'),
    (
        "Capital expenditures at least doubled between fiscal 2024 and fiscal 2025.",
        "yoy(capex)[FY2025] >= 100%",
    ),
    (
        "Operating cash flow was over $120 billion on a trailing basis.",
        "operating_cash_flow[TTM] > $120B",
    ),
]


@pytest.mark.parametrize(("claim", "canonical"), EXPLAINED)
def test_a_claim_whose_every_word_is_explained_still_compiles(claim: str, canonical: str) -> None:
    result = compile_claim(claim)
    assert not isinstance(result, NotNumeric), result.reason
    assert result.canonical == canonical


def test_a_test_that_compares_a_measure_with_itself_is_refused() -> None:
    # SG&A was the example until the catalogue added it; licensing income is not a measure.
    result = compile_claim("Licensing income is growing more slowly than gross profit.")
    assert isinstance(result, NotNumeric)
    assert "licensing income" in result.reason
