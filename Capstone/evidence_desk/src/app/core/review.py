"""A reviewer's decisions on one run, and the verdicts that follow from them.

Pure: no store, no clock. Only a verified finding of the run can be decided;
any other decision is ignored and never counted. The reviewed verdict of a
claim is :func:`app.core.policy.claim_verdict` over the findings the reviewer
accepted, so the reviewer's verdict and the engine's follow the same rule.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.models import Decision, DecisionValue, Finding, Review, ReviewedClaim, Run
from app.core.policy import claim_verdict


def _valid_decisions(run: Run, decisions: Sequence[Decision]) -> dict[str, Decision]:
    """The decisions that name a verified finding of ``run``, by finding id.

    When one finding has several decisions, the latest by ``decided_at`` wins.
    """
    verified = {finding.id for finding in run.findings if finding.verified}
    chosen: dict[str, Decision] = {}
    for decision in decisions:
        if decision.run_id != run.id or decision.finding_id not in verified:
            continue
        held = chosen.get(decision.finding_id)
        if held is None or decision.decided_at >= held.decided_at:
            chosen[decision.finding_id] = decision
    return chosen


def build_review(run: Run, decisions: Sequence[Decision]) -> Review:
    """Every valid decision on ``run`` and, per claim, the verdict that follows from them.

    ``reviewed_verdict`` is None while none of the claim's findings is decided.
    ``complete`` is true when the run has verified findings and every one is decided.
    """
    chosen = _valid_decisions(run, decisions)
    verified: list[Finding] = [finding for finding in run.findings if finding.verified]
    claims: list[ReviewedClaim] = []
    for claim in run.claims:
        own = [finding for finding in verified if finding.claim_id == claim.id]
        values = [chosen[f.id].value if f.id in chosen else None for f in own]
        pairs = zip(own, values, strict=True)
        accepted = [f for f, value in pairs if value == DecisionValue.accepted]
        rejected = sum(1 for value in values if value == DecisionValue.rejected)
        undecided = sum(1 for value in values if value is None)
        decided_any = len(accepted) + rejected > 0
        claims.append(
            ReviewedClaim(
                claim_id=claim.id,
                engine_verdict=claim.verdict,
                reviewed_verdict=claim_verdict(accepted) if decided_any else None,
                accepted=len(accepted),
                rejected=rejected,
                undecided=undecided,
            )
        )
    ordered = [chosen[finding.id] for finding in verified if finding.id in chosen]
    return Review(
        run_id=run.id,
        decisions=ordered,
        claims=claims,
        findings_total=len(verified),
        decided=len(ordered),
        complete=bool(verified) and len(ordered) == len(verified),
    )
