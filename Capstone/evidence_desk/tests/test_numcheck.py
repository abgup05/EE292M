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
        ("shipped 1,250 systems", 1250, "count", 0),  # a count of things, never an amount
        ("3.2 million units", 3_200_000, "count", 1),
        ("a total of 1,250 and then more", 1250, "plain", 0),  # a connective is not a thing
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


# The referee's demonstrations (docs/reviews/referee-1-version-4.md, finding 3) ---------------


@pytest.mark.parametrize("source", ["Revenue change (3)%", "Revenue change -3%"])
def test_growth_does_not_match_a_negative_source(source: str) -> None:
    """3b: "grew 3%" against a source that says the figure fell 3%."""
    check = check_numbers("Revenue grew 3% from a year ago.", [source], [])
    assert check.status == "failed" and check.unmatched == ["3%"]


@pytest.mark.parametrize("source", ["Revenue change (3)%", "Revenue change -3%"])
def test_a_word_of_decline_lets_an_unsigned_number_match_a_negative_source(source: str) -> None:
    assert check_numbers("Revenue declined 3% from a year ago.", [source], []).status == "passed"


def test_the_word_of_decline_must_be_in_the_same_sentence() -> None:
    statement = "Revenue grew 3% from a year ago. Gross margin fell."
    assert check_numbers(statement, ["Revenue change (3)%"], []).status == "failed"
    statement = "Gross margin fell. Revenue grew 3% from a year ago."
    assert check_numbers(statement, ["Revenue change (3)%"], []).status == "failed"


def test_a_negative_statement_number_still_needs_a_negative_source() -> None:
    assert check_numbers("Revenue declined -3%.", ["Revenue change 3%"], []).status == "failed"
    assert check_numbers("Revenue declined -3%.", ["Revenue change (3)%"], []).status == "passed"


def test_an_unsigned_number_still_matches_a_positive_source_whatever_the_wording() -> None:
    assert check_numbers("Revenue fell 3% short of plan.", ["up 3%"], []).status == "passed"


# The second referee's demonstration (docs/reviews/referee-2-version-6.md, finding 7) ---------


@pytest.mark.parametrize(
    "statement",
    [
        "Operating expenses grew 3% from a year ago.",
        "The company paid 3% more in dividends than a year ago.",
        "Purchases of inventory rose 3%.",
    ],
)
def test_a_word_for_an_outflow_does_not_let_a_percentage_match_a_decline(statement: str) -> None:
    """A percentage in parentheses is a fall; "expenses" or "paid" beside it says nothing of one."""
    check = check_numbers(statement, ["Change from a year ago (3)%"], [])
    assert check.status == "failed" and check.unmatched == ["3%"]


def test_a_word_of_decline_beside_an_outflow_still_matches_the_fall() -> None:
    statement = "Operating expenses declined 3% from a year ago."
    assert check_numbers(statement, ["Change from a year ago (3)%"], []).status == "passed"


def test_a_word_for_an_outflow_still_lets_an_amount_match_one_printed_in_parentheses() -> None:
    source = "Payments for repurchases of common stock were $(3,236) million in the year."
    statement = "The company spent $3,236 million on repurchases."
    assert check_numbers(statement, [source], []).status == "passed"
    assert check_numbers("Cash received was $3,236 million.", [source], []).status == "failed"


def test_a_negative_cited_figure_needs_a_word_of_decline() -> None:
    figure = metric(value=-2.8, display="-2.8%")
    assert check_numbers("Revenue grew 2.8% in fiscal 2026.", [], [figure]).status == "failed"
    assert check_numbers("Revenue fell 2.8% in fiscal 2026.", [], [figure]).status == "passed"


def test_lower_case_notes_followed_by_a_rate_are_checked() -> None:
    """3c: the exemption for "Note 5" hid the 3.5 of "senior notes 3.5%"."""
    assert [(q.value, q.unit) for q in quantities("the senior notes 3.5% due")] == [
        (3.5, "percent")
    ]
    check = check_numbers(
        "The senior notes 3.5% are the company's cheapest debt.",
        ["The senior notes bear interest at 2.5% per year."],
        [],
    )
    assert check.status == "failed" and check.unmatched == ["3.5%"]


@pytest.mark.parametrize(
    "text",
    [
        "see Note 5 to the financial statements",
        "described in Note 14",
        "as Notes 13 explains",
        "Item 1A and Item 7A",
        "our annual report on Form 10-K",
        "Part II of the 10-K",
        "tariffs under Section 232",
        "a Rule 10b5-1 trading plan",
        "Exhibit 31.1 and Exhibit 32.1",
    ],
)
def test_a_capitalised_reference_followed_by_its_number_stays_exempt(text: str) -> None:
    assert quantities(text) == []


