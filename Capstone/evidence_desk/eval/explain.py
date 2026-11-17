"""Explain, term by term, where a golden case's must-retrieve passage ranks and what beat it.

The evaluation's command line belongs to another module's owner, so this diagnosis
runs through pytest, one parametrised item per answerable case:

    make test T="eval/explain.py -s"                          # every answerable case
    make test T="eval/explain.py -s -k 'ko-irs or cost-north'"  # chosen cases

Each item prints the queries (claim plus the recorded planner queries from
``eval/queries.json``), then the first-ranked passage and the first relevant
passage with the per-term BM25 contributions of the query that gave each its
best score (see ``app.evaluation.retrieval_eval.explain_ranking``). It also checks
that the shares add up to the score and that the rank agrees with the scorer.
Needs the filings in ``eval/cache`` (``make eval ARGS="fetch"``); offline.
"""

from __future__ import annotations

import json
from functools import cache

import pytest

from app.evaluation.corpus import CACHE_DIR, EVAL_DIR, Corpus, load_pins
from app.evaluation.golden import GOLDEN_PATH, GoldenCase, Target, read_golden, validate_golden
from app.evaluation.retrieval_eval import (
    IndexCache,
    explain_ranking,
    render_explanation,
    score_case,
    spans_for,
    variant_queries,
)

VARIANT = "claim+queries"
QUERIES = json.loads((EVAL_DIR / "queries.json").read_text())["queries"]
ANSWERABLE = [
    case["id"]
    for case in json.loads(GOLDEN_PATH.read_text())["cases"]
    if case["kind"] == "answerable"
]


@cache
def _material() -> tuple[dict[str, tuple[GoldenCase, list[Target]]], IndexCache]:
    corpus = Corpus(load_pins(), cache_dir=CACHE_DIR)
    raw, _ = read_golden()
    validation = validate_golden(raw, corpus.load_filing)
    assert validation.ok, "the golden set does not validate: run make eval-validate"
    cases = {case.id: (case, targets) for case, targets in validation.cases()}
    return cases, IndexCache(corpus.load_filing)


@pytest.mark.parametrize("case_id", ANSWERABLE)
def test_explain(case_id: str) -> None:
    cases, indexes = _material()
    case, targets = cases[case_id]
    index = indexes.index(case)
    queries, extra = variant_queries(VARIANT, case, QUERIES)
    spans = spans_for(case, targets)
    explanation = explain_ranking(index, queries, spans)
    print("\n" + render_explanation(case_id, explanation))
    assert explanation.relevant is not None
    for side in (explanation.top, explanation.relevant):
        assert side is not None
        assert sum(term.score for term in side.terms) == pytest.approx(side.score)
    scored = score_case(case_id, case.ticker, index, queries, spans, extra=extra)
    assert scored.rank == (
        explanation.relevant.rank
        if explanation.relevant.rank is not None and explanation.relevant.rank <= 50
        else None
    )
