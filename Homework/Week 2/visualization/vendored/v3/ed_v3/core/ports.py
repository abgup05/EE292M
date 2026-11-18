"""The narrow interfaces the pipeline depends on, and the drafts that cross them.

The pipeline imports this module and nothing concrete: an SEC client, a page
fetcher and an analysis engine are handed to it. Each outside system has one
adapter that satisfies one of these protocols.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from ed_v3.core.documents import FetchedFiling, FilingRef, Passage
from ed_v3.core.metric_models import Metric
from ed_v3.core.models import Claim, Company, Confidence, Finding, Stance, ThesisRequest


class SourceError(RuntimeError):
    """A source could not be read; the message is safe to show to the user."""


class UnknownTicker(SourceError):
    """The ticker is not in SEC's company list."""


class FilingSource(Protocol):
    """What the pipeline needs from SEC EDGAR."""

    def company(self, ticker: str) -> Company:
        """Resolve a ticker. Raises :class:`UnknownTicker` or :class:`SourceError`."""
        ...

    def periodic_filings(self, company: Company, limit: int) -> list[FilingRef]:
        """The latest 10-K and the 10-Qs filed after it, newest first, at most ``limit``."""
        ...

    def fetch(self, ref: FilingRef) -> FetchedFiling:
        """Retrieve the primary document. Raises :class:`SourceError`."""
        ...

    def company_facts(self, company: Company) -> dict:
        """The company's XBRL facts as EDGAR serves them. Raises :class:`SourceError`."""
        ...


@dataclass(frozen=True)
class Quote:
    """Text an engine says it copied from one passage. Unverified until the gate runs."""

    passage_id: str
    text: str


@dataclass
class FindingDraft:
    """One drafted finding. ``metric_ids`` name reported figures the statement relies on."""

    statement: str
    stance: Stance
    quotes: list[Quote]
    confidence: Confidence
    rationale: str
    metric_ids: list[str] = field(default_factory=list)


@dataclass
class ClaimDraft:
    """An engine's unverified assessment of one claim."""

    findings: list[FindingDraft] = field(default_factory=list)
    rationale: str = ""
    unknowns: list[str] = field(default_factory=list)


@dataclass
class SummaryDraft:
    summary: str
    next_steps: list[str] = field(default_factory=list)


class Planner(Protocol):
    """Turns each claim into retrieval queries."""

    name: str

    def plan(self, request: ThesisRequest, company: Company) -> list[list[str]]:
        """Queries for each claim, in the order of ``request.claims``."""
        ...


class Assessor(Protocol):
    """Reads the passages retrieved for one claim and drafts findings with quotes."""

    name: str

    def assess(
        self,
        request: ThesisRequest,
        company: Company,
        claim: Claim,
        passages: list[Passage],
        figures: Sequence[Metric] = (),
    ) -> ClaimDraft:
        """Draft findings for ``claim`` from ``passages`` and the reported ``figures``."""
        ...


class Summarizer(Protocol):
    """Writes the decision-level summary from verified findings only."""

    name: str

    def summarize(
        self,
        request: ThesisRequest,
        company: Company,
        claims: list[Claim],
        findings: list[Finding],
    ) -> SummaryDraft: ...


class Analyst(Planner, Assessor, Summarizer, Protocol):
    """An engine that does all three jobs. Engines are interchangeable behind this."""


# A page fetcher for the optional extra URLs: URL in, FetchedPage out, FetchError on failure.
PageFetcher = Callable[[str], "object"]
