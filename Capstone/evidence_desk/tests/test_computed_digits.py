"""The printed comparison of a computed test is the comparison that was made.

A test compares the stored values, never the rounded ones. Its arithmetic line and its margin
are printed with as many digits as it takes for the printed numbers to compare as the stored
ones did: "75.0% >= 75%: fails" over a stored 74.96% would print a comparison that holds beside
the word "fails" (the fifth referee, finding 3).
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from app.core.claim_eval import OPS, evaluate
from app.core.claimtest import ClaimTest, compile_claim
from app.core.facts import FactBook
from app.core.periods import fiscal_calendar
from tests.test_claim_eval import synthetic

LINE = re.compile(r"^(?P<left>\S+) (?P<op>>=|<=|>|<) (?P<right>\S+): (?P<word>holds|fails)$")
NUMBER = re.compile(r"^([+\-−]?)\$?([0-9][0-9,]*(?:\.[0-9]+)?)(B|M)?%?$")


def _value(text: str) -> float:
    """The number a printed side shows, in its own scale."""
    match = NUMBER.match(text)
    assert match, text
    sign, digits, scale = match.groups()
    value = float(digits.replace(",", "")) * {"B": 1e9, "M": 1e6, None: 1.0}[scale]
    return -value if sign in ("-", "−") else value


def _with_newest_gross_profit(payload: dict[str, Any], share: float) -> dict[str, Any]:
    """``payload`` with the newest quarter's and year's gross profit set to ``share`` of revenue."""
    gaap = payload["facts"]["us-gaap"]
    revenue = {(f["end"], f.get("start")): f["val"] for f in gaap["Revenues"]["units"]["USD"]}
    newest = max(end for end, _ in revenue)
    for entry in gaap["GrossProfit"]["units"]["USD"]:
        if entry["end"] == newest:
            entry["val"] = round(revenue[(entry["end"], entry.get("start"))] * share)
    return payload


def _evaluate(claim: str, payload: dict[str, Any]):
    test = compile_claim(claim)
    assert isinstance(test, ClaimTest), test
    return evaluate(test, FactBook(payload), calendar=fiscal_calendar(payload))


def _printed(result) -> tuple[float, str, float, str]:
    match = LINE.match(result.arithmetic[-1])
    assert match, result.arithmetic[-1]
    return _value(match["left"]), match["op"], _value(match["right"]), match["word"]


@pytest.mark.parametrize("share", [0.7496, 0.74996, 0.75004, 0.7501, 0.75])
def test_a_margin_next_to_its_threshold_prints_the_comparison_it_made(share: float) -> None:
    payload = _with_newest_gross_profit(synthetic(), share)
    result = _evaluate("Gross margin is at least 75%.", payload)
    assert result.left is not None and result.left.value is not None
    stored = result.left.value
    assert result.outcome == ("holds" if stored >= 75 else "fails")
    left, op, right, word = _printed(result)
    assert word == ("holds" if result.outcome == "holds" else "fails")
    assert OPS[op](left, right) == (word == "holds"), result.arithmetic[-1]


def test_the_stored_values_are_compared_not_the_rounded_ones() -> None:
    payload = _with_newest_gross_profit(synthetic(), 0.7496)
    result = _evaluate("Gross margin is at least 75%.", payload)
    assert result.left is not None and result.left.value == pytest.approx(74.96, abs=1e-3)
    assert result.left.display == "75.0%"  # the value as the page shows it, unchanged
    assert result.outcome == "fails" and result.counted_as == "challenges"
    assert result.arithmetic[-1] == "74.96% >= 75.00%: fails"


def test_the_margin_shows_enough_digits_to_have_its_sign() -> None:
    payload = _with_newest_gross_profit(synthetic(), 0.7496)
    result = _evaluate("Gross margin is at least 75%.", payload)
    assert result.margin is not None and result.margin < 0
    assert result.margin_display == "-0.04 points"


def test_a_comparison_the_rounding_does_not_hide_prints_as_before() -> None:
    result = _evaluate("Gross margin is expanding.", synthetic())
    assert result.margin_display == "+4.0 points"
    assert result.arithmetic[-1] == f"{result.left.display} > {result.right.display}: holds"


def test_an_amount_next_to_its_threshold_prints_the_comparison_it_made() -> None:
    payload = synthetic()
    revenue = payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    for entry in revenue:
        if entry["end"] == "2023-12-31" and entry.get("start") == "2023-01-01":
            entry["val"] = 8_999_999_000  # shown as $9.00B
    result = _evaluate("Revenue was at least $9 billion in fiscal 2023.", payload)
    assert result.outcome == "fails"
    left, op, right, word = _printed(result)
    assert word == "fails" and not OPS[op](left, right), result.arithmetic[-1]
    assert result.margin_display.startswith("-") and result.margin_display != "-$0"


def test_a_history_point_prints_its_sides_as_the_comparison_was_made() -> None:
    from app.core.claim_eval import claim_history

    payload = _with_newest_gross_profit(synthetic(), 0.7496)
    test = compile_claim("Gross margin is at least 75%.")
    assert isinstance(test, ClaimTest)
    points, _ = claim_history(test, payload)
    newest = points[-1]
    assert newest.outcome == "fails"
    assert not OPS[">="](_value(newest.left_display), _value(newest.right_display))
