"""Rank a run's passages for one claim's queries with BM25.

A passage's score for a claim is its best BM25 score over that claim's queries,
so the order or number of the other queries cannot lower it, and one claim's
passages never depend on any other claim. Ties go to the passage that comes
first, which makes every result deterministic.

The per-source cap keeps one filing from crowding out the others, so it applies
only when the run's passages come from more than one source: a run on a single
filing is offered the full ``k`` passages.
"""

from __future__ import annotations

from collections.abc import Sequence

from ed_v9.core import limits
from ed_v9.core.documents import Passage
from ed_v9.core.text import tokenize
from ed_v9.retrieval.bm25 import Bm25Index, TermScore


class PassageIndex:
    """A BM25 index over every passage of a run, built once and searched per claim."""

    def __init__(self, passages: list[Passage]) -> None:
        self._passages = list(passages)
        self._index = Bm25Index([passage.text for passage in self._passages])
        self._sources = len({passage.source_id for passage in self._passages})
        self._positions = {passage.id: n for n, passage in enumerate(self._passages)}

    def __len__(self) -> int:
        return len(self._passages)

    @property
    def passages(self) -> tuple[Passage, ...]:
        """Every passage of the index, in the order it was given."""
        return tuple(self._passages)

    def contributions(self, query: str, passage: Passage) -> list[TermScore]:
        """Each term of ``query`` found in ``passage`` with its share of the BM25 score.

        For diagnosis (``app.evaluation.retrieval_eval.explain_ranking``). Raises
        KeyError for a passage that is not in the index.
        """
        return self._index.contributions(query, self._positions[passage.id])

    def ranked(self, queries: list[str]) -> list[tuple[Passage, float]]:
        """Every passage with a positive score, best first, ties in passage order.

        Queries with no content token (blank, or only stop words) are ignored.
        """
        best = [0.0] * len(self._passages)
        for query in queries:
            if not tokenize(query):
                continue
            for position, score in enumerate(self._index.scores(query)):
                if score > best[position]:
                    best[position] = score
        order = sorted(
            (position for position, score in enumerate(best) if score > 0),
            key=lambda position: (-best[position], position),
        )
        return [(self._passages[position], best[position]) for position in order]

    def search(
        self,
        queries: list[str],
        k: int = limits.PASSAGES_PER_CLAIM,
        per_source: int = limits.MAX_PASSAGES_PER_SOURCE,
    ) -> list[Passage]:
        """The top ``k`` passages for ``queries``, at most ``per_source`` from one source.

        The cap applies only when the index holds passages of more than one source.
        """
        return self.cut(self.ranked(queries), k, per_source)

    def cut(
        self,
        ranked: Sequence[tuple[Passage, float]],
        k: int = limits.PASSAGES_PER_CLAIM,
        per_source: int = limits.MAX_PASSAGES_PER_SOURCE,
    ) -> list[Passage]:
        """The first ``k`` of a ranking of this index's passages, with the per-source cap.

        :meth:`search` is ``cut(ranked(queries))``; the evaluation cuts other rankings
        the same way. The cap applies only when the index has more than one source.
        """
        capped = self._sources > 1
        chosen: list[Passage] = []
        taken: dict[str, int] = {}
        for passage, _score in ranked:
            if len(chosen) >= k:
                break
            if capped and taken.get(passage.source_id, 0) >= per_source:
                continue
            taken[passage.source_id] = taken.get(passage.source_id, 0) + 1
            chosen.append(passage)
        return chosen
