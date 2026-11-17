"""Test doubles for the pipeline's ports: SEC EDGAR, public pages, an engine and a clock.

``FakeFilings`` serves the recorded NVIDIA filings under ``tests/fixtures/edgar``
(and any small synthetic filing a test supplies) through the same
:class:`~app.core.ports.FilingSource` interface the real EDGAR client has.
``ScriptedAnalyst`` is an engine whose assessments a test writes by hand.
"""

from __future__ import annotations

import functools
import gzip
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.documents import FetchedFiling, FilingRef, Passage
from app.core.metric_models import Metric
from app.core.models import Claim, Company, Finding, ThesisRequest
from app.core.ports import ClaimDraft, SourceError, SummaryDraft, UnknownTicker
from app.engines.extractive import ExtractiveAnalyst
from app.sources.edgar import archive_url, normalize_ticker
from app.sources.http import FetchedPage, FetchError

EDGAR = Path(__file__).parent / "fixtures" / "edgar"
NVIDIA = Company(cik=1045810, ticker="NVDA", name="NVIDIA CORP")
RETRIEVED_AT = datetime(2026, 11, 17, 11, 8, 51, tzinfo=UTC)


def _ref(accession: str, form: str, period_end: str, filed: str, document: str) -> FilingRef:
    return FilingRef(
        cik=NVIDIA.cik,
        accession=accession,
        form=form,
        period_end=period_end,
        filed_date=filed,
        primary_document=document,
        url=archive_url(NVIDIA.cik, accession, document),
    )


# The three filings EDGAR selects for NVIDIA by default (PROMPT.md section 3), newest first.
Q2_2027 = _ref("0001045810-26-000075", "10-Q", "2026-07-26", "2026-08-26", "nvda-20260726.htm")
Q1_2027 = _ref("0001045810-26-000052", "10-Q", "2026-04-26", "2026-05-20", "nvda-20260426.htm")
FY_2026 = _ref("0001045810-26-000021", "10-K", "2026-01-25", "2026-02-25", "nvda-20260125.htm")
# Recorded primary documents, by filing URL. Q1_2027 was not recorded.
RECORDED = {Q2_2027.url: "nvda-10q-20260726.htm.gz", FY_2026.url: "nvda-10k-20260125.htm.gz"}


@functools.cache
def recorded_html(name: str) -> str:
    """A recorded primary document, decompressed."""
    return gzip.decompress((EDGAR / name).read_bytes()).decode("utf-8", errors="replace")


@functools.cache
def _recorded_facts_text(cik: int) -> str:
    return gzip.decompress((EDGAR / f"companyfacts-CIK{cik:010d}.json.gz").read_bytes()).decode()


def recorded_facts(cik: int = NVIDIA.cik) -> dict[str, Any]:
    """The recorded (trimmed) XBRL company facts of ``cik``, a fresh copy each call."""
    return json.loads(_recorded_facts_text(cik))


def recorded_companies() -> dict[str, Company]:
    """SEC's company list as recorded (a trimmed copy), by EDGAR-style ticker."""
    payload = json.loads((EDGAR / "company_tickers.json").read_text())
    return {
        normalize_ticker(entry["ticker"]): Company(
            cik=int(entry["cik_str"]), ticker=entry["ticker"], name=entry["title"]
        )
        for entry in payload.values()
    }


def synthetic_ref(number: int, form: str = "10-Q") -> FilingRef:
    """A made-up NVIDIA filing reference; its document is whatever the test supplies."""
    return _ref(
        f"0009999999-26-{number:06d}",
        form,
        f"2026-0{number}-01",
        f"2026-0{number}-15",
        f"synthetic-{number}.htm",
    )


MDA_HEADING = "Item 2. Management's Discussion and Analysis"


def filing_html(*paragraphs: str, item: str = MDA_HEADING) -> str:
    """A minimal 10-Q primary document: one Part I Item holding ``paragraphs``."""
    body = "".join(f"<p>{text}</p>" for text in paragraphs)
    return (
        f"<html><body><p>PART I. FINANCIAL INFORMATION</p><p><b>{item}</b></p>{body}</body></html>"
    )


