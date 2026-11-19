"""The outside view's pure parts: frames, concept resolution, base rates, peers, growth spread.

Every expected value is counted by hand from the table in ``tests/outside_fakes.py``;
the comments show the counting. None of them is produced by the function under test.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from app.core.base_rates import (
    RefClass,
    annual_test,
    base_rate,
    growth_distribution,
    percentile,
)
from app.core.claimtest import ClaimTest, compile_claim
from app.core.frames import (
    admitted_years,
    cutoff,
    parse_frame,
    resolve_group,
    scale_break,
)
from app.core.peers import peer_standing, standing
from tests.outside_fakes import M, frame, panel, row

OWN = 9


def compiled(claim: str) -> ClaimTest:
    test = compile_claim(claim)
    assert isinstance(test, ClaimTest), test
    return test


# Frames


def test_a_row_that_is_not_a_year_long_is_dropped_and_counted() -> None:
    body = frame(
        "Revenues",
        "CY2022",
        [
            row(1, "Alpha", 2022, 5.0),
            {**row(2, "Beta", 2022, 7.0), "start": "2022-07-01"},  # six months
            {"cik": "3", "val": 1},  # malformed
        ],
    )
    parsed = parse_frame(body, "Revenues", "CY2022")
    assert [r.cik for r in parsed.rows] == [1]
    assert parsed.dropped == {
        "not a year long (350 to 380 days)": 1,
        "row has no positive integer 'cik'": 1,
    }


def test_the_first_concept_in_the_apps_order_is_taken_and_the_others_counted() -> None:
    # GROUPS["revenue"] lists RevenueFromContractWithCustomerExcludingAssessedTax before
    # Revenues. Filer 1 has both, equal; filer 2 both, 5% apart; filer 3 only Revenues;
    # filer 4 both, a thousand times apart: left out.
    contract = frame(
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "CY2022",
        [
            row(1, "A", 2022, 100.0),
            row(2, "B", 2022, 95.0),
            row(4, "D", 2022, 145_233_000_000.0),
        ],
    )
    revenues = frame(
        "Revenues",
        "CY2022",
        [
            row(1, "A", 2022, 100.0),
            row(2, "B", 2022, 100.0),
            row(3, "C", 2022, 7.0),
            row(4, "D", 2022, 145_233_000.0),
        ],
    )
    parsed = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": parse_frame(
            contract, "RevenueFromContractWithCustomerExcludingAssessedTax", "CY2022"
        ),
        "Revenues": parse_frame(revenues, "Revenues", "CY2022"),
    }
    values, counts = resolve_group("revenue", 2022, parsed)
    assert {cik: v.value for cik, v in values.items()} == {1: 100.0, 2: 95.0, 3: 7.0}
    assert values[2].row.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    # 4 filers; 1, 2 and 4 have several concepts; 2 differs by more than 1%; 4 is a break.
    assert counts == (4, 3, 1, 1)


def test_rows_ending_after_the_cutoff_are_left_out() -> None:
    body = frame("Revenues", "CY2022", [row(1, "A", 2022, 1.0), row(5, "E", 2022, 2.0, june=True)])
    parsed = {"Revenues": parse_frame(body, "Revenues", "CY2022")}
    values, _ = resolve_group("revenue", 2022, parsed, last_end=date(2022, 9, 30))
    assert list(values) == [5]


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (145_233_000_000, 145_233_000, True),  # a thousand
        (54_014_000, 54_014_000_000_000, True),  # a million the other way
        (1015, 1, True),  # within 2% of a thousand
        (1100, 1, False),  # 10% off
        (2, 1, False),
        (100, -0.1, False),  # opposite signs
        (0, 5, False),
    ],
)
def test_a_scale_break_is_a_factor_near_a_power_of_a_thousand(
    first: float, second: float, expected: bool
) -> None:
    assert scale_break(first, second) is expected


def test_a_year_is_admitted_when_its_window_ended_a_year_before_the_as_of_date() -> None:
    # As of 2025-06-30 the cutoff is 2024-06-30. CY2023's window ends 2024-01-30: in.
    # CY2024's ends 2025-01-30: out.
    assert cutoff(date(2025, 6, 30), date(2026, 11, 18)) == date(2024, 6, 30)
    assert admitted_years(date(2025, 6, 30), date(2026, 11, 18))[-1] == 2023
    # Without one, 120 days before today: 2026-07-21; CY2025's window ends 2026-01-30.
    assert cutoff(None, date(2026, 11, 18)) == date(2026, 7, 21)
    assert admitted_years(None, date(2026, 11, 18))[-1] == 2025
    assert admitted_years(None, date(2026, 11, 18))[0] == 2009


# Reading a claim test on years


def test_a_quarter_growth_claim_is_read_on_years_and_says_so() -> None:
    read = annual_test(compiled("Revenue grew more than 50% year over year"))
    assert not isinstance(read, str)
    assert read.text() == "yoy(revenue)[t] > 50%"
    assert read.from_quarters
    assert read.reach == 1


@pytest.mark.parametrize(
    ("claim", "reason"),
    [
        ("Revenue grew sequentially", "quarter before"),
        ("Inventory is rising", "not built from frames"),
        ("Data Center is more than 80% of revenue", "share of revenue"),
    ],
)
def test_a_test_frames_cannot_hold_is_refused_with_the_reason(claim: str, reason: str) -> None:
    read = annual_test(compiled(claim))
    assert isinstance(read, str)
    assert reason in read


# The base rate


def test_the_base_rate_counts_company_years_of_the_class_by_hand() -> None:
    # Floor $80M in the base year (t-1); the company itself (Own) is never counted. By hand:
    # t=2021, base 2020: in class Alpha 100, Beta 200, Delta 300, Epsilon 90
    #   (Gamma 50 is under the floor): 4. Epsilon's 2020 and 2021 ends are not a year
    #   apart: 3 computable. Held (> 50%): Alpha +60%: 1.
    # t=2022, base 2021: Alpha 160, Beta 250, Gamma 120, Delta 290, Epsilon 200:
    #   5. Delta has no 2022: 4 computable. Held: Beta +60%, Gamma +150%: 2
    #   (Epsilon +5%, Alpha +25%).
    # In all 3 of 7. Persistence: the 2021 hit (Alpha) at 2022: +25%: 0 of 1.
    test = annual_test(compiled("Revenue grew more than 50% year over year"))
    assert not isinstance(test, str)
    rate = base_rate(
        panel(),
        test,
        RefClass("filers of at least $80M", 80 * M, definition="test"),
        [2021, 2022],
        company_cik=OWN,
        claim_test="yoy(revenue)[Q] > 50%",
        as_of="2026-11-18",
        result_id="r",
    )
    assert [(y.year, y.in_class, y.computable, y.held) for y in rate.years] == [
        (2021, 4, 3, 1),
        (2022, 5, 4, 2),
    ]
    assert (rate.held, rate.computable) == (3, 7)
    assert rate.value == pytest.approx(300 / 7)
    assert rate.display == "3 of 7 (42.9%)"
    assert (rate.persisted, rate.persist_base) == (0, 1)
    # Nearest to Own's newest value, +17.6% (2022): Beta and Alpha (+60%, 42.4 points away;
    # the later year first), then Gamma (+150%). Own's own hit is listed apart.
    assert [(c.name, c.year) for c in rate.cases] == [
        ("Beta", 2022),
        ("Alpha", 2021),
        ("Gamma", 2022),
    ]
    assert rate.cases[1].next_year == "did not hold"
    assert rate.cases[0].next_year == ""  # 2023 is not read
    assert [(c.year, c.display) for c in rate.own] == [(2021, "70.0%")]
    assert "held in 3 of 7 company-years from 2021 to 2022" in rate.reading
    assert any("The company itself is not counted" in a for a in rate.assumptions)
    assert any("read on years" in a for a in rate.assumptions)


def test_an_industry_class_counts_only_its_members() -> None:
    # Members 1, 2, 3, floor $80M. t=2021: Alpha, Beta (Gamma under): 2 computable,
    # held Alpha. t=2022: Alpha, Beta, Gamma: 3, held Beta and Gamma. 3 of 5.
    test = annual_test(compiled("Revenue grew more than 50% year over year"))
    assert not isinstance(test, str)
    rate = base_rate(
        panel(),
        test,
        RefClass("industry", 80 * M, members={1, 2, 3}),
        [2021, 2022],
        company_cik=OWN,
        claim_test="",
        as_of="",
        result_id="r",
    )
    assert (rate.held, rate.computable) == (3, 5)


def test_a_streak_of_years_counts_rises_in_a_row() -> None:
    # Own: 1000 -> 1700 -> 2000, two rises by 2022. Alpha: 100 -> 160 -> 200, two.
    # Beta: 200 -> 250 -> 400, two. Gamma: 50 -> 120 -> 300, two. Epsilon: its ends are
    # not a year apart: not computable. Delta has no 2022. Class floor $1M at t-2 (2020):
    # the five others; computable three (Alpha, Beta, Gamma); held three. Own is not counted.
    test = annual_test(compiled("Revenue has grown for 2 consecutive years"))
    assert not isinstance(test, str), test
    rate = base_rate(
        panel(),
        test,
        RefClass("all", 1 * M),
        [2022],
        company_cik=OWN,
        claim_test="",
        as_of="",
        result_id="r",
    )
    assert (rate.held, rate.computable, rate.years[0].in_class) == (3, 3, 5)


def test_no_computable_year_is_cannot_compute_not_zero() -> None:
    test = annual_test(compiled("Revenue grew more than 50% year over year"))
    assert not isinstance(test, str)
    rate = base_rate(
        panel(),
        test,
        RefClass("nobody", 1e15),
        [2021, 2022],
        company_cik=OWN,
        claim_test="",
        as_of="",
        result_id="r",
    )
    assert rate.outcome == "cannot_compute"
    assert rate.value is None


# Peers


def test_peer_standing_ranks_by_hand() -> None:
    # Operating margin 2022 among members 1, 2, 3 (and Own, always ranked):
    # Alpha 20/200 = 10%, Beta 100/400 = 25%, Gamma 30/300 = 10%, Own 400/2000 = 20%.
    # Own: one higher (Beta): rank 2 of 4; two lower: percentile 100 × 2 ÷ 3.
    # Median of 10, 10, 20, 25: 15.
    ref = RefClass("industry", 80 * M, members={1, 2, 3})
    found = standing(panel(), "operating_margin", OWN, 2022, ref)
    assert (found.rank, found.n) == (2, 4)
    assert found.percentile == pytest.approx(200 / 3)
    assert found.median == pytest.approx(15.0)
    assert [n.name for n in found.above] == ["Beta"]
    assert [(n.name, n.rank) for n in found.below] == [("Alpha", 3), ("Gamma", 3)]
    result = peer_standing(panel(), "operating_margin", OWN, 2022, ref, as_of="x", result_id="p")
    assert result.display == "rank 2 of 4"
    assert result.year_before is not None and result.year_before.rank is None
    assert "operating_income were not read" in result.year_before.reason


def test_revenue_growth_is_a_peer_measure() -> None:
    # 2022 growth: Alpha 25%, Beta 60%, Gamma 150%, Own 17.6%: Own is last, 4 of 4.
    ref = RefClass("industry", 80 * M, members={1, 2, 3})
    found = standing(panel(), "revenue_growth", OWN, 2022, ref)
    assert (found.rank, found.n, found.percentile) == (4, 4, 0.0)


# Percentiles and the spread of growth


def test_percentile_interpolates_between_ranks() -> None:
    values = [5.0, 1.0, 4.0, 2.0, 3.0]
    assert percentile(values, 25) == 2.0  # position (5 - 1) × 0.25 = 1
    assert percentile(values, 90) == pytest.approx(4.6)  # position 3.6: 4 + 0.6 × 1
    assert percentile([7.0], 50) == 7.0


def test_growth_distribution_of_survivors_of_a_size() -> None:
    # Start 2020, span 2, revenue $80M to $1.5B, Own left out: Alpha 100 -> 200 and
    # Beta 200 -> 400, each (2)^(1/2) - 1 = 41.42%; Delta has no 2022 and Epsilon's ends
    # are not two years apart: dropped 2. Gamma (50) is under the size.
    found = growth_distribution(panel(), 80 * M, 1500 * M, span=2, at_least=40.0, exclude=OWN)
    root_two = (math.sqrt(2) - 1) * 100
    assert found.n == 2
    assert found.dropped == 2
    assert found.percentiles["p50"] == pytest.approx(root_two)
    assert found.at_least == 2


# A level of revenue in a class chosen on revenue (seventh referee, finding 6) -------------------


def _level_rate(floor_millions: float):  # noqa: ANN202
    test = annual_test(compiled("Revenue was above $295 million in the latest fiscal year"))
    assert not isinstance(test, str), test
    return test, base_rate(
        panel(),
        test,
        RefClass("filers of that size", floor_millions * M, definition="test"),
        [2021, 2022],
        company_cik=OWN,
        claim_test="revenue[FY] > $295M",
        as_of="2026-11-18",
        result_id="r",
    )


def test_a_revenue_level_is_not_counted_in_a_class_chosen_on_that_years_revenue() -> None:
    """The referee's case: a floor above the threshold. Until version 14.3 the class was
    chosen in the year the test reads, so every filer in it had already passed: Beta (400)
    and Gamma (300) in 2022, 2 of 2 by construction.

    Chosen a year earlier, by hand, floor $296M:
    t=2021, class of 2020: Delta 300 only. Delta's 2021 is 290: does not hold. 0 of 1.
    t=2022, class of 2021: nobody is at 296 (Delta 290, Beta 250). 0 of 0.
    """
    test, rate = _level_rate(296)
    assert [(y.year, y.in_class, y.computable, y.held) for y in rate.years] == [
        (2021, 1, 1, 0),
        (2022, 0, 0, 0),
    ]
    assert (rate.held, rate.computable) == (0, 1)
    assert test.reach == 0 and test.class_reach == 1
    assert any("decided a year earlier" in a for a in rate.assumptions)


def test_a_level_of_another_measure_keeps_the_class_of_the_year_read() -> None:
    growth = annual_test(compiled("Revenue grew more than 50% year over year"))
    assert not isinstance(growth, str)
    assert growth.reach == 1 and growth.class_reach == 1
    margin = annual_test(compiled("Operating margin is above 20%"))
    assert not isinstance(margin, str), margin
    assert margin.reach == 0 and margin.class_reach == 0
