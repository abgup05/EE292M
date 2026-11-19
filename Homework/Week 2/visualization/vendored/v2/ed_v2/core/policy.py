"""The rules that decide what a run may claim, and the words used to say it.

One home for the verdict rule, the complete/partial rule, and the status and
verdict wording. The pipeline applies these rules; the API hands the wording
to every view, so the page and the Markdown export cannot disagree.
"""

from __future__ import annotations

from ed_v2.core.models import Claim, Finding, RunStatus, Stance, Verdict

STATUS_NOTES: dict[RunStatus, str] = {
    RunStatus.running: "The run is in progress.",
    RunStatus.complete: (
        "Every claim has verified evidence from the sources requested, and nothing was withheld."
    ),
    RunStatus.partial: (
        "Part of the thesis could not be assessed with verified evidence. "
        "The reasons are listed under coverage limits."
    ),
    RunStatus.failed: "No source could be read, so there is no brief.",
}

VERDICT_LABELS: dict[Verdict, str] = {
    Verdict.supported: "Supported",
    Verdict.challenged: "Challenged",
    Verdict.mixed: "Mixed evidence",
    Verdict.unjudged: "Passages found, not judged",
    Verdict.not_addressed: "Not addressed",
}

VERDICT_NOTES: dict[Verdict, str] = {
    Verdict.supported: "Verified excerpts support the claim and none challenge it.",
    Verdict.challenged: "Verified excerpts challenge the claim and none support it.",
    Verdict.mixed: "Verified excerpts point both ways.",
    Verdict.unjudged: (
        "Relevant passages were found and quoted, but no engine judged whether they "
        "support or challenge the claim."
    ),
    Verdict.not_addressed: "No verified excerpt in the passages retrieved bears on the claim.",
}

PROVENANCE_NOTE = (
    "Evidence comes from the company's own filings with the SEC. It shows what the company "
    "reported, not whether an outside party agrees."
)


def claim_verdict(findings: list[Finding]) -> Verdict:
    """The verdict for one claim, from its verified findings alone.

    A model proposes a stance per finding; it never sets the verdict. Findings
    that did not survive the citation gate do not count.
    """
    verified = [finding for finding in findings if finding.verified]
    supports = any(finding.stance == Stance.supports for finding in verified)
    challenges = any(finding.stance == Stance.challenges for finding in verified)
    if supports and challenges:
        return Verdict.mixed
    if supports:
        return Verdict.supported
    if challenges:
        return Verdict.challenged
    if verified:
        return Verdict.unjudged
    return Verdict.not_addressed


def run_status(
    *,
    sources_requested: int,
    sources_extracted: int,
    claims: list[Claim],
    withheld_findings: int,
    engine_fallbacks: int,
    time_limit_hit: bool,
) -> tuple[RunStatus, list[str]]:
    """Complete only when nothing limits the brief; otherwise partial, with each reason.

    Failed when no source at all was read. The reasons are sentences a reader
    can act on, each with its denominator.
    """
    if sources_extracted == 0:
        return RunStatus.failed, ["No source could be retrieved and read; no brief was produced."]
    reasons: list[str] = []
    if sources_extracted < sources_requested:
        reasons.append(
            f"{sources_requested - sources_extracted} of {sources_requested} source(s) "
            "could not be read."
        )
    if withheld_findings:
        reasons.append(f"{withheld_findings} finding(s) had no verified excerpt and were withheld.")
    total = len(claims)
    unaddressed = sum(1 for claim in claims if claim.verdict in (None, Verdict.not_addressed))
    if unaddressed:
        reasons.append(
            f"{unaddressed} of {total} claim(s) have no verified evidence in the passages "
            "retrieved."
        )
    unjudged = sum(1 for claim in claims if claim.verdict == Verdict.unjudged)
    if unjudged:
        reasons.append(
            f"{unjudged} of {total} claim(s) have relevant passages but no judged stance."
        )
    if engine_fallbacks:
        reasons.append(
            f"The model engine failed for {engine_fallbacks} step(s); "
            "the deterministic engine was used for those."
        )
    if time_limit_hit:
        reasons.append("The run time limit was reached before every step finished.")
    return (RunStatus.partial if reasons else RunStatus.complete), reasons
