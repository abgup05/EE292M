"""The verdict rule and the complete/partial/failed rule (PROMPT.md 4.9)."""

from datetime import UTC, datetime
from itertools import product

import pytest

from app.core.models import (
    Claim,
    Confidence,
    DecisionValue,
    ExtractionStatus,
    Finding,
    FindingChecks,
    RunStatus,
    Source,
    SourceKind,
    Stance,
    Verdict,
)
from app.core.policy import (
    DECISION_LABELS,
    PROVENANCE_NOTE,
    REVIEW_NOTE,
    STATUS_NOTES,
    UNDECIDED,
    VERDICT_LABELS,
    VERDICT_NOTES,
    claim_verdict,
    mark_counted,
    provenance_note,
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
        ({"withheld_findings": 2}, "2 finding(s) could not be verified and were withheld."),
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
        (
            {"unchecked_findings": 2, "verified_findings": 5},
            "The meaning check could not run for 2 of 5 verified finding(s); for those, whether "
            "the excerpts support the statement rests on the engine's reading alone.",
        ),
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
        "3 finding(s) could not be verified and were withheld.",
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


def test_decision_wording_covers_every_value_and_the_undecided_state() -> None:
    assert DECISION_LABELS == {
        DecisionValue.accepted.value: "Accepted",
        DecisionValue.rejected.value: "Rejected",
        UNDECIDED: "Undecided",
    }
    assert REVIEW_NOTE.count(".") == 1 and REVIEW_NOTE.endswith(".")
    assert "accepted" in REVIEW_NOTE and "undecided" in REVIEW_NOTE


# A finding with no passage (referee 1 of version 4, finding 1)

FIGURE_ONLY_NOTE = (
    "backed by reported figures only and not confirmed by the meaning check: counted as context"
)


def _figure_only(stance: Stance, support: str = "unchecked", index: int = 9) -> Finding:
    return Finding(
        id=f"f{index}",
        claim_id="c1",
        statement="Revenue grew 65% in fiscal 2026.",
        stance=stance,
        evidence_ids=[],
        confidence=Confidence.medium,
        rationale="These figures are company-wide.",
        verified=True,
        metric_ids=["revenue_yoy:annual:2026-01-25"],
        checks=FindingChecks(quotes="none", numbers="passed", support=support),
    )


@pytest.mark.parametrize(
    ("support", "expected"),
    [
        ("unchecked", Verdict.supported),
        ("partly", Verdict.supported),
        ("passed", Verdict.mixed),
    ],
)
def test_a_figure_only_challenge_moves_the_verdict_only_when_the_meaning_check_passed(
    support: str, expected: Verdict
) -> None:
    # The referee's case: two supporting findings with quotes, one challenge with a figure only.
    findings = [
        _finding(Stance.supports, index=1),
        _finding(Stance.supports, index=2),
        _figure_only(Stance.challenges, support),
    ]
    assert claim_verdict(findings) == expected


def test_a_figure_only_finding_alone_leaves_the_claim_unjudged_until_checked() -> None:
    assert claim_verdict([_figure_only(Stance.supports)]) == Verdict.unjudged
    assert claim_verdict([_figure_only(Stance.supports, "passed")]) == Verdict.supported


def test_mark_counted_records_the_stance_the_verdict_used_and_why() -> None:
    quoted = _finding(Stance.challenges, index=1)
    unchecked = _figure_only(Stance.supports, index=2)
    confirmed = _figure_only(Stance.challenges, "passed", index=3)
    context = _figure_only(Stance.context, index=4)
    withheld = _finding(Stance.supports, verified=False, index=5)
    mark_counted([quoted, unchecked, confirmed, context, withheld])
    assert (quoted.counted_as, quoted.count_note) == (Stance.challenges, "")
    assert (unchecked.counted_as, unchecked.count_note) == (Stance.context, FIGURE_ONLY_NOTE)
    assert (confirmed.counted_as, confirmed.count_note) == (Stance.challenges, "")
    assert (context.counted_as, context.count_note) == (Stance.context, "")
    assert (withheld.counted_as, withheld.count_note) == (None, "")


# Thin evidence (referee 1 of version 4, finding 4)


def test_a_filing_mostly_outside_item_headings_makes_the_run_partial() -> None:
    status, reasons = run_status(**CLEAN, thin_filings=1, filings_read=3)
    assert status == RunStatus.partial
    assert reasons == [
        "Item headings were not found for most of 1 of 3 filing(s); passages from it are "
        "located by sub-heading only."
    ]


def test_unreadable_reported_figures_make_the_run_partial() -> None:
    status, reasons = run_status(**CLEAN, facts_error="EDGAR answered HTTP 503")
    assert status == RunStatus.partial
    assert reasons == [
        "The reported figures (XBRL company facts) could not be read (EDGAR answered HTTP 503); "
        "findings rest on the filing text alone."
    ]


# Provenance (referee 1 of version 4, finding 6)


def _read_source(source_id: str, kind: SourceKind, status: ExtractionStatus) -> Source:
    return Source(
        id=source_id,
        kind=kind,
        title=source_id,
        publisher="",
        url=f"https://example.com/{source_id}",
        retrieved_at=datetime(2026, 11, 17, tzinfo=UTC),
        content_hash="",
        extraction_status=status,
    )


def test_the_provenance_note_says_when_a_page_you_added_was_read() -> None:
    filing = _read_source("s1", SourceKind.sec_filing, ExtractionStatus.extracted)
    facts = _read_source("s2", SourceKind.sec_xbrl, ExtractionStatus.extracted)
    page = _read_source("s3", SourceKind.public_html, ExtractionStatus.extracted)
    unread = _read_source("s4", SourceKind.public_html, ExtractionStatus.failed)
    assert provenance_note([filing, facts, unread]) == PROVENANCE_NOTE
    assert provenance_note([filing, facts, page, unread]) == (
        "Evidence comes from the company's SEC filings and from 1 page you added; each excerpt "
        "names its source. A page you added is not a filing."
    )
    second = page.model_copy(update={"id": "s5"})
    assert "from 2 pages you added" in provenance_note([filing, page, second])


def test_the_complete_note_says_what_complete_means_and_what_it_does_not() -> None:
    """The third referee, finding 1: the note promised evidence "from the sources requested"."""
    note = STATUS_NOTES[RunStatus.complete]
    assert "sources requested" not in note
    assert "Every stage ran on every source that was read" in note
    assert "not a measure of how much evidence stands behind a verdict" in note
