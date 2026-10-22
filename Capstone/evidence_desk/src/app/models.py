"""Record types for a research run and the validated request that starts one.

These are the shapes persisted by :mod:`app.store` and returned by the API.
Field limits follow the data contract in ``Capstone/PROMPT.md``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.urls import UnsafeURL, canonicalize, validate_public_url


class RunStatus(StrEnum):
    running = "running"
    complete = "complete"
    partial = "partial"
    failed = "failed"


class Stance(StrEnum):
    supports = "supports"
    challenges = "challenges"
    context = "context"


class Confidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class SubquestionStatus(StrEnum):
    pending = "pending"
    answered = "answered"
    unanswered = "unanswered"


class ExtractionStatus(StrEnum):
    extracted = "extracted"
    failed = "failed"


def _trimmed(value: str) -> str:
    return value.strip()


class ResearchRequest(BaseModel):
    """Inputs for one research run, validated at the API boundary."""

    question: str = Field(min_length=20, max_length=2000)
    decision: str = Field(min_length=10, max_length=500)
    scope_notes: str = Field(default="", max_length=5000)
    seed_urls: list[str] = Field(default_factory=list, max_length=20)
    source_budget: int = Field(default=10, ge=6, le=15, strict=True)

    @field_validator("question", "decision", "scope_notes", mode="before")
    @classmethod
    def _trim_text(cls, value: object) -> object:
        return _trimmed(value) if isinstance(value, str) else value

    @field_validator("question", "decision")
    @classmethod
    def _not_blank(cls, value: str, info) -> str:
        if not value:
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("seed_urls")
    @classmethod
    def _public_distinct_urls(cls, urls: list[str]) -> list[str]:
        canonical: list[str] = []
        for url in urls:
            try:
                validate_public_url(url)
            except UnsafeURL as exc:
                raise ValueError(f"{url!r}: {exc}") from exc
            normalized = canonicalize(url)
            if normalized in canonical:
                raise ValueError(f"seed_urls must be distinct; {normalized!r} repeats")
            canonical.append(normalized)
        return canonical


class Subquestion(BaseModel):
    id: str
    text: str
    search_query: str
    status: SubquestionStatus = SubquestionStatus.pending


class Source(BaseModel):
    """A retrieved page. ``published_date`` is metadata-derived or absent, never guessed."""

    id: str
    canonical_url: str
    requested_url: str
    title: str
    publisher: str
    published_date: str | None = None
    retrieved_at: datetime
    content_hash: str
    extraction_status: ExtractionStatus
    source_type: str = "public_html"
    origin: str = "seed"
    error: str | None = None


class Evidence(BaseModel):
    """An exact excerpt from a stored source, tied to one finding."""

    id: str
    source_id: str
    excerpt: str
    locator: str
    stance: Stance
    finding_id: str


class Finding(BaseModel):
    id: str
    statement: str
    evidence_ids: list[str]
    confidence: Confidence
    rationale: str
    subquestion_ids: list[str] = Field(default_factory=list)
    verified: bool = False
    single_source: bool = False


class Brief(BaseModel):
    direct_answer: str
    findings: list[Finding]
    disagreements: list[str]
    unknowns: list[str]
    next_steps: list[str]
    source_ids: list[str]
    coverage_status: RunStatus


class Run(BaseModel):
    """The full persisted record of one research run."""

    id: str
    inputs: ResearchRequest
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    coverage_limits: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    subquestions: list[Subquestion] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    unsupported_findings: list[Finding] = Field(default_factory=list)
    brief: Brief | None = None
    synthesizer: str = "extractive"
