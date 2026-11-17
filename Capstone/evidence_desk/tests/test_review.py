"""A reviewer's decisions and the verdicts that follow from them (core/review.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.models import (
    Claim,
    Confidence,
    Decision,
    DecisionValue,
    Finding,
    Run,
    RunStatus,
    Stance,
    ThesisRequest,
    Verdict,
)
from app.core.review import build_review

DECIDED_AT = datetime(2026, 11, 17, 15, 0, tzinfo=UTC)
REQUEST = ThesisRequest(
    ticker="NVDA",
    decision="Keep the position into the next earnings report",
    claims=[
        "Data-center revenue is still growing",
        "A few customers account for most revenue",
        "The company operates grocery stores in Norway",
    ],
)


def finding(fid: str, claim_id: str, stance: Stance, *, verified: bool = True) -> Finding:
    return Finding(
        id=fid,
        claim_id=claim_id,
        statement=f"Statement {fid}.",
        stance=stance,
        evidence_ids=["e-" + fid] if verified else [],
        confidence=Confidence.high,
        rationale="Because.",
        verified=verified,
    )


def mixed_run() -> Run:
    """c1 is mixed (f1 supports, f2 challenges, f3 context); c2 unjudged (f4); c3 not addressed.

    f5 (c2) was withheld.
    """
    return Run(
        id="run-1",
        inputs=REQUEST,
        status=RunStatus.partial,
        started_at=DECIDED_AT - timedelta(hours=1),
        claims=[
            Claim(id="c1", text=REQUEST.claims[0], verdict=Verdict.mixed),
            Claim(id="c2", text=REQUEST.claims[1], verdict=Verdict.unjudged),
            Claim(id="c3", text=REQUEST.claims[2], verdict=Verdict.not_addressed),
        ],
        findings=[
            finding("f1", "c1", Stance.supports),
            finding("f2", "c1", Stance.challenges),
            finding("f3", "c1", Stance.context),
            finding("f4", "c2", Stance.context),
        ],
        unsupported_findings=[finding("f5", "c2", Stance.supports, verified=False)],
    )


def decide(
    finding_id: str, value: DecisionValue, *, run_id: str = "run-1", minutes: int = 0
) -> Decision:
    return Decision(
        run_id=run_id,
        finding_id=finding_id,
        value=value,
        decided_at=DECIDED_AT + timedelta(minutes=minutes),
    )


ACCEPT = DecisionValue.accepted
REJECT = DecisionValue.rejected


def by_claim(run: Run, decisions: list[Decision]) -> dict[str, tuple[Verdict | None, ...]]:
    review = build_review(run, decisions)
    return {c.claim_id: (c.engine_verdict, c.reviewed_verdict) for c in review.claims}


def test_no_decisions_leaves_every_reviewed_verdict_open() -> None:
    review = build_review(mixed_run(), [])
    assert review.run_id == "run-1"
    assert review.findings_total == 4 and review.decided == 0 and not review.complete
    assert [(c.claim_id, c.engine_verdict, c.reviewed_verdict) for c in review.claims] == [
        ("c1", Verdict.mixed, None),
        ("c2", Verdict.unjudged, None),
        ("c3", Verdict.not_addressed, None),
    ]
    assert [(c.accepted, c.rejected, c.undecided) for c in review.claims] == [
        (0, 0, 3),
        (0, 0, 1),
        (0, 0, 0),
    ]


def test_rejecting_the_one_challenging_finding_makes_a_mixed_claim_supported() -> None:
    decisions = [decide("f1", ACCEPT), decide("f2", REJECT)]
    assert by_claim(mixed_run(), decisions)["c1"] == (Verdict.mixed, Verdict.supported)


def test_rejecting_everything_makes_the_claim_not_addressed() -> None:
    decisions = [decide(f, REJECT) for f in ("f1", "f2", "f3")]
    review = build_review(mixed_run(), decisions)
    c1 = review.claims[0]
    assert c1.reviewed_verdict == Verdict.not_addressed
    assert (c1.accepted, c1.rejected, c1.undecided) == (0, 3, 0)


def test_undecided_findings_do_not_count_toward_the_reviewed_verdict() -> None:
    # Only the challenging finding is accepted; the supporting one is undecided.
    review = build_review(mixed_run(), [decide("f2", ACCEPT)])
    c1 = review.claims[0]
    assert c1.reviewed_verdict == Verdict.challenged
    assert (c1.accepted, c1.rejected, c1.undecided) == (1, 0, 2)
    assert review.claims[1].reviewed_verdict is None  # c2 has no decision yet


def test_accepting_everything_reproduces_the_engine_verdicts() -> None:
    decisions = [decide(f, ACCEPT) for f in ("f1", "f2", "f3", "f4")]
    review = build_review(mixed_run(), decisions)
    assert review.complete and review.decided == review.findings_total == 4
    assert [c.reviewed_verdict for c in review.claims] == [
        Verdict.mixed,
        Verdict.unjudged,
        None,  # c3 has no finding to decide
    ]


def test_a_decision_on_a_withheld_or_unknown_finding_is_ignored() -> None:
    decisions = [
        decide("f5", ACCEPT),  # withheld
        decide("f99", REJECT),  # not in the run
        decide("f1", ACCEPT, run_id="run-other"),  # another run's decision
    ]
    review = build_review(mixed_run(), decisions)
    assert review.decisions == [] and review.decided == 0
    assert all(c.reviewed_verdict is None for c in review.claims)
    assert review.claims[1].undecided == 1


def test_complete_only_when_every_verified_finding_is_decided() -> None:
    three = [decide(f, ACCEPT) for f in ("f1", "f2", "f3")]
    assert not build_review(mixed_run(), three).complete
    assert build_review(mixed_run(), [*three, decide("f4", REJECT)]).complete


def test_a_run_without_verified_findings_is_never_complete() -> None:
    run = mixed_run()
    run.findings = []
    review = build_review(run, [])
    assert review.findings_total == 0 and not review.complete


def test_decisions_come_back_in_finding_order_and_the_later_one_wins() -> None:
    decisions = [
        decide("f4", ACCEPT),
        decide("f1", ACCEPT, minutes=1),
        decide("f1", REJECT, minutes=2),
    ]
    review = build_review(mixed_run(), decisions)
    assert [(d.finding_id, d.value) for d in review.decisions] == [("f1", REJECT), ("f4", ACCEPT)]
    assert review.decided == 2
