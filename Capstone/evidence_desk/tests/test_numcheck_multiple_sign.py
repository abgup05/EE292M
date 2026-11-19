"""A multiple written with the letter x is the multiple a figure shows with the sign ×.

Found on two live runs of 19 November 2026: sentences writing "28.5x", "45.7x" and "0.86x"
were marked although the analytics they cite display "28.5×", "45.7×" and "0.86×".
"""

from __future__ import annotations

from app.core.numcheck import check_numbers


def unmatched(statement: str, excerpt: str) -> list[str]:
    return list(check_numbers(statement, [excerpt], []).unmatched)


def test_a_multiple_with_x_matches_one_shown_with_the_multiplication_sign() -> None:
    assert unmatched("The stock costs 28.5x earnings.", "Price to earnings: 28.5×") == []
    assert unmatched("Cash conversion is 0.86x.", "0.86× over four quarters") == []


def test_a_different_multiple_is_still_unmatched() -> None:
    assert unmatched("The stock costs 31.0x earnings.", "Price to earnings: 28.5×") != []
