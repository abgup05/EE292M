"""Okapi BM25 over a fixed list of texts.

S. Robertson and H. Zaragoza, *The Probabilistic Relevance Framework: BM25 and
Beyond* (2009). For a query Q and a text D::

    score(D, Q) = sum over distinct terms t of Q of
                  idf(t) * f(t, D) * (k1 + 1) / (f(t, D) + k1 * (1 - b + b * |D| / avgdl))
    idf(t)      = ln(1 + (N - n(t) + 0.5) / (n(t) + 0.5))

where f is the term frequency, |D| the text's length in tokens, avgdl the mean
length, N the number of texts and n(t) the number containing t. The idf form
never goes negative. Tokens come from :func:`app.core.text.tokenize`.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from ed_v13.core.text import tokenize


@dataclass(frozen=True)
class TermScore:
    """One query term's part of a text's BM25 score: its idf, frequency and contribution."""

    term: str
    idf: float
    frequency: int
    score: float


class Bm25Index:
    """Term statistics for ``texts``, computed once; :meth:`scores` ranks them for a query."""

    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        if k1 < 0:
            raise ValueError("k1 must not be negative")
        if not 0 <= b <= 1:
            raise ValueError("b must be between 0 and 1")
        self.k1 = k1
        self.b = b
        self._frequencies: list[Counter[str]] = []
        self._lengths: list[int] = []
        containing: Counter[str] = Counter()
        for text in texts:
            tokens = tokenize(text)
            counts = Counter(tokens)
            self._frequencies.append(counts)
            self._lengths.append(len(tokens))
            containing.update(counts.keys())
        total = len(texts)
        self._average_length = sum(self._lengths) / total if total else 0.0
        self._idf = {
            term: math.log(1 + (total - count + 0.5) / (count + 0.5))
            for term, count in containing.items()
        }

    def __len__(self) -> int:
        return len(self._lengths)

    def scores(self, query: str) -> list[float]:
        """The BM25 score of every text for ``query``, in the order the texts were given.

        Each distinct query term counts once. A term found in no text adds
        nothing, so an unmatched or empty query scores 0.0 everywhere.
        """
        terms = [term for term in dict.fromkeys(tokenize(query)) if term in self._idf]
        out: list[float] = []
        for counts, length in zip(self._frequencies, self._lengths, strict=True):
            score = 0.0
            if terms and length:
                norm = self.k1 * (1 - self.b + self.b * length / self._average_length)
                for term in terms:
                    frequency = counts.get(term, 0)
                    if frequency:
                        score += self._idf[term] * frequency * (self.k1 + 1) / (frequency + norm)
            out.append(score)
        return out

    def contributions(self, query: str, position: int) -> list[TermScore]:
        """The terms of ``query`` found in text ``position``, each with its share of the score.

        In query order; the shares sum to ``scores(query)[position]``. For
        diagnosis only: :meth:`scores` is the ranking path.
        """
        counts, length = self._frequencies[position], self._lengths[position]
        if not length:
            return []
        norm = self.k1 * (1 - self.b + self.b * length / self._average_length)
        parts: list[TermScore] = []
        for term in dict.fromkeys(tokenize(query)):
            frequency = counts.get(term, 0)
            if frequency and term in self._idf:
                idf = self._idf[term]
                score = idf * frequency * (self.k1 + 1) / (frequency + norm)
                parts.append(TermScore(term, idf, frequency, score))
        return parts
