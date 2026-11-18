"""The forms added from the "form" and "period" refusals of sets A and B.

- each: a test held in each of the last N quarters or fiscal years, or every year since a
  named one;
- change: growth between two periods (two named fiscal years, since a year, over N years);
- compare: the levels of two different measures in one period;
- a conjunction: two tests that both hold;
- a share, or a part's figure, for the fiscal year or quarter a newest filing reports.

Each composed outcome is checked against its parts evaluated alone, on NVIDIA's recorded
facts and recorded 10-K and 10-Q tags; the golden results (``eval/claim-results.json``)
check the values by the independent route.
"""

from __future__ import annotations

import gzip
from datetime import date

import pytest

from app.core.breakdown_models import FilingInfo
from app.core.breakdowns import build_report
from app.core.claim_eval import claim_history, evaluate
from app.core.claim_normal import Newest, normal_form
from app.core.claim_reading import as_reading, from_reading
from app.core.claimtest import ClaimTest, NotNumeric, Number, Period, Term, compile_claim
from app.core.facts import FactBook
from app.core.periods import fiscal_calendar
from app.evaluation.claim_oracle import load_payload, recorded_report
from app.sources.ixbrl import read_tagged_facts
from tests.fakes import EDGAR, NVIDIA
from tests.lookahead import late_refs

Q, FY = Period("Q"), Period("FY")


def v(subject: str, period: Period = Q) -> Term:
    return Term("value", subject, period)


def pct(value: float) -> Number:
    return Number(value, "percent")


@pytest.fixture(scope="module")
def payload():
    return load_payload("NVDA")


def run(test: ClaimTest, payload, as_of: date | None = None, reports=()):
    return evaluate(
        test,
        FactBook(payload, as_of=as_of),
        calendar=fiscal_calendar(payload, as_of=as_of),
        reports=reports,
    )


def back(period: Period, steps: int) -> Period:
    for _ in range(steps):
        period = period.step_back()
    return period


# Canonical texts


def test_each_new_form_prints_one_canonical_text() -> None:
    each = ClaimTest("threshold", v("gross_margin"), ">", pct(70), each=4)
    assert each.canonical == "each(4): gross_margin[Q] > 70%"
    since = ClaimTest(
        "direction",
        v("free_cash_flow", FY),
        ">",
        v("free_cash_flow", Period("FY", 1)),
        each_since=2023,
    )
    assert since.canonical == "each(since FY2023): free_cash_flow[FY] > free_cash_flow[FY-1]"
    change = Term(
        "change", "revenue", Period("FY", fiscal_year=2025), base=Period("FY", fiscal_year=2023)
    )
    assert change.text() == "change(revenue, FY2023)[FY2025]"
    compare = ClaimTest("compare", v("operating_cash_flow", FY), ">", v("net_income", FY))
    assert compare.canonical == "operating_cash_flow[FY] > net_income[FY]"
    both = ClaimTest("threshold", v("gross_margin"), ">", pct(70), also=compare)
    assert both.canonical == (
        "(gross_margin[Q] > 70%) and (operating_cash_flow[FY] > net_income[FY])"
    )


# each


def test_each_holds_only_when_every_period_holds(payload) -> None:
    for threshold in (60, 70, 75):
        test = ClaimTest("threshold", v("gross_margin"), ">", pct(threshold), each=4)
        alone = [
            run(ClaimTest("threshold", v("gross_margin", back(Q, k)), ">", pct(threshold)), payload)
            for k in range(4)
        ]
        result = run(test, payload)
        assert result.combines == "each" and len(result.parts) == 4
        assert [p.bound for p in result.parts] == [a.bound for a in alone]
        outcomes = {a.outcome for a in alone}
        expected = "fails" if "fails" in outcomes else "cannot_compute"
        if outcomes == {"holds"}:
            expected = "holds"
        assert result.outcome == expected
        assert result.left == alone[0].left  # the newest period's sides
        assert result.counted_as == {"holds": "supports", "fails": "challenges"}.get(
            result.outcome, ""
        )


def test_each_since_a_named_year_counts_the_years_after_it(payload) -> None:
    rise = ClaimTest(
        "direction", v("revenue", FY), ">", v("revenue", Period("FY", 1)), each_since=2023
    )
    result = run(rise, payload)
    newest = run(ClaimTest("threshold", v("revenue", FY), ">", Number(0, "USD")), payload)
    year = int(newest.bound.split("[FY")[1].split("]")[0])
    assert len(result.parts) == year - 2023
    assert result.parts[-1].bound == "revenue[FY2024] > revenue[FY2023]"


