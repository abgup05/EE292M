"""The meaning check's pure part: what a second model is shown, and what its judgements do.

The quote check and the number check are mechanical: a real sentence that the
engine misread passes both. A :class:`~app.core.ports.Checker` reads each
verified finding again, from what a reader would see (the statement, its
stance, its verified excerpts and its cited figures) and never from the
engine's rationale or confidence. :func:`check_items` builds that view;
:func:`apply_judgements` turns the checker's judgements into the record:
"supported" passes, "partly" is kept and marked, "not_supported" is withheld
with the checker's reason.

Pure: no network, no I/O, no clock.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ed_v7.core import policy
from ed_v7.core.metric_models import Metric
from ed_v7.core.models import Evidence, Finding
from ed_v7.core.ports import CheckExcerpt, CheckFigure, CheckItem, Judgement, SupportVerdict

SUPPORT_STATUS: dict[SupportVerdict, str] = {
    SupportVerdict.supported: "passed",
    SupportVerdict.partly: "partly",
    SupportVerdict.not_supported: "failed",
}


class IncompleteJudgements(ValueError):
    """A checker's answer does not judge every item exactly once; the message is safe to show."""


def check_items(
    findings: Sequence[Finding],
    evidence: Mapping[str, Evidence],
    figures: Mapping[str, Metric],
) -> list[CheckItem]:
    """One :class:`CheckItem` per finding, in order: statement, stance, excerpts and figures.

    ``evidence`` maps evidence ids to the run's verified excerpts; ``figures``
    maps metric ids to the figures that were offered. Nothing else of a
    finding crosses: not its rationale, not its confidence.
    """
    items: list[CheckItem] = []
    for finding in findings:
        excerpts = tuple(
            CheckExcerpt(text=evidence[eid].excerpt, locator=evidence[eid].locator)
            for eid in finding.evidence_ids
            if eid in evidence
        )
        cited = tuple(
            CheckFigure(label=metric.label, period=metric.period_label, display=metric.display)
            for mid in finding.metric_ids
            if (metric := figures.get(mid)) is not None
        )
        items.append(
            CheckItem(
                statement=finding.statement, stance=finding.stance, excerpts=excerpts, figures=cited
            )
        )
    return items


def by_index(judgements: Sequence[Judgement], count: int) -> dict[int, Judgement]:
    """The judgements keyed by item index.

    Raises :class:`IncompleteJudgements` unless each of the ``count`` items is
    judged exactly once.
    """
    keyed: dict[int, Judgement] = {}
    for judgement in judgements:
        if not 0 <= judgement.index < count:
            raise IncompleteJudgements(f"the checker judged an unknown finding ({judgement.index})")
        if judgement.index in keyed:
            raise IncompleteJudgements("the checker judged one finding twice")
        keyed[judgement.index] = judgement
    if len(keyed) != count:
        raise IncompleteJudgements(
            f"the checker judged {len(keyed)} of {count} finding(s); every one must be judged"
        )
    return keyed


@dataclass
class MeaningResult:
    """One claim's verified findings after the meaning check.

    ``kept`` stay verified (supported or partly supported); ``withheld`` were
    judged unsupported and are no longer verified; ``dropped_evidence`` are
    the ids of the withheld findings' excerpts, which leave the run.
    """

    kept: list[Finding] = field(default_factory=list)
    withheld: list[Finding] = field(default_factory=list)
    dropped_evidence: set[str] = field(default_factory=set)
    checked: int = 0
    partly: int = 0
    failed: int = 0


def withheld_reason(reason: str) -> str:
    """The reason a finding the checker judged unsupported is withheld, with the checker's words."""
    return policy.MEANING_WITHHELD.format(reason=reason.strip().rstrip("."))


def apply_judgements(findings: Sequence[Finding], judgements: Sequence[Judgement]) -> MeaningResult:
    """Mark each finding with its judgement; withhold the ones judged unsupported.

    ``judgements`` must judge every finding exactly once, by its index in
    ``findings`` (:class:`IncompleteJudgements` otherwise, and nothing is
    changed). Each finding's ``checks.support`` becomes "passed", "partly" or
    "failed" and ``checks.support_detail`` the reason. A failed finding is
    withheld: ``verified`` False, the reason in ``withheld_reason``, no
    evidence ids, no filings cited.
    """
    keyed = by_index(judgements, len(findings))
    result = MeaningResult()
    for index, finding in enumerate(findings):
        judgement = keyed[index]
        finding.checks.support = SUPPORT_STATUS[judgement.verdict]
        finding.checks.support_detail = judgement.reason
        result.checked += 1
        if judgement.verdict == SupportVerdict.not_supported:
            result.failed += 1
            result.dropped_evidence.update(finding.evidence_ids)
            finding.verified = False
            finding.evidence_ids = []
            finding.filings_cited = 0
            finding.withheld_reason = withheld_reason(judgement.reason)
            result.withheld.append(finding)
            continue
        if judgement.verdict == SupportVerdict.partly:
            result.partly += 1
        result.kept.append(finding)
    return result
