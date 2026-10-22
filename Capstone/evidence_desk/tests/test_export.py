"""Markdown export: status, dates and traceable citations stay visible in the file."""

from datetime import UTC, datetime

from app.export import render_markdown
from app.models import (
    Brief,
    Confidence,
    Evidence,
    ExtractionStatus,
    Finding,
    ResearchRequest,
    Run,
    RunStatus,
    Source,
    Stance,
    Subquestion,
    SubquestionStatus,
)


def sample_run() -> Run:
    finding = Finding(
        id="f-1",
        statement="The framework is voluntary.",
        evidence_ids=["e-1"],
        confidence=Confidence.medium,
        rationale="Primary source states it directly.",
        verified=True,
        single_source=True,
    )
    return Run(
        id="run-1",
        inputs=ResearchRequest(
            question="What risks should an organization examine before using generative AI?",
            decision="Whether to investigate a limited internal pilot",
            seed_urls=["https://www.nist.gov/rmf"],
        ),
        status=RunStatus.partial,
        started_at=datetime(2026, 10, 21, 12, 0, tzinfo=UTC),
        finished_at=datetime(2026, 10, 21, 12, 1, tzinfo=UTC),
        coverage_limits=["Fewer than six sources were extracted (1)."],
        subquestions=[
            Subquestion(
                id="sq-1",
                text="What risks?",
                search_query="risks",
                status=SubquestionStatus.answered,
            )
        ],
        sources=[
            Source(
                id="src-1",
                canonical_url="https://www.nist.gov/rmf",
                requested_url="https://www.nist.gov/rmf",
                title="AI Risk Management Framework",
                publisher="NIST",
                published_date=None,
                retrieved_at=datetime(2026, 10, 21, 12, 0, 30, tzinfo=UTC),
                content_hash="abc",
                extraction_status=ExtractionStatus.extracted,
            ),
            Source(
                id="src-2",
                canonical_url="https://www.gao.gov/missing",
                requested_url="https://www.gao.gov/missing",
                title="",
                publisher="",
                retrieved_at=datetime(2026, 10, 21, 12, 0, 31, tzinfo=UTC),
                content_hash="",
                extraction_status=ExtractionStatus.failed,
                error="HTTP 404",
            ),
        ],
        evidence=[
            Evidence(
                id="e-1",
                source_id="src-1",
                excerpt="The AI RMF is a voluntary framework.",
                locator="Overview",
                stance=Stance.supports,
                finding_id="f-1",
            )
        ],
        findings=[finding],
        brief=Brief(
            direct_answer="Risks are documented; coverage is thin.",
            findings=[finding],
            disagreements=[],
            unknowns=["No cost data."],
            next_steps=["Add a second source."],
            source_ids=["src-1"],
            coverage_status=RunStatus.partial,
        ),
    )


def test_markdown_shows_status_citations_and_dates() -> None:
    text = render_markdown(sample_run())
    assert "PARTIAL" in text
    assert "Fewer than six sources" in text
    assert "The framework is voluntary." in text
    assert "> The AI RMF is a voluntary framework." in text
    assert "Overview" in text
    assert "AI Risk Management Framework" in text
    assert "https://www.nist.gov/rmf" in text
    assert "single source" in text.lower()
    assert "Published: not available" in text
    assert "2026-10-21 12:00:30 UTC" in text
    assert "HTTP 404" in text
    assert "No cost data." in text
    assert "Add a second source." in text


def test_markdown_for_failed_run_has_no_findings_section_content() -> None:
    run = sample_run()
    run.status = RunStatus.failed
    run.brief = None
    run.findings = []
    run.errors = ["No source could be retrieved."]
    text = render_markdown(run)
    assert "FAILED" in text
    assert "No source could be retrieved." in text
    assert "The framework is voluntary." not in text