def test_a_capitalised_reference_followed_by_a_rate_is_checked() -> None:
    assert [q.value for q in quantities("Notes 3.5% due 2030")] == [3.5]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("the company had 2000 employees", 2000),
        ("it opened 2025 stores last year", 2025),
        ("a fee of $2025", 2025),
        ("about 1950 suppliers", 1950),
    ],
)
def test_a_four_digit_number_outside_a_date_is_checked(text: str, value: float) -> None:
    """3e: "2000 employees" was exempt as a year."""
    assert [q.value for q in quantities(text)] == [value]


def test_2000_employees_is_checked_against_the_quote() -> None:
    check = check_numbers("The company has 2000 employees.", ["We had 1,800 employees."], [])
    assert check.status == "failed" and check.unmatched == ["2000"]


@pytest.mark.parametrize(
    "text",
    [
        "In 2025 the company grew.",
        "revenue in 2025",
        "since 2019",
        "during 2024",
        "by 2030",
        "guidance for 2026",
        "the end of 2025",
        "the year ended 2025",
        "the period ending 2026",
        "fiscal 2026 and fiscal year 2025",
        "FY 2026",
        "in June 2025",
        "Q3 2025",
        "the third quarter 2025",
        "2024 and 2025",
        "2023 to 2025",
        "from 2023 through 2025",
        "on 2026-07-26",
        "as of July 26, 2026",
        "at fiscal year-end 2026",
        "at year end 2025",
        "inventory at quarter-end 2026",
    ],
)
def test_a_year_in_a_date_like_context_is_exempt(text: str) -> None:
    assert quantities(text) == []


def test_a_year_after_year_end_is_not_a_quantity_in_a_recorded_statement() -> None:
    """A stand-in's true statement, withheld on 17 November 2026 because 2026 was read as a number.

    From the first replay of ``demo/cassettes/nvda-example-tagged``: the three shares were
    each found in a cited figure and the finding was still withheld for "2026".
    """
    statement = (
        "Accounts receivable are also concentrated: at fiscal year-end 2026, Customer One was "
        "25%, Customer Two 18% and Customer Three 13% of receivables."
    )
    assert [(q.value, q.unit) for q in quantities(statement)] == [
        (25.0, "percent"),
        (18.0, "percent"),
        (13.0, "percent"),
    ]


# The third referee's demonstrations (docs/reviews/referee-3-version-9.md, finding 2) ----------


@pytest.mark.parametrize(
    "statement",
    [
        "Revenue grew 3% while gross margin fell.",
        "Gross margin fell while revenue grew 3%.",
        "A 3% increase in revenue came as costs fell.",
    ],
)
def test_a_word_of_decline_about_something_else_does_not_let_growth_match_a_fall(
    statement: str,
) -> None:
    """2c: a word of decline anywhere in the sentence used to let "grew 3%" match "(3)%"."""
    check = check_numbers(statement, ["Revenue change (3)%"], [])
    assert check.status == "failed" and check.unmatched == ["3%"]


@pytest.mark.parametrize(
    "statement",
    [
        "Revenue was down 3% while costs rose.",
        "A 3% decline in revenue came as costs rose.",
        "Revenue fell 3% in the first quarter and 5% in the second.",
        "Revenue was 3% lower than a year ago, although services grew.",
    ],
)
def test_the_direction_word_nearest_a_percentage_decides(statement: str) -> None:
    """The nearest direction word before the number governs it; with none before, the next."""
    sources = ["Revenue change (3)%", "Revenue change (5)%"]
    assert check_numbers(statement, sources, []).status == "passed"


@pytest.mark.parametrize(
    ("statement", "quote"),
    [
        ("The company earned $46 million of revenue.", "It served 46 customers in the period."),
        ("Revenue was $130 million.", "The company sells in 130 countries."),
        ("Costs were $2,000 million.", "It has 2,000 employees in the region."),
        ("Revenue was $46 million.", "It reached 46 million developers."),
    ],
)
def test_a_count_of_things_in_a_quote_does_not_match_a_dollar_amount(
    statement: str, quote: str
) -> None:
    """2b: "46 customers" times a million used to match "$46 million"."""
    assert check_numbers(statement, [quote], []).status == "failed"


@pytest.mark.parametrize(
    ("statement", "quote"),
    [
        ("It has 2,000 employees in the region.", "approximately 2,000 employees"),
        ("It served 46 customers.", "sales to 46 customers"),
        ("It reached 46 million developers.", "more than 46 million developers"),
        ("The count was 2,000.", "approximately 2,000 employees"),
        # A table row and a number followed by a function word are still amounts.
        ("Revenue was $46.7 billion.", "Revenue 46,743 39,331"),
        ("Revenue was $46.7 billion.", "Revenue of 46,743 and 39,331 in the two years"),
        ("Revenue was $46.7 billion.", "Revenue was 46,743 in the year (in millions)"),
    ],
)
def test_a_count_still_matches_a_count_and_a_table_number_still_matches_an_amount(
    statement: str, quote: str
) -> None:
    check = check_numbers(statement, [quote], [])
    assert check.status == "passed", check.details
