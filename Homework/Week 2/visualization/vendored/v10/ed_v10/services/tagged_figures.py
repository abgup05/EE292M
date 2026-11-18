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
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from ed_v10.core import policy
from ed_v10.core.breakdown_models import BreakdownReport
from ed_v10.core.breakdowns import build_report
from ed_v10.core.documents import FilingRef
from ed_v10.core.metric_models import Metric
from ed_v10.core.models import Company
from ed_v10.core.ports import FilingSource, SourceError
from ed_v10.core.tagged_figures import select_tagged, tagged_units
from ed_v10.services.breakdowns import filing_info
from ed_v10.sources.ixbrl import read_tagged_facts

log = logging.getLogger(__name__)

MAX_ERROR_CHARS = 320  # as app.services.thesis_run.safe_message cuts our own messages
NOT_READ = "No {kind} report was read, so no tagged figure is offered from one."
NO_BREAKDOWN = (
    "The {form} for the period ended {period_end} tags no revenue by segment, product or "
    "geography and no customer's share; no tagged figure is offered from it."
)


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


def _read(company: Company, filings: FilingSource, ref: FilingRef) -> BreakdownReport | str:
    """The breakdowns tagged in ``ref``, or why they could not be read."""
    try:
        fetched = filings.fetch(ref)
    except SourceError as exc:
        return str(exc)[:MAX_ERROR_CHARS]  # our own message: it names the URL and the status
    except Exception as exc:  # noqa: BLE001 - any failure of the port leaves the run to the rest
        log.warning("Fetching %s for its tags failed: %s", ref.url, type(exc).__name__)
        return f"the filing could not be fetched ({type(exc).__name__})"
    try:
        facts = read_tagged_facts(fetched.html)
        if facts.reason is not None:
            return facts.reason.rstrip(".")
        return build_report(facts, company=company, filing=filing_info(ref))
    except Exception as exc:  # noqa: BLE001 - a filing is untrusted text; its tags are optional
        log.exception("Reading the tags of %s failed", ref.url)
        return f"its tags could not be read ({type(exc).__name__})"


def load_tagged_figures(
    company: Company, filings: FilingSource, refs: Iterable[FilingRef]
) -> TaggedFigures:
    """Read the tags of the newest annual and quarterly report among ``refs`` (those the run read).

    Returns the figures to offer (at most
    :data:`app.core.limits.MAX_TAGGED_FIGURES_OFFERED`), notes on what was not
    offered, and a :data:`~app.core.policy.TAGGED_UNAVAILABLE` sentence for each
    filing whose tags could not be read. Never raises for EDGAR or for a filing's content.
    """
    result = TaggedFigures()
    chosen = newest_reports(refs)
    kinds = {ref.form.upper()[:4] for ref in chosen}
    for prefix, kind in (("10-K", "annual"), ("10-Q", "quarterly")):
        if prefix not in kinds:
            result.notes.append(NOT_READ.format(kind=kind))
    reports: list[BreakdownReport] = []
    for ref in chosen:
        read = _read(company, filings, ref)
        if isinstance(read, str):
            result.errors.append(
                policy.TAGGED_UNAVAILABLE.format(
                    form=ref.form, period_end=ref.period_end, error=read
                )
            )
        elif not read.breakdowns:
            result.notes.append(NO_BREAKDOWN.format(form=ref.form, period_end=ref.period_end))
        else:
            reports.append(read)
    units, notes = tagged_units(reports)
    result.figures, cut = select_tagged(units)
    result.notes += notes + cut
    return result