def test_each_reads_nothing_filed_after_its_date(payload) -> None:
    day = date(2025, 6, 1)
    test = ClaimTest("threshold", v("gross_margin"), ">", pct(60), each=4)
    result = run(test, payload, as_of=day)
    assert late_refs(result, day) == []
    assert all(late_refs(part, day) == [] for part in result.parts)


# change between two periods


def test_change_between_two_named_years_is_the_growth_from_one_to_the_other(payload) -> None:
    span = Term(
        "change", "revenue", Period("FY", fiscal_year=2025), base=Period("FY", fiscal_year=2023)
    )
    result = run(ClaimTest("growth_threshold", span, ">", pct(100)), payload)
    now = run(
        ClaimTest("threshold", v("revenue", Period("FY", fiscal_year=2025)), ">", Number(0, "USD")),
        payload,
    ).left.value
    then = run(
        ClaimTest("threshold", v("revenue", Period("FY", fiscal_year=2023)), ">", Number(0, "USD")),
        payload,
    ).left.value
    assert result.left.value == pytest.approx((now - then) / then * 100)
    assert result.bound == "change(revenue, FY2023)[FY2025] > 100%"


def test_a_change_whose_base_is_not_earlier_cannot_be_computed(payload) -> None:
    span = Term(
        "change", "revenue", Period("FY", fiscal_year=2023), base=Period("FY", fiscal_year=2025)
    )
    result = run(ClaimTest("growth_threshold", span, ">", pct(0)), payload)
    assert result.outcome == "cannot_compute" and "earlier" in result.reason


# compare


def test_compare_reads_two_measures_of_one_period(payload) -> None:
    test = ClaimTest("compare", v("operating_cash_flow", FY), ">", v("net_income", FY))
    result = run(test, payload)
    ocf = run(ClaimTest("threshold", v("operating_cash_flow", FY), ">", Number(0, "USD")), payload)
    income = run(ClaimTest("threshold", v("net_income", FY), ">", Number(0, "USD")), payload)
    assert result.left.value == ocf.left.value and result.right.value == income.left.value
    assert result.outcome == ("holds" if ocf.left.value > income.left.value else "fails")


# a conjunction


def test_a_conjunction_holds_when_both_hold_and_fails_when_either_fails(payload) -> None:
    high = ClaimTest("threshold", v("gross_margin"), ">", pct(10))
    low = ClaimTest("threshold", v("gross_margin"), "<", pct(10))
    unknown = ClaimTest("threshold", v("inventory", Period("Q", 200)), ">", Number(1, "USD"))
    cases = [
        (high, high, "holds"),
        (high, low, "fails"),
        (unknown, low, "fails"),
        (high, unknown, "cannot_compute"),
    ]
    for first, second, outcome in cases:
        both = ClaimTest(first.form, first.left, first.op, first.right, also=second)
        result = run(both, payload)
        assert result.outcome == outcome, (first.canonical, second.canonical)
        assert result.combines == "and" and len(result.parts) == 2
        assert result.parts[1].canonical == second.canonical
        operands = {o.term for o in result.operands}
        assert {o.term for p in result.parts for o in p.operands} <= operands


def test_a_conjunction_has_a_history_point_per_filing(payload) -> None:
    high = ClaimTest("threshold", v("gross_margin"), ">", pct(10))
    rise = ClaimTest("direction", v("revenue"), ">", v("revenue", Period("Q", 4)))
    both = ClaimTest(high.form, high.left, high.op, high.right, also=rise)
    points, note = claim_history(both, payload, as_of=date(2026, 9, 1))
    alone, _ = claim_history(rise, payload, as_of=date(2026, 9, 1))
    assert len(points) == len(alone) > 4
    assert "and" in points[-1].bound


# a share, or a part, for a period the newest filing reports


@pytest.fixture(scope="module")
def annual_report():
    html = gzip.decompress((EDGAR / "nvda-10k-20260125.htm.gz").read_bytes()).decode("utf-8")
    return build_report(
        read_tagged_facts(html),
        company=NVIDIA,
        filing=FilingInfo(
            form="10-K",
            period_end="2026-01-25",
            filed_date="2026-02-25",
            accession="0001045810-26-000021",
            url="",
        ),
    )


def share(period: Period) -> ClaimTest:
    return ClaimTest("share", Term("share", "segment", period, member="Data Center"), ">", pct(80))


