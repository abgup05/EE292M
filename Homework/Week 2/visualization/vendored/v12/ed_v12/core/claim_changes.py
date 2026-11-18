"""Which changed paragraphs of a run's filings share words with each of its claims.

Pure: claims and filing comparisons in, one :class:`ClaimChanges` per claim out; no
network, no files, no clock, and no model. This is deterministic keyword retrieval:
a paragraph is listed for a claim because it shares words with the claim or with
the search queries the run wrote for it, which says nothing about whether it
supports or challenges the claim.

**Corpus.** Every changed paragraph of every comparison, in a fixed order:
comparisons as given, Items in filing order, then added, removed, reworded and
numbers-only, each list in document order. The text searched is the paragraph
itself for an added one (of the later filing) or a removed one (of the earlier
filing), and the later paragraph of a reworded or numbers-only pair.

**Score.** One :class:`~app.retrieval.bm25.Bm25Index` over the corpus. A
paragraph's score for a claim is its best BM25 score over the claim's text and
its stored planner queries (``Claim.queries``), the rule the run's own retrieval
uses (:mod:`app.retrieval.search`), so one claim's list never depends on another
claim.

**Rule.** A paragraph is listed only if it holds at least :data:`MIN_SHARED_TERMS`
distinct content terms of the claim: tokens of :func:`app.core.text.tokenize`
(stemmed, stop words dropped) of the claim's text and queries, less tokens that
are only digits, so a shared year is never enough. Of those, the
:data:`MAX_CHANGES_PER_CLAIM` with the highest score (rounded as recorded) are
listed, best first, equal scores in corpus order.

**Copies.** Filings repeat a paragraph under two Items. Changed paragraphs of the
same comparison and kind whose text is equal once whitespace is collapsed and case
folded (for a pair, both the later and the earlier text) are one change: it takes
one place in the list, under its first copy in corpus order, and names the other
copies' Items in ``also_under``.

The comparisons must list every changed paragraph
(``diff_documents(..., max_listed=None)``): a cut list would make ``considered``
and ``matched`` count only what was kept, so it is refused.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import get_args

from ed_v12.core.change_models import FilingChanges, ItemChanges, Paragraph, RewordedParagraph
from ed_v12.core.claim_change_models import (
    ChangeKind,
    ClaimChanges,
    ComparedFilings,
    CompareForm,
    RelevantChange,
)
from ed_v12.core.models import Claim
from ed_v12.core.text import tokenize
from ed_v12.retrieval.bm25 import Bm25Index

# A paragraph must share at least this many distinct content terms with a claim to be listed.
# Two, so that one common word ("revenue", "China") is never enough on its own; the extractive
# engine quotes a sentence on the same rule (engines/extractive.MIN_SHARED_TOKENS).
MIN_SHARED_TERMS = 2
# At most this many distinct changes are listed per claim; ``matched`` and ``distinct_matched``
# keep the true counts.
MAX_CHANGES_PER_CLAIM = 5
# Decimal places a score is recorded with; the order uses the recorded score.
SCORE_PLACES = 4

_FORMS: frozenset[str] = frozenset(get_args(CompareForm))


@dataclass(frozen=True, slots=True)
class _Changed:
    """One changed paragraph of the corpus and where it came from."""

    comparison: int
    kind: ChangeKind
    form: CompareForm
    item: str
    paragraph: Paragraph | None
    pair: RewordedParagraph | None

    @property
    def text(self) -> str:
        """The text searched: the paragraph, or the later paragraph of a pair."""
        if self.paragraph is not None:
            return self.paragraph.text
        assert self.pair is not None  # set for every pair kind by _changed_paragraphs
        return self.pair.after.text

    @property
    def key(self) -> tuple[int, ChangeKind, str, str]:
        """Equal for copies of one change: same comparison, kind and normalised text(s)."""
        earlier = "" if self.pair is None else _normal(self.pair.before.text)
        return (self.comparison, self.kind, _normal(self.text), earlier)


def _normal(text: str) -> str:
    """``text`` with whitespace collapsed and case folded, to recognise a repeated paragraph."""
    return " ".join(text.casefold().split())


def content_terms(text: str) -> set[str]:
    """The distinct content terms of ``text``: its word tokens, figures left out."""
    return {token for token in tokenize(text) if not token.isdigit()}


def compared_filings(comparison: FilingChanges) -> ComparedFilings:
    """The summary of one comparison a reader is shown: the two filings and the totals."""
    return ComparedFilings(
        form=_form(comparison),
        earlier=comparison.earlier,
        later=comparison.later,
        totals=comparison.totals,
    )


def _form(comparison: FilingChanges) -> CompareForm:
    form = comparison.later.form
    if form not in _FORMS or comparison.earlier.form != form:
        raise ValueError(f"only a 10-K or a 10-Q pair can be searched, not {form!r}")
    return form  # type: ignore[return-value]  # checked against CompareForm just above


def _check_complete(item: ItemChanges) -> None:
    cut = item.truncated
    if cut.added or cut.removed or cut.reworded or cut.numbers_only:
        raise ValueError(
            f"the comparison of {item.item!r} was cut; every changed paragraph must be listed "
            "(diff_documents(..., max_listed=None))"
        )


def _changed_paragraphs(comparisons: Sequence[FilingChanges]) -> Iterator[_Changed]:
    """The corpus, in the order documented at the top of this module."""
    for number, comparison in enumerate(comparisons):
        form = _form(comparison)
        for item in comparison.items:
            _check_complete(item)
            for paragraph in item.added_paragraphs:
                yield _Changed(number, "added", form, item.item, paragraph, None)
            for paragraph in item.removed_paragraphs:
                yield _Changed(number, "removed", form, item.item, paragraph, None)
            for pair in item.reworded_paragraphs:
                yield _Changed(number, "reworded", form, item.item, None, pair)
            for pair in item.numbers_only_paragraphs:
                yield _Changed(number, "numbers_only", form, item.item, None, pair)


def _for_claim(
    claim: Claim, corpus: list[_Changed], terms: list[set[str]], index: Bm25Index
) -> ClaimChanges:
    queries = [claim.text, *claim.queries]
    wanted: set[str] = set()
    for query in queries:
        wanted |= content_terms(query)
    best = [0.0] * len(corpus)
    for query in queries:
        if not tokenize(query):
            continue
        for position, score in enumerate(index.scores(query)):
            best[position] = max(best[position], score)
    passing = [
        position
        for position in range(len(corpus))
        if len(wanted & terms[position]) >= MIN_SHARED_TERMS
    ]
    # One entry per distinct change: its first copy in corpus order, the rest named by Item.
    copies: dict[tuple[int, ChangeKind, str, str], list[int]] = {}
    for position in passing:
        copies.setdefault(corpus[position].key, []).append(position)
    entries = sorted(
        copies.values(),
        key=lambda group: (-round(best[group[0]], SCORE_PLACES), group[0]),
    )
    changes: list[RelevantChange] = []
    for group in entries[:MAX_CHANGES_PER_CLAIM]:
        first = corpus[group[0]]
        also_under: list[str] = []
        for position in group[1:]:
            item = corpus[position].item
            if item != first.item and item not in also_under:
                also_under.append(item)
        changes.append(
            RelevantChange(
                kind=first.kind,
                form=first.form,
                item=first.item,
                paragraph=first.paragraph,
                pair=first.pair,
                score=round(best[group[0]], SCORE_PLACES),
                matched_terms=sorted(wanted & terms[group[0]]),
                also_under=also_under,
            )
        )
    return ClaimChanges(
        claim_id=claim.id,
        changes=changes,
        considered=len(corpus),
        matched=len(passing),
        distinct_matched=len(copies),
    )


def relevant_changes(
    claims: Sequence[Claim], comparisons: Sequence[FilingChanges]
) -> list[ClaimChanges]:
    """For each claim, in the order given, the changed paragraphs that share its words.

    ``comparisons`` are filing comparisons of a 10-K or 10-Q pair that list every
    changed paragraph; a cut list or another form is ValueError. Each claim is
    scored on its own, so the result for one claim does not depend on the others.
    """
    corpus = list(_changed_paragraphs(comparisons))
    index = Bm25Index([changed.text for changed in corpus])
    terms = [content_terms(changed.text) for changed in corpus]
    return [_for_claim(claim, corpus, terms, index) for claim in claims]
