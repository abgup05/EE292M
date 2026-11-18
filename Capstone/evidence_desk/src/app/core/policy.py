"""The rules that decide what a run may claim, and the words used to say it.

One home for the verdict rule, the complete/partial rule, and the status and
verdict wording. The pipeline applies these rules; the API hands the wording
to every view, so the page and the Markdown export cannot disagree.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.core.models import (
    Claim,
    DecisionValue,
    ExtractionStatus,
    Finding,
    RunStatus,
    Source,
    SourceKind,
    Stance,
    Verdict,
)

STATUS_NOTES: dict[RunStatus, str] = {
    RunStatus.running: "The run is in progress.",
    RunStatus.complete: (
        "Every stage ran on every source that was read: each claim has verified evidence and "
        "nothing was withheld. This is not a measure of how much evidence stands behind a verdict."
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

# A verified finding with no decision yet; not a DecisionValue, because nothing is stored for it.
UNDECIDED = "undecided"

DECISION_LABELS: dict[str, str] = {
    DecisionValue.accepted.value: "Accepted",
    DecisionValue.rejected.value: "Rejected",
    UNDECIDED: "Undecided",
}

REVIEW_NOTE = (
    "The verdict after your review follows by the same rule from the findings you accepted, "
    "and undecided findings do not count toward it."
)

# The note for a run that read only the company's SEC filings and XBRL facts, and the one
# shown before any run. A run's own note is built by provenance_note from what it read.
PROVENANCE_NOTE = (
    "Evidence comes from the company's own filings with the SEC. It shows what the company "
    "reported, not whether an outside party agrees."
)
PROVENANCE_WITH_PAGES = (
    "Evidence comes from the company's SEC filings and from {pages} you added; each excerpt "
    "names its source. A page you added is not a filing."
)


FIGURES_NOTE = (
    "Reported figures are computed by the backend from the XBRL facts the company filed with "
    "the SEC; each shows the facts it used and its arithmetic."
)
# Reported figures are a second path to the numbers, not a source of excerpts: when they
# cannot be read the run continues from the filing text, and is partial, with this reason.
FACTS_UNAVAILABLE = (
    "The reported figures (XBRL company facts) could not be read ({error}); "
    "findings rest on the filing text alone."
)
# Figures tagged in a filing's own inline XBRL, offered only when the run asks for them. A filing
# whose tags cannot be read leaves the run to the rest, and the run is partial with this reason.
TAGGED_UNAVAILABLE = (
    "The tagged figures of the {form} for the period ended {period_end} could not be read "
    "({error}); its segment, product, geography and customer figures were not offered."
)
SUMMARY_REPLACED = (
    "The model's summary was replaced by the template summary: {numbers} in it "
    "is not in any verified finding or reported figure."
)
# A filing whose text mostly sits outside numbered Item headings: its passages carry
# sub-heading locators only, so the run is partial.
THIN_FILINGS = (
    "Item headings were not found for most of {thin} of {read} filing(s); passages from "
    "{pronoun} are located by sub-heading only."
)

# Every number an engine writes beside the evidence is checked like a statement's. A
# finding's reason, or a claim's commentary, that cites a number its evidence does not hold
# is replaced by one of these; the finding and the verdict stand.
REASON_WITHHELD = (
    "[Reason withheld: it cited a number ({numbers}) that is in neither the finding's quotes "
    "nor its cited figures.]"
)
REASON_NUMBER_DETAIL = "in the reason: {number} was not found in the quotes or the cited figures"
COMMENTARY_WITHHELD = (
    "[Commentary withheld: it cited a number ({numbers}) that is in none of the claim's "
    "verified quotes or cited figures.]"
)
ENTRIES_DROPPED = (
    "{count} unknown(s) or next step(s) written by the engine were dropped: each cited a "
    "number that is in no verified excerpt, finding or reported figure."
)

# A verified finding with no excerpt rests on reported figures alone. Whether a figure bears
# on the claim is a question of meaning, so its stance counts toward the verdict only when
# the meaning check confirmed it ("passed"); otherwise it counts as context.
FIGURE_ONLY_NOTE = (
    "backed by reported figures only and not confirmed by the meaning check: counted as context"
)

# The meaning check: a second model reads each verified finding's excerpts and figures, without
# the engine's reasoning, and judges whether they support the statement. A finding it judges
# unsupported is withheld; one it judges partly supported is kept, counts toward the verdict
# (unless it rests on reported figures alone: see FIGURE_ONLY_NOTE) and is shown as such (it
# does not make the run partial: the evidence still points the way stated). A check that was
# configured and could not run leaves its findings unchecked and makes the run partial, as an
# engine that fell back does: the run did less than it was set up to do. Having no checker at
# all is a configuration, shown on the run, and does not.
SUPPORT_LABELS: dict[str, str] = {
    "passed": "supported",
    "partly": "partly supported",
    "failed": "not supported",
    "unchecked": "not checked",
}
MEANING_WITHHELD = (
    "a second model judged that its evidence does not support the statement: {reason}"
)
MEANING_UNCHECKED_ERROR = (
    "The meaning check could not run for {claims} claim(s), so {findings} finding(s) were "
    "left unchecked: {reasons}."
)
MEANING_CHECK_FAILED = (
    "The meaning check could not run for {findings} of {verified} verified finding(s); for "
    "those, whether the excerpts support the statement rests on the engine's reading alone."
)
MEANING_SAME_MODEL = (
    "The meaning check used the same model as the engine; it is not an independent reading."
)
NO_CHECKER_NOTE = "No second model checked the findings' meaning."

# Current reports (8-K) since the annual report (app.core.events). Reported, never withheld:
# none of these changes a verdict or the run's status.
AS_OF_LINE = (
    "Evidence as of {date} ({form}), {days} before {when}. "
    "Newest periodic report: {periodic_form} filed {periodic_date}."
)
AS_OF_NO_PERIODIC = "Evidence as of {date} ({form}), {days} before {when}."
AS_OF_RUN = "this run"
AS_OF_TODAY = "today"
# A run as of a past date (ThesisRequest.as_of): its evidence is dated against that day.
AS_OF_REQUESTED = "the date this run is as of"
AS_OF_REQUESTED_NOTE = (
    "This run is as of {date}: it read only the filings, 8-Ks and XBRL facts filed by then, "
    "and nothing filed later."
)
AS_OF_NOTHING_READ = "No filing was read, so the evidence has no date."

# Computed claims (app.core.claimtest, app.core.claim_eval). A compiled claim's outcome is
# verified evidence computed from the facts: it holds (counts as support), fails (counts as
# a challenge) or cannot be computed (counts as nothing, and says why).
COMPUTED_LABELS: dict[str, str] = {
    "holds": "Holds",
    "fails": "Fails",
    "cannot_compute": "Cannot be computed",
}
COMPUTED_COUNTS: dict[str, str] = {"holds": "supports", "fails": "challenges"}
COMPUTED_NO_HISTORY = (
    "A share of revenue is read from the newest filing's tagged breakdowns, which have no "
    "history in the company facts; no history is drawn."
)
COMPUTED_HISTORY_NOTE = (
    "The outcome as of each of the {points} 10-K and 10-Q filing dates in the {years} years to "
    "{last}, each from the facts filed by that date{capped}; it flipped {flips} time(s)."
)
COMPUTED_NOT_NUMERIC = "Not a numeric claim this version computes: {reason}."
EVENT_COUNTS = (
    "{listed} 8-K(s) filed since the annual report of {annual}: {read} read, {failed} could not "
    "be read, {capped} not read because of the cap of {cap} per run, {index_only} routine 8-K(s) "
    "filed before the newest periodic report listed from the index only."
)
EVENT_COUNTS_TIME = " {out_of_time} not read because the run time limit came first."
EVENT_INDEX_UNREAD_COUNTS = "EDGAR's list of 8-Ks could not be read ({error})."
PREDATES_LABEL = "Predates the {form} of {date}, {items}"
EVENT_CAUTION = (
    "The evidence for this verdict was filed before the {form} of {date} ({items}), which "
    "reports {words}. Read that filing before relying on the verdict."
)
EVENT_ABSENT = (
    "No 8-K filed since {annual} reports {subjects}. The newest filing read is dated {newest}; "
    "anything later is not in the record."
)
EVENT_NOT_READ = "The {form} of {date} reports {items}, but its text was not read: {reason}."
EVENT_INDEX_UNREAD = (
    "EDGAR's list of 8-Ks could not be read ({error}), so whether one filed since {annual} "
    "reports {subjects} is not known."
)
# What became of each 8-K a run listed, keyed by EventStatus value: the page, the brief and
# `make events` say it in these words.
EVENT_STATUS_LABELS = {
    "read": "read",
    "failed": "could not be read",
    "capped": "not read: the cap per run came first",
    "out_of_time": "not read: the run time limit came first",
    "index_only": "listed from the index only",
}
EVENT_KIND_LABELS = {"substantive": "substantive", "routine": "routine"}
EVENTS_NO_ANNUAL = "No annual report was read, so no 8-K was listed."
EVENTS_HEADING = "Since the annual report"
EVENTS_NONE = "EDGAR lists no 8-K filed since the annual report of {annual}."
EVENTS_NOTE = (
    "Current reports (8-K) the company filed after the annual report this run read, newest "
    "first, as EDGAR's index lists them. The opening sentences of each item are quoted from "
    "the 8-Ks read; exhibits, such as a press release, are not read."
)


def counted_stance(finding: Finding) -> Stance | None:
    """The stance the verdict rule uses for ``finding``; None when it is not verified.

    A verified finding counts as its own stance when it has at least one verified
    excerpt, or when the meaning check passed it. One that rests on reported figures
    alone and was not confirmed (unchecked, or only partly supported) counts as context.
    """
    if not finding.verified:
        return None
    if finding.evidence_ids or finding.checks.support == "passed":
        return finding.stance
    return Stance.context


def mark_counted(findings: Iterable[Finding]) -> None:
    """Record on each finding the stance the verdict rule uses, and why when it was demoted.

    Sets ``counted_as`` (:func:`counted_stance`) and ``count_note``
    (:data:`FIGURE_ONLY_NOTE` when a supporting or challenging finding counts as
    context; empty otherwise), so no view has to work it out.
    """
    for finding in findings:
        finding.counted_as = counted_stance(finding)
        demoted = finding.counted_as == Stance.context and finding.stance != Stance.context
        finding.count_note = FIGURE_ONLY_NOTE if demoted else ""


def claim_verdict(findings: list[Finding]) -> Verdict:
    """The verdict for one claim, from its verified findings alone.

    A model proposes a stance per finding; it never sets the verdict. Findings
    that did not survive the citation gate do not count, and each verified one
    counts as :func:`counted_stance` says.
    """
    verified = [finding for finding in findings if finding.verified]
    stances = [counted_stance(finding) for finding in verified]
    supports = Stance.supports in stances
    challenges = Stance.challenges in stances
    if supports and challenges:
        return Verdict.mixed
    if supports:
        return Verdict.supported
    if challenges:
        return Verdict.challenged
    if verified:
        return Verdict.unjudged
    return Verdict.not_addressed


def provenance_note(sources: Sequence[Source]) -> str:
    """Where a run's evidence came from, built from the sources it actually read.

    :data:`PROVENANCE_NOTE` when only SEC filings and XBRL facts were read; when
    any page the user added was read, a note that says so and how many.
    """
    pages = sum(
        1
        for source in sources
        if source.kind == SourceKind.public_html
        and source.extraction_status == ExtractionStatus.extracted
    )
    if not pages:
        return PROVENANCE_NOTE
    return PROVENANCE_WITH_PAGES.format(pages=f"{pages} page{'s' if pages > 1 else ''}")


def run_status(
    *,
    sources_requested: int,
    sources_extracted: int,
    claims: list[Claim],
    withheld_findings: int,
    engine_fallbacks: int,
    time_limit_hit: bool,
    thin_filings: int = 0,
    filings_read: int = 0,
    facts_error: str | None = None,
    unchecked_findings: int = 0,
    verified_findings: int = 0,
    tagged_errors: Sequence[str] = (),
) -> tuple[RunStatus, list[str]]:
    """Complete only when nothing limits the brief; otherwise partial, with each reason.

    Failed when no source at all was read. The reasons are sentences a reader
    can act on, each with its denominator. ``thin_filings`` of the
    ``filings_read`` filings have most of their text outside numbered Items;
    ``facts_error`` says why the reported figures could not be read;
    ``unchecked_findings`` of the ``verified_findings`` were left unchecked because
    the meaning check failed; ``tagged_errors`` are the :data:`TAGGED_UNAVAILABLE`
    sentences of the filings whose tagged figures a run asked for and could not read.
    Complete says that every stage ran on everything it was
    given. It says nothing about how much evidence stands behind a verdict: that is
    shown per claim, as the findings and filings it rests on.
    """
    if sources_extracted == 0:
        return RunStatus.failed, ["No source could be retrieved and read; no brief was produced."]
    reasons: list[str] = []
    if sources_extracted < sources_requested:
        reasons.append(
            f"{sources_requested - sources_extracted} of {sources_requested} source(s) "
            "could not be read."
        )
    if thin_filings:
        reasons.append(
            THIN_FILINGS.format(
                thin=thin_filings,
                read=max(filings_read, thin_filings),
                pronoun="it" if thin_filings == 1 else "them",
            )
        )
    if facts_error is not None:
        reasons.append(FACTS_UNAVAILABLE.format(error=facts_error))
    reasons.extend(tagged_errors)
    if withheld_findings:
        # A finding is withheld for no surviving quote or figure, or for a number in its
        # statement that its quotes and figures do not contain; the reason is on the finding.
        reasons.append(f"{withheld_findings} finding(s) could not be verified and were withheld.")
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
    if unchecked_findings:
        reasons.append(
            MEANING_CHECK_FAILED.format(
                findings=unchecked_findings, verified=max(verified_findings, unchecked_findings)
            )
        )
    return (RunStatus.partial if reasons else RunStatus.complete), reasons
