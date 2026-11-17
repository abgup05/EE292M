"""Markdown export of a thesis run: the same verified record the API returns, as a file.

All status and verdict wording comes from :mod:`app.core.policy`, so the export
and the page say the same thing. The export computes no verdict; it only
counts the verified findings the backend already decided per claim.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.metric_models import Metric
from app.core.models import (
    Claim,
    Evidence,
    ExtractionStatus,
    Finding,
    FindingChecks,
    Run,
    RunStatus,
    Source,
    SourceKind,
    Stance,
)
from app.core.policy import (
    FIGURES_NOTE,
    PROVENANCE_NOTE,
    STATUS_NOTES,
    VERDICT_LABELS,
    VERDICT_NOTES,
)

# For records written before findings carried their own reason.
WITHHELD_REASON = "no quote could be verified against the stored source text"
NOT_AVAILABLE = "n/a"
XBRL_FORM = "XBRL company facts"
UNMATCHED_SUFFIX = "was not found in the quotes or the cited figures"
QUOTE_CHECKS = {"passed": "found in the filing", "none": "none cited", "failed": "not found"}
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


def _header(run: Run) -> list[str]:
    company = run.company
    name = f"{company.name} ({company.ticker})" if company else run.inputs.ticker
    lines = [
        f"# Evidence Desk brief: {_text(name)}",
        "",
        f"**Status: {run.status.upper()}.** {STATUS_NOTES[run.status]}",
        "",
        f"- Run: {run.id}",
        f"- Started: {_utc(run.started_at)}",
        f"- Finished: {_utc(run.finished_at)}",
        f"- Engine: {run.engine}" + (f" ({_text(run.engine_detail)})" if run.engine_detail else ""),
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


def _verdict_table(run: Run) -> list[str]:
    lines = [
        "## Verdicts",
        "",
        "| Claim | Verdict | Supporting | Challenging | Context |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for claim in run.claims:
        findings = _verified_for(run, claim)
        counts = [sum(1 for f in findings if f.stance == stance) for stance in Stance]
        label = VERDICT_LABELS[claim.verdict] if claim.verdict else NOT_AVAILABLE
        lines.append(
            f"| {_cell(claim.text)} | {label} | "
            + " | ".join(str(count) for count in counts)
            + " |"
        )
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
    before findings carried their checks.
    """
    checks: FindingChecks = finding.checks
    quote = (
        QUOTE_CHECKS["passed"]
        if finding.evidence_ids
        else QUOTE_CHECKS.get(checks.quotes, checks.quotes)
    )
    if checks.numbers == "none":
        numbers = "none to check"
    else:
        total = len(checks.numbers_detail)
        matched = sum(1 for d in checks.numbers_detail if not d.endswith(UNMATCHED_SUFFIX))
        numbers = f"{matched} of {total} matched"
    return f"quote: {quote}; numbers: {numbers}"


def _claims(run: Run) -> list[str]:
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
        for finding in findings:
            lines += [
                f"#### {finding.id}. {_text(finding.statement)}",
                "",
                f"- Stance: {finding.stance}; confidence: {finding.confidence}",
                f"- Rationale: {_text(finding.rationale)}",
                f"- Sources cited: {finding.filings_cited}",
                f"- Checks: {_checks_line(finding)}",
            ]
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


def render_markdown(run: Run) -> str:
    """Render ``run`` as a Markdown brief.

    Order: title, status, decision, verdict table (finished runs only), summary,
    reported figures (when the run has any), claims with their verified findings,
    their checks, cited figures and excerpts, unknowns, next steps,
    sources, coverage limits, errors, provenance, withheld findings. Never
    raises on a running or failed run; those have no verdict table.
    """
    lines = _header(run)
    if run.status in _DECIDED and run.claims:
        lines += _verdict_table(run)
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
    lines += _claims(run)
    if brief is not None:
        lines += ["## Unknowns", "", *_bullets(brief.unknowns, "None recorded."), ""]
        lines += ["## Next steps", "", *_bullets(brief.next_steps, "None recorded."), ""]
    lines += _sources(run)
    lines += ["## Coverage limits", "", *_bullets(run.coverage_limits, "None recorded."), ""]
    lines += ["## Errors", "", *_bullets(run.errors, "None."), ""]
    lines += ["## Provenance", "", PROVENANCE_NOTE, ""]
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
    return "\n".join(lines)
