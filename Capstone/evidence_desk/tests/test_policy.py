"""The verdict rule and the complete/partial/failed rule (PROMPT.md 4.9)."""

from itertools import product

import pytest

from app.core.models import Claim, Confidence, Finding, RunStatus, Stance, Verdict
from app.core.policy import (
    PROVENANCE_NOTE,
    STATUS_NOTES,
    VERDICT_LABELS,
    VERDICT_NOTES,
    claim_verdict,
    run_status,
)


def _finding(stance: Stance, verified: bool = True, index: int = 1) -> Finding:
    return Finding(
        id=f"f{index}",
        claim_id="c1",
        statement="A statement.",
        stance=stance,
        evidence_ids=["e1"] if verified else [],
        confidence=Confidence.medium,
        rationale="Because.",
        verified=verified,
    )


def _expected(supports: bool, challenges: bool, context: bool) -> Verdict:
    if supports and challenges:
        return Verdict.mixed
    if supports:
        return Verdict.supported
    if challenges:
        return Verdict.challenged
    if context:
        return Verdict.unjudged
    return Verdict.not_addressed


@pytest.mark.parametrize(
    ("supports", "challenges", "context"), list(product([False, True], repeat=3))
)
def test_verdict_for_every_combination_of_verified_stances(
    supports: bool, challenges: bool, context: bool
) -> None:
    findings = []
    if supports:
        findings.append(_finding(Stance.supports, index=1))
    if challenges:
        findings.append(_finding(Stance.challenges, index=2))
    if context:
        findings.append(_finding(Stance.context, index=3))
    assert claim_verdict(findings) == _expected(supports, challenges, context)


@pytest.mark.parametrize(
    ("verified_stances", "unverified_stances", "expected"),
    [
        ([], [Stance.supports], Verdict.not_addressed),
        ([], [Stance.supports, Stance.challenges, Stance.context], Verdict.not_addressed),
        ([Stance.supports], [Stance.challenges], Verdict.supported),
        ([Stance.challenges], [Stance.supports], Verdict.challenged),
        ([Stance.context], [Stance.supports, Stance.challenges], Verdict.unjudged),
    ],
)
def test_unverified_findings_are_ignored(
    verified_stances: list[Stance], unverified_stances: list[Stance], expected: Verdict
) -> None:
    findings = [_finding(stance, index=i) for i, stance in enumerate(verified_stances)]
    findings += [
        _finding(stance, verified=False, index=10 + i)
        for i, stance in enumerate(unverified_stances)
    ]
    assert claim_verdict(findings) == expected


def _claims(*verdicts: Verdict | None) -> list[Claim]:
    return [
        Claim(id=f"c{i}", text=f"Claim number {i} about revenue.", verdict=verdict)
        for i, verdict in enumerate(verdicts, start=1)
    ]


CLEAN = {
    "sources_requested": 3,
    "sources_extracted": 3,
    "claims": _claims(Verdict.supported, Verdict.challenged, Verdict.mixed),
    "withheld_findings": 0,
    "engine_fallbacks": 0,
    "time_limit_hit": False,
}


def test_complete_when_nothing_limits_the_brief() -> None:
    assert run_status(**CLEAN) == (RunStatus.complete, [])


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"sources_extracted": 2}, "1 of 3 source(s) could not be read."),
        ({"withheld_findings": 2}, "2 finding(s) had no verified excerpt and were withheld."),
        (
            {"claims": _claims(Verdict.supported, Verdict.not_addressed, Verdict.mixed)},
            "1 of 3 claim(s) have no verified evidence in the passages retrieved.",
        ),
        (
            {"claims": _claims(Verdict.supported, None, Verdict.mixed)},
            "1 of 3 claim(s) have no verified evidence in the passages retrieved.",
        ),
        (
            {"claims": _claims(Verdict.unjudged, Verdict.unjudged, Verdict.mixed)},
            "2 of 3 claim(s) have relevant passages but no judged stance.",
        ),
        (
            {"engine_fallbacks": 1},
            "The model engine failed for 1 step(s); the deterministic engine was used for those.",
        ),
        ({"time_limit_hit": True}, "The run time limit was reached before every step finished."),
    ],
)
def test_each_reason_alone_makes_the_run_partial(change: dict, reason: str) -> None:
    assert run_status(**{**CLEAN, **change}) == (RunStatus.partial, [reason])


def test_reasons_combine_in_order() -> None:
    status, reasons = run_status(
        sources_requested=4,
        sources_extracted=1,
        claims=_claims(Verdict.not_addressed, Verdict.unjudged, Verdict.supported, None),
        withheld_findings=3,
        engine_fallbacks=2,
        time_limit_hit=True,
    )
    assert status == RunStatus.partial
    assert reasons == [
        "3 of 4 source(s) could not be read.",
        "3 finding(s) had no verified excerpt and were withheld.",
        "2 of 4 claim(s) have no verified evidence in the passages retrieved.",
        "1 of 4 claim(s) have relevant passages but no judged stance.",
        "The model engine failed for 2 step(s); the deterministic engine was used for those.",
        "The run time limit was reached before every step finished.",
    ]


@pytest.mark.parametrize("requested", [0, 1, 3])
def test_failed_when_no_source_was_read(requested: int) -> None:
    status, reasons = run_status(
        **{**CLEAN, "sources_requested": requested, "sources_extracted": 0}
    )
    assert status == RunStatus.failed
    assert reasons == ["No source could be retrieved and read; no brief was produced."]


def test_wording_covers_every_status_and_verdict() -> None:
    assert set(STATUS_NOTES) == set(RunStatus)
    assert set(VERDICT_LABELS) == set(Verdict) == set(VERDICT_NOTES)
    assert all(text.strip() for text in [*STATUS_NOTES.values(), *VERDICT_LABELS.values()])
    assert all(text.strip() for text in VERDICT_NOTES.values())
    assert "SEC" in PROVENANCE_NOTE
