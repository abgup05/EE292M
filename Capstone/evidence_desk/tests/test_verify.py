"""Citation verification: a finding survives only with an exact, existing excerpt."""

from app.models import Confidence, Evidence, Finding, Stance
from app.verify import verify_findings

SOURCE_TEXT = {
    "src-1": "Overview\nThe framework is voluntary. It has four functions.",
    "src-2": "Summary\nGenerative AI raises new risks for organizations.",
}


def evidence(eid: str, source: str, excerpt: str, finding: str) -> Evidence:
    return Evidence(
        id=eid,
        source_id=source,
        excerpt=excerpt,
        locator="Overview",
        stance=Stance.supports,
        finding_id=finding,
    )


def finding(fid: str, *evidence_ids: str) -> Finding:
    return Finding(
        id=fid,
        statement="The framework is voluntary.",
        evidence_ids=list(evidence_ids),
        confidence=Confidence.medium,
        rationale="One primary source states it directly.",
    )


def test_exact_excerpt_keeps_finding_verified() -> None:
    result = verify_findings(
        [finding("f-1", "e-1")],
        [evidence("e-1", "src-1", "The framework is voluntary.", "f-1")],
        SOURCE_TEXT,
    )
    assert [f.id for f in result.verified] == ["f-1"]
    assert result.verified[0].verified is True
    assert result.unsupported == []
    assert [e.id for e in result.evidence] == ["e-1"]


def test_corrupted_excerpt_marks_finding_unsupported() -> None:
    result = verify_findings(
        [finding("f-1", "e-1")],
        [evidence("e-1", "src-1", "The framework is mandatory.", "f-1")],
        SOURCE_TEXT,
    )
    assert result.verified == []
    assert [f.id for f in result.unsupported] == ["f-1"]
    assert result.unsupported[0].verified is False
    assert result.evidence == []
    assert any("not an exact" in problem for problem in result.problems)


def test_missing_evidence_id_marks_finding_unsupported() -> None:
    result = verify_findings([finding("f-1", "e-missing")], [], SOURCE_TEXT)
    assert result.verified == []
    assert [f.id for f in result.unsupported] == ["f-1"]
    assert any("e-missing" in problem for problem in result.problems)


def test_evidence_for_unknown_source_is_dropped() -> None:
    result = verify_findings(
        [finding("f-1", "e-1")],
        [evidence("e-1", "src-9", "The framework is voluntary.", "f-1")],
        SOURCE_TEXT,
    )
    assert result.verified == []
    assert [e.id for e in result.evidence] == []


def test_bad_evidence_is_dropped_but_good_evidence_keeps_finding() -> None:
    result = verify_findings(
        [finding("f-1", "e-1", "e-2")],
        [
            evidence("e-1", "src-1", "The framework is voluntary.", "f-1"),
            evidence("e-2", "src-2", "This sentence is not on the page.", "f-1"),
        ],
        SOURCE_TEXT,
    )
    assert [f.id for f in result.verified] == ["f-1"]
    assert result.verified[0].evidence_ids == ["e-1"]
    assert [e.id for e in result.evidence] == ["e-1"]


def test_single_source_findings_are_flagged() -> None:
    one = verify_findings(
        [finding("f-1", "e-1")],
        [evidence("e-1", "src-1", "The framework is voluntary.", "f-1")],
        SOURCE_TEXT,
    )
    assert one.verified[0].single_source is True
    two = verify_findings(
        [finding("f-1", "e-1", "e-2")],
        [
            evidence("e-1", "src-1", "The framework is voluntary.", "f-1"),
            evidence("e-2", "src-2", "Generative AI raises new risks", "f-1"),
        ],
        SOURCE_TEXT,
    )
    assert two.verified[0].single_source is False


def test_whitespace_differences_do_not_count_as_exact() -> None:
    result = verify_findings(
        [finding("f-1", "e-1")],
        [evidence("e-1", "src-1", "The framework  is voluntary.", "f-1")],
        SOURCE_TEXT,
    )
    assert result.verified == []
