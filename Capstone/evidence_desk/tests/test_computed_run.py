"""Computed claims in a run: compiled, evaluated from the run's facts, counted by the verdict rule.

The engine is asked exactly as before and the summariser is shown the verdicts of the
findings alone; the computed outcome then enters each claim's verdict as verified
evidence marked computed (holds supports, fails challenges, cannot-compute counts as
nothing and says why), and the brief shows the tests and their histories.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.core import policy
from app.core.claim_test_models import ComputedTest
from app.core.models import Confidence, Finding, Stance, ThesisRequest, Verdict
from app.core.ports import ClaimDraft
from app.services.export import render_markdown
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import FakePages, ScriptedAnalyst
from tests.lookahead import late_refs
from tests.replay_run import recorded_filings

CLAIMS = [
    "Gross margin is expanding.",
    "Revenue grew more than 200% year over year.",
    "Data center revenue is still growing year over year.",
    "Data center is more than 80% of revenue.",
    "Revenue grew in fiscal 2008.",
]


def _run(tmp_path: Path, *, as_of: str | None = None, tagged: bool = False):
    request = ThesisRequest(
        ticker="NVDA",
        decision="Whether to keep an overweight position in NVIDIA",
        claims=CLAIMS,
        as_of=as_of,
        tagged_figures=tagged,
    )
    # No finding at all: whatever a claim's verdict is, the computed test made it.
    analyst = ScriptedAnalyst(lambda claim, passages: ClaimDraft())
    run = execute_run(
        new_run(request),
        Store(tmp_path / "record.sqlite"),
        filings=recorded_filings(),
        analyst=analyst,
        fetch_page=FakePages({}),
        cache=FilingCache(),
    )
    return run, analyst


def _computed(run, index: int) -> ComputedTest:
    computed = run.claims[index].computed
    assert computed is not None, run.claims[index].compile_note
    return computed


def test_each_claim_is_compiled_and_a_compiled_one_is_computed(tmp_path: Path) -> None:
    run, _ = _run(tmp_path)
    margin = _computed(run, 0)
    assert margin.canonical == "gross_margin[Q] > gross_margin[Q-4]"
    assert margin.bound == "gross_margin[Q2 FY2027] > gross_margin[Q2 FY2026]"
    assert margin.outcome == "holds" and margin.counted_as == "supports"
    assert all(ref.filed and ref.accession for o in margin.operands for ref in o.inputs)
    segment = run.claims[2]
    assert segment.computed is None and "segment" in segment.compile_note
    assert segment.compile_note.startswith("Not a numeric claim")
    assert run.coverage.claims_compiled == 4
    assert (run.coverage.computed_holds, run.coverage.computed_fails) == (2, 1)
    assert run.coverage.computed_cannot == 1


def test_the_computed_outcome_enters_the_verdict(tmp_path: Path) -> None:
    run, analyst = _run(tmp_path)
    verdicts = [claim.verdict for claim in run.claims]
    assert verdicts == [
        Verdict.supported,
        Verdict.challenged,
        Verdict.not_addressed,
        Verdict.supported,
        Verdict.not_addressed,
    ]
    # The summariser was shown the verdicts of the findings alone, as before.
    assert set(analyst.summarized.values()) == {Verdict.not_addressed}
    cannot = _computed(run, 4)
    assert cannot.outcome == "cannot_compute" and cannot.counted_as == "" and cannot.reason


def test_the_verdict_rule_counts_a_computed_test_as_verified_evidence() -> None:
    def computed(outcome: str) -> ComputedTest:
        return ComputedTest(
            canonical="x",
            form="threshold",
            outcome=outcome,  # type: ignore[arg-type]
            outcome_label=policy.COMPUTED_LABELS[outcome],
            comparison=">",
            counted_as=policy.COMPUTED_COUNTS.get(outcome, ""),
        )

    challenge = Finding(
        id="f1",
        claim_id="c1",
        stance=Stance.challenges,
        statement="s",
        evidence_ids=["e1"],
        confidence=Confidence.medium,
        rationale="r",
        verified=True,
    )
    assert policy.claim_verdict([], computed("holds")) == Verdict.supported
    assert policy.claim_verdict([], computed("fails")) == Verdict.challenged
    assert policy.claim_verdict([], computed("cannot_compute")) == Verdict.not_addressed
    assert policy.claim_verdict([challenge], computed("holds")) == Verdict.mixed
    assert policy.claim_verdict([challenge], None) == Verdict.challenged


def test_a_computed_claim_has_its_history_and_a_share_has_none(tmp_path: Path) -> None:
    run, _ = _run(tmp_path, tagged=True)
    margin = _computed(run, 0)
    assert len(margin.history) >= 15
    assert [p.filed for p in margin.history] == sorted(p.filed for p in margin.history)
    assert margin.history[-1].filed == "2026-08-26"
    assert any(p.flipped for p in margin.history)
    assert "flipped" in margin.history_note
    share = _computed(run, 3)
    assert share.outcome == "holds" and share.history == []
    assert "no history" in share.history_note


def test_the_brief_has_a_deterministic_section_of_computed_tests(tmp_path: Path) -> None:
    run, _ = _run(tmp_path)
    text = render_markdown(run)
    assert "## Computed tests" in text
    section = text.split("## Computed tests", 1)[1].split("\n## ", 1)[0]
    assert "gross_margin[Q2 FY2027] > gross_margin[Q2 FY2026]" in section
    assert "Holds" in section and "Cannot be computed" in section
    assert "| Filed | Form | Outcome |" in section
    assert "Not a numeric claim" in section
    assert text.index("## Computed tests") < text.index("## Claims")


def test_as_of_a_date_the_computed_tests_see_nothing_later(tmp_path: Path) -> None:
    run, _ = _run(tmp_path, as_of="2026-06-01")
    margin = _computed(run, 0)
    assert margin.as_of == "2026-06-01"
    assert margin.bound == "gross_margin[Q1 FY2027] > gross_margin[Q1 FY2026]"
    assert margin.history and margin.history[-1].filed == "2026-05-20"
    assert late_refs(run, date(2026, 6, 1)) == []