def test_a_share_for_the_fiscal_year_reads_the_10k_column_for_that_year(
    payload, annual_report
) -> None:
    reports = [recorded_report(), annual_report]
    newest = run(share(Period("filing")), payload, reports=reports)
    latest_year = run(share(FY), payload, reports=reports)
    named = run(share(Period("FY", fiscal_year=2026)), payload, reports=reports)
    year_before = run(share(Period("FY", fiscal_year=2025)), payload, reports=reports)
    assert newest.left.inputs[0].form == "10-Q"  # the newest filing is the quarter's
    assert latest_year.left.inputs[0].form == "10-K"
    assert latest_year.left.inputs[0].end == "2026-01-25"
    assert named.left.value == latest_year.left.value
    assert year_before.left.inputs[0].end == "2025-01-26"
    assert year_before.left.value != latest_year.left.value


def test_a_share_for_a_period_no_filing_read_reports_says_which_it_has(
    payload, annual_report
) -> None:
    result = run(share(Period("FY", fiscal_year=2022)), payload, reports=[annual_report])
    assert result.outcome == "cannot_compute"
    assert "FY2022" in result.reason and "2026-01-25" in result.reason


def test_a_share_for_the_latest_quarter_reads_the_10q(payload) -> None:
    result = run(share(Q), payload, reports=[recorded_report()])
    assert result.left.inputs[0].end == "2026-07-26" and result.outcome != "cannot_compute"


# The readers' schema and the normal form


NEW_FORMS = [
    ClaimTest("threshold", v("gross_margin"), ">", pct(70), each=4),
    ClaimTest("direction", v("revenue", FY), ">", v("revenue", Period("FY", 1)), each_since=2022),
    ClaimTest(
        "growth_threshold",
        Term("change", "revenue", Period("FY"), base=Period("FY", 3)),
        ">=",
        pct(200),
    ),
    ClaimTest("compare", v("operating_cash_flow", FY), ">", v("net_income", FY)),
    ClaimTest(
        "threshold",
        v("gross_margin"),
        ">",
        pct(70),
        also=ClaimTest("growth_threshold", Term("yoy", "revenue", Q), ">", pct(50)),
    ),
    share(Period("FY", fiscal_year=2026)),
    ClaimTest(
        "threshold",
        Term("value", "revenue", FY, member="Data Center", axis="segment"),
        ">",
        Number(1e11, "USD"),
    ),
]


@pytest.mark.parametrize("test", NEW_FORMS, ids=[t.canonical for t in NEW_FORMS])
def test_every_new_form_survives_the_readers_json(test: ClaimTest) -> None:
    assert from_reading(as_reading(test)) == test


@pytest.mark.parametrize(
    "bad",
    [
        ClaimTest(
            "share", Term("share", "segment", Period("filing"), member="X"), ">", pct(1), each=3
        ),
        ClaimTest("threshold", v("gross_margin", FY), ">", pct(1), each_since=2022),
        ClaimTest("compare", v("revenue", FY), ">", v("revenue", Period("FY", 1))),
        ClaimTest("compare", v("revenue", FY), ">", v("gross_margin", FY)),
        ClaimTest("compare", v("revenue", FY), ">", v("cash", FY)),
        ClaimTest("threshold", v("revenue", Period("TTM")), ">", Number(1, "USD"), each=2),
        ClaimTest("threshold", v("revenue"), ">", Number(1, "USD"), each=1),
        ClaimTest(
            "growth_threshold",
            Term("change", "gross_margin", FY, base=Period("FY", 2)),
            ">",
            pct(1),
        ),
    ],
    ids=[
        "each share",
        "each since a level",
        "compare one measure",
        "compare units",
        "compare flow and balance",
        "each ttm",
        "each of one",
        "change of a ratio",
    ],
)
def test_the_readers_json_refuses_what_the_forms_do_not_allow(bad: ClaimTest) -> None:
    assert isinstance(from_reading(as_reading(bad)), NotNumeric)


def test_a_nested_conjunction_is_refused() -> None:
    inner = ClaimTest("threshold", v("gross_margin"), ">", pct(70))
    middle = ClaimTest("threshold", v("net_margin"), ">", pct(10), also=inner)
    outer = ClaimTest("threshold", v("operating_margin"), ">", pct(10))
    reading = as_reading(outer)
    reading["test"]["and_test"] = as_reading(middle)["test"]
    assert isinstance(from_reading(reading), NotNumeric)


