"""Three numbers the number check let through (the fifth referee, finding 5).

- A decline stated against a computed figure whose sign is known: "fell 65.5%" beside a
  cited growth of +65.5%. A filing writes most declines as a positive number with a word,
  so a quote cannot be held to this; a figure the backend computed, printed with its sign,
  can.
- A number glued to a scale letter without a dollar sign ("46.7B", "2.5M") was not read at
  all, so a wrong one passed.
- A day of a month followed by a percent sign ("March 15%") was masked as a date.

A bare integer up to 12 is still exempt ("2 customers"), on purpose: see the README's
blind spots.
"""

from __future__ import annotations

import pytest

from app.core.numcheck import check_numbers, quantities
from tests.test_numcheck import metric

GROWTH = metric()  # revenue growth, year over year: +65.5%, a computed figure
DECLINE = metric(value=-5.2, display="-5.2%")


def test_a_decline_against_a_computed_increase_fails() -> None:
    check = check_numbers("Revenue fell 65.5% year over year.", [], [GROWTH])
    assert check.status == "failed" and check.unmatched == ["65.5%"]


def test_a_rise_against_the_same_increase_passes() -> None:
    assert check_numbers("Revenue rose 65.5% year over year.", [], [GROWTH]).status == "passed"
    assert check_numbers("Revenue grew by 65.5%.", [], [GROWTH]).status == "passed"


def test_a_decline_against_a_computed_decrease_passes_and_a_rise_fails() -> None:
    assert check_numbers("Revenue fell 5.2%.", [], [DECLINE]).status == "passed"
    assert check_numbers("Revenue rose 5.2%.", [], [DECLINE]).status == "failed"


def test_a_decline_against_a_quote_is_still_not_held_to_its_sign() -> None:
    # The filing's own "up 56%" is a positive number with a word: the check cannot tell.
    quote = "Data Center revenue was $41.1 billion, up 56% from a year ago."
    assert check_numbers("Data Center revenue fell 56%.", [quote], []).status == "passed"


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("revenue of 46.7B in the quarter", 46_700_000_000),
        ("2.5M units shipped", 2_500_000),
        ("a 1.2bn charge", 1_200_000_000),
        ("10M subscribers", 10_000_000),
        ("100B of buybacks", 100_000_000_000),
    ],
)
def test_a_number_glued_to_a_scale_letter_is_read(text: str, value: float) -> None:
    found = quantities(text)
    assert [q.value for q in found] == [pytest.approx(value)]


@pytest.mark.parametrize(
    "text",
    ["shares of 3M and 4K displays", "the RTX 5090Ti and 300GB of memory", "a 10K filing"],
)
def test_a_name_with_a_scale_letter_stays_a_name(text: str) -> None:
    assert quantities(text) == []


def test_a_wrong_glued_amount_fails_and_a_right_one_passes() -> None:
    quote = "Revenue was $46.7 billion, up 56% from a year ago."
    assert check_numbers("Revenue was 52.1B.", [quote], []).status == "failed"
    assert check_numbers("Revenue was 46.7B.", [quote], []).status == "passed"


def test_a_day_of_a_month_followed_by_a_percent_sign_is_a_percentage() -> None:
    assert [q.value for q in quantities("In March 15% of units shipped late.")] == [15]
    assert quantities("as of March 15, 2026") == []


# "tn" and a spaced "bn" (seventh referee, finding 11) ----------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("a market value of $1.2tn at the close", 1.2e12),
        ("a market value of $3tn", 3e12),
        ("revenue of $46.7 bn in the quarter", 46.7e9),
        ("revenue of $46.7 tn", 46.7e12),
        ("revenue of $46.7 mn", 46.7e6),
        ("revenue of $46.7mn", 46.7e6),
        ("revenue of 46.7tn in the quarter", 46.7e12),
        ("revenue of 46.7mn", 46.7e6),
    ],
)
def test_trillions_and_spaced_abbreviations_are_amounts(text: str, value: float) -> None:
    (found,) = quantities(text)
    assert found.value == pytest.approx(value)
    assert found.raw.endswith(("tn", "bn", "mn"))


def test_a_wrong_figure_in_trillions_is_checked_and_a_right_one_passes() -> None:
    """ "$1.2tn" was skipped whole: the letters after the digits made it a name."""
    quote = "The company's market value passed $1.2 trillion in the quarter."
    assert check_numbers("Its market value passed $1.2tn.", [quote], []).status == "passed"
    wrong = check_numbers("Its market value passed $1.3tn.", [quote], [])
    assert wrong.status == "failed" and wrong.unmatched == ["$1.3tn"]


def test_a_spaced_bn_matches_billions_and_not_millions() -> None:
    """ "$46.7 bn" read as 46.7 dollars, so it failed against "$46.7 billion". (A quote's
    bare "$46.70" still matches it at a thousand, a million and a billion times: the
    README's blind spot for a bare amount, which this does not close.)"""
    billions = "Revenue was $46.7 billion, up 56% from a year ago."
    assert check_numbers("Revenue was $46.7 bn.", [billions], []).status == "passed"
    millions = "Revenue was $46.7 million, up 56% from a year ago."
    assert check_numbers("Revenue was $46.7 bn.", [millions], []).status == "failed"


@pytest.mark.parametrize(
    "text",
    [
        "It runs a $5 TN plant in Memphis.",  # Tennessee, not trillions
        "The $5 BN line is a rail line.",  # upper case is a name
        "It paid $46.7 tnt for the freight.",  # a longer word that begins "tn"
        "It sold 3 bn-class units.",  # no currency, a space: not read as a scale
    ],
)
def test_a_name_that_looks_like_an_abbreviation_is_not_a_scale(text: str) -> None:
    assert all(found.scale == 1.0 for found in quantities(text))
