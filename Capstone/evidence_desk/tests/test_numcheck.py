"""The numeric check: every number a statement writes must be in its quotes or cited figures."""

from __future__ import annotations

import random

import pytest

from app.core.metric_models import FactRef, Metric
from app.core.numcheck import Quantity, check_numbers, quantities

QUOTE = "Data Center revenue was $41.1 billion, up 56% from a year ago."


def metric(**overrides: object) -> Metric:
    values: dict = {
        "id": "revenue_yoy:annual:2026-01-25",
        "key": "revenue_yoy",
        "label": "Revenue growth, year over year",
        "period": "annual",
        "period_end": "2026-01-25",
        "period_label": "Fiscal year ended 2026-01-25",
        "value": 65.4735357900948,
        "unit": "percent",
        "display": "+65.5%",
        "formula": "(215,938 − 130,497) ÷ 130,497; USD millions",
        "inputs": [
            FactRef(
                concept="Revenues",
                unit="USD",
                start="2025-01-27",
                end="2026-01-25",
                value=215_938_000_000,
                accession="0001045810-26-000021",
                form="10-K",
                filed="2026-02-25",
            )
        ],
    }
    return Metric(**{**values, **overrides})


def one(text: str) -> Quantity:
    [found] = quantities(text)
    return found


# quantities ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value", "unit", "decimals"),
    [
        ("up 56% from a year ago", 56, "percent", 0),
        ("grew 55.6 percent", 55.6, "percent", 1),
        ("rose 1.5 percentage points", 1.5, "percent", 1),
        ("widened by 40 basis points", 40, "bps", 0),
        ("a 25 bps cut", 25, "bps", 0),
        ("revenue of $46.7 billion", 46_700_000_000, "usd", 1),
        ("revenue of $46,743 million", 46_743_000_000, "usd", 0),
        ("$2.5B of buybacks", 2_500_000_000, "usd", 1),
        ("$300K in fees", 300_000, "usd", 0),
        ("$1.2bn of debt", 1_200_000_000, "usd", 1),
        ("$45mm charge", 45_000_000, "usd", 0),
        ("Revenue $ 46,743", 46_743, "usd", 0),
        ("46.7 billion dollars", 46_700_000_000, "usd", 1),
        ("USD 3.2 million", 3_200_000, "usd", 1),
        ("diluted EPS of $2.46", 2.46, "usd", 2),
        ("trades at 30x earnings", 30, "multiple", 0),
        ("grew 3 times faster", 3, "multiple", 0),
        ("shipped 1,250 systems", 1250, "plain", 0),
        ("3.2 million units", 3_200_000, "plain", 1),
        ("a net loss of (1,234)", -1234, "plain", 0),
        ("a net loss of $(1,234)", -1234, "usd", 0),
        ("a net loss of ($1,234)", -1234, "usd", 0),
        ("margin fell (2.8)%", -2.8, "percent", 1),
        ("growth of -2.8%", -2.8, "percent", 1),
        ("a loss of -$1.20B", -1_200_000_000, "usd", 2),
    ],
)
def test_quantities_read_unit_scale_sign_and_precision(
    text: str, value: float, unit: str, decimals: int
) -> None:
    found = one(text)
    assert found.unit == unit
    assert found.value == pytest.approx(value)
    assert found.decimals == decimals


@pytest.mark.parametrize(
    "text",
    [
        "In fiscal 2026 the company grew.",
        "as reported in 2025",
        "our Form 10-K and 10-Q and 8-K reports",
        "see Item 1A and Item 7 of Part II",
        "a Rule 10b5-1 trading plan",
        "tariffs under Section 232",
        "in Q2 and FY2026 and fiscal year 2027",
        "the first and 2nd and 3rd quarters",
        "sales of H20 and RTX 5090 products",
        "as of July 26, 2026 and Jan 25, 2026",
        "on 2026-07-26",
        "2 customers and 12 suppliers and 0 defaults",
    ],
)
def test_exempt_numbers_are_not_quantities(text: str) -> None:
    assert quantities(text) == []


def test_a_bare_integer_above_twelve_and_ranges_are_quantities() -> None:
    assert [q.value for q in quantities("13 customers")] == [13]
    assert [(q.value, q.unit) for q in quantities("between 20-25%")] == [
        (20, "plain"),
        (25, "percent"),
    ]
    # A minus with a space after it is an operator, not a sign.
    assert [q.value for q in quantities("(68,127 − 57,006)")] == [68_127, 57_006]


def test_raw_keeps_the_text_written() -> None:
    assert one("revenue of $46.7 billion, up").raw == "$46.7 billion"
    assert one("up 56% from").raw == "56%"


# check_numbers ------------------------------------------------------------------------------


def test_the_wrong_program_65_percent_above_a_56_percent_quote_fails() -> None:
    check = check_numbers("Data Center revenue grew 65% from a year ago.", [QUOTE], [])
    assert check.status == "failed"
    assert check.unmatched == ["65%"]
    assert check.details == ["65% was not found in the quotes or the cited figures"]
    assert check.checked == 1


def test_the_quoted_number_passes() -> None:
    check = check_numbers("Data Center revenue grew 56% from a year ago.", [QUOTE], [])
    assert check.status == "passed" and check.unmatched == []
    assert check.details == ["56% matched 56% in a quote"]


