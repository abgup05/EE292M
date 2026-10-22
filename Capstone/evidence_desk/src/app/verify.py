"""Citation verification: the gate between synthesis and anything a client sees.

A finding is verified only when at least one of its evidence records exists,
points at a stored source, and quotes an exact substring of that source's
extracted text. Everything else is marked unsupported and reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import Evidence, Finding


@dataclass
class VerificationResult:
    """Verified findings, unsupported findings, surviving evidence and the reasons."""

    verified: list[Finding] = field(default_factory=list)
    unsupported: list[Finding] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def verify_findings(
    findings: list[Finding],
    evidence: list[Evidence],
    source_text: dict[str, str],
) -> VerificationResult:
    """Check every citation against the stored source text.

    ``source_text`` maps source ID to the exact extracted text. Excerpts are
    compared byte-for-byte; whitespace differences do not count as a match.
    """
    result = VerificationResult()
    by_id = {item.id: item for item in evidence}
    for finding in findings:
        kept: list[str] = []
        source_ids: set[str] = set()
        for evidence_id in finding.evidence_ids:
            item = by_id.get(evidence_id)
            if item is None:
                result.problems.append(f"{finding.id}: evidence {evidence_id} does not exist")
                continue
            text = source_text.get(item.source_id)
            if text is None:
                result.problems.append(f"{finding.id}: source {item.source_id} is not stored")
                continue
            if not item.excerpt or item.excerpt not in text:
                result.problems.append(
                    f"{finding.id}: excerpt {evidence_id} is not an exact substring of its source"
                )
                continue
            kept.append(evidence_id)
            source_ids.add(item.source_id)
            result.evidence.append(item)
        if kept:
            result.verified.append(
                finding.model_copy(
                    update={
                        "evidence_ids": kept,
                        "verified": True,
                        "single_source": len(source_ids) == 1,
                    }
                )
            )
        else:
            result.unsupported.append(finding.model_copy(update={"verified": False}))
    return result
