"""Reported numbers for one company: XBRL company facts in, a metrics report out.

One job: ask the :class:`~app.core.ports.FilingSource` for the company facts,
build the report with :mod:`app.core.metrics`, and describe what was read as a
:class:`~app.core.models.Source` of kind ``sec_xbrl``. A failure is returned
as ``error``, never raised, so a run continues from the filings alone.
:func:`select_figures` chooses the few figures an engine is shown.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ed_v9.core import limits
from ed_v9.core.facts import FactBook, FactsError
from ed_v9.core.metric_models import Metric, MetricsReport
from ed_v9.core.metrics import build_report
from ed_v9.core.models import Company, ExtractionStatus, Source, SourceKind
from ed_v9.core.ports import FilingSource, SourceError
from ed_v9.sources.xbrl import company_facts_url

log = logging.getLogger(__name__)

PUBLISHER = "SEC EDGAR (XBRL API)"
# The metric keys an engine is shown for each recent quarter and fiscal year.
FIGURE_KEYS: tuple[str, ...] = (
    "revenue",
    "revenue_yoy",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "free_cash_flow",
    "eps_diluted",
)
INSTANT_KEYS: tuple[str, ...] = ("cash", "inventory", "receivables")


@dataclass
class NumbersResult:
    """The report (None when it could not be built), its source record, notes and error."""

    report: MetricsReport | None
    source: Source | None
    notes: list[str] = field(default_factory=list)
    error: str | None = None


def facts_title(company: Company) -> str:
    """The title the facts are shown under, such as "NVIDIA CORP XBRL company facts"."""
    return f"{company.name} XBRL company facts"


def content_hash(payload: object) -> str:
    """SHA-256 of the canonical JSON (sorted keys, no spaces) of ``payload``."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _source(
    source_id: str, company: Company, retrieved_at: datetime, digest: str, error: str | None
) -> Source:
    return Source(
        id=source_id,
        kind=SourceKind.sec_xbrl,
        title=facts_title(company),
        publisher=PUBLISHER,
        url=company_facts_url(company.cik),
        requested_url=company_facts_url(company.cik),
        retrieved_at=retrieved_at,
        content_hash=digest,
        extraction_status=ExtractionStatus.failed if error else ExtractionStatus.extracted,
        error=error,
    )


def load_numbers(
    company: Company,
    filings: FilingSource,
    *,
    source_id: str = "x1",
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> NumbersResult:
    """Read the company facts of ``company`` and build its metrics report.

    A :class:`SourceError` (EDGAR) or :class:`FactsError` (an unexpected shape)
    is returned as ``error`` with a failed source record and no report.
    """
    try:
        payload = filings.company_facts(company)
    except SourceError as exc:
        error = str(exc)
        return NumbersResult(None, _source(source_id, company, now(), "", error), error=error)
    retrieved_at = now()
    digest = content_hash(payload)
    try:
        report = build_report(FactBook(payload))
    except FactsError as exc:
        log.warning("Company facts of CIK %s could not be read: %s", company.cik, exc)
        error = f"The XBRL company facts could not be read: {exc}"
        return NumbersResult(
            None, _source(source_id, company, retrieved_at, digest, error), error=error
        )
    source = _source(source_id, company, retrieved_at, digest, None)
    return NumbersResult(report, source, notes=list(report.notes))


def _newest(metrics: list[Metric], period: str, count: int) -> list[str]:
    ends = sorted({m.period_end for m in metrics if m.period == period}, reverse=True)
    return ends[:count]


def select_figures(report: MetricsReport | None) -> list[Metric]:
    """The figures an engine is shown, at most :data:`limits.MAX_FIGURES_OFFERED`.

    For the newest :data:`limits.FIGURE_QUARTERS` quarters and newest
    :data:`limits.FIGURE_YEARS` fiscal years, each key of :data:`FIGURE_KEYS`;
    then the cash, inventory and receivables balances at the latest balance-sheet
    date. Metrics with no value are left out.
    """
    if report is None:
        return []
    metrics = [m for m in report.metrics if m.value is not None]
    by_id = {m.id: m for m in metrics}
    wanted: list[str] = []
    for period, count in (("quarter", limits.FIGURE_QUARTERS), ("annual", limits.FIGURE_YEARS)):
        for end in _newest(metrics, period, count):
            wanted += [f"{key}:{period}:{end}" for key in FIGURE_KEYS]
    for end in _newest(metrics, "instant", 1):
        wanted += [f"{key}:instant:{end}" for key in INSTANT_KEYS]
    chosen = [by_id[metric_id] for metric_id in dict.fromkeys(wanted) if metric_id in by_id]
    return chosen[: limits.MAX_FIGURES_OFFERED]