def test_a_statement_with_no_number_is_none() -> None:
    check = check_numbers("Revenue is concentrated in a few customers.", [QUOTE], [])
    assert check.status == "none" and check.checked == 0 and check.details == []


@pytest.mark.parametrize(
    ("statement", "source", "status"),
    [
        ("grew 56%", "grew 55.6%", "passed"),
        ("grew 56%", "grew 56.4%", "passed"),
        ("grew 56%", "grew 55.4%", "failed"),
        ("grew 56%", "grew 56.6%", "failed"),
        ("grew 55.6%", "grew 56%", "failed"),  # the statement claims more precision
        ("revenue of $46.7 billion", "revenue of $46,743 million", "passed"),
        ("revenue of $46.7 billion", "revenue of $46,651 million", "passed"),
        ("revenue of $46.7 billion", "revenue of $46,649 million", "failed"),
        ("revenue of $47 billion", "revenue of $46.743 billion", "passed"),
    ],
)
def test_tolerance_is_half_a_unit_in_the_last_digit_the_statement_wrote(
    statement: str, source: str, status: str
) -> None:
    assert check_numbers(statement, [source], []).status == status


def test_a_table_number_without_a_scale_word_matches_in_thousands_millions_or_billions() -> None:
    table = "Revenue $ 96,221 $ 46,743\nCost of revenue 24,079 12,890"
    assert check_numbers("Revenue was $96.2 billion.", [table], []).status == "passed"
    assert check_numbers("Cost of revenue was $24.1 billion.", [table], []).status == "passed"
    assert check_numbers("Revenue was $96,221 million.", [table], []).status == "passed"
    assert check_numbers("Revenue was $96.3 billion.", [table], []).status == "failed"
    # A source that wrote a scale word is not rescaled.
    assert check_numbers("Revenue was $96.2 billion.", ["$96,221 thousand"], []).status == "failed"


def test_negative_numbers_in_parentheses() -> None:
    source = "Other income (expense), net (1,234)"
    assert check_numbers("A net expense of $1.2 billion.", [source], []).status == "passed"
    assert check_numbers("Other expense was -1,234.", [source], []).status == "passed"
    assert check_numbers("Other expense was -1,234.", ["income of 1,234"], []).status == "failed"


def test_units_must_agree() -> None:
    assert check_numbers("grew 56%", ["56 customers"], []).status == "failed"
    assert check_numbers("$56 million", ["56%"], []).status == "failed"
    assert check_numbers("trades at 56x", ["56%"], []).status == "failed"


def test_basis_points_match_hundredths_of_a_percent() -> None:
    points = check_numbers("margin rose 50 basis points", ["up 0.5 percentage points"], [])
    assert points.status == "passed"
    assert check_numbers("margin rose 0.5%", ["an increase of 50 bps"], []).status == "passed"
    assert check_numbers("margin rose 50 bps", ["up 50 bps"], []).status == "passed"
    assert check_numbers("margin rose 60 bps", ["up 0.5%"], []).status == "failed"


def test_a_cited_metric_matches_through_its_value_and_its_inputs() -> None:
    figures = [metric()]
    check = check_numbers("Revenue grew 65% to $215.9 billion in fiscal 2026.", [], figures)
    assert check.status == "passed", check.details
    assert check.checked == 2
    assert check.details[0] == (
        "65% matched +65.5% (Revenue growth, year over year, fiscal year ended 2026-01-25) "
        "in a cited figure"
    )
    assert "an input of revenue_yoy:annual:2026-01-25" in check.details[1]


def test_a_number_present_only_in_an_uncited_metric_fails() -> None:
    check = check_numbers("Revenue grew 65% in fiscal 2026.", [QUOTE], [])
    assert check.status == "failed" and check.unmatched == ["65%"]


def test_eps_metric_matches_a_dollar_amount() -> None:
    eps = metric(
        id="eps_diluted:quarter:2026-07-26",
        key="eps_diluted",
        label="Diluted EPS",
        value=2.46,
        unit="USD_per_share",
        display="$2.46",
        formula="",
        inputs=[],
    )
    assert check_numbers("Diluted EPS was $2.46.", [], [eps]).status == "passed"
    assert check_numbers("Diluted EPS was $2.64.", [], [eps]).status == "failed"


def test_one_unmatched_number_fails_the_whole_statement() -> None:
    check = check_numbers("Revenue grew 56% to $41.1 billion, or 70% of the total.", [QUOTE], [])
    assert check.status == "failed" and check.unmatched == ["70%"] and check.checked == 3


def _words(millions: int) -> str:
    return f"{millions:,}"


def test_property_an_amount_matches_itself_written_with_separators_and_scale_words() -> None:
    rng = random.Random(292)
    for _ in range(400):
        millions = rng.randint(1, 999_999)
        dollars = millions * 1_000_000
        billions = f"{millions / 1000:.3f}".rstrip("0").rstrip(".")
        statement = f"Revenue was ${_words(millions)} million."
        sources = [
            f"Revenue was ${billions} billion.",
            f"Revenue $ {_words(millions)}",
            f"Revenue of ${dollars:,}",
            f"revenue of {_words(millions)} million dollars",
        ]
        for source in sources:
            check = check_numbers(statement, [source], [])
            assert check.status == "passed", (statement, source, check.details)
        rounded = f"Revenue was ${millions / 1000:.1f} billion."
        assert check_numbers(rounded, [sources[1]], []).status == "passed", (rounded, sources[1])
