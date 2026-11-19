"""Record types for one thesis run, and the request that starts it.

Pure data: nothing here touches the network, the file system or URL policy.
These are the shapes persisted by :mod:`app.store` and returned by the API;
their limits come from :mod:`app.core.limits`.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ed_v10.core import limits
from ed_v10.core.metric_models import Metric, Series


class RunStatus(StrEnum):
    running = "running"
    complete = "complete"
    partial = "partial"
    failed = "failed"


class Stance(StrEnum):
    """How one finding bears on the claim it was assessed against."""

    supports = "supports"
    challenges = "challenges"
    context = "context"


class Verdict(StrEnum):
    """Computed by the backend from verified findings, never asserted by a model."""

    supported = "supported"
    challenged = "challenged"
    mixed = "mixed"
    unjudged = "unjudged"
    not_addressed = "not_addressed"


class Confidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class SourceKind(StrEnum):
    sec_filing = "sec_filing"
    sec_xbrl = "sec_xbrl"
    public_html = "public_html"


class ExtractionStatus(StrEnum):
    extracted = "extracted"
    failed = "failed"


# One to six characters, optionally a class suffix: NVDA, BRK.B, BF-B.
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z]{1,2})?$")


class ThesisRequest(BaseModel):
    """Inputs for one run: a company, the decision, and the claims to test.

    A field the request does not have is refused, not ignored: a misspelt option
    would otherwise start a run without it and say nothing.
    """

    model_config = ConfigDict(extra="forbid")

    ticker: str
    decision: str = Field(
        min_length=limits.MIN_DECISION_CHARS, max_length=limits.MAX_DECISION_CHARS
    )
    claims: list[str] = Field(min_length=limits.MIN_CLAIMS, max_length=limits.MAX_CLAIMS)
    scope_notes: str = Field(default="", max_length=limits.MAX_SCOPE_CHARS)
    filings: int = Field(default=limits.DEFAULT_FILINGS, ge=1, le=limits.MAX_FILINGS, strict=True)
    extra_urls: list[str] = Field(default_factory=list, max_length=limits.MAX_EXTRA_URLS)
    tagged_figures: bool = Field(
        default=False,
        strict=True,
        description=(
            "Also offer the engine the segment, product, geography and customer figures tagged "
            "in the newest annual and quarterly report read. Off by default: the figures change "
            "the engine's assessment prompt, and recorded model answers are keyed by the exact "
            "prompt, so a run without the option must ask exactly what it asked before."
        ),
    )

    @field_validator("ticker", "decision", "scope_notes", mode="before")
    @classmethod
    def _trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("ticker")
    @classmethod
    def _ticker_shape(cls, value: str) -> str:
        ticker = value.upper()
        if not TICKER_PATTERN.fullmatch(ticker):
            raise ValueError(
                "ticker must be 1 to 6 letters or digits, optionally with a class suffix "
                "such as BRK.B"
            )
        return ticker

    @field_validator("claims")
    @classmethod
    def _claims_distinct_and_sized(cls, claims: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for position, claim in enumerate(claims, start=1):
            text = " ".join(claim.split())
            if not limits.MIN_CLAIM_CHARS <= len(text) <= limits.MAX_CLAIM_CHARS:
                raise ValueError(
                    f"claim {position} must be {limits.MIN_CLAIM_CHARS} to "
                    f"{limits.MAX_CLAIM_CHARS} characters; it has {len(text)}"
                )
            key = text.casefold()
            if key in seen:
                raise ValueError(f"claims must be distinct; claim {position} repeats")
            seen.add(key)
            cleaned.append(text)
        return cleaned


class Company(BaseModel):
    """A filer as SEC EDGAR identifies it."""

    cik: int
    ticker: str
    name: str


class Claim(BaseModel):
    """One testable statement from the thesis and what the run concluded about it."""

    id: str
    text: str
    queries: list[str] = Field(default_factory=list)
    verdict: Verdict | None = None
    rationale: str = ""
    finding_ids: list[str] = Field(default_factory=list)
    passages_considered: int = 0
    assessed_by: str = ""


class Source(BaseModel):
    """A retrieved document. For a filing, ``published_date`` is the filing date.

    ``item_coverage`` is the share (0.0 to 1.0) of a filing's text that sits under a
    numbered Item heading, set for every filing read; None for pages, XBRL facts and
    filings that were not read.
    """

    id: str
    kind: SourceKind
    title: str
    publisher: str
    url: str
    requested_url: str = ""
    form: str | None = None
    accession: str | None = None
    period_end: str | None = None
    published_date: str | None = None
    retrieved_at: datetime
    content_hash: str
    extraction_status: ExtractionStatus
    sections: int = 0
    characters: int = 0
    error: str | None = None
    item_coverage: float | None = None


class Evidence(BaseModel):
    """An exact excerpt of a stored source. ``start`` is its offset in the stored text.

    ``locator`` is the heading of the offered passage that holds the excerpt. ``link_kind``
    says what ``link`` opens (:func:`app.core.links.link_kind`): "passage", "first-line" or
    "document"; "" in records written before it was kept.
    """

    id: str
    source_id: str
    finding_id: str
    excerpt: str
    locator: str
    start: int
    context_before: str = ""
    context_after: str = ""
    link: str = ""
    link_kind: str = ""


class FindingChecks(BaseModel):
    """Which automatic checks a finding went through. A check that did not run says so.

    ``quotes``: "passed" when at least one quote was found in the stored text, "none" when
    the finding cites no quote. ``numbers``: "passed" when every number in the statement was
    matched to a quote or a cited reported figure, "failed" when one was not, "none" when the
    statement has no number to check. A number in the finding's reason that its quotes and
    figures do not hold adds a line starting "in the reason:" to ``numbers_detail`` (and the
    reason is withheld); it does not change ``numbers``. ``support`` is the second-model check
    that the excerpts
    mean what the statement says: "passed" (supported), "partly" (they support a weaker
    statement; the finding is kept and counts), "failed" (the finding is withheld) or
    "unchecked" (no checker, or the check could not run). ``support_detail`` is the
    checker's one-sentence reason.
    """

    quotes: str = "none"
    numbers: str = "none"
    numbers_detail: list[str] = Field(default_factory=list)
    support: str = "unchecked"
    support_detail: str = ""


class Finding(BaseModel):
    """A statement about one claim, tied to the excerpts and reported figures that back it.

    ``counted_as`` is the stance the verdict rule used for a verified finding (None for a
    withheld one): its own stance, or context when it rests on reported figures alone and
    the meaning check did not confirm it; ``count_note`` then says why
    (:func:`app.core.policy.mark_counted`).
    """

    id: str
    claim_id: str
    statement: str
    stance: Stance
    evidence_ids: list[str]
    confidence: Confidence
    rationale: str
    verified: bool = False
    filings_cited: int = 0
    metric_ids: list[str] = Field(default_factory=list)
    checks: FindingChecks = Field(default_factory=FindingChecks)
    withheld_reason: str = ""
    counted_as: Stance | None = None
    count_note: str = ""


class Brief(BaseModel):
    """The decision-level summary. ``summary_origin`` says who wrote the summary text.

    ``provenance_note`` says where this run's evidence came from (the SEC filings, and any
    page the user added); "" in records written before it was kept.
    """

    summary: str
    summary_origin: str
    unknowns: list[str]
    next_steps: list[str]
    coverage_status: RunStatus
    status_note: str
    provenance_note: str = ""


class DecisionValue(StrEnum):
    accepted = "accepted"
    rejected = "rejected"


class Decision(BaseModel):
    """A reviewer's decision on one verified finding of one run.

    Decisions are the one kind of data here that nothing can rebuild: they
    are kept in the record database, which is the file that is backed up.
    """

    run_id: str
    finding_id: str
    value: DecisionValue
    note: str = Field(default="", max_length=limits.MAX_NOTE_CHARS)
    decided_at: datetime


class DecisionRequest(BaseModel):
    """What a client sends for one finding: a value, or null to clear the decision."""

    value: DecisionValue | None
    note: str = Field(default="", max_length=limits.MAX_NOTE_CHARS)

    @field_validator("note", mode="before")
    @classmethod
    def _trim_note(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ReviewedClaim(BaseModel):
    """One claim after review. ``reviewed_verdict`` counts accepted findings only."""

    claim_id: str
    engine_verdict: Verdict | None
    reviewed_verdict: Verdict | None
    accepted: int = 0
    rejected: int = 0
    undecided: int = 0


class Review(BaseModel):
    """Every decision on a run and the verdicts that follow from them, computed by the backend."""

    run_id: str
    decisions: list[Decision] = Field(default_factory=list)
    claims: list[ReviewedClaim] = Field(default_factory=list)
    findings_total: int = 0
    decided: int = 0
    complete: bool = False


class Thesis(BaseModel):
    """A saved thesis: a named request that can be run again when a new filing arrives."""

    id: str
    name: str = Field(min_length=1, max_length=limits.MAX_THESIS_NAME_CHARS)
    request: ThesisRequest
    created_at: datetime
    run_ids: list[str] = Field(default_factory=list)


class ThesisCreate(BaseModel):
    """What a client sends to save a thesis."""

    name: str = Field(min_length=1, max_length=limits.MAX_THESIS_NAME_CHARS)
    request: ThesisRequest

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value


class ClaimChange(BaseModel):
    """How one claim's result differs between two runs of the same thesis."""

    claim: str
    before: Verdict | None
    after: Verdict | None
    moved: bool
    change: str = ""
    reviewed_before: Verdict | None = None
    reviewed_after: Verdict | None = None
    excerpts_added: int = 0
    excerpts_dropped: int = 0