def test_the_normal_form_of_the_new_forms() -> None:
    yoy = ClaimTest("growth_threshold", Term("yoy", "revenue", FY), ">", pct(20))
    one_year = ClaimTest(
        "growth_threshold", Term("change", "revenue", FY, base=Period("FY", 1)), ">", pct(20)
    )
    assert normal_form(yoy) == normal_form(one_year)
    rise = ClaimTest("direction", v("revenue", FY), ">", v("revenue", Period("FY", 3)))
    zero = ClaimTest(
        "growth_threshold", Term("change", "revenue", FY, base=Period("FY", 3)), ">", pct(0)
    )
    assert normal_form(rise) == normal_form(zero)
    rises = ClaimTest("direction", v("revenue"), ">", v("revenue", Period("Q", 1)), each=4)
    streak = ClaimTest("streak", Term("streak", "revenue", Q), ">=", Number(4, "count"))
    assert normal_form(rises) == normal_form(streak)
    since = ClaimTest(
        "direction", v("revenue", FY), ">", v("revenue", Period("FY", 1)), each_since=2022
    )
    years = ClaimTest("streak", Term("streak", "revenue", FY), ">=", Number(4, "count"))
    assert normal_form(since, Newest(fiscal_year=2026)) == normal_form(years)
    once = ClaimTest("threshold", v("gross_margin"), ">", pct(70))
    assert normal_form(ClaimTest(once.form, once.left, once.op, once.right, each=1)) == (
        normal_form(once)
    )
    a = ClaimTest("compare", v("operating_cash_flow", FY), ">", v("net_income", FY))
    b = ClaimTest("compare", v("net_income", FY), "<", v("operating_cash_flow", FY))
    assert normal_form(a) == normal_form(b)
    first = ClaimTest(once.form, once.left, once.op, once.right, also=a)
    second = ClaimTest(a.form, a.left, a.op, a.right, also=once)
    assert normal_form(first) == normal_form(second)


# A run: the filing's tags are read when any part of a test needs them


def test_a_run_reads_the_tags_for_a_share_in_the_second_part_of_an_and(tmp_path) -> None:
    from tests.test_reading_rule import _readers, _run

    claim = "The company is doing well on two counts."
    both = ClaimTest(
        "threshold", v("gross_margin"), ">", pct(10), also=share(Period("FY", fiscal_year=2026))
    )
    reading = as_reading(both)
    run = _run(tmp_path, [claim], _readers({claim: reading}, {claim: reading}))

    computed = run.claims[0].computed
    assert computed is not None and computed.combines == "and"
    second = computed.parts[1]
    assert second.outcome != "cannot_compute", second.reason
    assert second.left is not None and second.left.inputs[0].form == "10-K"
    assert computed.history == [] and computed.history_note


# The grammar: the new forms it reads, whole sentence only


READS = [
    # each of the last N periods
    (
        "Gross margin has stayed above 70% for the last four quarters.",
        "each(4): gross_margin[Q] > 70%",
    ),
    (
        "Operating margin has been above 30% in each of the last three fiscal years.",
        "each(3): operating_margin[FY] > 30%",
    ),
    (
        "Capital expenditures have grown by at least 50% in each of the last two years.",
        "each(2): yoy(capex)[FY] >= 50%",
    ),
    (
        "Net income grew faster than revenue in each of the last two fiscal years.",
        "each(2): yoy(net_income)[FY] > yoy(revenue)[FY]",
    ),
    (
        "The diluted share count has shrunk every year for the past five years.",
        "each(5): diluted_shares[FY] < diluted_shares[FY-1]",
    ),
    (
        "Free cash flow has risen every year since fiscal 2023.",
        "each(since FY2023): free_cash_flow[FY] > free_cash_flow[FY-1]",
    ),
    (
        "Dividends paid have gone up every year since fiscal 2021.",
        "each(since FY2021): dividends_paid[FY] > dividends_paid[FY-1]",
    ),
    (
        "Net sales rose in fiscal 2025 for the second consecutive year.",
        "each(2): revenue[FY2025] > revenue[FY2024]",
    ),
    (
        "Gross margin was above 70% in each quarter of fiscal 2026.",
        "each(4): gross_margin[Q4 FY2026] > 70%",
    ),
    # rises sequentially in each period stay a streak
    ("Revenue grew sequentially in each of the last four quarters.", "streak(revenue)[Q] >= 4"),
    # a change over a span, and multiples
    (
        "Diluted EPS was more than three times its fiscal 2023 level.",
        "change(eps_diluted, FY2023)[FY] > 200%",
    ),
    (
        "Total assets more than tripled over the past three fiscal years.",
        "change(total_assets, FY-3)[FY] > 200%",
    ),
    (
        "Revenue grew more than 100% between fiscal 2023 and fiscal 2025.",
        "change(revenue, FY2023)[FY2025] > 100%",
    ),
    (
        "Capex more than doubled between fiscal 2022 and fiscal 2024.",
        "change(capex, FY2022)[FY2024] > 100%",
    ),
    ("Revenue has more than doubled since fiscal 2023.", "change(revenue, FY2023)[FY] > 100%"),
    (
        "Revenue quadrupled from fiscal 2023 to fiscal 2025.",
        "change(revenue, FY2023)[FY2025] >= 300%",
    ),
    ("Revenue rose between fiscal 2023 and fiscal 2025.", "revenue[FY2025] > revenue[FY2023]"),
    (
        "Net sales compounded at less than 3% a year from fiscal 2022 to fiscal 2025.",
        "cagr(revenue, 3y)[FY2025] < 3%",
    ),
    ("NVIDIA's revenue more than doubled in fiscal 2024.", "yoy(revenue)[FY2024] > 100%"),
    # two measures compared
    (
        "Operating cash flow was above net income in the latest fiscal year.",
        "operating_cash_flow[FY] > net_income[FY]",
    ),
    (
        "Cash and short-term investments exceed total debt.",
        "cash_and_securities[Q] > total_debt[Q]",
    ),
    # a share for a period the filing reports
    (
        "Data Center revenue made up over 80% of total revenue last fiscal year.",
        'share(segment "Data Center")[FY] > 80%',
    ),
    (
        "Services made up more than a quarter of total net sales last year.",
        'share(segment "Services")[FY] > 25%',
    ),
    (
        "Data Center accounts for more than 80% of revenue in fiscal 2026.",
        'share(segment "Data Center")[FY2026] > 80%',
    ),
    ("Data Center is more than 80% of revenue.", 'share(segment "Data Center")[filing] > 80%'),
    # two tests joined by "and"
    (
        "Revenue grew more than 50% year over year and gross margin is above 70%.",
        "(yoy(revenue)[Q] > 50%) and (gross_margin[Q] > 70%)",
    ),
    (
        "Revenue rose in fiscal 2025 and net income rose in fiscal 2025.",
        "(revenue[FY2025] > revenue[FY2024]) and (net_income[FY2025] > net_income[FY2024])",
    ),
    # an "and" inside a name is not two tests
    ("Research and development expense rose year over year.", "rnd[Q] > rnd[Q-4]"),
]


