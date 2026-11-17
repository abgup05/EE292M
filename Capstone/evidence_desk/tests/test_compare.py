"""What moved between two runs of one thesis (core/compare.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.compare import compare_runs
from app.core.models import (
    Claim,
    Confidence,
    Decision,
    DecisionValue,
    Evidence,
    ExtractionStatus,
    Finding,
    Run,
    RunStatus,
    Source,
    SourceKind,
    Stance,
    ThesisRequest,
    Verdict,
)
from app.core.review import build_review

STARTED = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
CLAIMS = [
    "Data-center revenue is still growing",
    "A few customers account for most revenue",
    "Gross margin stays above seventy percent",
]
REQUEST = ThesisRequest(ticker="NVDA", decision="Keep the position into earnings", claims=CLAIMS)
GROWTH = "Data Center revenue grew 56% from a year ago."
CONCENTRATION = "Sales to one customer represented 16% of revenue."


def filing(sid: str, accession: str, title: str) -> Source:
    return Source(
        id=sid,
        kind=SourceKind.sec_filing,
        title=title,
        publisher="SEC EDGAR",
        url=f"https://www.sec.gov/Archives/{accession}.htm",
        form="10-Q",
        accession=accession,
        retrieved_at=STARTED,
        content_hash="ab" * 32,
        extraction_status=ExtractionStatus.extracted,
    )


Q2 = ("0001045810-26-000075", "NVIDIA CORP 10-Q, period ended 2026-07-26")
Q3 = ("0001045810-26-000099", "NVIDIA CORP 10-Q, period ended 2026-10-25")


def make_run(
    run_id: str,
    verdicts: list[Verdict],
    *,
    filings: tuple[tuple[str, str], ...] = (Q2,),
    excerpts: dict[int, list[tuple[int, str]]] | None = None,
    claim_texts: list[str] | None = None,
    hours: int = 0,
) -> Run:
    """One finished run. ``excerpts`` maps a claim position to (filing position, excerpt)."""
    texts = claim_texts or CLAIMS[: len(verdicts)]
    excerpts = excerpts if excerpts is not None else {0: [(0, GROWTH)]}
    sources = [filing(f"s{i + 1}", acc, title) for i, (acc, title) in enumerate(filings)]
    claims, findings, evidence = [], [], []
    for position, (text, verdict) in enumerate(zip(texts, verdicts, strict=True)):
        claim_id = f"c{position + 1}"
        claims.append(Claim(id=claim_id, text=text, verdict=verdict))
        for source_position, excerpt in excerpts.get(position, []):
            n = len(evidence) + 1
            findings.append(
                Finding(
                    id=f"f{n}",
                    claim_id=claim_id,
                    statement="A statement.",
                    stance=Stance.supports,
                    evidence_ids=[f"e{n}"],
                    confidence=Confidence.high,
                    rationale="Stated.",
                    verified=True,
                )
            )
            evidence.append(
                Evidence(
                    id=f"e{n}",
                    source_id=sources[source_position].id,
                    finding_id=f"f{n}",
                    excerpt=excerpt,
                    locator="Part I, Item 2",
                    start=0,
                )
            )
    return Run(
        id=run_id,
        inputs=REQUEST,
        thesis_id="th-1",
        status=RunStatus.complete,
        started_at=STARTED + timedelta(hours=hours),
        finished_at=STARTED + timedelta(hours=hours, minutes=2),
        claims=claims,
        sources=sources,
        evidence=evidence,
        findings=findings,
    )


THREE = [Verdict.supported, Verdict.unjudged, Verdict.not_addressed]


def test_identical_runs_move_nothing() -> None:
    earlier = make_run("run-a", THREE)
    later = make_run("run-b", THREE, hours=24)
    comparison = compare_runs(earlier, later)
    assert comparison.thesis_id == "th-1"
    assert (comparison.earlier_run_id, comparison.later_run_id) == ("run-a", "run-b")
    assert comparison.earlier_finished_at == earlier.finished_at
    assert comparison.later_finished_at == later.finished_at
    assert comparison.verdicts_moved == 0 and comparison.claims_total == 3
    assert not any(change.moved for change in comparison.claims)
    assert [(c.claim, c.before, c.after) for c in comparison.claims] == [
        (CLAIMS[0], Verdict.supported, Verdict.supported),
        (CLAIMS[1], Verdict.unjudged, Verdict.unjudged),
        (CLAIMS[2], Verdict.not_addressed, Verdict.not_addressed),
    ]
    assert comparison.sources_added == comparison.sources_dropped == []
    assert all(c.excerpts_added == c.excerpts_dropped == 0 for c in comparison.claims)
    assert comparison.note == "No verdict moved and no filing is new."


def test_one_verdict_moved() -> None:
    later_verdicts = [Verdict.supported, Verdict.challenged, Verdict.not_addressed]
    comparison = compare_runs(make_run("run-a", THREE), make_run("run-b", later_verdicts))
    assert [c.moved for c in comparison.claims] == [False, True, False]
    moved = comparison.claims[1]
    assert (moved.before, moved.after) == (Verdict.unjudged, Verdict.challenged)
    assert comparison.verdicts_moved == 1
    assert comparison.note == "1 of 3 verdicts moved and no filing is new."


def test_a_new_filing_and_its_excerpts() -> None:
    earlier = make_run("run-a", THREE, excerpts={0: [(0, GROWTH)]})
    later = make_run(
        "run-b",
        [Verdict.supported, Verdict.supported, Verdict.not_addressed],
        filings=(Q3, Q2),
        excerpts={0: [(1, GROWTH)], 1: [(0, CONCENTRATION)]},
    )
    comparison = compare_runs(earlier, later)
    assert comparison.sources_added == [Q3[1]] and comparison.sources_dropped == []
    # The same excerpt of the same filing is not "added", though its ids differ.
    assert (comparison.claims[0].excerpts_added, comparison.claims[0].excerpts_dropped) == (0, 0)
    assert (comparison.claims[1].excerpts_added, comparison.claims[1].excerpts_dropped) == (1, 0)
    assert comparison.note == (
        "1 of 3 verdicts moved; 1 filing is new: NVIDIA CORP 10-Q, period ended 2026-10-25."
    )


def test_a_dropped_filing_and_its_excerpt() -> None:
    earlier = make_run("run-a", THREE, filings=(Q2, Q3), excerpts={0: [(0, GROWTH), (1, GROWTH)]})
    later = make_run("run-b", THREE, filings=(Q2,), excerpts={0: [(0, GROWTH)]})
    comparison = compare_runs(earlier, later)
    assert comparison.sources_dropped == [Q3[1]] and comparison.sources_added == []
    assert (comparison.claims[0].excerpts_added, comparison.claims[0].excerpts_dropped) == (0, 1)


def test_two_new_filings_are_named_in_the_note() -> None:
    other = ("0001045810-26-000101", "NVIDIA CORP 8-K, filed 2026-11-01")
    later = make_run("run-b", THREE, filings=(Q3, other, Q2))
    comparison = compare_runs(make_run("run-a", THREE), later)
    assert comparison.note == (f"No verdict moved; 2 filings are new: {Q3[1]}; {other[1]}.")


def test_a_claim_reworded_only_in_spacing_and_case_still_matches() -> None:
    reworded = ["  DATA-CENTER revenue   is still\ngrowing ", *CLAIMS[1:]]
    later = make_run("run-b", THREE, claim_texts=reworded)
    comparison = compare_runs(make_run("run-a", THREE), later)
    assert comparison.claims_total == 3 and comparison.verdicts_moved == 0
    assert comparison.claims[0].before == comparison.claims[0].after == Verdict.supported


def test_a_claim_present_in_one_run_only() -> None:
    earlier = make_run("run-a", THREE[:2])
    later = make_run(
        "run-b",
        [Verdict.supported, Verdict.challenged],
        claim_texts=[CLAIMS[0], CLAIMS[2]],
    )
    comparison = compare_runs(earlier, later)
    rows = {c.claim: (c.before, c.after, c.moved) for c in comparison.claims}
    assert rows == {
        CLAIMS[0]: (Verdict.supported, Verdict.supported, False),
        CLAIMS[2]: (None, Verdict.challenged, True),
        CLAIMS[1]: (Verdict.unjudged, None, True),
    }
    # The later run's claims come first, in its order; then claims only the earlier run had.
    assert [c.claim for c in comparison.claims] == [CLAIMS[0], CLAIMS[2], CLAIMS[1]]
    assert comparison.claims_total == 3


def test_the_same_excerpt_in_a_different_filing_is_added() -> None:
    earlier = make_run("run-a", THREE, filings=(Q2, Q3), excerpts={0: [(0, GROWTH)]})
    later = make_run("run-b", THREE, filings=(Q2, Q3), excerpts={0: [(1, GROWTH)]})
    change = compare_runs(earlier, later).claims[0]
    assert (change.excerpts_added, change.excerpts_dropped) == (1, 1)


def test_reviewed_verdicts_come_from_each_runs_review() -> None:
    earlier = make_run("run-a", THREE)
    later = make_run("run-b", THREE)
    rejected = Decision(
        run_id="run-b",
        finding_id="f1",
        value=DecisionValue.rejected,
        decided_at=STARTED + timedelta(days=1),
    )
    comparison = compare_runs(
        earlier, later, build_review(earlier, []), build_review(later, [rejected])
    )
    first = comparison.claims[0]
    assert first.reviewed_before is None
    assert first.reviewed_after == Verdict.not_addressed
    assert not first.moved  # moved compares the engine's verdicts
    assert compare_runs(earlier, later).claims[0].reviewed_after is None
