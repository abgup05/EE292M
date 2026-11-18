"""A part of the company's measures: a segment's revenue, its change, its operating income.

Read from the newest filing's tagged breakdowns, so they have no history. The grammar does
not read a part (its labels say a part's figure is not the company's); a model reader can
name one (:func:`app.core.claim_reading.from_reading`), and the evaluator computes it.
"""

from __future__ import annotations

import pytest

from app.core.breakdown_models import (
    Breakdown,
    BreakdownReport,
    BreakdownRow,
    BreakdownValue,
    FilingInfo,
    PeriodColumn,
)
from app.core.claim_eval import claim_history, evaluate
from app.core.claim_reading import as_reading, from_reading
from app.core.claimtest import ClaimTest, NotNumeric, Number, Period, Term, compile_claim
from app.core.facts import FactBook
from app.core.models import Company
from tests.test_claim_eval import synthetic

FILING = Period("filing")


def part(subject: str, member: str, fn: str = "value", axis: str = "segment") -> Term:
    return Term(fn, subject, FILING, member=member, axis=axis)  # type: ignore[arg-type]


def _value(v: float, change: float | None = None) -> BreakdownValue:
    return BreakdownValue(
        period_start="2025-01-01",
        period_end="2025-12-31",
        value=v,
        unit="USD",
        shown="",
        display="",
        change=change,
        change_display="" if change is None else f"{change:+.1f}%",
        change_formula="" if change is None else "(new − old) ÷ old",
    )


def report() -> BreakdownReport:
    period = PeriodColumn(period_start="2025-01-01", period_end="2025-12-31", label="Fiscal year")

    def breakdown(ident: str, concept: str, rows: dict[str, BreakdownValue]) -> Breakdown:
        return Breakdown(
            id=ident,
            title=ident,
            concept=concept,
            axis="us-gaap:StatementBusinessSegmentsAxis",
            period_kind="fiscal year",
            unit_label="USD millions",
            periods=[period],
            rows=[
                BreakdownRow(member=f"t:{k}Member", label=k, values=[v]) for k, v in rows.items()
            ],
        )

    return BreakdownReport(
        company=Company(cik=1, ticker="TEST", name="Test Corp"),
        filing=FilingInfo(
            form="10-K",
            period_end="2025-12-31",
            filed_date="2026-02-15",
            accession="k-2025",
            url="",
        ),
        breakdowns=[
            breakdown(
                "revenue_by_segment",
                "Revenues",
                {"Data Center": _value(900e6, 68.2), "Gaming": _value(100e6)},
            ),
            breakdown(
                "operating_income_by_segment",
                "OperatingIncomeLoss",
                {"Compute & Networking": _value(600e6, 40.0)},
            ),
        ],
    )


def _run(test: ClaimTest, reports=None):
    payload = synthetic()
    read = [report()] if reports is None else reports
    return evaluate(test, FactBook(payload), calendar=None, reports=read)


def test_a_parts_terms_print_with_their_axis_and_member() -> None:
    assert part("revenue", "Data Center").text() == 'revenue(segment "Data Center")[filing]'
    yoy = part("revenue", "Data Center", "yoy")
    assert yoy.text() == 'yoy(revenue(segment "Data Center"))[filing]'


def test_a_segments_revenue_is_read_from_the_newest_filing() -> None:
    test = ClaimTest("threshold", part("revenue", "Data Center"), ">", Number(500e6, "USD"))

    result = _run(test)

    assert result.outcome == "holds"
    assert result.left.value == 900e6
    assert result.left.inputs[0].accession == "k-2025"
    assert "no history" in result.left.note


def test_its_change_is_the_filings_own_and_missing_when_one_year_is_tagged() -> None:
    grew = ClaimTest(
        "growth_threshold", part("revenue", "Data Center", "yoy"), ">", Number(50, "percent")
    )
    unknown = ClaimTest(
        "growth_threshold", part("revenue", "Gaming", "yoy"), ">", Number(0, "percent")
    )

    assert _run(grew).outcome == "holds"
    assert _run(grew).left.value == pytest.approx(68.2)
    assert _run(unknown).outcome == "cannot_compute"
    assert "year earlier" in _run(unknown).reason


def test_a_segments_operating_income_and_a_missing_member() -> None:
    income = ClaimTest(
        "threshold", part("operating_income", "Compute & Networking"), ">", Number(1e9, "USD")
    )
    missing = ClaimTest("threshold", part("revenue", "Automotive"), ">", Number(1, "USD"))

    assert _run(income).outcome == "fails"
    assert _run(missing).outcome == "cannot_compute"
    assert "Automotive" in _run(missing).reason
    assert _run(income, reports=[]).outcome == "cannot_compute"


def test_a_part_has_no_history() -> None:
    test = ClaimTest("threshold", part("revenue", "Data Center"), ">", Number(1, "USD"))

    points, note = claim_history(test, synthetic())

    assert points == [] and "no history" in note


def test_a_model_reading_can_name_a_part_and_the_grammar_still_does_not() -> None:
    test = ClaimTest(
        "growth_threshold", part("revenue", "data center", "yoy"), ">", Number(50, "percent")
    )

    read = from_reading(as_reading(test))

    assert isinstance(read, ClaimTest)
    assert read.canonical == 'yoy(revenue(segment "Data Center"))[filing] > 50%'
    assert isinstance(compile_claim("Data Center revenue grew more than 50%."), NotNumeric)
    for wrong in (
        part("rnd", "Data Center"),
        Term("value", "revenue", Period("Q"), member="Data Center", axis="segment"),
        part("revenue", "Data Center", axis="customer"),
    ):
        bad = ClaimTest("threshold", wrong, ">", Number(1, "USD"))
        assert isinstance(from_reading(as_reading(bad)), NotNumeric)


# A segment's operating income: a breakdown only a claim test reads


def test_the_recorded_nvidia_10k_tags_each_segments_operating_income_for_claims_only() -> None:
    from app.core.breakdowns import CLAIM_SPECS, SPECS, build_report
    from app.sources.ixbrl import read_tagged_facts
    from tests.fakes import FY_2026, NVIDIA, recorded_html
    from tests.test_breakdowns import info

    facts = read_tagged_facts(recorded_html("nvda-10k-20260125.htm.gz"))
    shown = build_report(facts, company=NVIDIA, filing=info(FY_2026))
    both = (*SPECS, *CLAIM_SPECS)
    for_claims = build_report(facts, company=NVIDIA, filing=info(FY_2026), specs=both)

    assert "operating_income_by_segment" not in [b.id for b in shown.breakdowns]
    [income] = [b for b in for_claims.breakdowns if b.id == "operating_income_by_segment"]
    labels = {row.label: row.values[0].value for row in income.rows}
    assert labels["Compute and Networking Segment"] > labels["Graphics Segment"] > 0
    test = ClaimTest(
        "threshold", part("operating_income", "Compute & Networking"), ">", Number(1e9, "USD")
    )
    result = _run(test, reports=[for_claims])
    assert result.outcome == "holds" and result.left.inputs[0].accession == FY_2026.accession
    assert for_claims.breakdowns[: len(shown.breakdowns)] == shown.breakdowns