@pytest.mark.parametrize(("claim", "canonical"), READS, ids=[c for c, _ in READS])
def test_the_grammar_reads_the_new_forms(claim: str, canonical: str) -> None:
    test = compile_claim(claim)
    assert isinstance(test, ClaimTest), test
    assert test.canonical == canonical


REFUSES = [
    # "grew in each quarter": on the quarter before, or on a year earlier?
    "Revenue grew in each of the last four quarters.",
    # since a year, for a level: is the named year itself held?
    "Operating margin has been above 30% every year since fiscal 2022.",
    # a change in a percentage: points or percent?
    "Gross margin more than doubled since fiscal 2023.",
    # a sum of members, not one member (set B, g046)
    "Japan and Rest of Asia Pacific together are less than 15% of net sales.",
    "Mac and iPad combined are more than 15% of net sales.",
    # a share with words after it that name no period
    "Data Center revenue made up over 80% of total revenue, a record.",
    # contrast words are still two statements
    "Revenue grew more than 50%, but gross margin fell.",
    "Inventory has grown, but more slowly than revenue.",
    # a period named in one part only may be meant for both
    "Revenue grew and gross margin was above 70% in fiscal 2025.",
    # a half that is not a test
    "Inventory is under $10 billion and has barely moved in three years.",
    # growth words make a comparison of two measures ambiguous
    "Operating income grew more than revenue.",
    # two measures of different kinds
    "Revenue is above gross margin.",
    # each of more periods than the limit
    "Gross margin has stayed above 70% for the last twenty quarters.",
]


@pytest.mark.parametrize("claim", REFUSES)
def test_the_grammar_still_refuses(claim: str) -> None:
    assert isinstance(compile_claim(claim), NotNumeric), compile_claim(claim)


# The model readers' prompt names every form and field the schema allows


def test_the_readers_prompt_explains_the_new_forms_and_fields() -> None:
    from app.core.claim_reading import READING_SCHEMA
    from app.engines.claim_reader import READ_SYSTEM

    test = READING_SCHEMA["properties"]["test"]["anyOf"][0]["properties"]
    term = test["left"]["properties"]
    for field in ("each", "each_since", "and_test"):
        assert field in test and f"{field}:" in READ_SYSTEM, field
    assert "base" in term and "base:" in READ_SYSTEM
    for form in ("compare", "change"):
        assert f"- {form}:" in READ_SYSTEM or f"fn {form}" in READ_SYSTEM, form
    assert "a part's figure at any period other than the newest filing" not in READ_SYSTEM
    assert "period kind FY" in READ_SYSTEM  # a share or a part of a named fiscal year
