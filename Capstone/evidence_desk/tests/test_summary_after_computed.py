"""A run's summary never contradicts its verdict table (the fifth referee, finding 2).

The computed tests count after the summary step. A template summary is therefore written
again from the final verdicts. A model's summary cannot be: its request shows the verdicts of
the findings alone, and changing that request would orphan every recording. It is kept, and
a line written by code (``Brief.verdicts_after_summary``) says which claims' verdicts the
computed tests set or changed after it was written. The Markdown brief prints that line, and
its verdict table says what the computed test counted, so that no row reads "Supported" over
nothing.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from app.core import policy
from app.core.documents import Passage
from app.core.models import Claim, Confidence, Stance, ThesisRequest, Verdict
from app.core.ports import ClaimDraft, FindingDraft, Quote
from app.services.export import render_markdown
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import FakePages, ScriptedAnalyst
from tests.replay_run import recorded_filings

CLAIMS = [
    "Gross margin is expanding.",
    "Revenue grew more than 200% year over year.",
    "Data center revenue is still growing year over year.",
    "Data center is more than 80% of revenue.",
    "Revenue grew in fiscal 2008.",
]
CONTEXT_CLAIM = CLAIMS[2]  # does not compile: its verdict is the findings' alone


def _request() -> ThesisRequest:
    return ThesisRequest(
        ticker="NVDA",
        decision="Whether to keep an overweight position in NVIDIA",
        claims=CLAIMS,
    )


def _execute(tmp_path: Path, analyst):
    return execute_run(
        new_run(_request()),
        Store(tmp_path / "record.sqlite"),
        filings=recorded_filings(),
        analyst=analyst,
        fetch_page=FakePages({}),
        cache=FilingCache(),
    )


def _context_only(claim: Claim, passages: list[Passage]) -> ClaimDraft:
    """One finding of context on the claim that does not compile, quoting its first passage."""
    if claim.text != CONTEXT_CLAIM or not passages:
        return ClaimDraft()
    words = passages[0].text.split()[:8]
    return ClaimDraft(
        findings=[
            FindingDraft(
                statement="The filing discusses this.",
                stance=Stance.context,
                quotes=[Quote(passages[0].id, " ".join(words))],
                confidence=Confidence.low,
                rationale="Background only.",
            )
        ]
    )


def _counted(summary: str) -> Counter[str]:
    """The verdict counts a template summary states, by label."""
    counts: Counter[str] = Counter()
    body = summary.split(" — ", 1)[1].split(".", 1)[0]
    for part in body.split("; "):
        label, count = part.rsplit(": ", 1)
        counts[label] = int(count)
    return counts


def test_a_template_summary_counts_the_final_verdicts(tmp_path: Path) -> None:
    run = _execute(tmp_path, ScriptedAnalyst(lambda claim, passages: ClaimDraft()))
    assert run.brief is not None and run.brief.summary_origin == "template"
    final = Counter(policy.VERDICT_LABELS[c.verdict] for c in run.claims if c.verdict)
    assert _counted(run.brief.summary) == final
    assert final[policy.VERDICT_LABELS[Verdict.supported]] == 2
    assert run.brief.verdicts_after_summary == ""


def test_a_model_summary_is_kept_and_followed_by_what_the_computed_tests_changed(
    tmp_path: Path,
) -> None:
    analyst = ScriptedAnalyst(_context_only, summary="The thesis rests on margins.")
    run = _execute(tmp_path, analyst)
    assert run.brief is not None and run.brief.summary_origin == "model"
    assert run.brief.summary == "The thesis rests on margins."
    # The summariser was shown the findings' verdicts alone: its request is unchanged.
    assert Verdict.supported not in analyst.summarized.values()
    line = run.brief.verdicts_after_summary
    assert line.startswith(policy.VERDICTS_AFTER_SUMMARY_LEAD)
    moved = [c for c in run.claims if analyst.summarized.get(c.id) != c.verdict]
    assert {c.text for c in moved} == {CLAIMS[0], CLAIMS[1], CLAIMS[3]}
    for claim in moved:
        assert f"“{claim.text}”" in line
        assert policy.VERDICT_LABELS[claim.verdict] in line
    assert CONTEXT_CLAIM not in line and CLAIMS[4] not in line


def test_the_brief_prints_the_line_and_a_computed_column(tmp_path: Path) -> None:
    analyst = ScriptedAnalyst(_context_only, summary="The thesis rests on margins.")
    run = _execute(tmp_path, analyst)
    text = render_markdown(run)
    assert run.brief is not None
    assert f"_{run.brief.verdicts_after_summary}_" in text.replace("\\", "")
    header = next(line for line in text.splitlines() if line.startswith("| Claim |"))
    assert "| Computed |" in header
    rows = {line.split(" | ")[0].lstrip("| ").replace("\\", ""): line for line in text.splitlines()}
    assert "Holds, counted as support" in rows[CLAIMS[0]]
    assert "Fails, counted as a challenge" in rows[CLAIMS[1]]
    assert "No test" in rows[CONTEXT_CLAIM]
    assert "Cannot be computed" in rows[CLAIMS[4]]
