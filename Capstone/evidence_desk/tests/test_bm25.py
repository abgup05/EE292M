"""Okapi BM25 checked against a scorer written directly from the formula.

Reference: S. Robertson and H. Zaragoza, The Probabilistic Relevance Framework:
BM25 and Beyond (2009), with the Robertson-Sparck Jones idf
ln(1 + (N - n + 0.5) / (n + 0.5)). The brute-force scorer below shares only the
tokenizer with the index; it recounts every statistic for every query.
"""

import math

import pytest

from app.core.text import tokenize
from app.retrieval.bm25 import Bm25Index

CORPUS = [
    "Data Center revenue grew 56% from a year ago, driven by Blackwell systems.",
    "Gaming revenue was flat as channel inventory normalized.",
    "Export controls restrict sales of H20 products to China.",
    "The U.S. government imposed licensing requirements on exports to China.",
    "A limited number of customers account for a substantial portion of revenue.",
    "Direct customer A represented 23% of total revenue for the quarter.",
    "Indirect customers buy through system integrators and distributors.",
    "We depend on foundries such as TSMC to manufacture our products.",
    "Supply constraints could limit our ability to meet customer demand.",
    "Gross margin decreased due to inventory provisions for H20.",
    "Operating expenses increased on compensation and infrastructure.",
    "We returned cash to shareholders through repurchases and dividends.",
    "Automotive revenue grew on self-driving platform adoption.",
    "Professional visualization revenue grew modestly.",
    "Our networking revenue grew strongly on InfiniBand and Ethernet demand.",
    "Competition in accelerated computing is intensifying.",
    "Customers may develop their own chips and reduce purchases from us.",
    "Revenue concentration among cloud service providers remains high.",
    "Data Center compute revenue grew on Hopper and Blackwell demand.",
    "China revenue declined as a share of Data Center revenue.",
    "Legal proceedings are described in Note 13.",
    "We may be subject to litigation regarding intellectual property.",
    "Cybersecurity incidents could harm our business.",
    "Climate regulation could increase our costs.",
    "Our fiscal year ends on the last Sunday in January.",
    "Inventory and purchase obligations increased to secure supply.",
    "Restrictions on exports could reduce Data Center revenue materially.",
    "Large customers concentrate purchasing power and negotiate prices.",
    "Revenue from the top two customers grew faster than total revenue.",
    "Interest income increased on higher cash balances.",
]


def brute_force_scores(texts: list[str], query: str, k1: float, b: float) -> list[float]:
    """BM25 written out term by term from the paper, with no shared state between calls."""
    documents = [tokenize(text) for text in texts]
    total = len(documents)
    average_length = sum(len(d) for d in documents) / total
    out = []
    for document in documents:
        score = 0.0
        for term in set(tokenize(query)):
            containing = sum(1 for d in documents if term in d)
            idf = math.log(1 + (total - containing + 0.5) / (containing + 0.5))
            frequency = document.count(term)
            denominator = frequency + k1 * (1 - b + b * len(document) / average_length)
            score += idf * frequency * (k1 + 1) / denominator
        out.append(score)
    return out


def top_five(scores: list[float]) -> list[int]:
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:5]


@pytest.mark.parametrize(
    "query",
    [
        "data center revenue growing",
        "customers concentrated revenue",
        "export restrictions China H20",
    ],
)
def test_agrees_with_brute_force_on_top_five(query: str) -> None:
    index = Bm25Index(CORPUS)
    expected = brute_force_scores(CORPUS, query, 1.5, 0.75)
    got = index.scores(query)
    assert top_five(got) == top_five(expected)
    assert got == pytest.approx(expected)
    assert expected[top_five(expected)[0]] > 0


def test_custom_parameters_are_used() -> None:
    index = Bm25Index(CORPUS, k1=0.9, b=0.4)
    expected = brute_force_scores(CORPUS, "revenue grew", 0.9, 0.4)
    assert index.scores("revenue grew") == pytest.approx(expected)


def test_absent_term_scores_zero_everywhere() -> None:
    assert Bm25Index(CORPUS).scores("grocery Norway") == [0.0] * len(CORPUS)


def test_rarer_term_outweighs_common_term() -> None:
    texts = ["revenue alpha", "revenue beta", "revenue gamma", "revenue delta", "rare delta"]
    scores = Bm25Index(texts).scores("revenue rare")
    assert scores[4] > scores[0]


def test_empty_corpus_and_empty_query() -> None:
    assert Bm25Index([]).scores("revenue") == []
    assert Bm25Index(CORPUS).scores("") == [0.0] * len(CORPUS)
    assert Bm25Index(["", "the and of"]).scores("revenue") == [0.0, 0.0]


def test_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError):
        Bm25Index(CORPUS, k1=-1.0)
    with pytest.raises(ValueError):
        Bm25Index(CORPUS, b=1.5)


def test_contributions_sum_to_the_score_and_name_each_matched_term() -> None:
    index = Bm25Index(CORPUS)
    query = "export controls China revenue"
    for position, score in enumerate(index.scores(query)):
        parts = index.contributions(query, position)
        assert sum(part.score for part in parts) == pytest.approx(score)
        assert all(part.frequency > 0 and part.score > 0 for part in parts)
    parts = index.contributions(query, 2)  # "Export controls restrict sales of H20 ... China."
    assert [part.term for part in parts] == ["export", "control", "china"]
    assert index.contributions("", 2) == []
