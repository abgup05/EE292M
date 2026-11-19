"""The tagged figures a thesis run offers when it asks for them (``ThesisRequest.tagged_figures``).

One job: for the newest annual report and the newest quarterly report the run
read, fetch the primary document again through the run's
:class:`~app.core.ports.FilingSource` (the filing cache keeps a filing's parsed
text, and the tags are only in the raw HTML), read its inline XBRL
(:func:`app.sources.ixbrl.read_tagged_facts`), build its breakdowns
(:func:`app.core.breakdowns.build_report`) and turn them into figures
(:mod:`app.core.tagged_figures`). A filing whose tags cannot be read is a sentence
in ``errors`` (:data:`app.core.policy.TAGGED_UNAVAILABLE`), never an exception:
the run goes on without its figures and is partial for that reason.

What was read from a filing is kept in the disposable filing cache, by accession and
by :data:`READER_VERSION`, so a later run does not fetch the filing again: a filing
does not change, and a change to the reader changes the version. A failure is never
kept.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from ed_v14.core import breakdown_models, breakdowns, metrics, policy
from ed_v14.core.breakdown_models import BreakdownReport
from ed_v14.core.breakdowns import CLAIM_SPECS, SPECS, BreakdownSpec, build_report
from ed_v14.core.documents import FilingRef
from ed_v14.core.metric_models import Metric
from ed_v14.core.models import Company
from ed_v14.core.ports import FilingSource, SourceError
from ed_v14.core.tagged_figures import select_tagged, tagged_units
from ed_v14.services.breakdowns import filing_info
from ed_v14.sources import ixbrl
from ed_v14.sources.ixbrl import read_tagged_facts
from ed_v14.store import FilingCache

log = logging.getLogger(__name__)

MAX_ERROR_CHARS = 320  # as app.services.thesis_run.safe_message cuts our own messages
NOT_READ = "No {kind} report was read, so no tagged figure is offered from one."
NO_BREAKDOWN = (
    "The {form} for the period ended {period_end} tags no revenue by segment, product or "
    "geography and no customer's share; no tagged figure is offered from it."
)


def reader_version() -> str:
    """Identifies the code that turns a filing's HTML into its breakdowns.

    The SHA-256 of the four source files that do it (the tag reader, the
    breakdown builder, the record's shape, and the metrics module whose number
    formats and year window a kept report's display strings and change formulas
    are written with), so that editing any of them makes every kept report a
    miss, as editing the parser does for kept text.
    """
    digest = hashlib.sha256()
    for module in (ixbrl, breakdowns, breakdown_models, metrics):
        digest.update(Path(module.__file__ or "").read_bytes())
    return digest.hexdigest()[:16]


READER_VERSION: Final = reader_version()
# Reports read for a claim test's part (with app.core.breakdowns.CLAIM_SPECS) are kept
# under their own version, so a run's own reports are never replaced by them.
CLAIM_READER_VERSION: Final = f"{READER_VERSION}-claims"
FOR_CLAIMS: Final = (*SPECS, *CLAIM_SPECS)


def _version(specs: Sequence[BreakdownSpec]) -> str:
    return READER_VERSION if tuple(specs) == tuple(SPECS) else CLAIM_READER_VERSION


@dataclass
class TaggedFigures:
    """The figures to offer, in order; notes on what was left out; one sentence per failure."""

    figures: list[Metric] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def newest_reports(refs: Iterable[FilingRef]) -> list[FilingRef]:
    """The newest annual (10-K) and newest quarterly (10-Q) report in ``refs``, newest first.

    Newest by period end, then filing date. A kind with no report is left out.
    """
    chosen: list[FilingRef] = []
    for prefix in ("10-K", "10-Q"):
        of_kind = [ref for ref in refs if ref.form.upper().startswith(prefix)]
        if of_kind:
            chosen.append(max(of_kind, key=lambda ref: (ref.period_end, ref.filed_date)))
    return sorted(chosen, key=lambda ref: (ref.period_end, ref.filed_date), reverse=True)


def _kept(
    cache: FilingCache | None, ref: FilingRef, version: str = READER_VERSION
) -> BreakdownReport | None:
    """The breakdowns of ``ref`` as this reader kept them, if it did and they still read."""
    if cache is None:
        return None
    stored = cache.get_tagged(ref.accession, version)
    if stored is None:
        return None
    try:
        return BreakdownReport.model_validate_json(stored)
    except ValidationError:
        log.warning("The kept tags of %s do not read; the filing is read again", ref.accession)
        return None


NOT_FETCHED = (
    "its tags were not kept when the filing was cached, and the filing is not fetched again "
    "for them (a run after the cache is refreshed reads them)"
)


def _html(
    filings: FilingSource, ref: FilingRef, at_hand: Mapping[str, str], fetch: bool = True
) -> str | Exception | None:
    """The filing's HTML: what the run already fetched, else fetched now (None when
    ``fetch`` is off); or the failure."""
    if ref.accession in at_hand:
        return at_hand[ref.accession]
    if not fetch:
        return None
    try:
        return filings.fetch(ref).html
    except Exception as exc:  # noqa: BLE001 - any failure of the port leaves the run to the rest
        return exc


def _read(
    company: Company,
    filings: FilingSource,
    ref: FilingRef,
    cache: FilingCache | None,
    at_hand: Mapping[str, str],
    specs: Sequence[BreakdownSpec] = SPECS,
    fetch: bool = True,
) -> BreakdownReport | str:
    """The breakdowns tagged in ``ref``, or why they could not be read."""
    kept = _kept(cache, ref, _version(specs))
    if kept is not None:
        return kept
    html = _html(filings, ref, at_hand, fetch)
    if html is None:
        return NOT_FETCHED
    if isinstance(html, SourceError):
        return str(html)[:MAX_ERROR_CHARS]  # our own message: it names the URL and the status
    if isinstance(html, Exception):
        log.warning("Fetching %s for its tags failed: %s", ref.url, type(html).__name__)
        return f"the filing could not be fetched ({type(html).__name__})"
    try:
        facts = read_tagged_facts(html)
        if facts.reason is not None:
            return facts.reason.rstrip(".")
        report = build_report(facts, company=company, filing=filing_info(ref), specs=specs)
    except Exception as exc:  # noqa: BLE001 - a filing is untrusted text; its tags are optional
        log.exception("Reading the tags of %s failed", ref.url)
        return f"its tags could not be read ({type(exc).__name__})"
    if cache is not None:
        cache.put_tagged(ref.accession, _version(specs), report.model_dump_json())
    return report


def read_reports(
    company: Company,
    filings: FilingSource,
    refs: Iterable[FilingRef],
    *,
    cache: FilingCache | None = None,
    html_by_accession: Mapping[str, str] | None = None,
    specs: Sequence[BreakdownSpec] = SPECS,
    fetch: bool = True,
) -> tuple[list[BreakdownReport], list[str], list[str]]:
    """The breakdowns tagged in each of ``refs``, in order: reports, failures and notes.

    A filing whose tags cannot be read is a :data:`~app.core.policy.TAGGED_UNAVAILABLE`
    sentence in the failures; one that tags no breakdown is a note. Never raises for
    EDGAR or for a filing's content. Kept reports are read from ``cache``. ``specs`` are
    the breakdowns built: a run's own, or :data:`FOR_CLAIMS` for a claim test's part
    (kept apart, under :data:`CLAIM_READER_VERSION`). With ``fetch`` off a filing is read
    only from the kept tags or the HTML at hand, never fetched for its tags
    (:data:`NOT_FETCHED` is then the failure).
    """
    reports: list[BreakdownReport] = []
    errors: list[str] = []
    notes: list[str] = []
    for ref in refs:
        read = _read(company, filings, ref, cache, html_by_accession or {}, specs, fetch)
        if isinstance(read, str):
            errors.append(
                policy.TAGGED_UNAVAILABLE.format(
                    form=ref.form, period_end=ref.period_end, error=read
                )
            )
        elif not read.breakdowns:
            notes.append(NO_BREAKDOWN.format(form=ref.form, period_end=ref.period_end))
        else:
            reports.append(read)
    return reports, errors, notes


def load_tagged_figures(
    company: Company,
    filings: FilingSource,
    refs: Iterable[FilingRef],
    *,
    cache: FilingCache | None = None,
    html_by_accession: Mapping[str, str] | None = None,
) -> TaggedFigures:
    """Read the tags of the newest annual and quarterly report among ``refs`` (those the run read).

    Returns the figures to offer (at most
    :data:`app.core.limits.MAX_TAGGED_FIGURES_OFFERED`), notes on what was not
    offered, and a :data:`~app.core.policy.TAGGED_UNAVAILABLE` sentence for each
    filing whose tags could not be read. Never raises for EDGAR or for a filing's content.
    With a ``cache``, a filing whose tags this reader has read before is not fetched again.
    ``html_by_accession`` is the HTML the run has already fetched in this run, by accession:
    a filing found there is not fetched a second time.
    """
    result = TaggedFigures()
    chosen = newest_reports(refs)
    kinds = {ref.form.upper()[:4] for ref in chosen}
    for prefix, kind in (("10-K", "annual"), ("10-Q", "quarterly")):
        if prefix not in kinds:
            result.notes.append(NOT_READ.format(kind=kind))
    reports, errors, notes = read_reports(
        company, filings, chosen, cache=cache, html_by_accession=html_by_accession
    )
    result.errors += errors
    result.notes += notes
    units, notes = tagged_units(reports)
    result.figures, cut = select_tagged(units)
    result.notes += notes + cut
    return result
