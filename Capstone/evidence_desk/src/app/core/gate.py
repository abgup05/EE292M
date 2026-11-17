"""The citation gate: the step between an engine's drafts and anything a reader sees.

An engine says it copied a quote from a named passage. The gate looks for that
quote in the stored text of the passage's source, exactly or after collapsing
whitespace and folding typographic quotes, dashes and the ellipsis, and keeps
the *stored* span, never the engine's wording. So every excerpt shown is
byte-exact: ``stored_text[e.start : e.start + len(e.excerpt)] == e.excerpt``.
A finding with no surviving quote is withheld and reported (PROMPT.md 4.8).

Pure: no network, no I/O, no clock.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.core import limits
from app.core.documents import Passage
from app.core.links import passage_link
from app.core.models import Evidence, Finding
from app.core.ports import ClaimDraft, FindingDraft

# Typographic characters folded to their plain forms before comparison.
_FOLDS: dict[str, str] = {
    "‘": "'",  # ‘
    "’": "'",  # ’
    "‚": "'",  # ‚
    "‛": "'",  # ‛
    "“": '"',  # “
    "”": '"',  # ”
    "„": '"',  # „
    "‟": '"',  # ‟
    "‐": "-",  # hyphen
    "‑": "-",  # non-breaking hyphen
    "‒": "-",  # figure dash
    "–": "-",  # –
    "—": "-",  # —
    "―": "-",  # horizontal bar
    "−": "-",  # minus sign
    "…": "...",  # …
}
# Spans that normalisation rewrites: whitespace runs other than one plain space, and folds.
# A lone plain space is already normal, so typical prose produces few matches.
_REWRITE = re.compile(r"\s{2,}|[^\S ]|[" + "".join(_FOLDS) + "]")


def normalise(text: str) -> str:
    """Collapse whitespace runs to one space and fold typographic characters.

    Leading and trailing whitespace is kept (as one space); callers that
    compare quotes strip it.
    """
    return _REWRITE.sub(lambda match: _FOLDS.get(match.group(), " "), text)


class TextIndex:
    """One stored text, prepared for locating many quotes in it.

    The normalised text and its offset map are built once, on the first quote
    that is not an exact match, and reused for every later quote. The map is a
    list of breakpoints ``(normalised offset, original offset)``; between two
    breakpoints the texts advance together, so lookups are a binary search.
    """

    def __init__(self, text: str) -> None:
        """Index ``text``; nothing is computed until a quote needs it."""
        self.text = text
        self._normal: str | None = None
        self._norm_starts: list[int] = []
        self._orig_starts: list[int] = []

    def _build(self) -> str:
        if self._normal is not None:
            return self._normal
        pieces: list[str] = []
        norm_starts = [0]
        orig_starts = [0]
        emitted = 0
        copied_to = 0
        for match in _REWRITE.finditer(self.text):
            begin, end = match.span()
            pieces.append(self.text[copied_to:begin])
            emitted += begin - copied_to
            replacement = _FOLDS.get(match.group(), " ")
            pieces.append(replacement)
            if len(replacement) != end - begin:
                # Every normalised character of the replacement maps to its first original one.
                for offset in range(len(replacement)):
                    norm_starts.append(emitted + offset)
                    orig_starts.append(begin)
                norm_starts.append(emitted + len(replacement))
                orig_starts.append(end)
            emitted += len(replacement)
            copied_to = end
        pieces.append(self.text[copied_to:])
        self._normal = "".join(pieces)
        self._norm_starts = norm_starts
        self._orig_starts = orig_starts
        return self._normal

    def _to_original(self, position: int) -> int:
        index = bisect_right(self._norm_starts, position) - 1
        return self._orig_starts[index] + (position - self._norm_starts[index])

    def _to_normal(self, position: int) -> int:
        """The normalised offset at or just before original ``position`` (a search hint)."""
        index = bisect_right(self._orig_starts, position) - 1
        normal = self._norm_starts[index] + (position - self._orig_starts[index])
        if index + 1 < len(self._norm_starts):
            normal = min(normal, self._norm_starts[index + 1])
        return normal

    def _aligned(self, begin: int, end: int, length: int) -> bool:
        """True when a normalised match neither starts nor ends inside one original character."""
        if begin > 0 and self._to_original(begin) == self._to_original(begin - 1):
            return False
        return end >= length or self._to_original(end) != self._to_original(end - 1)

    def locate(self, quote: str, start: int = 0) -> tuple[int, int] | None:
        """The ``(start, end)`` span of ``quote`` in the original text, or None.

        Searches from original offset ``start``. An exact match wins; otherwise
        both sides are normalised (see :func:`normalise`) and the match is
        mapped back, so ``text[start:end]`` is the stored span. Surrounding
        whitespace of the quote is ignored.
        """
        wanted = quote.strip()
        if not wanted:
            return None
        exact = self.text.find(wanted, start)
        if exact >= 0:
            return exact, exact + len(wanted)
        needle = normalise(wanted).strip()
        if not needle:
            return None
        haystack = self._build()
        position = haystack.find(needle, self._to_normal(start) if start > 0 else 0)
        while position >= 0:
            finish = position + len(needle)
            if self._aligned(position, finish, len(haystack)):
                begin = self._to_original(position)
                if begin >= start:
                    return begin, self._to_original(finish - 1) + 1
            position = haystack.find(needle, position + 1)
        return None


def locate(quote: str, text: str) -> tuple[int, int] | None:
    """The ``(start, end)`` span of ``quote`` in ``text``, or None. See :class:`TextIndex`."""
    return TextIndex(text).locate(quote)


class IdMinter:
    """Issues sequential identifiers with one prefix: ``f1``, ``f2``, ..."""

    def __init__(self, prefix: str) -> None:
        """Start counting at 1 for ``prefix``."""
        self.prefix = prefix
        self.issued = 0

    def __call__(self) -> str:
        """The next identifier."""
        self.issued += 1
        return f"{self.prefix}{self.issued}"


@dataclass
class RunIds:
    """The run-wide identifier counters; pass the same instance to every ``gate_claim``."""

    findings: IdMinter = field(default_factory=lambda: IdMinter("f"))
    evidence: IdMinter = field(default_factory=lambda: IdMinter("e"))


class StoredSource:
    """A source's exact stored text, its URL, and the index used to locate quotes in it.

    Build one per source per run and reuse it for every claim.
    """

    def __init__(self, text: str, url: str) -> None:
        """Keep ``text`` exactly as stored; ``url`` is where the reader can open it."""
        self.text = text
        self.url = url
        self.index = TextIndex(text)


@dataclass
class GateResult:
    """What survived the gate for one claim, what did not, and why."""

    findings: list[Finding] = field(default_factory=list)
    unsupported: list[Finding] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    quotes_offered: int = 0
    quotes_rejected: int = 0


def _context_before(text: str, start: int) -> str:
    cut = max(0, start - limits.CONTEXT_CHARS)
    window = text[cut:start]
    if cut > 0 and not text[cut - 1].isspace() and window and not window[0].isspace():
        # The window begins mid-word: drop the partial word.
        space = next((i for i, char in enumerate(window) if char.isspace()), len(window))
        window = window[space:]
    return window.lstrip()


def _context_after(text: str, end: int) -> str:
    cut = min(len(text), end + limits.CONTEXT_CHARS)
    window = text[end:cut]
    if cut < len(text) and not text[cut].isspace() and window and not window[-1].isspace():
        # The window ends mid-word: drop the partial word.
        space = next((i for i in range(len(window) - 1, -1, -1) if window[i].isspace()), -1)
        window = window[: space + 1]
    return window.rstrip()


def _place(passage: Passage, source: StoredSource, quote: str) -> tuple[int, int] | None:
    """Locate ``quote`` in its source, preferring an occurrence inside the passage."""
    span = source.index.locate(quote, start=passage.start)
    if span is not None and span[1] <= passage.start + len(passage.text):
        return span
    return source.index.locate(quote)


def _check_finding(
    draft: FindingDraft,
    finding_id: str,
    passages: Mapping[str, Passage],
    sources: Mapping[str, StoredSource],
    result: GateResult,
) -> list[tuple[Passage, StoredSource, int, int]]:
    """The located, in-bounds, distinct spans of one draft finding; problems go to ``result``."""
    kept: list[tuple[Passage, StoredSource, int, int]] = []
    seen: set[tuple[str, int, int]] = set()
    for quote in draft.quotes:
        result.quotes_offered += 1
        passage = passages.get(quote.passage_id)
        problem: str | None = None
        if passage is None:
            problem = f"quote names unknown passage {quote.passage_id}"
        elif (source := sources.get(passage.source_id)) is None:
            problem = f"source {passage.source_id} of passage {passage.id} has no stored text"
        elif (span := _place(passage, source, quote.text)) is None:
            problem = f"quote not found in {passage.source_id} ({passage.locator})"
        elif (length := span[1] - span[0]) < limits.MIN_EXCERPT_CHARS:
            problem = (
                f"quote in {passage.source_id} ({passage.locator}) is too short: {length} "
                f"characters, at least {limits.MIN_EXCERPT_CHARS} required"
            )
        elif length > limits.MAX_EXCERPT_CHARS:
            problem = (
                f"quote in {passage.source_id} ({passage.locator}) is too long: {length} "
                f"characters, at most {limits.MAX_EXCERPT_CHARS} allowed"
            )
        if problem is not None:
            result.quotes_rejected += 1
            result.problems.append(f"{finding_id}: {problem}")
            continue
        key = (passage.source_id, span[0], span[1])
        if key not in seen:
            seen.add(key)
            kept.append((passage, source, span[0], span[1]))
    return kept


def gate_claim(
    claim_id: str,
    draft: ClaimDraft,
    passages: Mapping[str, Passage],
    sources: Mapping[str, StoredSource],
    ids: RunIds,
) -> GateResult:
    """Turn one engine draft into verified findings and evidence, and withheld findings.

    ``passages`` are the passages offered to the engine for this claim, by
    passage id; ``sources`` maps every source id to its :class:`StoredSource`.
    Each draft finding gets the next finding id from ``ids`` whether or not it
    survives, and each kept excerpt the next evidence id. A quote survives
    only if it is located in the stored text of its passage's source and the
    located span is ``MIN_EXCERPT_CHARS`` to ``MAX_EXCERPT_CHARS`` long.
    Drafts beyond ``MAX_FINDINGS_PER_CLAIM`` are not checked and are reported.
    """
    result = GateResult()
    drafts = draft.findings
    if len(drafts) > limits.MAX_FINDINGS_PER_CLAIM:
        result.problems.append(
            f"{claim_id}: the engine returned {len(drafts)} findings; only the first "
            f"{limits.MAX_FINDINGS_PER_CLAIM} were checked"
        )
        drafts = drafts[: limits.MAX_FINDINGS_PER_CLAIM]
    for finding_draft in drafts:
        finding_id = ids.findings()
        kept = _check_finding(finding_draft, finding_id, passages, sources, result)
        evidence_ids: list[str] = []
        for passage, source, start, end in kept:
            excerpt = source.text[start:end]
            item = Evidence(
                id=ids.evidence(),
                source_id=passage.source_id,
                finding_id=finding_id,
                excerpt=excerpt,
                locator=passage.locator,
                start=start,
                context_before=_context_before(source.text, start),
                context_after=_context_after(source.text, end),
                link=passage_link(source.url, excerpt),
            )
            result.evidence.append(item)
            evidence_ids.append(item.id)
        finding = Finding(
            id=finding_id,
            claim_id=claim_id,
            statement=finding_draft.statement,
            stance=finding_draft.stance,
            evidence_ids=evidence_ids,
            confidence=finding_draft.confidence,
            rationale=finding_draft.rationale,
            verified=bool(evidence_ids),
            filings_cited=len({passage.source_id for passage, *_ in kept}),
        )
        (result.findings if evidence_ids else result.unsupported).append(finding)
    return result
