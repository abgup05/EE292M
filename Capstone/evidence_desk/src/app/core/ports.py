"""The narrow interfaces the pipeline depends on, and the drafts that cross them.

The pipeline imports this module and nothing concrete: an SEC client, a page
fetcher, an analysis engine and a meaning checker are handed to it. Each outside
system has one adapter that satisfies one of these protocols.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.core.documents import FetchedFiling, FilingRef, Passage
from app.core.metric_models import Metric
from app.core.models import Claim, Company, Confidence, Finding, Stance, ThesisRequest


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

    def current_reports(self, company: Company, filed_after: str) -> list[FilingRef]:
        """The 8-K and 8-K/A filings filed after a ``YYYY-MM-DD`` date, newest first.

        Each carries the item numbers EDGAR's index lists. Raises :class:`SourceError`.
        """
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


class SupportVerdict(StrEnum):
    """A second reader's judgement of whether a finding's evidence supports its statement."""

    supported = "supported"
    partly = "partly"
    not_supported = "not_supported"


@dataclass(frozen=True)
class CheckExcerpt:
    """One verified excerpt as the reader sees it: the stored text and where it sits."""

    text: str
    locator: str


@dataclass(frozen=True)
class CheckFigure:
    """One cited reported figure as the reader sees it."""

    label: str
    period: str
    display: str


@dataclass(frozen=True)
class CheckItem:
    """One verified finding, reduced to what a reader would see and nothing else.

    The engine's rationale and confidence are left out on purpose: the checker
    must judge the evidence, not be persuaded by the writer's reasoning.
    """

    statement: str
    stance: Stance
    excerpts: tuple[CheckExcerpt, ...] = ()
    figures: tuple[CheckFigure, ...] = ()


@dataclass(frozen=True)
class Judgement:
    """A checker's verdict on the item at ``index`` (0-based) and a one-sentence reason."""

    index: int
    verdict: SupportVerdict
    reason: str


class Checker(Protocol):
    """A second reader that judges, finding by finding, whether the evidence means what is said.

    ``name`` and ``detail`` are recorded on the run. ``check`` returns one
    :class:`Judgement` per item, by index, and raises on any failure; the
    pipeline then leaves the findings unchecked and says so.
    """

    name: str
    detail: str

    def check(
        self,
        request: ThesisRequest,
        company: Company,
        claim: Claim,
        findings: Sequence[CheckItem],
    ) -> list[Judgement]:
        """One judgement per item of ``findings``."""
        ...

    def same_model_as(self, engine_model: str | None) -> bool:
        """True when this checker reads with the model that wrote the findings."""
        ...


# A page fetcher for the optional extra URLs: URL in, FetchedPage out, FetchError on failure.
PageFetcher = Callable[[str], "object"]
