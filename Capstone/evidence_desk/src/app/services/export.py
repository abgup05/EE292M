"""Markdown export of a thesis run: the same verified record the API returns, as a file.

All status, verdict and decision wording comes from :mod:`app.core.policy`, so
the export and the page say the same thing. The export computes no verdict; it
only counts the verified findings the backend already decided per claim, and
the distinct filings their excerpts quote, and, for a reviewed brief, shows the
:class:`~app.core.models.Review` the backend built.

Every piece of text the export did not write itself (excerpts, statements,
reasons, titles, names, notes) is backslash-escaped so a Markdown viewer shows
it literally: it cannot become an image fetched when the brief is opened, a
link, emphasis, code, a heading or a list. Undoing the escapes gives back the
stored text exactly. The links the export writes itself have percent-encoded
destinations that cannot end early.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import quote as percent_encode

from app.core.claim_change_models import RelevantChange, RunChanges
from app.core.event_models import Event, EventStatus
from app.core.metric_models import Metric
from app.core.models import (
    Claim,
    Decision,
    DecisionValue,
    Evidence,
    ExtractionStatus,
    Finding,
    FindingChecks,
    Review,
    Run,
    RunStatus,
    Source,
    SourceKind,
    Stance,
)
from app.core.policy import (
    DECISION_LABELS,
    EVENT_INDEX_UNREAD_COUNTS,
    EVENTS_NONE,
    EVENTS_NOTE,
    FIGURES_NOTE,
    NO_CHECKER_NOTE,
    REVIEW_NOTE,
    STATUS_NOTES,
    SUPPORT_LABELS,
    UNDECIDED,
    VERDICT_LABELS,
    VERDICT_NOTES,
    provenance_note,
)

# For records written before findings carried their own reason.
WITHHELD_REASON = "no quote could be verified against the stored source text"
NOT_AVAILABLE = "n/a"
XBRL_FORM = "XBRL company facts"
UNMATCHED_SUFFIX = "was not found in the quotes or the cited figures"
# A numbers_detail line about the finding's reason, not its statement.
REASON_DETAIL_PREFIX = "in the reason: "
QUOTE_CHECKS = {"passed": "found in the filing", "none": "none cited", "failed": "not found"}
# The line under a finding whose period check could not place a year it names.
PERIOD_UNVERIFIED_PREFIX = "Period not found in its evidence: "
NO_CHECKER = "none"
# The verdict table's column of distinct SEC filings a claim's verified findings quote.
FILINGS_QUOTED = "Filings quoted"
# Statuses whose claims carry a final verdict worth tabulating.
_DECIDED = (RunStatus.complete, RunStatus.partial)


def _utc(value: datetime | None) -> str:
    """A timestamp as ``YYYY-MM-DD HH:MM:SS UTC``; naive values are taken to be UTC."""
    if value is None:
        return NOT_AVAILABLE
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


# Untrusted text: everything the export did not write itself (excerpts from a filing or from a
# page the user added, statements, reasons and notes from a model, titles, names). Each piece is
# backslash-escaped so a Markdown viewer shows it literally: CommonMark makes a backslash before
# any ASCII punctuation character stand for that character, and nothing else.
#
# Escaped anywhere in a line: the characters that open or close inline syntax (images, links,
# emphasis, code spans, raw HTML and autolinks, GFM strikethrough and table cells) and the
# backslash itself.
_INLINE_ACTIVE = re.compile(r"[\\`*_\[\]<~|]")
# "&" only where it would start an entity or character reference ("&amp;" would show as "&").
_REFERENCE = re.compile(r"&(?=#[0-9]{1,7};|#[xX][0-9a-fA-F]{1,6};|[A-Za-z][A-Za-z0-9]{0,31};)")
# Escaped only at the start of a line (after any indentation): the markers of a heading, a
# block quote, a list item, a setext underline or a thematic break, and an ordered list's
# "1." or "1)". Within a line they are text, so ordinary text keeps them unescaped.
_LINE_MARKER = re.compile(r"^([ \t]*)([#>+=-])", re.MULTILINE)
_ORDERED_MARKER = re.compile(r"^([ \t]*[0-9]{1,9})([.)])(?=[ \t]|$)", re.MULTILINE)
# A link destination the export writes keeps the characters a URL may hold and that Markdown
# does not read in a destination; everything else is percent-encoded, so ")", a space, "<" or a
# trailing "\" cannot end the link early or turn it into something else.
_URL_SAFE = "/:?#[]@!$&'*+,;=%~"


def _escape(value: str, *, line_start: bool) -> str:
    """``value`` backslash-escaped so it renders as the text it is.

    Line-leading markers are escaped on every line after the first, and on the first too
    when ``line_start`` (the text begins a line or a list item of the brief).
    """
    escaped = _INLINE_ACTIVE.sub(r"\\\g<0>", value)
    escaped = _REFERENCE.sub(r"\\&", escaped)
    if line_start:
        escaped = _LINE_MARKER.sub(r"\1\\\2", escaped)
        return _ORDERED_MARKER.sub(r"\1\\\2", escaped)
    first, newline, rest = escaped.partition("\n")
    if not newline:
        return first
    rest = _ORDERED_MARKER.sub(r"\1\\\2", _LINE_MARKER.sub(r"\1\\\2", rest))
    return f"{first}\n{rest}"


def _text(value: str, *, line_start: bool = False) -> str:
    """Untrusted text, escaped to render literally (see :func:`_escape`).

    ``line_start`` when the text begins a line of the brief or a list item, where a
    leading "#", ">", "-", "+", "=" or "1." would otherwise start a block.
    """
    return _escape(value, line_start=line_start)


def _cell(value: str) -> str:
    """Untrusted text safe inside one Markdown table cell: one line, every "|" escaped."""
    return _text(" ".join(value.split()))


def _link_text(value: str) -> str:
    """Untrusted text as the text of a link the export writes: one line, brackets escaped."""
    return _text(" ".join(value.split()))


def _url(value: str) -> str:
    """A URL as the destination of a link the export writes; it cannot close the link early."""
    return percent_encode(value, safe=_URL_SAFE)


def _bullets(items: list[str], empty: str) -> list[str]:
    return [f"- {_text(item, line_start=True)}" for item in items] if items else [f"- {empty}"]


def _blockquote(text: str) -> list[str]:
    return [f"> {_text(line, line_start=True)}".rstrip() for line in text.splitlines() or [""]]


def _verified_for(run: Run, claim: Claim) -> list[Finding]:
    return [f for f in run.findings if f.claim_id == claim.id and f.verified]


def _decision_label(finding_id: str, decisions: dict[str, Decision]) -> str:
    decision = decisions.get(finding_id)
    return DECISION_LABELS[decision.value if decision else UNDECIDED]


def _your_review(review: Review) -> list[str]:
    """How much of the run the reviewer decided, and the rule for the reviewed verdict."""
    return [
        "## Your review",
        "",
        f"You decided {review.decided} of {review.findings_total} findings. {REVIEW_NOTE}",
        "",
    ]


def _review_footer(review: Review) -> list[str]:
    if not review.decisions:
        return ["This brief includes no reviewer decision yet.", ""]
    latest = max(decision.decided_at for decision in review.decisions)
    return [f"This brief includes the reviewer's decisions as of {_utc(latest)}.", ""]


def _header(run: Run, review: Review | None) -> list[str]:
    company = run.company
    name = f"{company.name} ({company.ticker})" if company else run.inputs.ticker
    lines = [
        f"# Evidence Desk brief: {_text(name)}",
        "",
        f"**Status: {run.status.upper()}.** {STATUS_NOTES[run.status]}",
        "",
        *(_your_review(review) if review is not None else []),
        f"- Run: {run.id}",
        f"- Started: {_utc(run.started_at)}",
        f"- Finished: {_utc(run.finished_at)}",
        f"- Engine: {run.engine}" + (f" ({_text(run.engine_detail)})" if run.engine_detail else ""),
        _checker_line(run),
    ]
    if company:
        lines.append(f"- SEC CIK: {company.cik}")
    if run.status in _DECIDED and run.claims:
        coverage = run.coverage
        lines.append(
            f"- Claims with verified excerpts or figures: {coverage.claims_with_evidence} of "
            f"{coverage.claims_total or len(run.claims)}"
        )
    if run.status == RunStatus.running:
        detail = f" ({_text(run.stage_detail)})" if run.stage_detail else ""
        lines.append(f"- Stage: {run.stage}{detail}")
    if run.as_of is not None and run.as_of.line:
        lines += ["", _text(run.as_of.line, line_start=True)]
    lines += ["", "## Decision", "", _text(run.inputs.decision, line_start=True), ""]
    if run.inputs.scope_notes:
        lines += [f"**Scope notes:** {_text(run.inputs.scope_notes)}", ""]
    return lines


def _filings_quoted(run: Run, findings: list[Finding]) -> int:
    """How many distinct SEC filings the excerpts of ``findings`` quote: evidence to source.

    A page the user added is a source but not a filing, and is not counted; nor is an
    excerpt whose evidence or source is missing from the record.
    """
    evidence = {item.id: item for item in run.evidence}
    filings = {s.id for s in run.sources if s.kind == SourceKind.sec_filing}
    quoted = {
        evidence[evidence_id].source_id
        for finding in findings
        for evidence_id in finding.evidence_ids
        if evidence_id in evidence
    }
    return len(quoted & filings)


def _verdict_table(run: Run, review: Review | None) -> list[str]:
    """Each claim's verdict, its verified findings by stance, and the filings they quote.

    "Filings quoted" tells a claim judged on one quote from one filing from one judged on
    many; the page shows the same thing per finding.
    """
    reviewed = {c.claim_id: c.reviewed_verdict for c in review.claims} if review else {}
    after = " After your review |" if review is not None else ""
    lines = [
        "## Verdicts",
        "",
        f"| Claim | Verdict |{after} Supporting | Challenging | Context | {FILINGS_QUOTED} |",
        f"| --- | --- |{' --- |' if review is not None else ''} ---: | ---: | ---: | ---: |",
    ]
    for claim in run.claims:
        findings = _verified_for(run, claim)
        # Each finding as the verdict rule counted it (its own stance in older records).
        counts = [
            sum(1 for f in findings if (f.counted_as or f.stance) == stance) for stance in Stance
        ]
        label = VERDICT_LABELS[claim.verdict] if claim.verdict else NOT_AVAILABLE
        cells = [_cell(claim.text), label]
        if review is not None:
            verdict = reviewed.get(claim.id)
            cells.append(VERDICT_LABELS[verdict] if verdict else DECISION_LABELS[UNDECIDED])
        cells += [str(count) for count in counts]
        cells.append(str(_filings_quoted(run, findings)))
        lines.append("| " + " | ".join(cells) + " |")
    return [*lines, ""]


def _excerpt(item: Evidence, sources: dict[str, Source]) -> list[str]:
    source = sources.get(item.source_id)
    title = source.title if source else item.source_id
    url = item.link or (source.url if source else "")
    where = f"[{_link_text(title)}]({_url(url)})" if url else _link_text(title)
    return [*_blockquote(item.excerpt), "", f"— {_text(item.locator)}, {where}", ""]


EVENTS_HEADING_MD = "## Events since the annual report"
EVENT_STATUS_WORDS = {
    EventStatus.read: "read",
    EventStatus.failed: "could not be read",
    EventStatus.capped: "not read: the cap per run came first",
    EventStatus.out_of_time: "not read: the run time limit came first",
    EventStatus.index_only: "listed from the index only",
}


def _event(event: Event) -> list[str]:
    """One 8-K: its date, form and link, each item with its category, the opening quoted."""
    kind = "substantive" if event.substantive else "routine"
    status = EVENT_STATUS_WORDS[event.status]
    if event.reason:
        status += f": {_text(event.reason)}"
    where = f"[{_link_text(event.form)}, filed {event.filed_label}]({_url(event.url)})"
    lines = [f"- {where} ({kind}; {status})"]
    for item in event.items:
        lines.append(f"  - Item {item.number}. {_text(item.title)} ({item.category})")
        if item.roles:
            lines.append(f"    - Roles named: {_text(', '.join(item.roles))}")
        lines += [f"    - “{_text(sentence)}”" for sentence in item.opening]
    return lines


def _events(run: Run) -> list[str]:
    """The 8-Ks since the annual report, newest first, and what became of each; none in old runs."""
    as_of = run.as_of
    if as_of is None:
        return []
    lines = [EVENTS_HEADING_MD, "", EVENTS_NOTE, ""]
    if as_of.index_error:
        error = as_of.index_error.rstrip(".")
        lines += [_text(EVENT_INDEX_UNREAD_COUNTS.format(error=error), line_start=True), ""]
        return lines
    lines += [_text(as_of.counts.line, line_start=True), ""]
    if not run.timeline:
        annual = as_of.annual_filed or NOT_AVAILABLE
        return [*lines, _text(EVENTS_NONE.format(annual=annual), line_start=True), ""]
    for event in run.timeline:
        lines += _event(event)
    return [*lines, ""]


def _figure_line(metric: Metric) -> str:
    """ "Gross margin, Quarter ended 2026-07-26: 75.0% (72,142 ÷ 96,221; USD millions)"."""
    formula = f" ({_text(metric.formula)})" if metric.formula else ""
    label = _text(metric.label, line_start=True)  # it begins a list item in "Reported figures"
    return f"{label}, {_text(metric.period_label)}: {_text(metric.display)}{formula}"


def _newest(metrics: list[Metric], period: str) -> list[Metric]:
    ends = [m.period_end for m in metrics if m.period == period]
    if not ends:
        return []
    newest = max(ends)
    return [m for m in metrics if m.period == period and m.period_end == newest]


def _reported_figures(run: Run) -> list[str]:
    """The newest quarter and fiscal year as reported in XBRL, with notes on what was missing."""
    if not run.metrics and not run.metrics_notes:
        return []
    lines = ["## Reported figures", "", FIGURES_NOTE, ""]
    for period in ("quarter", "annual"):
        chosen = _newest(run.metrics, period)
        if chosen:
            lines += [f"### {_text(chosen[0].period_label)}", ""]
            lines += [f"- {_figure_line(metric)}" for metric in chosen]
            lines.append("")
    if run.metrics_notes:
        lines += ["Notes on the reported figures:", "", *_bullets(run.metrics_notes, ""), ""]
    return lines


def _checks_line(finding: Finding) -> str:
    """ "quote: found in the filing; numbers: 2 of 2 matched".

    A finding with evidence passed the quote check even in a record written
    before findings carried their checks. Numbers count the statement's; a
    withheld reason adds "; reason: withheld (<its numbers>)".
    """
    checks: FindingChecks = finding.checks
    quote = (
        QUOTE_CHECKS["passed"]
        if finding.evidence_ids
        else QUOTE_CHECKS.get(checks.quotes, checks.quotes)
    )
    statement = [d for d in checks.numbers_detail if not d.startswith(REASON_DETAIL_PREFIX)]
    reason = [
        d.removeprefix(REASON_DETAIL_PREFIX).removesuffix(UNMATCHED_SUFFIX).strip()
        for d in checks.numbers_detail
        if d.startswith(REASON_DETAIL_PREFIX)
    ]
    if checks.numbers == "none":
        numbers = "none to check"
    else:
        matched = sum(1 for d in statement if not d.endswith(UNMATCHED_SUFFIX))
        numbers = f"{matched} of {len(statement)} matched"
    # The reason's numbers are words from the model's text.
    withheld = f"; reason: withheld ({_text(', '.join(reason))})" if reason else ""
    return f"quote: {quote}; numbers: {numbers}{withheld}"


def _checker_line(run: Run) -> str:
    """ "- Meaning check: claude (<how it answered>)", or that nothing checked meaning."""
    if run.checker == NO_CHECKER:
        return f"- Meaning check: none. {NO_CHECKER_NOTE}"
    detail = f" ({_text(run.checker_detail)})" if run.checker_detail else ""
    return f"- Meaning check: {_text(run.checker)}{detail}"


def _meaning_line(finding: Finding) -> str:
    """ "- Meaning: partly supported: <the checker's reason>", or "- Meaning: not checked"."""
    checks: FindingChecks = finding.checks
    label = SUPPORT_LABELS.get(checks.support, checks.support)
    reason = " ".join(checks.support_detail.split())
    return f"- Meaning: {label}" + (f": {_text(reason)}" if reason else "")


def _period_lines(finding: Finding) -> list[str]:
    """ "- Period not found in its evidence: <each year not found>.", only when one was not.

    A passed check, or a statement that names no year, adds nothing.
    """
    checks: FindingChecks = finding.checks
    if checks.periods != "unverified":
        return []
    missing = [year.detail for year in checks.periods_unverified]
    return [f"- {PERIOD_UNVERIFIED_PREFIX}{_text('; '.join(missing))}."] if missing else []


def _predated_lines(finding: Finding, timeline: dict[str, Event]) -> list[str]:
    """ "- [Predates the 8-K of 12 Nov 2026, Item 5.02](<link>)", one per later 8-K."""
    lines: list[str] = []
    for mark in finding.predated_by:
        event = timeline.get(mark.event_id)
        label = _link_text(mark.label)
        lines.append(f"- [{label}]({_url(event.url)})" if event else f"- {label}")
    return lines


def _decision_line(finding_id: str, decisions: dict[str, Decision]) -> str:
    """ "- Your decision: Rejected. <the reviewer's note>"."""
    decision = decisions.get(finding_id)
    note = f" {_text(' '.join(decision.note.split()))}" if decision and decision.note else ""
    return f"- Your decision: {_decision_label(finding_id, decisions)}.{note}"


def _claims(run: Run, review: Review | None) -> list[str]:
    decisions = {d.finding_id: d for d in review.decisions} if review else {}
    rejected = {f for f, d in decisions.items() if d.value == DecisionValue.rejected}
    sources = {source.id: source for source in run.sources}
    evidence = {item.id: item for item in run.evidence}
    metrics = {metric.id: metric for metric in run.metrics}
    lines = ["## Claims", ""]
    for claim in run.claims:
        lines += [f"### {claim.id}. {_text(claim.text)}", ""]
        if claim.verdict:
            lines += [
                f"**Verdict: {VERDICT_LABELS[claim.verdict]}.** {VERDICT_NOTES[claim.verdict]}",
                "",
            ]
        if claim.rationale:
            lines += [_text(claim.rationale, line_start=True), ""]
        if claim.caution:
            lines += [f"**Caution:** {_text(claim.caution)}", ""]
        if claim.event_note:
            lines += [f"**8-Ks since the annual report:** {_text(claim.event_note)}", ""]
        timeline = {event.id: event for event in run.timeline}
        findings = _verified_for(run, claim)
        if not findings:
            note = VERDICT_NOTES[claim.verdict] if claim.verdict else "This claim was not assessed."
            lines += [f"No verified findings. {note}", ""]
        # Rejected findings last in their claim (a stable sort keeps the run's order otherwise).
        for finding in sorted(findings, key=lambda f: f.id in rejected):
            heading = f"{finding.id}. {_text(finding.statement)}"
            if finding.id in rejected:
                heading = f"~~{heading}~~"
            lines += [f"#### {heading}", ""]
            if review is not None:
                lines.append(_decision_line(finding.id, decisions))
            lines += [
                f"- Stance: {finding.stance}; confidence: {finding.confidence}",
                f"- Rationale: {_text(finding.rationale)}",
                f"- Sources cited: {finding.filings_cited}",
                f"- Checks: {_checks_line(finding)}",
                _meaning_line(finding),
                *_period_lines(finding),
                *_predated_lines(finding, timeline),
            ]
            if finding.count_note:
                counted = finding.counted_as or Stance.context
                lines.append(f"- Counted as: {counted} ({_text(finding.count_note)})")
            for metric_id in finding.metric_ids:
                metric = metrics.get(metric_id)
                shown = _figure_line(metric) if metric else _text(metric_id)
                lines.append(f"- Reported figure: {shown}")
            lines.append("")
            for evidence_id in finding.evidence_ids:
                item = evidence.get(evidence_id)
                if item is not None:
                    lines += _excerpt(item, sources)
    if not run.claims:
        # The run stopped (or has not yet got) before claims were recorded: list what was asked.
        for position, text in enumerate(run.inputs.claims, start=1):
            lines += [f"### {position}. {_text(text)}", "", "This claim was not assessed.", ""]
    return lines


def _source_status(source: Source) -> str:
    if source.extraction_status == ExtractionStatus.extracted:
        return source.extraction_status.value
    return f"{source.extraction_status.value}: {source.error or 'no reason recorded'}"


def _sources(run: Run) -> list[str]:
    lines = ["## Sources", ""]
    if not run.sources:
        return [*lines, "No sources were attempted.", ""]
    lines += [
        "| ID | Document | Form | Period end | Filed | Retrieved (UTC) | Status |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for source in run.sources:
        kind_form = {SourceKind.public_html: "web page", SourceKind.sec_xbrl: XBRL_FORM}
        form = source.form or kind_form.get(source.kind, "")
        document = f"[{_link_text(source.title)}]({_url(source.url)})"
        if source.accession:
            document += f" ({source.accession})"
        cells = [
            source.id,
            document,
            _cell(form or NOT_AVAILABLE),
            _cell(source.period_end or NOT_AVAILABLE),
            _cell(source.published_date or NOT_AVAILABLE),
            _utc(source.retrieved_at),
            _cell(_source_status(source)),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return [*lines, ""]


CHANGE_KINDS = {
    "added": "Added",
    "removed": "Removed",
    "reworded": "Reworded",
    "numbers_only": "Numbers only",
}
# What app.services.claim_changes.filings_read compares: the newest 10-K and the newest 10-Q
# the run read, each with the filing of its form filed before it, and nothing else.
READING_LIST_HEADING = "Changed since the previous annual and quarterly report"
READING_LIST_NOTE = (
    "A reading list, not findings. Each paragraph below changed between the newest annual "
    "report this run read and the annual report filed before it, or between the newest "
    "quarterly report it read and the quarterly report filed before that. An older quarterly "
    "report the run read is not compared with the one before it, though it may be the earlier "
    "filing of the quarterly pair. The earlier filing of a pair may be one the run did not "
    "read: then it was fetched for this comparison. A paragraph is listed because it shares at "
    "least two words with the claim or with the search queries the run wrote for it. No model "
    "chose or judged these, and none counts toward a verdict."
)


def _compared(changes: RunChanges) -> list[str]:
    lines = []
    for pair in changes.compared:
        later, earlier = pair.later, pair.earlier
        lines.append(
            f"- [{_link_text(pair.form)} for the period ended {_link_text(later.period_end)}]"
            f"({_url(later.url)}) against "
            f"[the one for {_link_text(earlier.period_end)}]({_url(earlier.url)})"
        )
    return lines


def _relevant_change(number: int, change: RelevantChange) -> list[str]:
    """One listed change: its kind and place, the words it shares, its text and its links."""
    shares = f" Shares: {_text(', '.join(change.matched_terms))}." if change.matched_terms else ""
    also = change.also_under
    repeated = f" Also under {_text('; '.join(also))}." if also else ""
    kind = CHANGE_KINDS.get(change.kind, change.kind)
    where = f"{_text(change.form)}, {_text(change.item)}"
    head = f"{number}. **{_text(kind)}** in the {where}.{shares}{repeated}"
    if change.pair is not None:
        text, later, earlier = change.pair.after.text, change.pair.after, change.pair.before
        links = (
            f"[Open in the later filing]({_url(later.link)}) · "
            f"[earlier paragraph]({_url(earlier.link)})"
        )
    elif change.paragraph is not None:
        text = change.paragraph.text
        side = "earlier" if change.kind == "removed" else "later"
        links = f"[Open in the {side} filing]({_url(change.paragraph.link)})"
    else:
        return [head, ""]
    quoted = [f"   {line}" for line in _blockquote(text)]
    return [head, "", *quoted, "", f"   {links}", ""]


def _reading_list(run: Run, changes: RunChanges) -> list[str]:
    """The changed paragraphs listed under each claim (``docs/claim-changes.md``).

    Only the newest annual and the newest quarterly report the run read are compared, each
    with the filing of its form before it; :data:`READING_LIST_NOTE` says so.
    """
    lines = [f"## {READING_LIST_HEADING}", "", READING_LIST_NOTE, ""]
    if changes.compared:
        lines += ["Compared:", "", *_compared(changes), ""]
    if changes.notes:
        lines += [*(f"- {_text(note, line_start=True)}" for note in changes.notes), ""]
    by_claim = {found.claim_id: found for found in changes.claims}
    for claim in run.claims:
        found = by_claim.get(claim.id)
        lines += [f"### {claim.id}: {_text(claim.text)}", ""]
        if found is None or not found.changes:
            searched = found.considered if found is not None else 0
            lines += [
                "No changed paragraph shares two words with this claim or its search queries "
                f"({searched} searched).",
                "",
            ]
            continue
        lines += [
            f"{len(found.changes)} listed of {found.distinct_matched} that share at least two "
            f"words with the claim or its search queries, among {found.considered} changed "
            "paragraphs.",
            "",
        ]
        for number, change in enumerate(found.changes, start=1):
            lines += _relevant_change(number, change)
    return lines


def render_markdown(
    run: Run, review: Review | None = None, changes: RunChanges | None = None
) -> str:
    """Render ``run`` as a Markdown brief; with ``review``, the reviewed brief.

    With ``changes``, a reading list follows the claims: the paragraphs that changed in the
    filings the run read, under each claim they share words with, marked as no finding.

    Order: title, status, your review (reviewed brief only), decision, verdict
    table (finished runs only), summary,
    reported figures (when the run has any), the 8-Ks since the annual report (runs
    from version 12), claims with their caution and 8-K note and their verified findings,
    their checks, cited figures and excerpts, unknowns, next steps,
    sources, coverage limits, errors, provenance, withheld findings, and for a
    reviewed brief a closing line dating the decisions. A reviewed brief adds
    the reviewed verdict column, each finding's decision and note, and strikes
    through rejected findings, listed last in their claim. Never raises on a
    running or failed run; those have no verdict table.
    """
    lines = _header(run, review)
    if run.status in _DECIDED and run.claims:
        lines += _verdict_table(run, review)
    brief = run.brief
    if brief is not None:
        lines += [
            "## Summary",
            "",
            _text(brief.summary, line_start=True),
            "",
            f"_Summary written by: {_text(brief.summary_origin)}_",
            "",
        ]
    lines += _reported_figures(run)
    lines += _events(run)
    lines += _claims(run, review)
    if changes is not None:
        lines += _reading_list(run, changes)
    if brief is not None:
        lines += ["## Unknowns", "", *_bullets(brief.unknowns, "None recorded."), ""]
        lines += ["## Next steps", "", *_bullets(brief.next_steps, "None recorded."), ""]
    lines += _sources(run)
    lines += ["## Coverage limits", "", *_bullets(run.coverage_limits, "None recorded."), ""]
    lines += ["## Errors", "", *_bullets(run.errors, "None."), ""]
    # The run's own note; a record written before runs kept one gets it from its sources.
    note = brief.provenance_note if brief is not None and brief.provenance_note else ""
    provenance = note or provenance_note(run.sources)
    lines += ["## Provenance", "", _text(provenance, line_start=True), ""]
    lines += ["## Withheld findings", ""]
    if run.unsupported_findings:
        lines += [
            f"- {finding.id} ({finding.claim_id}): {_text(finding.statement)} "
            f"Withheld: {_text(finding.withheld_reason or WITHHELD_REASON)}."
            for finding in run.unsupported_findings
        ]
    else:
        lines.append("- None.")
    lines.append("")
    if review is not None:
        lines += _review_footer(review)
    return "\n".join(lines)
