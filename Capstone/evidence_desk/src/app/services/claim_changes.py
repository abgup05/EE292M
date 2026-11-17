"""For each claim of a run, the changed paragraphs of the filings it read that share its words.

One use case. For each form (10-K, 10-Q) among the filings the run read, take the
newest one it read and the filing of that form filed immediately before it, read
both through the :class:`~app.store.FilingCache` as
:mod:`app.services.filing_changes` does, and compare them with every changed
paragraph listed. Then :func:`app.core.claim_changes.relevant_changes` ranks the
changed paragraphs for each claim. This is keyword retrieval (BM25 and shared
words), not a model's judgement.

The pair is fixed by the run, not by today's index: the later filing is the one
the run read (found in EDGAR's list by its accession) and the earlier one is the
newest of that form filed before it, so a run made last quarter gives the same
pair after the company files again. A comparison that cannot be made (no earlier
filing, a source that cannot list filings of a form, EDGAR failing) becomes a
note and the other form is still compared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from app.core.change_models import FilingChanges
from app.core.claim_change_models import ClaimChanges, RunChanges
from app.core.claim_changes import compared_filings, relevant_changes
from app.core.documents import FilingRef
from app.core.models import (
    Company,
    ExtractionStatus,
    Run,
    RunStatus,
    Source,
    SourceKind,
)
from app.core.ports import FilingSource, SourceError
from app.services.filing_changes import FORMS, FormFilingSource, compare_pair, read_pair
from app.services.thesis_run import safe_message
from app.store import FilingCache

# How many of a form's latest filings are listed to find the run's filing and the one before
# it: three years of 10-Qs, or twelve of 10-Ks. A run whose filing is older is given a note.
FORM_HISTORY = 12

NOT_FINISHED_NOTE = (
    "The run is still running; its claims are matched to changed paragraphs once it has finished."
)
NO_FILING_NOTE = (
    "The run read no 10-K or 10-Q, so there is no filing to compare with the one filed before it."
)
NO_COMPANY_NOTE = (
    "The run records no company, so the filings before the ones it read cannot be listed."
)
CANNOT_LIST_NOTE = (
    "No {form} comparison: the filing source cannot list a company's {form} filings, so the "
    "filing before {title} cannot be found."
)
NOT_LISTED_NOTE = (
    "No {form} comparison: {title}, the {form} this run read, is not among the {count} latest "
    "{form} filings EDGAR lists, so the filing before it cannot be found."
)
NO_EARLIER_NOTE = (
    "No {form} comparison: EDGAR lists no {form} filed before {title}, the {form} this run read."
)
FAILED_NOTE = "No {form} comparison for {title}: {reason}"
REREAD_NOTE = (
    "{title} reads differently now than when the run read it (the parser has changed); its "
    "paragraphs are from today's reading."
)
COMPARISON_NOTE = "{form} comparison: {note}"


@dataclass
class _Outcome:
    """What one form gave: its comparison (None when it could not be made) and its notes."""

    changes: FilingChanges | None = None
    notes: list[str] = field(default_factory=list)


def filings_read(run: Run) -> list[Source]:
    """The newest 10-K and the newest 10-Q the run read, in that order (either may be absent).

    A filing counts as read when its source is an SEC filing that was extracted and
    records its form, accession and filing date. Newest is by filing date, then accession.
    """
    newest: dict[str, Source] = {}
    for source in run.sources:
        if (
            source.kind != SourceKind.sec_filing
            or source.extraction_status != ExtractionStatus.extracted
            or source.form not in FORMS
            or not source.accession
            or not source.published_date
        ):
            continue
        current = newest.get(source.form)
        if current is None or _when(source) > _when(current):
            newest[source.form] = source
    return [newest[form] for form in FORMS if form in newest]


def _when(source: Source) -> tuple[str, str]:
    return (source.published_date or "", source.accession or "")


def _empty(run: Run, note: str) -> RunChanges:
    claims = [ClaimChanges(claim_id=claim.id) for claim in run.claims]
    return RunChanges(run_id=run.id, claims=claims, notes=[note])


def _earlier_ref(refs: list[FilingRef], later: FilingRef) -> FilingRef | None:
    """The newest of ``refs`` of the same form filed before ``later``, or None."""
    key = (later.filed_date, later.accession)
    before = [
        ref
        for ref in refs
        if ref.form == later.form
        and ref.accession != later.accession
        and (ref.filed_date, ref.accession) < key
    ]
    return max(before, key=lambda ref: (ref.filed_date, ref.accession), default=None)


def _compare_form(
    company: Company,
    source: Source,
    filings: FilingSource | FormFilingSource,
    cache: FilingCache,
) -> _Outcome:
    """Compare the run's filing ``source`` with the one filed before it, or say why not."""
    form, title = cast(str, source.form), source.title
    lister = getattr(filings, "filings_of_form", None)
    if not callable(lister):
        return _Outcome(notes=[CANNOT_LIST_NOTE.format(form=form, title=title)])
    try:
        refs: list[FilingRef] = lister(company, form, FORM_HISTORY)
    except SourceError as exc:
        reason = safe_message(exc)
        return _Outcome(notes=[FAILED_NOTE.format(form=form, title=title, reason=reason)])
    later = next((ref for ref in refs if ref.accession == source.accession), None)
    if later is None:
        return _Outcome(notes=[NOT_LISTED_NOTE.format(form=form, title=title, count=len(refs))])
    earlier = _earlier_ref(refs, later)
    if earlier is None:
        return _Outcome(notes=[NO_EARLIER_NOTE.format(form=form, title=title)])
    reader = cast(FormFilingSource, filings)
    try:
        pair = read_pair(company, earlier, later, filings=reader, cache=cache)
    except SourceError as exc:
        reason = safe_message(exc)
        return _Outcome(notes=[FAILED_NOTE.format(form=form, title=title, reason=reason)])
    changes = compare_pair(pair, max_listed=None)
    notes = [COMPARISON_NOTE.format(form=form, note=note) for note in changes.notes]
    if pair.later.content_hash != source.content_hash:
        notes.append(REREAD_NOTE.format(title=title))
    return _Outcome(changes, notes)


def run_changes(
    run: Run,
    *,
    filings: FilingSource | FormFilingSource,
    cache: FilingCache | None = None,
) -> RunChanges:
    """For each claim of ``run``, the changed paragraphs of the filings it read that share words.

    ``filings`` must be able to list a company's filings of one form
    (``filings_of_form``, as :class:`app.sources.edgar.EdgarClient` can); a source that
    cannot gives a note per form. With no ``cache``, one in memory serves this call
    only. Never raises for a comparison that cannot be made: an unfinished run, a run
    that read no filing, a missing earlier filing or an EDGAR failure each give a note,
    and every claim of the run still has its (then empty) record.
    """
    if run.status == RunStatus.running:
        return _empty(run, NOT_FINISHED_NOTE)
    sources = filings_read(run)
    if not sources:
        return _empty(run, NO_FILING_NOTE)
    if run.company is None:
        return _empty(run, NO_COMPANY_NOTE)
    store = FilingCache() if cache is None else cache
    try:
        outcomes = [_compare_form(run.company, source, filings, store) for source in sources]
    finally:
        if cache is None:
            store.close()
    comparisons = [outcome.changes for outcome in outcomes if outcome.changes is not None]
    return RunChanges(
        run_id=run.id,
        compared=[compared_filings(changes) for changes in comparisons],
        claims=relevant_changes(run.claims, comparisons),
        notes=[note for outcome in outcomes for note in outcome.notes],
    )
