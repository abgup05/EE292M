"""The deterministic engine used when no model key is configured, and as the fallback.

It never judges: it quotes the sentences of the retrieved passages that share
the most terms with a claim, labels each one ``context`` with low confidence,
and writes a summary that counts the verdicts the backend computed. Every
quote is an exact substring of its passage, so the citation gate can always
verify it.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from ed_v13.core import limits, policy
from ed_v13.core.documents import Passage
from ed_v13.core.metric_models import Metric
from ed_v13.core.models import (
    Claim,
    Company,
    Confidence,
    Finding,
    Stance,
    ThesisRequest,
    Verdict,
)
from ed_v13.core.ports import ClaimDraft, FindingDraft, Quote, SummaryDraft
from ed_v13.core.text import sentence_spans, tokenize

MIN_SENTENCE_CHARS = 40
MAX_SENTENCE_CHARS = 400
MAX_QUOTED_SENTENCES = min(3, limits.MAX_FINDINGS_PER_CLAIM)
MIN_SHARED_TOKENS = 2
MAX_STATEMENT_CHARS = 400

STATEMENT_PREFIX = "The filing states: "
FINDING_RATIONALE = "Quoted by keyword overlap with the claim; no stance was judged."
NO_MATCH_RATIONALE = "No sentence in the retrieved passages shares enough terms with the claim."
NEXT_STEPS = [
    "Open each excerpt in its filing and judge whether it supports or challenges the claim.",
    "Configure a model key and run again to have each finding's stance judged.",
]
JUDGED_NEXT_STEPS = [
    "Open each excerpt in its filing and read it in context before relying on it.",
]
NOT_ASSESSED_LABEL = "Not assessed"

_WORD = re.compile(r"[A-Za-z0-9]+")


def _query(claim: str) -> str:
    """The claim's words that survive tokenizing, in order, one per distinct token."""
    words: list[str] = []
    seen: set[str] = set()
    for word in _WORD.findall(claim):
        tokens = tokenize(word)
        if tokens and tokens[0] not in seen:
            seen.add(tokens[0])
            words.append(word)
    return " ".join(words)


def _quoted(passage_id: str, sentence: str) -> FindingDraft:
    """A context finding quoting ``sentence`` from passage ``passage_id``."""
    return FindingDraft(
        statement=_statement(sentence),
        stance=Stance.context,
        quotes=[Quote(passage_id=passage_id, text=sentence)],
        confidence=Confidence.low,
        rationale=FINDING_RATIONALE,
    )


def _opening(passage: Passage) -> tuple[str, str] | None:
    """The passage's first sentence a quote may be (40 characters up to the excerpt limit)."""
    for start, end in sentence_spans(passage.text):
        sentence = passage.text[start:end]
        if MIN_SENTENCE_CHARS <= len(sentence) <= limits.MAX_EXCERPT_CHARS:
            return passage.id, sentence
    return None


def _statement(sentence: str) -> str:
    statement = f"{STATEMENT_PREFIX}{sentence}"
    if len(statement) <= MAX_STATEMENT_CHARS:
        return statement
    return statement[: MAX_STATEMENT_CHARS - 1].rstrip() + "…"


class ExtractiveAnalyst:
    """Keyword-overlap quoting with no stance and no invented facts."""

    name = "extractive"
    detail = "deterministic sentence matching, no model"

    def plan(self, request: ThesisRequest, company: Company) -> list[list[str]]:
        """One query per claim: the claim's content words."""
        return [[_query(claim)] for claim in request.claims]

    def assess(
        self,
        request: ThesisRequest,
        company: Company,
        claim: Claim,
        passages: list[Passage],
        figures: Sequence[Metric] = (),
    ) -> ClaimDraft:
        """Quote up to three sentences sharing the most tokens (at least two) with the claim.

        Candidates are sentences of 40 to 400 characters; ties go to the earlier
        passage, then the earlier sentence. Each quote is an exact substring of
        its passage. A current report's passage offered to the claim (one with a
        ``form``, pinned there because the claim bears on its item) is quoted
        first, by its opening sentence, whatever words it shares; the findings
        stay at most :data:`~app.core.limits.MAX_FINDINGS_PER_CLAIM`. ``figures``
        are accepted for the interface and ignored: this engine judges nothing,
        so it cites no figure.
        """
        wanted = set(tokenize(claim.text))
        pinned = [_opening(p) for p in passages if p.form]
        candidates: list[tuple[int, int, int, str, str]] = []
        for passage_order, passage in enumerate(passages):
            if passage.form:
                continue
            for sentence_order, (start, end) in enumerate(sentence_spans(passage.text)):
                sentence = passage.text[start:end]
                if not MIN_SENTENCE_CHARS <= len(sentence) <= MAX_SENTENCE_CHARS:
                    continue
                shared = len(wanted & set(tokenize(sentence)))
                if shared >= MIN_SHARED_TOKENS:
                    candidates.append(
                        (-shared, passage_order, sentence_order, passage.id, sentence)
                    )
        candidates.sort()
        findings: list[FindingDraft] = []
        quoted: set[str] = set()
        for passage_id, sentence in (item for item in pinned if item is not None):
            if sentence in quoted or len(findings) >= limits.MAX_FINDINGS_PER_CLAIM:
                continue
            quoted.add(sentence)
            findings.append(_quoted(passage_id, sentence))
        current = len(findings)
        matched = 0
        for _shared, _passage_order, _sentence_order, passage_id, sentence in candidates:
            if matched >= MAX_QUOTED_SENTENCES or len(findings) >= limits.MAX_FINDINGS_PER_CLAIM:
                break
            if sentence in quoted:
                continue
            quoted.add(sentence)
            findings.append(_quoted(passage_id, sentence))
            matched += 1
        if not findings:
            return ClaimDraft(rationale=NO_MATCH_RATIONALE)
        rationale = (
            f"{matched} sentence(s) quoted because they share the most terms with the claim; "
            "no stance was judged."
        )
        if current:
            rationale = (
                f"{current} opening sentence(s) quoted from current reports (8-K) filed after "
                f"the periodic reports, on a subject the claim bears on; {rationale}"
            )
        return ClaimDraft(findings=findings, rationale=rationale)

    def summarize(
        self,
        request: ThesisRequest,
        company: Company,
        claims: list[Claim],
        findings: list[Finding],
    ) -> SummaryDraft:
        """A template sentence counting the verdicts present; it states no fact from the filings.

        Verdicts are counted under their labels from :data:`policy.VERDICT_LABELS`,
        in that order, then claims not assessed at all. The warning that no
        engine judged a stance is added only when some claim is unjudged, so a
        run whose verdicts a model judged is not misdescribed when only its
        summary step fell back to this engine.
        """
        counts = Counter(claim.verdict for claim in claims)
        parts = [
            f"{label}: {counts[verdict]}"
            for verdict, label in policy.VERDICT_LABELS.items()
            if counts[verdict]
        ]
        if counts[None]:
            parts.append(f"{NOT_ASSESSED_LABEL}: {counts[None]}")
        summary = f"Verdicts across {len(claims)} claims — " + "; ".join(parts) + "."
        unjudged = counts[Verdict.unjudged]
        if unjudged:
            summary += (
                f" No engine judged the stance of the passages found for {unjudged} claim(s), "
                "so read those excerpts before relying on them."
            )
        return SummaryDraft(
            summary=summary,
            next_steps=list(NEXT_STEPS if unjudged else JUDGED_NEXT_STEPS),
        )
