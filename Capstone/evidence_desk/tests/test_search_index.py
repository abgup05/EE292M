"""Passage ranking over a run: best score over a claim's queries, capped per source."""

from app.core import limits
from app.core.documents import Passage
from app.retrieval.search import PassageIndex


def passage(source: str, number: int, text: str) -> Passage:
    return Passage(id=f"{source}-p{number}", source_id=source, locator="Item 2", text=text, start=0)


PASSAGES = [
    passage("src-1", 1, "Data Center revenue grew on Blackwell demand."),
    passage("src-1", 2, "Data Center revenue grew again on Hopper."),
    passage("src-1", 3, "Data Center revenue grew in every region."),
    passage("src-1", 4, "Data Center revenue grew faster than gaming."),
    passage("src-1", 5, "Data Center revenue grew with networking."),
    passage("src-1", 6, "Data Center revenue grew despite export rules."),
    passage("src-1", 7, "Data Center revenue grew year over year."),
    passage("src-2", 1, "Data Center revenue grew sequentially."),
    passage("src-2", 2, "Export controls restrict H20 sales to China."),
    passage("src-3", 1, "A few customers account for most revenue."),
    passage("src-3", 2, "The weather was pleasant."),
]


def test_ranked_takes_the_best_score_over_queries() -> None:
    index = PassageIndex(PASSAGES)
    data = dict((p.id, s) for p, s in index.ranked(["data center revenue grew"]))
    export = dict((p.id, s) for p, s in index.ranked(["export H20 China"]))
    queries = ["data center revenue grew", "export H20 China"]
    both = dict((p.id, s) for p, s in index.ranked(queries))
    for passage_id in both:
        assert both[passage_id] == max(data.get(passage_id, 0.0), export.get(passage_id, 0.0))
    assert "src-3-p2" not in both  # zero-score passages are excluded


def test_ties_break_by_passage_order_and_results_are_deterministic() -> None:
    index = PassageIndex(PASSAGES)
    first = index.ranked(["revenue grew"])
    assert first == index.ranked(["revenue grew"])
    scores = [score for _, score in first]
    assert scores == sorted(scores, reverse=True)
    order = {p.id: n for n, p in enumerate(PASSAGES)}
    for (a, score_a), (b, score_b) in zip(first, first[1:], strict=False):
        if score_a == score_b:
            assert order[a.id] < order[b.id]


def test_search_keeps_top_k_with_a_per_source_cap() -> None:
    index = PassageIndex(PASSAGES)
    found = index.search(["data center revenue grew"])
    assert len(found) <= limits.PASSAGES_PER_CLAIM
    per_source = [p.source_id for p in found]
    assert max(per_source.count(s) for s in set(per_source)) <= limits.MAX_PASSAGES_PER_SOURCE
    assert per_source.count("src-1") == limits.MAX_PASSAGES_PER_SOURCE
    assert "src-2-p1" in {p.id for p in found}
    small = index.search(["data center revenue grew"], k=3, per_source=2)
    assert [p.source_id for p in small].count("src-1") == 2 and len(small) == 3


def test_one_claims_passages_do_not_depend_on_other_queries_or_their_order() -> None:
    index = PassageIndex(PASSAGES)
    claim_queries = ["a few customers account for most revenue", "customer concentration"]
    alone = index.search(claim_queries)
    reversed_alone = index.search(list(reversed(claim_queries)))
    assert [p.id for p in alone] == [p.id for p in reversed_alone]
    index.search(["export H20 China"])  # another claim searched in between
    assert [p.id for p in index.search(claim_queries)] == [p.id for p in alone]
    shuffled = PassageIndex(PASSAGES)
    assert [p.id for p in shuffled.search(claim_queries)] == [p.id for p in alone]


def test_blank_queries_are_ignored() -> None:
    index = PassageIndex(PASSAGES)
    assert index.ranked(["", "   ", "the of and"]) == []
    assert index.ranked(["", "customers"]) == index.ranked(["customers"])
    assert index.search([]) == []


def test_empty_index() -> None:
    assert PassageIndex([]).search(["revenue"]) == []
