"""Markdown export of a run: the same verified brief the API returns, as a file."""

from __future__ import annotations

from datetime import datetime

from app.models import ExtractionStatus, Run, RunStatus

STATUS_NOTES = {
    RunStatus.complete: "COMPLETE: all acceptance conditions were met.",
    RunStatus.partial: "PARTIAL: evidence is incomplete; see coverage limits before relying on it.",
    RunStatus.failed: "FAILED: no usable source; no answer was produced.",
    RunStatus.running: "RUNNING: this export was taken before the run finished.",
}


def _utc(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S UTC") if value else "n/a"


def _bullets(items: list[str], empty: str) -> list[str]:
    return [f"- {item}" for item in items] if items else [f"- {empty}"]


def render_markdown(run: Run) -> str:
    """Render the run as Markdown with status, findings, excerpts and a source list."""
    sources = {source.id: source for source in run.sources}
    evidence = {item.id: item for item in run.evidence}
    lines = [
        f"# Evidence Desk brief: {run.id}",
        "",
        f"**Status: {run.status.upper()}** - {STATUS_NOTES[run.status]}",
        "",
        f"- Started: {_utc(run.started_at)}",
        f"- Finished: {_utc(run.finished_at)}",
        f"- Synthesizer: {run.synthesizer}",
        "",
        "## Question",
        "",
        run.inputs.question,
        "",
        f"**Decision it informs:** {run.inputs.decision}",
        "",
    ]
    if run.inputs.scope_notes:
        lines += ["**Scope notes:** " + run.inputs.scope_notes, ""]
    lines += ["## Coverage limits", ""]
    lines += _bullets(run.coverage_limits, "None recorded.")
    lines += [""]

    if run.brief is not None:
        lines += ["## Direct answer", "", run.brief.direct_answer, "", "## Findings", ""]
        if not run.brief.findings:
            lines += ["No finding passed citation verification.", ""]
        for index, finding in enumerate(run.brief.findings, start=1):
            lines += [f"### {index}. {finding.statement}", ""]
            lines += [f"- Confidence: **{finding.confidence}** - {finding.rationale}"]
            if finding.single_source:
                lines += ["- Note: this finding rests on a single source."]
            lines += [""]
            for evidence_id in finding.evidence_ids:
                item = evidence.get(evidence_id)
                if item is None:
                    continue
                source = sources.get(item.source_id)
                title = source.title if source else item.source_id
                url = source.canonical_url if source else ""
                lines += [
                    f"- Evidence {item.id} ({item.stance}) from [{title}]({url}), "
                    f'section "{item.locator}":',
                    "",
                    f"  > {item.excerpt}",
                    "",
                ]
        lines += ["## Disagreements", ""]
        lines += _bullets(run.brief.disagreements, "No conflicting evidence was identified.")
        lines += ["", "## Unknowns and gaps", ""]
        lines += _bullets(run.brief.unknowns, "None recorded.")
        lines += ["", "## Recommended next research steps", ""]
        lines += _bullets(run.brief.next_steps, "None recorded.")
        lines += [""]

    if run.unsupported_findings:
        lines += ["## Withheld findings (no verified citation)", ""]
        lines += [f"- {finding.statement}" for finding in run.unsupported_findings]
        lines += [""]

    lines += ["## Subquestions", ""]
    lines += [f"- [{s.status}] {s.text} (query: `{s.search_query}`)" for s in run.subquestions] or [
        "- None."
    ]
    lines += ["", "## Sources", ""]
    for source in run.sources:
        if source.extraction_status == ExtractionStatus.extracted:
            lines += [
                f"- {source.id}: [{source.title}]({source.canonical_url}) - {source.publisher}. "
                f"Published: {source.published_date or 'not available'}. "
                f"Retrieved: {_utc(source.retrieved_at)}. SHA-256: {source.content_hash[:12]}..."
            ]
        else:
            lines += [f"- {source.id}: {source.requested_url} - FAILED: {source.error}"]
    if not run.sources:
        lines += ["- No sources were attempted."]
    lines += ["", "## Errors", ""]
    lines += _bullets(run.errors, "None.")
    lines += [""]
    return "\n".join(lines)