class RunComparison(BaseModel):
    """What moved between an earlier and a later run of one thesis."""

    thesis_id: str | None
    earlier_run_id: str
    later_run_id: str
    earlier_finished_at: datetime | None = None
    later_finished_at: datetime | None = None
    sources_added: list[str] = Field(default_factory=list)
    sources_dropped: list[str] = Field(default_factory=list)
    claims: list[ClaimChange] = Field(default_factory=list)
    verdicts_moved: int = 0
    claims_total: int = 0
    note: str = ""
    earlier_engine: str = ""
    later_engine: str = ""
    engines_differ: bool = False


class Coverage(BaseModel):
    """What the run read and kept, counted by the backend so no view has to."""

    # filings_asked: the filings the request asked for; sources_requested: the filings EDGAR
    # listed (at most that many) plus the extra pages, identical content counted once.
    filings_asked: int = 0
    sources_requested: int = 0
    sources_read: int = 0
    passages_indexed: int = 0
    claims_total: int = 0
    claims_with_evidence: int = 0
    findings_proposed: int = 0
    findings_verified: int = 0
    findings_withheld: int = 0
    # Verified findings that rest on reported figures alone, with no excerpt.
    findings_without_quote: int = 0
    engine_fallbacks: int = 0
    # Every quote offered is either found word for word inside a passage offered for its
    # claim (quotes_found, whatever became of its finding) or rejected, so
    # quotes_found + quotes_rejected == quotes_offered. excerpts_verified counts the
    # excerpts kept as evidence of verified findings.
    excerpts_verified: int = 0
    quotes_offered: int = 0
    quotes_found: int = 0
    quotes_rejected: int = 0
    # Reported figures (XBRL company facts): computed for the run, shown to the engine,
    # cited by verified findings; numbers written in finding statements and how many
    # were not found in the finding's quotes or cited figures.
    metrics_computed: int = 0
    figures_offered: int = 0
    # Figures from the filings' own tags shown to the engine after those above, when the run
    # asked for them (ThesisRequest.tagged_figures); the engine saw the sum of the two.
    # figures_cited counts citations of either kind.
    tagged_figures_offered: int = 0
    figures_cited: int = 0
    numbers_checked: int = 0
    numbers_unmatched: int = 0
    # Reasons and commentary replaced because they cited a number that is in neither their
    # quotes nor their cited figures: a finding's reason, or a claim's commentary.
    reasons_withheld: int = 0
    # The meaning check by a second model: verified findings it judged, those it judged only
    # partly supported (kept), and those it judged unsupported (withheld; also counted in
    # findings_withheld).
    findings_checked: int = 0
    findings_partly: int = 0
    findings_failed_meaning: int = 0


class Run(BaseModel):
    """The full persisted record of one thesis run."""

    id: str
    inputs: ThesisRequest
    thesis_id: str | None = None
    status: RunStatus
    stage: str = "queued"
    stage_detail: str = ""
    started_at: datetime
    finished_at: datetime | None = None
    company: Company | None = None
    engine: str = "extractive"
    engine_detail: str = ""
    # The second model that checked the findings' meaning; "none" when nothing checked them.
    checker: str = "none"
    checker_detail: str = ""
    claims: list[Claim] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    unsupported_findings: list[Finding] = Field(default_factory=list)
    coverage_limits: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    metrics: list[Metric] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)
    metrics_notes: list[str] = Field(default_factory=list)
    brief: Brief | None = None
