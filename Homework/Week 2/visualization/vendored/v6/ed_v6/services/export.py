"""Markdown export of a thesis run: the same verified record the API returns, as a file.

All status, verdict and decision wording comes from :mod:`app.core.policy`, so
the export and the page say the same thing. The export computes no verdict; it
only counts the verified findings the backend already decided per claim, and,
for a reviewed brief, shows the :class:`~app.core.models.Review` the backend built.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ed_v6.core.metric_models import Metric
from ed_v6.core.models import (
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
from ed_v6.core.policy import (
    DECISION_LABELS,
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
NO_CHECKER = "none"
# Statuses whose claims carry a final verdict worth tabulating.
_DECIDED = (RunStatus.complete, RunStatus.partial)


def _utc(value: datetime | None) -> str:
    """A timestamp as ``YYYY-MM-DD HH:MM:SS UTC``; naive values are taken to be UTC."""
    if value is None:
        return NOT_AVAILABLE
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _text(value: str) -> str:
    """Untrusted inline text (model output, filing text): no raw HTML."""
    return value.replace("<", "\\<")


def _cell(value: str) -> str:
    """Text safe inside one Markdown table cell."""
    return _text(" ".join(value.split())).replace("|", "\\|")


def _link_text(value: str) -> str:
    return _text(" ".join(value.split())).replace("[", "\\[").replace("]", "\\]")


def _url(value: str) -> str:
    return value.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _bullets(items: list[str], empty: str) -> list[str]:
    return [f"- {_text(item)}" for item in items] if items else [f"- {empty}"]


def _blockquote(text: str) -> list[str]:
    return [f"> {_text(line)}".rstrip() for line in text.splitlines() or [""]]


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
    lines += ["", "## Decision", "", _text(run.inputs.decision), ""]
    if run.inputs.scope_notes:
        lines += [f"**Scope notes:** {_text(run.inputs.scope_notes)}", ""]
    return lines


def _verdict_table(run: Run, review: Review | None) -> list[str]:
    reviewed = {c.claim_id: c.reviewed_verdict for c in review.claims} if review else {}
    after = " After your review |" if review is not None else ""
    lines = [
        "## Verdicts",
        "",
        f"| Claim | Verdict |{after} Supporting | Challenging | Context |",
        f"| --- | --- |{' --- |' if review is not None else ''} ---: | ---: | ---: |",
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
        lines.append("| " + " | ".join(cells) + " |")
    return [*lines, ""]


def _excerpt(item: Evidence, sources: dict[str, Source]) -> list[str]:
    source = sources.get(item.source_id)
    title = source.title if source else item.source_id
    url = item.link or (source.url if source else "")
    where = f"[{_link_text(title)}]({_url(url)})" if url else _link_text(title)
    return [*_blockquote(item.excerpt), "", f"— {_text(item.locator)}, {where}", ""]


def _figure_line(metric: Metric) -> str:
    """ "Gross margin, Quarter ended 2026-07-26: 75.0% (72,142 ÷ 96,221; USD millions)"."""
    formula = f" ({_text(metric.formula)})" if metric.formula else ""
    return f"{_text(metric.label)}, {_text(metric.period_label)}: {_text(metric.display)}{formula}"


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
    withheld = f"; reason: withheld ({', '.join(reason)})" if reason else ""
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
            lines += [_text(claim.rationale), ""]
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


def render_markdown(run: Run, review: Review | None = None) -> str:
    """Render ``run`` as a Markdown brief; with ``review``, the reviewed brief.

    Order: title, status, your review (reviewed brief only), decision, verdict
    table (finished runs only), summary,
    reported figures (when the run has any), claims with their verified findings,
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
            _text(brief.summary),
            "",
            f"_Summary written by: {_text(brief.summary_origin)}_",
            "",
        ]
    lines += _reported_figures(run)
    lines += _claims(run, review)
    if brief is not None:
        lines += ["## Unknowns", "", *_bullets(brief.unknowns, "None recorded."), ""]
        lines += ["## Next steps", "", *_bullets(brief.next_steps, "None recorded."), ""]
    lines += _sources(run)
    lines += ["## Coverage limits", "", *_bullets(run.coverage_limits, "None recorded."), ""]
    lines += ["## Errors", "", *_bullets(run.errors, "None."), ""]
    # The run's own note; a record written before runs kept one gets it from its sources.
    note = brief.provenance_note if brief is not None and brief.provenance_note else ""
    lines += ["## Provenance", "", _text(note or provenance_note(run.sources)), ""]
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