@dataclass
class FakeFilings:
    """A :class:`~app.core.ports.FilingSource` over fixed refs and documents.

    ``documents`` maps a filing URL to its HTML, or to the :class:`SourceError`
    its retrieval raises. A ref with no entry fails as EDGAR does for a missing
    document. Set ``index_error`` or ``company_error`` to make those calls fail.
    ``company_facts`` serves the recorded NVIDIA XBRL facts (``facts`` replaces
    them; ``facts_error`` makes the call fail) and counts calls in ``facts_calls``.
    """

    refs: list[FilingRef]
    documents: dict[str, str | SourceError]
    companies: dict[str, Company] = field(default_factory=lambda: {"NVDA": NVIDIA})
    index_error: SourceError | None = None
    company_error: SourceError | None = None
    facts: dict[str, Any] | None = None
    facts_error: SourceError | None = None
    fetched: list[str] = field(default_factory=list)
    facts_calls: int = 0

    @classmethod
    def nvidia(cls, *refs: FilingRef) -> FakeFilings:
        """NVIDIA with the recorded documents; ``refs`` default to the three EDGAR selects."""
        chosen = list(refs) or [Q2_2027, Q1_2027, FY_2026]
        documents: dict[str, str | SourceError] = {
            ref.url: recorded_html(RECORDED[ref.url]) for ref in chosen if ref.url in RECORDED
        }
        return cls(refs=chosen, documents=documents, companies=recorded_companies())

    @classmethod
    def synthetic(cls, *htmls: str) -> FakeFilings:
        """NVIDIA with one made-up 10-Q per HTML document given, in that order."""
        refs = [synthetic_ref(number) for number in range(1, len(htmls) + 1)]
        documents: dict[str, str | SourceError] = dict(
            zip([ref.url for ref in refs], htmls, strict=True)
        )
        return cls(refs=refs, documents=documents)

    def company(self, ticker: str) -> Company:
        """The company for ``ticker``, or the configured failure."""
        if self.company_error is not None:
            raise self.company_error
        key = normalize_ticker(ticker)
        if key not in self.companies:
            raise UnknownTicker(f"Ticker {key} is not in SEC's company list")
        return self.companies[key]

    def periodic_filings(self, company: Company, limit: int) -> list[FilingRef]:
        """The configured refs, at most ``limit``."""
        if self.index_error is not None:
            raise self.index_error
        return self.refs[:limit]

    def fetch(self, ref: FilingRef) -> FetchedFiling:
        """The configured document for ``ref``, or the configured failure."""
        self.fetched.append(ref.url)
        document = self.documents.get(ref.url)
        if document is None:
            raise SourceError(f"EDGAR answered HTTP 404 for {ref.url}")
        if isinstance(document, SourceError):
            raise document
        return FetchedFiling(ref=ref, html=document, retrieved_at=RETRIEVED_AT)

    def company_facts(self, company: Company) -> dict[str, Any]:
        """The configured facts, the recorded facts of the company, or the configured failure."""
        self.facts_calls += 1
        if self.facts_error is not None:
            raise self.facts_error
        if self.facts is not None:
            return self.facts
        if not (EDGAR / f"companyfacts-CIK{company.cik:010d}.json.gz").exists():
            raise SourceError(f"EDGAR answered HTTP 404 for company facts of CIK {company.cik}")
        return recorded_facts(company.cik)


@dataclass
class FakePages:
    """A page fetcher: URL to ``(final URL, HTML)``, or to the :class:`FetchError` it raises."""

    pages: dict[str, tuple[str, str] | FetchError]

    def __call__(self, url: str) -> FetchedPage:
        """Serve ``url`` as configured; unknown URLs fail like a 404."""
        page = self.pages.get(url, FetchError("HTTP 404"))
        if isinstance(page, FetchError):
            raise page
        final_url, html = page
        return FetchedPage(
            requested_url=url,
            final_url=final_url,
            status_code=200,
            content_type="text/html",
            html=html,
            retrieved_at=RETRIEVED_AT,
        )


class ScriptedFailure(RuntimeError):
    """What a scripted engine raises when told to fail (its message must not be shown)."""


Assess = Callable[[Claim, list[Passage]], ClaimDraft]


class ScriptedAnalyst:
    """An engine whose assessments the test writes; planning is the extractive engine's.

    Records the passage ids offered for each claim text in ``offered`` and the
    figures offered in ``figures``. Steps named in ``fail_on`` ("plan",
    "assess", "summarize") raise :class:`ScriptedFailure`; ``fail_claims``
    limits assessment failures to those claim texts. ``before_assess`` runs
    before every assessment (a test uses it to advance a clock). ``summary``
    replaces the fixed summary text.
    """

    detail = "scripted test engine"

    def __init__(
        self,
        assess: Assess | None = None,
        *,
        name: str = "scripted",
        fail_on: tuple[str, ...] = (),
        fail_claims: tuple[str, ...] = (),
        before_assess: Callable[[], None] | None = None,
        summary: str | None = None,
    ) -> None:
        self.name = name
        self._assess = assess
        self._fail_on = fail_on
        self._fail_claims = fail_claims
        self._before_assess = before_assess
        self._summary = summary
        self._extractive = ExtractiveAnalyst()
        self.offered: dict[str, list[str]] = {}
        self.figures: dict[str, list[Metric]] = {}

    def _maybe_fail(self, step: str) -> None:
        if step in self._fail_on:
            raise ScriptedFailure(f"secret detail from {step}")

    def plan(self, request: ThesisRequest, company: Company) -> list[list[str]]:
        """The extractive engine's queries."""
        self._maybe_fail("plan")
        return self._extractive.plan(request, company)

    def assess(
        self,
        request: ThesisRequest,
        company: Company,
        claim: Claim,
        passages: list[Passage],
        figures: Sequence[Metric] = (),
    ) -> ClaimDraft:
        """The scripted draft, or the extractive engine's when no script was given."""
        self.offered[claim.text] = [passage.id for passage in passages]
        self.figures[claim.text] = list(figures)
        if self._before_assess is not None:
            self._before_assess()
        if not self._fail_claims or claim.text in self._fail_claims:
            self._maybe_fail("assess")
        if self._assess is None:
            return self._extractive.assess(request, company, claim, passages)
        return self._assess(claim, passages)

    def summarize(
        self, request: ThesisRequest, company: Company, claims: list[Claim], findings: list[Finding]
    ) -> SummaryDraft:
        """A fixed summary naming how many findings it was given."""
        self._maybe_fail("summarize")
        return SummaryDraft(
            summary=self._summary or f"Scripted summary of {len(findings)} finding(s).",
            next_steps=["Read the filings."],
        )


class ManualClock:
    """A monotonic clock a test moves by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        """The current time in seconds."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Move the clock forward."""
        self.now += seconds
