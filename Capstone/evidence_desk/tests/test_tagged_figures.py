"""Tagged figures: a filing's own segment, geography and customer numbers offered to the engine.

Opt-in per run (``ThesisRequest.tagged_figures``). With the option on, the
newest annual and quarterly report the run read are read again for their
inline XBRL, their breakdowns become figures a finding can cite by id, and the
gate checks a statement's numbers against them by the same rules as any
figure. With it off nothing changes (the tripwire, ``tests/test_golden.py``,
holds the whole example run to that). Every test here is offline: the NVIDIA
filings are the recorded ones in ``tests/fixtures/edgar``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core import limits, policy
from app.core.breakdown_models import BreakdownReport
from app.core.breakdowns import build_report
from app.core.documents import FetchedFiling, FilingRef, Passage
from app.core.facts import FactBook
from app.core.metric_models import Metric
from app.core.metrics import build_report as metrics_report
from app.core.models import Confidence, Run, RunStatus, Stance, ThesisRequest, Verdict
from app.core.ports import ClaimDraft, FindingDraft, Quote, SourceError
from app.core.tagged_figures import TAGGED_PREFIX, select_tagged, tagged_units
from app.services.breakdowns import filing_info
from app.services.examples import EXAMPLE_THESIS
from app.services.export import render_markdown
from app.services.numbers import select_figures
from app.services.thesis_run import execute_run, new_run
from app.sources.ixbrl import read_tagged_facts
from app.store import Store
from tests import replay_run
from tests.fakes import (
    FY_2026,
    NVIDIA,
    Q2_2027,
    RECORDED,
    FakeFilings,
    FakePages,
    ManualClock,
    ScriptedAnalyst,
    filing_html,
    recorded_facts,
    recorded_html,
)
from tests.replay_run import DEFAULT_CASSETTE

DECISION = "Whether to keep an overweight position in NVIDIA into the next earnings report"
GROWTH = "Data center revenue is still growing year over year."
GROWTH_SENTENCE = (
    "Data Center revenue grew 56% from a year ago, driven by demand for our Blackwell platform."
)

DATA_CENTER = f"{TAGGED_PREFIX}revenue_by_product:nvda:DataCenterMember:annual:2026-01-25"
DATA_CENTER_CHANGE = (
    f"{TAGGED_PREFIX}revenue_by_product:nvda:DataCenterMember:change:annual:2026-01-25"
)
COMPUTE_CHANGE = f"{TAGGED_PREFIX}revenue_by_product:nvda:ComputeMember:change:annual:2026-01-25"
CHINA = f"{TAGGED_PREFIX}revenue_by_geography:nvda:ChinaIncludingHongKongMember:annual:2026-01-25"


def request(*claims: str, tagged: bool = True, filings: int = 2) -> ThesisRequest:
    return ThesisRequest(
        ticker="NVDA",
        decision=DECISION,
        claims=list(claims),
        filings=filings,
        tagged_figures=tagged,
    )


def run_with(store: Store, thesis: ThesisRequest, filings: FakeFilings, analyst: object) -> Run:
    return execute_run(
        new_run(thesis),
        store,
        filings=filings,
        analyst=analyst,  # type: ignore[arg-type]
        fetch_page=FakePages({}),
        clock=ManualClock(),
    )


def tagged(figures: list[Metric]) -> list[Metric]:
    return [figure for figure in figures if figure.key.startswith(TAGGED_PREFIX)]


# The request


def test_the_option_is_off_by_default_strict_and_unknown_fields_are_refused() -> None:
    assert EXAMPLE_THESIS.tagged_figures is False
    assert request(GROWTH, tagged=True).tagged_figures is True
    with pytest.raises(ValidationError):
        ThesisRequest.model_validate(
            {"ticker": "NVDA", "decision": DECISION, "claims": [GROWTH], "tagged_figures": "yes"}
        )
    with pytest.raises(ValidationError):
        ThesisRequest.model_validate(
            {"ticker": "NVDA", "decision": DECISION, "claims": [GROWTH], "tagged_figure": True}
        )


# (a) Off: nothing is fetched again and nothing is offered beyond the company-facts figures


def test_with_the_option_off_no_filing_is_read_again_and_no_tagged_figure_is_offered(
    tmp_path: Path,
) -> None:
    filings = FakeFilings.synthetic(filing_html(GROWTH_SENTENCE))
    analyst = ScriptedAnalyst()
    thesis = request(GROWTH, tagged=False, filings=1)
    run = run_with(Store(tmp_path / "r.sqlite"), thesis, filings, analyst)
    assert len(filings.fetched) == 1
    assert run.coverage.tagged_figures_offered == 0
    assert tagged(run.metrics) == [] and tagged(analyst.figures[GROWTH]) == []
    assert [f.id for f in analyst.figures[GROWTH]] == [f.id for f in select_figures_of(run)]
    assert not any("tagged" in limit for limit in run.coverage_limits)


def select_figures_of(run: Run) -> list[Metric]:
    """The company-facts figures a run on the recorded facts offers."""
    return select_figures(metrics_report(FactBook(recorded_facts())))


# (b) On, on the recorded filings: what is offered, stable, capped, deterministic


@pytest.fixture(scope="module")
def reports() -> list[BreakdownReport]:
    """The breakdowns of the recorded 10-Q (2026-07-26) and 10-K (2026-01-25), newest first."""
    return [
        build_report(
            read_tagged_facts(recorded_html(RECORDED[ref.url])),
            company=NVIDIA,
            filing=filing_info(ref),
        )
        for ref in (Q2_2027, FY_2026)
    ]


def _figure_only(statement: str, metric_id: str) -> FindingDraft:
    return FindingDraft(
        statement=statement,
        stance=Stance.supports,
        quotes=[],
        confidence=Confidence.medium,
        rationale="Scripted.",
        metric_ids=[metric_id],
    )


def _four_findings(claim: object, passages: list[Passage]) -> ClaimDraft:
    """(c) one honest figure-only finding, two wrong ones; (d) one with a quote and a figure."""
    first = passages[0]
    quote = first.text.split("\n")[0][:300]
    return ClaimDraft(
        findings=[
            _figure_only("Data Center revenue grew 68% in fiscal 2026.", DATA_CENTER_CHANGE),
            _figure_only("Data Center revenue grew 86% in fiscal 2026.", DATA_CENTER_CHANGE),
            _figure_only("Data Center revenue grew 68% in fiscal 2026.", COMPUTE_CHANGE),
            FindingDraft(
                statement="Data Center revenue grew 68% in fiscal 2026.",
                stance=Stance.supports,
                quotes=[Quote(first.id, quote)],
                confidence=Confidence.high,
                rationale="Scripted.",
                metric_ids=[DATA_CENTER_CHANGE],
            ),
        ],
        rationale="Assessed.",
    )


@pytest.fixture(scope="module")
def two_runs(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[tuple[Run, ScriptedAnalyst], tuple[Run, ScriptedAnalyst]]:
    """The same tagged run twice on the recorded 10-Q and 10-K, with the scripted findings."""
    out = []
    for name in ("first", "second"):
        store = Store(tmp_path_factory.mktemp(name) / "r.sqlite")
        analyst = ScriptedAnalyst(_four_findings)
        filings = FakeFilings.nvidia(Q2_2027, FY_2026)
        out.append((run_with(store, request(GROWTH), filings, analyst), analyst))
    return out[0], out[1]


def test_the_tagged_figures_offered_include_data_center_and_china(two_runs) -> None:
    (run, analyst), _ = two_runs
    offered = {figure.id: figure for figure in tagged(analyst.figures[GROWTH])}
    value, change, china = offered[DATA_CENTER], offered[DATA_CENTER_CHANGE], offered[CHINA]
    assert value.value == pytest.approx(193_737e6) and value.unit == "USD"
    assert value.period == "annual" and value.period_end == "2026-01-25"
    assert "Data Center" in value.label and "10-K" in value.label
    assert "nvda:DataCenterMember" in value.label and "2026-01-25" in value.label
    assert value.key == f"{TAGGED_PREFIX}revenue_by_product:nvda:DataCenterMember"
    assert change.value == pytest.approx(68.2, abs=0.05) and change.unit == "percent"
    assert change.display == "+68.2%" and "193,737" in change.formula
    assert "derived from" in value.note and "tag name" in value.note
    assert china.value == pytest.approx(19_677e6) and "China" in china.label


def test_the_tagged_figures_come_after_the_company_facts_and_are_recorded(two_runs) -> None:
    (run, analyst), _ = two_runs
    figures = analyst.figures[GROWTH]
    first_tagged = next(i for i, f in enumerate(figures) if f.key.startswith(TAGGED_PREFIX))
    assert all(f.key.startswith(TAGGED_PREFIX) for f in figures[first_tagged:])
    assert first_tagged == run.coverage.figures_offered > 0
    assert run.coverage.tagged_figures_offered == len(figures) - first_tagged
    assert [m.id for m in tagged(run.metrics)] == [f.id for f in figures[first_tagged:]]


def test_ids_and_keys_are_stable_across_runs(two_runs) -> None:
    (first, a), (second, b) = two_runs
    assert tagged(a.figures[GROWTH]), "the runs offered tagged figures"
    assert [(f.id, f.key) for f in a.figures[GROWTH]] == [(f.id, f.key) for f in b.figures[GROWTH]]
    assert first.metrics == second.metrics


def test_the_cap_holds_and_the_selection_prefers_the_largest_members(
    reports: list[BreakdownReport],
) -> None:
    units, _ = tagged_units(reports)
    built = sum(len(unit.figures) for unit in units)
    chosen, notes = select_tagged(units)
    assert built > limits.MAX_TAGGED_FIGURES_OFFERED >= len(chosen) > 0
    kept = {figure.id for figure in chosen}
    taken = [unit for unit in units if unit.figures[0].id in kept]
    left = [unit for unit in units if unit.figures[0].id not in kept]
    # No member is left out while a smaller one of the same breakdown is offered, and a value
    # is never offered without its change.
    assert max(unit.rank for unit in taken) <= min(unit.rank for unit in left)
    assert all(all(f.id in kept for f in unit.figures) for unit in taken)
    assert any(str(built) in note and str(len(chosen)) in note for note in notes)
    assert select_tagged(list(reversed(units)))[0] == chosen


def test_the_change_figure_carries_both_reported_values(reports: list[BreakdownReport]) -> None:
    units, _ = tagged_units(reports)
    [change] = [f for unit in units for f in unit.figures if f.id == DATA_CENTER_CHANGE]
    assert [ref.value for ref in change.inputs] == [193_737e6, 115_186e6]
    assert {ref.accession for ref in change.inputs} == {FY_2026.accession}


def test_a_share_tagged_as_a_fraction_is_offered_as_a_percentage(
    reports: list[BreakdownReport],
) -> None:
    """The filing tags a customer's share as 0.22; a statement and its quote say 22%.

    A planted fault (the fraction offered as 0.22%) passed every test of this module on
    17 November 2026 and was caught only by the replay, so this pins the conversion here.
    """
    units, _ = tagged_units(reports)
    shares = {
        figure.id: figure
        for unit in units
        for figure in unit.figures
        if figure.id.startswith(f"{TAGGED_PREFIX}revenue_concentration_by_customer:")
        and figure.id.endswith(":annual:2026-01-25")
    }
    assert sorted(figure.value for figure in shares.values()) == pytest.approx([14.0, 22.0])
    assert {figure.unit for figure in shares.values()} == {"percent"}
    assert sorted(figure.display for figure in shares.values()) == ["14.0%", "22.0%"]
    # The fact it was read from is kept as tagged, a fraction, so the two can be compared.
    assert sorted(figure.inputs[0].value for figure in shares.values()) == [0.14, 0.22]


def test_a_year_to_date_breakdown_is_left_out_and_said_so(reports: list[BreakdownReport]) -> None:
    units, notes = tagged_units(reports)
    ids = [figure.id for unit in units for figure in unit.figures]
    assert not any(i.startswith(f"{TAGGED_PREFIX}receivables_") and "2026-07-26" in i for i in ids)
    assert any("year to date" in note for note in notes)


# (c) The number check against a cited tagged figure; (d) a quote and a figure together


def test_a_figure_only_finding_with_the_tagged_change_is_verified(two_runs) -> None:
    (run, _), _ = two_runs
    honest = run.findings[0]
    assert honest.statement == "Data Center revenue grew 68% in fiscal 2026."
    assert honest.verified and honest.metric_ids == [DATA_CENTER_CHANGE]
    assert honest.checks.numbers == "passed" and honest.evidence_ids == []
    assert honest.checks.numbers_detail[0].startswith("68% matched +68.2%")
    # Figure-only and unchecked: it counts as context, as any figure-only finding does.
    assert honest.counted_as == Stance.context and honest.count_note == policy.FIGURE_ONLY_NOTE


def test_a_wrong_number_or_another_members_figure_is_withheld_naming_the_number(
    two_runs,
) -> None:
    (run, _), _ = two_runs
    wrong, other = run.unsupported_findings
    assert wrong.withheld_reason == (
        "a number in the statement is not in its quotes or cited figures: 86%"
    )
    assert other.metric_ids == [COMPUTE_CHANGE]
    assert other.withheld_reason == (
        "a number in the statement is not in its quotes or cited figures: 68%"
    )


def test_a_finding_with_a_quote_and_a_tagged_figure_records_both(two_runs) -> None:
    (run, _), _ = two_runs
    both = run.findings[1]
    assert both.verified and both.checks.quotes == "passed"
    assert len(both.evidence_ids) == 1 and both.metric_ids == [DATA_CENTER_CHANGE]
    assert both.counted_as == Stance.supports
    assert run.claims[0].verdict == Verdict.supported
    assert run.coverage.figures_cited == 2


# (f) The Markdown brief


def test_the_brief_lists_a_cited_tagged_figure_with_its_label_and_formula(two_runs) -> None:
    (run, _), _ = two_runs
    [change] = [m for m in run.metrics if m.id == DATA_CENTER_CHANGE]
    markdown = render_markdown(run)
    assert f"- Reported figure: {change.label}, {change.period_label}: +68.2% (" in markdown
    assert change.formula in markdown and "nvda:DataCenterMember" in change.label


# (e) Failure paths: a note, a partial run, never an exception


class _SecondFetchFails(FakeFilings):
    """EDGAR serves each filing once: the run reads it, the tagged-facts read then fails."""

    error: Exception = SourceError("EDGAR answered HTTP 503")

    def fetch(self, ref: FilingRef) -> FetchedFiling:
        if ref.url in self.fetched:
            self.fetched.append(ref.url)
            raise self.error
        return super().fetch(ref)


def _supports(claim: object, passages: list[Passage]) -> ClaimDraft:
    first = passages[0]
    return ClaimDraft(
        findings=[
            FindingDraft(
                statement="The filing supports the claim.",
                stance=Stance.supports,
                quotes=[Quote(first.id, GROWTH_SENTENCE)],
                confidence=Confidence.medium,
                rationale="Stated directly.",
            )
        ]
    )


def _failing(error: Exception | None) -> FakeFilings:
    if error is None:
        return FakeFilings.synthetic(filing_html(GROWTH_SENTENCE))  # no inline XBRL
    filings = _SecondFetchFails.synthetic(filing_html(GROWTH_SENTENCE))
    filings.error = error
    return filings


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (SourceError("EDGAR answered HTTP 503"), "EDGAR answered HTTP 503"),
        (RuntimeError("password hunter2"), "the filing could not be fetched (RuntimeError)"),
        (None, "The document has no inline XBRL: no xbrli:context and no ix:nonFraction element"),
    ],
    ids=["edgar-fails", "source-cannot-fetch", "no-inline-xbrl"],
)
def test_tagged_facts_that_cannot_be_read_leave_the_run_partial_and_say_so(
    tmp_path: Path, error: Exception | None, reason: str
) -> None:
    filings = _failing(error)
    analyst = ScriptedAnalyst(_supports)
    run = run_with(Store(tmp_path / "r.sqlite"), request(GROWTH, filings=1), filings, analyst)
    assert run.status == RunStatus.partial and run.claims[0].verdict == Verdict.supported
    assert run.coverage.tagged_figures_offered == 0 and tagged(run.metrics) == []
    assert run.coverage_limits == [
        policy.TAGGED_UNAVAILABLE.format(form="10-Q", period_end="2026-01-01", error=reason)
    ]
    assert "hunter2" not in run.model_dump_json()
    # Without the option the same filings give a complete run.
    off = request(GROWTH, tagged=False, filings=1)
    clean = run_with(Store(tmp_path / "c.sqlite"), off, _failing(error), analyst)
    assert clean.status == RunStatus.complete, clean.coverage_limits


def test_the_status_rule_names_each_unreadable_filing() -> None:
    sentence = policy.TAGGED_UNAVAILABLE.format(form="10-K", period_end="2026-01-25", error="x")
    status, reasons = policy.run_status(
        sources_requested=1,
        sources_extracted=1,
        claims=[],
        withheld_findings=0,
        engine_fallbacks=0,
        time_limit_hit=False,
        tagged_errors=[sentence],
    )
    assert status == RunStatus.partial and reasons == [sentence]


# The offline replay of a tagged run


def test_a_tagged_replay_asks_new_assessments_and_keeps_the_plan(tmp_path: Path) -> None:
    """The plan's prompt is the same with the option on; every assessment's is not."""
    copy = tmp_path / "cassette"
    shutil.copytree(Path(__file__).parent.parent / DEFAULT_CASSETTE, copy)
    out = tmp_path / "out"
    argv = ["--cassette", str(copy), "--tagged-figures", "--out", str(out), "--name", "tagged"]
    assert replay_run.main(argv) == 3
    pending = [json.loads(path.read_text()) for path in sorted((copy / "pending").glob("*.json"))]
    assert {request["step"] for request in pending} == {"assess"}
    assert len(pending) == len(EXAMPLE_THESIS.claims)
    assert all(DATA_CENTER in request["user"] for request in pending)
    assert not out.exists()
