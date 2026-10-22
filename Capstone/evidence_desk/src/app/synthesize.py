"""Synthesis interface and the credential-free extractive backend.

A synthesizer plans subquestions and drafts findings from stored source text.
Drafts are untrusted until :mod:`app.verify` checks every excerpt, so a
backend may be a model or, as here, a deterministic keyword matcher that only
ever quotes exact sentences from the extracted text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from app.extract import ExtractedDocument
from app.models import (
    Confidence,
    Evidence,
    Finding,
    ResearchRequest,
    Stance,
    Subquestion,
)

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "before",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "should",
        "that",
        "the",
        "their",
        "this",
        "to",
        "use",
        "using",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "would",
        "organization",
        "organizations",
        "whether",
    ]
)
CONTRARY_CUES = (
    "however",
    "risk",
    "risks",
    "challenge",
    "challenges",
    "limitation",
    "limitations",
    "concern",
    "concerns",
    "inaccurate",
    "cannot",
    "not ",
    "fail",
    "harm",
    "unknown",
    "uncertain",
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
MIN_SENTENCE = 40
MAX_SENTENCE = 400
MAX_FINDINGS = 8
MIN_FINDINGS = 3


@dataclass
class Draft:
    """Unverified synthesis output; IDs are assigned here, verification happens later."""

    direct_answer: str
    findings: list[Finding] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    disagreements: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    answered_subquestion_ids: set[str] = field(default_factory=set)


class Synthesizer(Protocol):
    """What the pipeline needs from any synthesis backend."""

    name: str

    def plan(self, request: ResearchRequest) -> list[Subquestion]: ...

    def synthesize(
        self,
        request: ResearchRequest,
        subquestions: list[Subquestion],
        documents: dict[str, ExtractedDocument],
    ) -> Draft: ...


def keywords(text: str) -> set[str]:
    """Lower-case content words of at least four letters, minus stopwords."""
    words = re.findall(r"[a-z][a-z-]{3,}", text.lower())
    return {word for word in words if word not in STOPWORDS}


def _query(text: str, limit: int = 8) -> str:
    seen: list[str] = []
    for word in re.findall(r"[a-z][a-z-]{3,}", text.lower()):
        if word not in STOPWORDS and word not in seen:
            seen.append(word)
    return " ".join(seen[:limit])


@dataclass(frozen=True)
class _Candidate:
    source_id: str
    locator: str
    sentence: str
    words: frozenset[str]
    contrary: bool


class ExtractiveSynthesizer:
    """Keyword-overlap synthesis that quotes exact sentences and never invents a conclusion."""

    name = "extractive"

    def plan(self, request: ResearchRequest) -> list[Subquestion]:
        """Template subquestions: the original question, support, the contrary case, unknowns."""
        texts = [
            request.question,
            f"What documented evidence supports this choice: {request.decision}?",
            (
                f"What evidence argues against this choice, or shows how the initial "
                f"hypothesis could be wrong: {request.decision}?"
            ),
            "What remains unknown, disputed, or undocumented about the question?",
        ]
        if request.scope_notes:
            texts.append(
                "Which stated scope constraints (geography, time, definitions) change the answer?"
            )
        return [
            Subquestion(
                id=f"sq-{index}",
                text=text,
                search_query=_query(f"{text} {request.question}"),
            )
            for index, text in enumerate(texts, start=1)
        ]

    def synthesize(
        self,
        request: ResearchRequest,
        subquestions: list[Subquestion],
        documents: dict[str, ExtractedDocument],
    ) -> Draft:
        """Pick the best-matching exact sentences per subquestion and present them as findings."""
        candidates = _candidates(documents)
        question_words = keywords(f"{request.question} {request.decision}")
        chosen: list[tuple[_Candidate, Subquestion, int]] = []
        used: set[tuple[str, str]] = set()
        for subquestion in subquestions:
            wanted = keywords(subquestion.text) | question_words
            contrary_question = (
                "against" in subquestion.text or "wrong" in subquestion.text
            )
            scored = []
            for candidate in candidates:
                score = len(candidate.words & wanted)
                if contrary_question and candidate.contrary:
                    score += 2
                elif contrary_question:
                    score -= 1
                if score > 0:
                    scored.append((score, candidate))
            scored.sort(
                key=lambda item: (-item[0], item[1].source_id, item[1].sentence)
            )
            picked_sources: set[str] = set()
            for score, candidate in scored:
                key = (candidate.source_id, candidate.sentence)
                if key in used or candidate.source_id in picked_sources:
                    continue
                used.add(key)
                picked_sources.add(candidate.source_id)
                chosen.append((candidate, subquestion, score))
                if len(picked_sources) >= 2:
                    break
        if len(chosen) < MIN_FINDINGS:
            for candidate in sorted(
                candidates, key=lambda c: -len(c.words & question_words)
            ):
                key = (candidate.source_id, candidate.sentence)
                if key not in used and candidate.words & question_words:
                    used.add(key)
                    chosen.append(
                        (candidate, subquestions[0] if subquestions else None, 0)
                    )
                if len(chosen) >= MIN_FINDINGS:
                    break
        chosen = chosen[:MAX_FINDINGS]
        return self._draft(request, subquestions, documents, chosen)

    def _draft(
        self,
        request: ResearchRequest,
        subquestions: list[Subquestion],
        documents: dict[str, ExtractedDocument],
        chosen: list[tuple[_Candidate, Subquestion | None, int]],
    ) -> Draft:
        findings: list[Finding] = []
        evidence: list[Evidence] = []
        answered: set[str] = set()
        for index, (candidate, subquestion, _score) in enumerate(chosen, start=1):
            doc = documents[candidate.source_id]
            finding_id = f"f-{index}"
            evidence_id = f"e-{index}"
            contrary_question = subquestion is not None and (
                "against" in subquestion.text or "wrong" in subquestion.text
            )
            if candidate.contrary or contrary_question:
                stance = Stance.challenges
            elif subquestion is not None and "unknown" in subquestion.text:
                stance = Stance.context
            else:
                stance = Stance.supports
            findings.append(
                Finding(
                    id=finding_id,
                    statement=f"{doc.title} ({doc.publisher}) states: {candidate.sentence}",
                    evidence_ids=[evidence_id],
                    confidence=Confidence.low,
                    rationale=(
                        "Extractive mode: one exact passage selected by keyword overlap from a "
                        "single source; no model judgement or corroboration was applied."
                    ),
                )
            )
            evidence.append(
                Evidence(
                    id=evidence_id,
                    source_id=candidate.source_id,
                    excerpt=candidate.sentence,
                    locator=candidate.locator,
                    stance=stance,
                    finding_id=finding_id,
                )
            )
            if subquestion is not None:
                answered.add(subquestion.id)
        unanswered = [s.text for s in subquestions if s.id not in answered]
        stances = {e.stance for e in evidence}
        disagreements = (
            [
                "Selected passages include both supporting and challenging statements; "
                "compare stances."
            ]
            if {Stance.supports, Stance.challenges} <= stances
            else []
        )
        source_count = len({e.source_id for e in evidence})
        direct_answer = (
            f"Extractive mode (no model credential configured): {len(findings)} exact passages "
            f"from {source_count} source(s) were selected by keyword overlap with the question "
            f"and decision. They are quoted verbatim as evidence to weigh, not as a conclusion."
        )
        return Draft(
            direct_answer=direct_answer,
            findings=findings,
            evidence=evidence,
            disagreements=disagreements,
            unknowns=[f"No passage matched: {text}" for text in unanswered],
            next_steps=[
                "Configure a model credential to obtain reasoned findings and confidence "
                "rationale.",
                "Add independent sources for each finding currently backed by a single page.",
                "Review each quoted passage in its source context before relying on it.",
            ],
            answered_subquestion_ids=answered,
        )


def _candidates(documents: dict[str, ExtractedDocument]) -> list[_Candidate]:
    out: list[_Candidate] = []
    for source_id, doc in documents.items():
        for section in doc.sections:
            for sentence in SENTENCE_SPLIT.split(section.text):
                sentence = sentence.strip()
                if (
                    not MIN_SENTENCE <= len(sentence) <= MAX_SENTENCE
                    or sentence not in doc.text
                ):
                    continue
                lowered = sentence.lower()
                out.append(
                    _Candidate(
                        source_id=source_id,
                        locator=section.heading or doc.title,
                        sentence=sentence,
                        words=frozenset(keywords(sentence)),
                        contrary=any(cue in lowered for cue in CONTRARY_CUES),
                    )
                )
    return out
