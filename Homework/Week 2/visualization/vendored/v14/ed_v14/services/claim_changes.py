"""For each claim of a run, the changed paragraphs of its newest 10-K and 10-Q that share its words.

One use case. For each form (10-K, 10-Q) among the filings the run read, take the
newest one it read and the filing of that form filed immediately before it, read
both through the :class:`~app.store.FilingCache` as
:mod:`app.services.filing_changes` does, and compare them with every changed
paragraph listed. Then :func:`app.core.claim_changes.relevant_changes` ranks the
changed paragraphs for each claim. This is keyword retrieval (BM25 and shared
words), not a model's judgement.

So at most two pairs are compared, never one per filing read. A default run reads
one 10-K and two 10-Qs: the older 10-Q is not compared with the one before it
(it is often the earlier side of the 10-Q pair, being the one filed just before
the newest). The brief's heading and note (:mod:`app.services.export`) say so.

The pair is fixed by the run, not by today's index: the later filing is the one
the run read (found in EDGAR's list by its accession) and the earlier one is the
newest of that form filed before it, so a run made last quarter gives the same
pair after the company files again. EDGAR's client lists a form from the recent
page of the index and stops once it has two, so for a run whose filing is no
longer the newest the older pages are read back to the filing before it
(:func:`app.services.filing_changes.find_predecessor`). A comparison that cannot be made (no earlier
filing, a source that cannot list filings of a form, EDGAR failing) becomes a
note and the other form is still compared.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import cast

from ed_v14.core.change_models import FilingChanges
from ed_v14.core.claim_change_models import ClaimChanges, RunChanges
from ed_v14.core.claim_changes import compared_filings, relevant_changes
from ed_v14.core.models import (
    Company,
    ExtractionStatus,
    Run,
    RunStatus,
    Source,
    SourceKind,
)
from ed_v14.core.ports import FilingSource, SourceError
from ed_v14.services.filing_changes import (
    FORMS,
    FormFilingSource,
    Predecessor,
    compare_pair,
    find_predecessor,
    read_pair,
)
from ed_v14.services.thesis_run import safe_message
from ed_v14.store import FilingCache

log = logging.getLogger(__name__)

# The most of a form's latest filings asked for to find the run's filing and the one before
# it. It is a ceiling, not a depth: EDGAR's client reads the recent page of the index and
# stops once it has two of the form, so what comes back is usually the one or two 10-Ks and
# the three or so 10-Qs of the last year. When that list does not reach the filing before
# the run's, the older pages are read for it (find_predecessor); a note says how far.
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
    "{form} filings listed, so the filing before it cannot be found."
)
NOT_FOUND_NOTE = (
    "No {form} comparison: {title}, the {form} this run read, is not among the {count} {form} "
    "filings in {where}, so the filing before it cannot be found."
)
# Said only when the whole index was read: only then does EDGAR list none.
NO_EARLIER_NOTE = (
    "No {form} comparison: EDGAR lists no {form} filed before {title}, the {form} this run read."
)
NO_EARLIER_FOUND_NOTE = (
    "No {form} comparison: no {form} filed before {title}, the {form} this run read, is in "
    "{where}; the rest of the index was not read."
)
NO_EARLIER_LISTED_NOTE = (
    "No {form} comparison: none of the {count} latest {form} filings listed was filed before "
    "{title}, the {form} this run read; older ones were not looked for."
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


def _missing_note(found: Predecessor, form: str, title: str) -> str:
    """Why the pair cannot be made, claiming no more about EDGAR than was read."""
    count = found.listed
    if found.later is None:
        if found.where:
            return NOT_FOUND_NOTE.format(form=form, title=title, count=count, where=found.where)
        return NOT_LISTED_NOTE.format(form=form, title=title, count=count)
    if found.complete:
        return NO_EARLIER_NOTE.format(form=form, title=title)
    if found.where:
        return NO_EARLIER_FOUND_NOTE.format(form=form, title=title, where=found.where)
    return NO_EARLIER_LISTED_NOTE.format(form=form, title=title, count=count)


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
        found = find_predecessor(filings, company, form, cast(str, source.accession), FORM_HISTORY)
    except SourceError as exc:
        reason = safe_message(exc)
        return _Outcome(notes=[FAILED_NOTE.format(form=form, title=title, reason=reason)])
    later, earlier = found.later, found.earlier
    if later is None or earlier is None:
        return _Outcome(notes=[_missing_note(found, form, title)])
    reader = cast(FormFilingSource, filings)
    try:
        pair = read_pair(company, earlier, later, filings=reader, cache=cache)
    except SourceError as exc:
        reason = safe_message(exc)
        return _Outcome(notes=[FAILED_NOTE.format(form=form, title=title, reason=reason)])
    try:
        changes = compare_pair(pair, max_listed=None)
    except Exception as exc:  # noqa: BLE001 - a filing is untrusted text; one bad pair is one note
        log.exception("Comparing %s with the filing before it failed", later.url)
        reason = f"the two filings could not be compared ({type(exc).__name__})"
        return _Outcome(notes=[FAILED_NOTE.format(form=form, title=title, reason=reason)])
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
    """For each claim of ``run``, the changed paragraphs that share its words.

    The paragraphs that changed between the newest 10-K the run read and the 10-K before
    it, and between the newest 10-Q it read and the 10-Q before it (:func:`filings_read`);
    an older filing the run read is not compared with the one before it.

    ``filings`` must be able to list a company's filings of one form (``filings_of_form``,
    as :class:`app.sources.edgar.EdgarClient` can); a source that cannot gives a note per
    form. With no ``cache``, one in memory serves this call only. Never raises for a
    comparison that cannot be made: an unfinished run, a run that read no filing, a missing
    earlier filing, an EDGAR failure or a pair of filings the comparison itself fails on
    each give a note, and every claim of the run still has its (then empty) record.
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
