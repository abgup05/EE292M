"""One normal form for a claim test: two readings of one claim compare as equal text.

Each equivalence the counting rule relies on has its own test, and each near miss that
must stay different has one too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.claim_normal import Newest, normal_form, normalize
from app.core.claimtest import ClaimTest, Number, Period, Term, compile_claim
from app.evaluation.claim_tests import load_labels

Q, Q4, FY, FY1 = Period("Q"), Period("Q", 4), Period("FY"), Period("FY", 1)


def v(subject: str, period: Period) -> Term:
    return Term("value", subject, period)


def g(fn: str, subject: str, period: Period) -> Term:
    return Term(fn, subject, period)  # type: ignore[arg-type]


def pct(value: float) -> Number:
    return Number(value, "percent")


def same(a: ClaimTest, b: ClaimTest, newest: Newest | None = None) -> bool:
    return normal_form(a, newest) == normal_form(b, newest)


# a > b and b < a


def test_a_direction_written_either_way_round_is_one_form() -> None:
    a = ClaimTest("direction", v("revenue", Q), ">", v("revenue", Q4))
    b = ClaimTest("direction", v("revenue", Q4), "<", v("revenue", Q))
    assert same(a, b)
    assert normal_form(a) == "revenue[Q] > revenue[Q-4]"


def test_faster_than_and_acceleration_written_either_way_round() -> None:
    a = ClaimTest("faster_than", g("yoy", "sga", Q), "<", g("yoy", "gross_profit", Q))
    b = ClaimTest("faster_than", g("yoy", "gross_profit", Q), ">", g("yoy", "sga", Q))
    assert same(a, b)
    c = ClaimTest("acceleration", g("yoy", "revenue", Q), ">=", g("yoy", "revenue", Period("Q", 1)))
    d = ClaimTest("acceleration", g("yoy", "revenue", Period("Q", 1)), "<=", g("yoy", "revenue", Q))
    assert same(c, d)


# An explicit period and the default it equals


def test_a_named_fiscal_year_is_the_default_when_it_is_the_newest() -> None:
    fy2026 = Period("FY", fiscal_year=2026)
    named = ClaimTest("threshold", v("revenue", fy2026), ">", Number(1e11, "USD"))
    default = ClaimTest("threshold", v("revenue", FY), ">", Number(1e11, "USD"))
    year_before = ClaimTest(
        "threshold", v("revenue", Period("FY", fiscal_year=2025)), ">", Number(1e11, "USD")
    )
    newest = Newest(fiscal_year=2026, quarter=(2027, 2))
    assert same(named, default, newest)
    assert normal_form(year_before, newest) == "revenue[FY-1] > $100B"
    assert not same(named, default)  # without the newest year, a named year stays named


def test_a_named_quarter_is_counted_back_from_the_newest() -> None:
    newest = Newest(fiscal_year=2026, quarter=(2027, 2))
    named = ClaimTest(
        "direction",
        v("revenue", Period("Q", fiscal_year=2027, quarter=2)),
        ">",
        v("revenue", Period("Q", fiscal_year=2026, quarter=2)),
    )
    default = ClaimTest("direction", v("revenue", Q), ">", v("revenue", Q4))
    assert same(named, default, newest)
    before = ClaimTest(
        "threshold", v("gross_margin", Period("Q", fiscal_year=2026, quarter=4)), ">", pct(70)
    )
    assert normal_form(before, newest) == "gross_margin[Q-2] > 70%"


def test_a_share_of_a_named_year_is_the_latest_year_and_not_the_newest_filing() -> None:
    def share(period: Period) -> ClaimTest:
        term = Term("share", "segment", period, member="Data Center")
        return ClaimTest("share", term, ">", pct(80))

    newest = Newest(fiscal_year=2026, quarter=(2027, 2))
    assert normal_form(share(Period("FY", fiscal_year=2026)), newest) == normal_form(
        share(Period("FY")), newest
    )
    # The newest filing may be a 10-K or a 10-Q: its period is not known here.
    assert normal_form(share(Q), newest) != normal_form(share(Period("filing")), newest)


# Equivalent thresholds and spans


def test_growth_above_zero_is_a_rise_on_the_same_span() -> None:
    yoy = ClaimTest("growth_threshold", g("yoy", "revenue", Q), ">", pct(0))
    rise = ClaimTest("direction", v("revenue", Q), ">", v("revenue", Q4))
    assert same(yoy, rise)
    qoq = ClaimTest("growth_threshold", g("qoq", "revenue", Q), "<", pct(0))
    fall = ClaimTest("direction", v("revenue", Period("Q", 1)), ">", v("revenue", Q))
    assert same(qoq, fall)
    annual = ClaimTest("growth_threshold", g("yoy", "net_income", FY), ">", pct(0))
    assert same(annual, ClaimTest("direction", v("net_income", FY), ">", v("net_income", FY1)))
    ttm = ClaimTest("growth_threshold", g("yoy", "capex", Period("TTM")), ">", pct(0))
    assert normal_form(ttm) == "capex[TTM] > capex[TTM-4]"


def test_a_compound_rate_above_zero_and_over_one_year() -> None:
    cagr = ClaimTest("compound", Term("cagr", "revenue", FY, years=3), ">", pct(0))
    rise = ClaimTest("direction", v("revenue", FY), ">", v("revenue", Period("FY", 3)))
    assert same(cagr, rise)
    one_year = ClaimTest("compound", Term("cagr", "revenue", FY, years=1), ">", pct(20))
    assert same(one_year, ClaimTest("growth_threshold", g("yoy", "revenue", FY), ">", pct(20)))


def test_a_streak_count_is_a_whole_number_of_rises() -> None:
    above = ClaimTest("streak", g("streak", "revenue", Q), ">", Number(3, "count"))
    at_least = ClaimTest("streak", g("streak", "revenue", Q), ">=", Number(4, "count"))
    assert same(above, at_least)
    below = ClaimTest("streak", g("streak", "revenue", Q), "<", Number(4, "count"))
    at_most = ClaimTest("streak", g("streak", "revenue", Q), "<=", Number(3, "count"))
    assert same(below, at_most)


def test_numbers_written_differently_are_one_number() -> None:
    a = ClaimTest("threshold", v("gross_margin", Q), ">", pct(70))
    b = ClaimTest("threshold", v("gross_margin", Q), ">", pct(70.0000001))
    assert same(a, b)
    c = ClaimTest("threshold", v("revenue", FY), ">", Number(20e9, "USD"))
    d = ClaimTest("threshold", v("revenue", FY), ">", Number(20_000_000_000.4, "USD"))
    assert same(c, d)


def test_a_members_name_is_compared_without_case_spacing_or_ampersand() -> None:
    filing = Period("filing")
    a = ClaimTest(
        "share", Term("share", "segment", filing, member="Compute & Networking"), ">", pct(80)
    )
    b = ClaimTest(
        "share", Term("share", "segment", filing, member="compute  and networking"), ">", pct(80)
    )
    assert same(a, b)


# Near misses stay different


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (
            ClaimTest("threshold", v("gross_margin", Q), ">", pct(70)),
            ClaimTest("threshold", v("gross_margin", Q), ">=", pct(70)),
        ),
        (
            ClaimTest("threshold", v("revenue", Q), ">", Number(1e9, "USD")),
            ClaimTest("threshold", v("revenue", Period("TTM")), ">", Number(1e9, "USD")),
        ),
        (
            ClaimTest("growth_threshold", g("yoy", "revenue", Q), ">", pct(5)),
            ClaimTest("direction", v("revenue", Q), ">", v("revenue", Q4)),
        ),
        (
            ClaimTest("growth_threshold", g("yoy", "revenue", Q), ">", pct(0)),
            ClaimTest("growth_threshold", g("qoq", "revenue", Q), ">", pct(0)),
        ),
        (
            ClaimTest("direction", v("revenue", Q), ">", v("revenue", Q4)),
            ClaimTest("direction", v("revenue", Q), "<", v("revenue", Q4)),
        ),
        (
            ClaimTest("compound", Term("cagr", "revenue", FY, years=3), ">", pct(10)),
            ClaimTest("compound", Term("cagr", "revenue", FY, years=2), ">", pct(10)),
        ),
    ],
)
def test_near_misses_stay_different(a: ClaimTest, b: ClaimTest) -> None:
    assert not same(a, b, Newest(fiscal_year=2026, quarter=(2027, 2)))


def test_the_grammars_own_readings_are_their_own_normal_form_when_nothing_changes() -> None:
    test = compile_claim("Gross margin is above 70%.")
    assert isinstance(test, ClaimTest)
    assert normal_form(test) == test.canonical


def test_every_labelled_reading_has_a_normal_form_that_is_stable() -> None:
    development, held_out = load_labels(Path("eval/claim-tests.json"))
    newest = Newest(fiscal_year=2026, quarter=(2027, 2))
    for label in (*development, *held_out):
        test = compile_claim(label.claim)
        if not isinstance(test, ClaimTest):
            continue
        once = normalize(test, newest)
        assert normalize(once, newest) == once, label.id  # a normal form is its own
