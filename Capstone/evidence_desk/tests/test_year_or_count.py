"""A four-digit number after "of", "for", "by" or "in": a year, or a count of things?

The sixth referee's finding 9. "headcount of 2000 employees" was read as the year 2000
because it follows "of": the number check did not check it, and the period check looked
for the year 2000 in the evidence. Both checks read a year the same way
(:func:`app.core.numcheck.is_year`), so one rule decides for both.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.numcheck import check_numbers, quantities, year_spans
from app.core.periods import FiscalCalendar, check_periods, period_mentions

REFEREE = "The company reports a headcount of 2000 employees."
CALENDAR = FiscalCalendar(end_month=1, end_day=25, label_offset=0)


def test_the_referees_sentence_is_a_count_to_the_number_check() -> None:
    assert [(q.value, q.unit) for q in quantities(REFEREE)] == [(2000.0, "count")]
    wrong = check_numbers(REFEREE, ["We had approximately 36,000 employees worldwide."], [])
    assert wrong.status == "failed" and wrong.checked == 1
    right = check_numbers(REFEREE, ["We had approximately 2,000 employees worldwide."], [])
    assert right.status == "passed"


def test_the_referees_sentence_names_no_year_to_the_period_check() -> None:
    assert year_spans(REFEREE) == [] and period_mentions(REFEREE) == []
    quote = [("We had approximately 2,000 employees worldwide.", date(2026, 1, 25))]
    check = check_periods(REFEREE, quote, [], CALENDAR)
    assert check.status == "none" and check.unverified == []


@pytest.mark.parametrize(
    "text",
    [
        "It grew to a total of 2000 employees.",
        "The plan provides for 2050 stores.",
        "Headcount rose by 2000 people.",
        "It operates in 2000 locations.",
        "It has a base of 2025 customers.",
    ],
)
def test_a_counted_noun_after_a_preposition_makes_a_count(text: str) -> None:
    assert [q.unit for q in quantities(text)] == ["count"]
    assert period_mentions(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "Revenue for 2026 remains ahead of plan.",  # a verb after the year, not a counted noun
        "Growth in 2026 reflects demand for accelerated computing.",
        "The first half of 2026 shows a recovery.",
        "It expects to finish by 2027.",
        "Revenue in 2026, as in 2025, rose.",
        "Results of 2026 were strong.",
        "In 2026 we expect growth.",
        "Guidance for 2026 assumes no sales to China.",
        "In fiscal 2026 employees received new grants.",  # "fiscal" decides, whatever follows
        "Since 2020 customers have doubled.",  # "since" is of time only
    ],
)
def test_a_year_after_a_preposition_is_still_a_year(text: str) -> None:
    assert quantities(text) == []
    assert len(period_mentions(text)) >= 1
