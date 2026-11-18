"""The claim compiler: claim text to a typed test, or the reason it is not a numeric claim.

These cases are written here, apart from the labels in ``eval/claim-tests.json``,
so that the grammar is pinned by the forms it must cover; the labels score it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.claimtest import NotNumeric, compile_claim

COMPILED = [
    ("Gross margin is expanding.", "gross_margin[Q] > gross_margin[Q-4]"),
    ("Operating margin is shrinking.", "operating_margin[Q] < operating_margin[Q-4]"),
    ("Revenue grew sequentially last quarter.", "revenue[Q] > revenue[Q-1]"),
    ("Annual revenue is growing.", "revenue[FY] > revenue[FY-1]"),
    ("Net margin expanded in fiscal 2026.", "net_margin[FY2026] > net_margin[FY2025]"),
    ("Revenue has grown over the last three years.", "revenue[FY] > revenue[FY-3]"),
    ("Trailing twelve month revenue is growing.", "revenue[TTM] > revenue[TTM-4]"),
    (
        "Gross profit increased in the second quarter of fiscal 2027.",
        "gross_profit[Q2 FY2027] > gross_profit[Q2 FY2026]",
    ),
    ("Revenue growth is accelerating.", "yoy(revenue)[Q] > yoy(revenue)[Q-1]"),
    ("Earnings growth is slowing.", "yoy(net_income)[Q] < yoy(net_income)[Q-1]"),
    ("Revenue has grown for eight consecutive quarters.", "streak(revenue)[Q] >= 8"),
    ("Net income has risen five years in a row.", "streak(net_income)[FY] >= 5"),
    ("Gross margin is above 70%.", "gross_margin[Q] > 70%"),
    ("Revenue is over $100 billion.", "revenue[FY] > $100B"),
    ("Cash on hand is more than $40 billion.", "cash[Q] > $40B"),
    ("Diluted EPS is above $3.", "eps_diluted[FY] > $3"),
    ("Operating income is more than half of revenue.", "operating_margin[Q] > 50%"),
    (
        "Operating cash flow was at least $500 million in Q2 fiscal 2027.",
        "operating_cash_flow[Q2 FY2027] >= $500M",
    ),
    ("Revenue grew more than 50% year over year.", "yoy(revenue)[Q] > 50%"),
    ("Revenue grew more than 10% sequentially.", "qoq(revenue)[Q] > 10%"),
    ("Net income more than doubled year over year.", "yoy(net_income)[Q] > 100%"),
    ("Revenue declined more than 10% year over year.", "yoy(revenue)[Q] < -10%"),
    (
        "Revenue is growing faster than operating expenses.",
        "yoy(revenue)[Q] > yoy(operating_expenses)[Q]",
    ),
    ("R&D spending is growing more slowly than revenue.", "yoy(rnd)[Q] < yoy(revenue)[Q]"),
    ("Revenue has compounded at over 20% for five years.", "cagr(revenue, 5y)[FY] > 20%"),
    ("Revenue's three-year CAGR is above 50%.", "cagr(revenue, 3y)[FY] > 50%"),
    ("Data center is more than 80% of revenue.", 'share(segment "Data Center")[filing] > 80%'),
    ("No customer is over 20% of revenue.", "max(share(customer))[filing] <= 20%"),
    ("China is less than 20% of revenue.", 'share(geography "China")[filing] < 20%'),
]

NOT_NUMERIC = [
    ("Growth is priced in.", "valuation"),
    ("Margins tell the story.", "which margin"),
    ("A 10-K risk factor warns about export controls.", "measure"),
    ("Our top 5 customers account for most of revenue.", "top"),
    ("Data center revenue is still growing year over year.", "segment"),
    ("Margins are expanding.", "which margin"),
    ("Revenue will grow 30% next year.", "forecast"),
    ("Gross margin is expanding because of Blackwell.", "cause"),
    ("Debt is manageable.", "metric set"),
    ("Deferred revenue is rising.", "metric set"),
    ("Gross margin is high.", "threshold"),
    ("Revenue grew 2% in 2008.", "calendar year"),
    ("Revenue grew faster than peers.", "peers"),
    ("The P/E ratio is below 30.", "share price"),
]


@pytest.mark.parametrize(("claim", "canonical"), COMPILED)
def test_a_numeric_claim_compiles_to_its_canonical_test(claim: str, canonical: str) -> None:
    test = compile_claim(claim)
    assert not isinstance(test, NotNumeric), test
    assert test.canonical == canonical


@pytest.mark.parametrize(("claim", "words"), NOT_NUMERIC)
def test_a_claim_that_is_not_numeric_says_why(claim: str, words: str) -> None:
    result = compile_claim(claim)
    assert isinstance(result, NotNumeric)
    assert words in result.reason


def test_the_form_is_named() -> None:
    forms = {
        "Gross margin is expanding.": "direction",
        "Revenue growth is accelerating.": "acceleration",
        "Revenue has grown for eight consecutive quarters.": "streak",
        "Gross margin is above 70%.": "threshold",
        "Revenue grew more than 50% year over year.": "growth_threshold",
        "Capex is growing faster than revenue.": "faster_than",
        "Revenue has compounded at over 20% for five years.": "compound",
        "Data center is more than 80% of revenue.": "share",
    }
    for claim, form in forms.items():
        test = compile_claim(claim)
        assert not isinstance(test, NotNumeric) and test.form == form, claim


def test_case_punctuation_and_spacing_do_not_matter() -> None:
    a = compile_claim("GROSS MARGIN IS EXPANDING")
    b = compile_claim("  gross   margin is expanding!  ")
    assert not isinstance(a, NotNumeric) and not isinstance(b, NotNumeric)
    assert a.canonical == b.canonical == "gross_margin[Q] > gross_margin[Q-4]"


def test_a_very_long_or_empty_claim_is_not_numeric() -> None:
    assert isinstance(compile_claim(""), NotNumeric)
    assert isinstance(compile_claim("revenue is growing " * 200), NotNumeric)


# Scoring against the labels


def test_the_labels_are_well_formed() -> None:
    from app.evaluation.claim_tests import load_labels

    dev, held = load_labels(Path("eval/claim-tests.json"))
    assert len(dev) == 150 and len(held) == 60
    ids = [label.id for label in dev + held]
    assert len(ids) == len(set(ids))
    compiled = sum(label.expected != "none" for label in dev)
    assert 60 <= compiled <= 90  # about half compile


def test_the_scorer_counts_exact_matches_and_lists_each_mismatch(tmp_path: Path) -> None:
    from app.evaluation.claim_tests import load_labels, render, score

    path = tmp_path / "labels.json"
    path.write_text(
        json.dumps(
            {
                "development": [
                    {
                        "id": "d1",
                        "claim": "Gross margin is expanding.",
                        "expected": "gross_margin[Q] > gross_margin[Q-4]",
                        "form": "direction",
                    },
                    {
                        "id": "d2",
                        "claim": "Growth is priced in.",
                        "expected": "gross_margin[Q] > 0%",
                        "form": "threshold",
                    },
                ],
                "held_out": [],
            }
        )
    )
    dev, _ = load_labels(path)
    result = score(dev)
    assert (result.exact, result.total) == (1, 2)
    assert result.compiled_expected == 2 and result.compiled_right == 1
    text = render(result, "development")
    assert "1 of 2" in text and "d2" in text and "gross_margin[Q] > 0%" in text
