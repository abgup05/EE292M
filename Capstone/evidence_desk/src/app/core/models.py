"""Record types for one thesis run, and the request that starts it.

Pure data: nothing here touches the network, the file system or URL policy.
These are the shapes persisted by :mod:`app.store` and returned by the API;
their limits come from :mod:`app.core.limits`.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.core import limits


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
    public_html = "public_html"


class ExtractionStatus(StrEnum):
    extracted = "extracted"
    failed = "failed"


# One to six characters, optionally a class suffix: NVDA, BRK.B, BF-B.
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z]{1,2})?$")


class ThesisRequest(BaseModel):
    """Inputs for one run: a company, the decision, and the claims to test."""

    ticker: str
    decision: str = Field(
        min_length=limits.MIN_DECISION_CHARS, max_length=limits.MAX_DECISION_CHARS
    )
    claims: list[str] = Field(min_length=limits.MIN_CLAIMS, max_length=limits.MAX_CLAIMS)
    scope_notes: str = Field(default="", max_length=limits.MAX_SCOPE_CHARS)
    filings: int = Field(default=limits.DEFAULT_FILINGS, ge=1, le=limits.MAX_FILINGS, strict=True)
    extra_urls: list[str] = Field(default_factory=list, max_length=limits.MAX_EXTRA_URLS)

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


class Source(BaseModel):
    """A retrieved document. For a filing, ``published_date`` is the filing date."""

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


class Evidence(BaseModel):
    """An exact excerpt of a stored source. ``start`` is its offset in the stored text."""

    id: str
    source_id: str
    finding_id: str
    excerpt: str
    locator: str
    start: int
    context_before: str = ""
    context_after: str = ""
    link: str = ""


class Finding(BaseModel):
    """A statement about one claim, tied to the excerpts that back it."""

    id: str
    claim_id: str
    statement: str
    stance: Stance
    evidence_ids: list[str]
    confidence: Confidence
    rationale: str
    verified: bool = False
    filings_cited: int = 0


class Brief(BaseModel):
    """The decision-level summary. ``summary_origin`` says who wrote the summary text."""

    summary: str
    summary_origin: str
    unknowns: list[str]
    next_steps: list[str]
    coverage_status: RunStatus
    status_note: str


class Coverage(BaseModel):
    """What the run read and kept, counted by the backend so no view has to."""

    sources_requested: int = 0
    sources_read: int = 0
    passages_indexed: int = 0
    claims_total: int = 0
    claims_with_evidence: int = 0
    findings_verified: int = 0
    findings_withheld: int = 0
    excerpts_verified: int = 0
    quotes_rejected: int = 0


class Run(BaseModel):
    """The full persisted record of one thesis run."""

    id: str
    inputs: ThesisRequest
    status: RunStatus
    stage: str = "queued"
    stage_detail: str = ""
    started_at: datetime
    finished_at: datetime | None = None
    company: Company | None = None
    engine: str = "extractive"
    claims: list[Claim] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    unsupported_findings: list[Finding] = Field(default_factory=list)
    coverage_limits: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    brief: Brief | None = None
