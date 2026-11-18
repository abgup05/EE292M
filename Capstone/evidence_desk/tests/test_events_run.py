"""8-Ks in a whole run: the case that motivated version 12, its opposite, and the engines.

A user ran "buy NVDA because Jensen is gone" and the run answered from the annual
report, in which he is chief executive, as though that settled it. Here a fake
EDGAR lists an Item 5.02 8-K filed after the quarterly report; the run must show it
on its timeline, give the claim the leadership category, offer the 8-K's section to
the engine and mark a finding quoting the older annual report as predated by it.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.documents import Passage
from app.core.event_models import EventStatus
from app.core.models import Claim, Confidence, Run, Stance, ThesisRequest, Verdict
from app.core.ports import ClaimDraft, FindingDraft, Quote
from app.engines.claude import CURRENT_REPORT_RULE, ClaudeAnalyst
from app.engines.extractive import ExtractiveAnalyst
from app.engines.transport import ModelRequest
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import (
    NVIDIA,
    FakeFilings,
    FakePages,
    ManualClock,
    ScriptedAnalyst,
    current_report_html,
    current_report_ref,
    filing_html,
    synthetic_ref,
)

ANNUAL = dataclasses.replace(synthetic_ref(1, "10-K"), filed_date="2026-01-15")
QUARTER = dataclasses.replace(synthetic_ref(2, "10-Q"), filed_date="2026-02-15")
CEO_SENTENCE = "Jane Smith is our Chief Executive Officer and has led the company since 2010."
DEPARTURE = (
    "On March 9, 2026, Jane Smith resigned as Chief Executive Officer of the Company, "
    "effective immediately."
)
DEPARTURE_8K = current_report_ref(1, "2026-03-10", "5.02", "9.01", event_date="2026-03-09")
RESULTS_8K = current_report_ref(2, "2026-03-12", "2.02", "9.01")
CLAIM = "Buy because Jane Smith is gone."
OLD_RUN = Path(__file__).parent / "fixtures" / "record" / "run-version-0.11.1.json.gz"


def filings(*current: tuple[object, str]) -> FakeFilings:
    """A 10-K that names the chief executive, a 10-Q, and the given 8-Ks with their HTML."""
    documents: dict[str, object] = {
        ANNUAL.url: filing_html(
            CEO_SENTENCE, item="Item 10. Directors, Executive Officers and Corporate Governance"
        ),
        QUARTER.url: filing_html("Revenue grew in the quarter as demand for systems rose."),
    }
    refs = []
    for ref, html in current:
        refs.append(ref)
        documents[ref.url] = html
    fake = FakeFilings(refs=[QUARTER, ANNUAL], documents=documents)  # type: ignore[arg-type]
    fake.current = refs  # type: ignore[assignment]
    return fake


def departure_html() -> str:
    return current_report_html(
        (
            "5.02",
            "Departure of Directors or Certain Officers.",
            [DEPARTURE, "The Board appointed John Doe as interim Chief Executive Officer."],
        ),
        ("9.01", "Financial Statements and Exhibits.", ["(d) Exhibits."]),
    )


def results_html() -> str:
    return current_report_html(
        ("2.02", "Results of Operations and Financial Condition.", ["The company reported."]),
        ("9.01", "Financial Statements and Exhibits.", ["(d) Exhibits."]),
    )


def quote_the_annual_report(claim: Claim, passages: list[Passage]) -> ClaimDraft:
    """A finding that rests on the annual report, which says she is chief executive."""
    passage = next(p for p in passages if CEO_SENTENCE in p.text)
    return ClaimDraft(
        findings=[
            FindingDraft(
                statement="The annual report names Jane Smith as chief executive.",
                stance=Stance.challenges,
                quotes=[Quote(passage_id=passage.id, text=CEO_SENTENCE)],
                confidence=Confidence.medium,
                rationale="The annual report says she leads the company.",
            )
        ],
        rationale="Checked against the annual report.",
    )


def run_with(source: FakeFilings, analyst: object, claims: list[str] | None = None) -> Run:
    request = ThesisRequest(
        ticker="NVDA",
        decision="Whether to buy the shares after the change at the top",
        claims=claims or [CLAIM],
        filings=2,
    )
    run = new_run(request)
    run.started_at = datetime(2026, 3, 20, tzinfo=UTC)
    return execute_run(
        run,
        Store(":memory:"),
        filings=source,
        analyst=analyst,  # type: ignore[arg-type]
        fetch_page=FakePages({}),
        clock=ManualClock(),
        cache=FilingCache(),
    )


def test_the_motivating_case_the_8k_is_shown_offered_and_marks_the_older_finding() -> None:
    analyst = ScriptedAnalyst(quote_the_annual_report)
    run = run_with(filings((DEPARTURE_8K, departure_html())), analyst)

    [event] = run.timeline
    assert (event.filed_date, [item.number for item in event.items]) == (
        "2026-03-10",
        ["5.02", "9.01"],
    )
    assert event.status == EventStatus.read
    assert event.items[0].opening[0] == DEPARTURE
    assert event.items[0].roles == ["Chief Executive Officer"]

    [claim] = run.claims
    assert claim.categories == ["leadership"]

    offered = analyst.offered[CLAIM]
    assert event.source_id is not None
    eight_k = [pid for pid in offered if pid.startswith(f"{event.source_id}-")]
    assert len(eight_k) == 1
    source = next(s for s in run.sources if s.id == event.source_id)
    assert (source.form, source.published_date) == ("8-K", "2026-03-10")

    [finding] = run.findings
    assert finding.verified
    assert [(mark.event_id, mark.items) for mark in finding.predated_by] == [(event.id, ["5.02"])]
    assert finding.predated_by[0].label == "Predates the 8-K of 10 Mar 2026, Item 5.02"
    assert "10 Mar 2026 (Item 5.02)" in claim.caution
    # Reported, never withheld: the verdict is what the finding's stance gives.
    assert claim.verdict == Verdict.challenged
    assert claim.event_note == ""
    assert run.as_of is not None
    assert (run.as_of.newest_form, run.as_of.newest_filed) == ("8-K", "2026-03-10")
    assert (run.as_of.periodic_form, run.as_of.periodic_filed) == ("10-Q", "2026-02-15")
    assert run.as_of.days_since_newest == 10


def test_with_no_5_02_since_the_annual_report_the_claim_gets_a_note_not_a_verdict() -> None:
    analyst = ScriptedAnalyst(lambda claim, passages: ClaimDraft(rationale="Nothing found."))
    run = run_with(filings((RESULTS_8K, results_html())), analyst)
    [claim] = run.claims
    assert claim.categories == ["leadership"]
    assert claim.event_note == (
        "No 8-K filed since 15 Jan 2026 reports a change of directors or officers (Item 5.02). "
        "The newest filing read is dated 12 Mar 2026; anything later is not in the record."
    )
    assert claim.verdict == Verdict.not_addressed
    assert claim.caution == ""
    assert all(not pid.startswith("s4-") for pid in analyst.offered[CLAIM])


def test_a_claim_with_no_category_is_offered_no_8k_and_gets_no_note() -> None:
    analyst = ScriptedAnalyst()
    run = run_with(
        filings((DEPARTURE_8K, departure_html())),
        analyst,
        claims=["Revenue grew in the quarter as demand rose."],
    )
    [claim] = run.claims
    assert (claim.categories, claim.caution, claim.event_note) == ([], "", "")
    assert all(source.form != "8-K" for source in run.sources)
    assert len(run.timeline) == 1


def test_the_extractive_engine_shows_the_pinned_8k_passage() -> None:
    run = run_with(filings((DEPARTURE_8K, departure_html())), ExtractiveAnalyst())
    [claim] = run.claims
    statements = [f.statement for f in run.findings if f.claim_id == claim.id]
    assert statements[0] == f"The filing states: {DEPARTURE}"
    first = run.findings[0]
    [evidence] = [e for e in run.evidence if e.id in first.evidence_ids]
    assert evidence.excerpt == DEPARTURE
    assert first.predated_by == []


def test_an_8k_that_cannot_be_fetched_leaves_the_run_complete_and_says_why() -> None:
    from app.core.ports import SourceError

    source = filings((DEPARTURE_8K, departure_html()))
    source.documents[DEPARTURE_8K.url] = SourceError("EDGAR answered HTTP 404 for the 8-K")
    run = run_with(source, ScriptedAnalyst(quote_the_annual_report))
    [event] = run.timeline
    assert (event.status, event.reason) == (
        EventStatus.failed,
        "EDGAR answered HTTP 404 for the 8-K",
    )
    assert not any("8-K" in error for error in run.errors)
    [claim] = run.claims
    # Not read, but listed: the finding still predates it, and the note says it was not read.
    assert claim.caution != ""
    assert claim.event_note == (
        "The 8-K of 10 Mar 2026 reports Item 5.02, but its text was not read: "
        "EDGAR answered HTTP 404 for the 8-K."
    )
    assert run.as_of is not None
    assert (run.as_of.counts.listed, run.as_of.counts.failed) == (1, 1)


class RecordingTransport:
    """Answers every request with no findings and keeps what was asked."""

    detail = "recording transport"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def __call__(self, request: ModelRequest) -> dict:
        self.requests.append(request)
        if request.step == "plan":
            return {"claims": [{"claim_number": 1, "queries": ["chief executive", "officer"]}]}
        if request.step == "assess":
            return {"findings": [], "rationale": "none", "unknowns": []}
        return {"summary": "None.", "next_steps": []}


def test_the_model_is_told_about_newer_filings_only_when_an_8k_passage_is_offered() -> None:
    with_event = RecordingTransport()
    run_with(filings((DEPARTURE_8K, departure_html())), ClaudeAnalyst(transport=with_event))
    [assess] = [r for r in with_event.requests if r.step == "assess"]
    assert 'form="8-K" filed="2026-03-10"' in assess.user
    assert CURRENT_REPORT_RULE in assess.system

    without = RecordingTransport()
    run_with(filings((RESULTS_8K, results_html())), ClaudeAnalyst(transport=without))
    [plain] = [r for r in without.requests if r.step == "assess"]
    assert CURRENT_REPORT_RULE not in plain.system
    assert "form=" not in plain.user


def test_a_run_recorded_by_version_11_still_loads_with_empty_event_fields(
    tmp_path: Path,
) -> None:
    record = gzip.decompress(OLD_RUN.read_bytes()).decode("utf-8")
    assert "timeline" not in json.loads(record)
    run = Run.model_validate_json(record)
    assert run.timeline == [] and run.as_of is None
    assert all(c.categories == [] and c.caution == "" and c.event_note == "" for c in run.claims)
    assert all(f.predated_by == [] for f in run.findings)
    store = Store(tmp_path / "record.sqlite")
    with store._db.transaction() as connection:  # noqa: SLF001 - an old record, as stored
        connection.execute(
            "INSERT INTO runs (id, started_at, thesis_id, record) VALUES (?, ?, ?, ?)",
            (run.id, run.started_at.isoformat(), None, record),
        )
    loaded = store.get_run(run.id)
    assert loaded is not None
    assert loaded.findings == run.findings
    assert NVIDIA.ticker == loaded.inputs.ticker


def test_the_example_thesis_has_no_claim_an_8k_bears_on() -> None:
    """The recorded model answers are for the example thesis; no 8-K is offered to its claims.

    So the replay's prompts, and the recordings that answer them, are those of version 11
    even though the replayed EDGAR now lists NVIDIA's 8-Ks.
    """
    from app.core.events import claim_categories
    from app.services.examples import EXAMPLE_THESIS

    assert {claim: claim_categories(claim) for claim in EXAMPLE_THESIS.claims} == {
        claim: [] for claim in EXAMPLE_THESIS.claims
    }


def test_the_brief_carries_the_as_of_line_the_events_the_caution_and_the_mark() -> None:
    from app.services.export import EVENTS_HEADING_MD, render_markdown

    analyst = ScriptedAnalyst(quote_the_annual_report)
    run = run_with(filings((DEPARTURE_8K, departure_html())), analyst)
    brief = render_markdown(run)
    assert run.as_of is not None and f"\n{run.as_of.line}\n" in brief
    events = brief.split(EVENTS_HEADING_MD, 1)[1].split("\n## ", 1)[0]
    assert run.as_of.counts.line in events
    assert f"- [8-K, filed 10 Mar 2026]({DEPARTURE_8K.url}) (substantive; read)" in events
    assert "  - Item 5.02. Departure of Directors or Certain Officers" in events
    assert "    - Roles named: Chief Executive Officer" in events
    assert f"    - “{DEPARTURE}”" in events
    [claim] = run.claims
    assert f"**Caution:** {claim.caution}" in brief
    assert f"- [Predates the 8-K of 10 Mar 2026, Item 5.02]({DEPARTURE_8K.url})" in brief
    assert brief.index(EVENTS_HEADING_MD) < brief.index("## Claims")


def test_8k_text_in_the_brief_is_escaped_as_excerpts_are() -> None:
    from app.services.export import EVENTS_HEADING_MD, render_markdown

    hostile = current_report_html(
        (
            "5.02",
            "Departure of Directors or Certain Officers.",
            ["On March 9, 2026, *Jane* [Smith](https://evil.example) <b>resigned</b> as CEO."],
        ),
    )
    brief = render_markdown(run_with(filings((DEPARTURE_8K, hostile)), ScriptedAnalyst()))
    events = brief.split(EVENTS_HEADING_MD, 1)[1].split("\n## ", 1)[0]
    assert "\\*Jane\\* \\[Smith\\](https://evil.example)" in events
    assert "[Smith](https://evil.example)" not in brief


def test_a_run_from_version_11_renders_with_no_event_section() -> None:
    from app.services.export import EVENTS_HEADING_MD, render_markdown

    run = Run.model_validate_json(gzip.decompress(OLD_RUN.read_bytes()))
    brief = render_markdown(run)
    assert EVENTS_HEADING_MD not in brief and "Evidence as of" not in brief
