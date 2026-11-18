"""Rank a run's passages for one claim's queries with BM25.

A passage's score for a claim is its best BM25 score over that claim's queries,
so the order or number of the other queries cannot lower it, and one claim's
passages never depend on any other claim. Ties go to the passage that comes
first, which makes every result deterministic.
"""

from __future__ import annotations

from ed_v3.core import limits
from ed_v3.core.documents import Passage
from ed_v3.core.text import tokenize
from ed_v3.retrieval.bm25 import Bm25Index


class PassageIndex:
    """A BM25 index over every passage of a run, built once and searched per claim."""

    def __init__(self, passages: list[Passage]) -> None:
        self._passages = list(passages)
        self._index = Bm25Index([passage.text for passage in self._passages])

    def __len__(self) -> int:
        return len(self._passages)

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
        """The top ``k`` passages for ``queries``, at most ``per_source`` from one source."""
        chosen: list[Passage] = []
        taken: dict[str, int] = {}
        for passage, _score in self.ranked(queries):
            if len(chosen) >= k:
                break
            if taken.get(passage.source_id, 0) >= per_source:
                continue
            taken[passage.source_id] = taken.get(passage.source_id, 0) + 1
            chosen.append(passage)
        return chosen
