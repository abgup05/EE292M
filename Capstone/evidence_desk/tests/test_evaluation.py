"""The retrieval evaluation: overlap rule, ranks, recall, the per-source cap, validation, pins.

Offline: only the recorded EDGAR fixtures and small synthetic documents are read.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.core import limits
from app.core.documents import Document, Passage
from app.evaluation.corpus import Corpus, CorpusError, PinnedFiling, load_pins
from app.evaluation.golden import GOLDEN_PATH, heading_matches, validate_golden
from app.evaluation.retrieval_eval import (
    MAX_RANK,
    NOT_IN_TOP,
    RRF_K,
    VARIANTS,
    Span,
    explain_ranking,
    first_relevant_rank,
    is_relevant,
    rank_by_rrf,
    rank_label,
    rank_with_headings,
    read_queries,
    read_queries_file,
    recall_at,
    reciprocal_rank,
    render_explanation,
    score_case,
    summarize,
    variant_queries,
)
from app.retrieval.search import PassageIndex
from app.sources.filing import parse_filing

# A synthetic 10-K: two Items, each with one paragraph long enough to cite.
RISK_TEXT = (
    "Our business depends on a small number of contract manufacturers in Asia, and any "
    "disruption at those suppliers could delay shipments and reduce revenue."
)
MDA_TEXT = (
    "Revenue increased twelve percent compared with the prior year, driven by higher unit "
    "volumes in the services segment and favourable pricing on new contracts."
)
SYNTHETIC_HTML = (
    "<html><body><p>PART I</p><p><b>Item 1A. Risk Factors</b></p>"
    f"<p>{RISK_TEXT}</p><p>PART II</p>"
    "<p><b>Item 7. Management's Discussion and Analysis</b></p>"
    f"<p>{MDA_TEXT}</p></body></html>"
)
ACCESSION = "0009999999-26-000001"
TICKER = "TEST"


def synthetic_document() -> Document:
    url = "https://example.test/f.htm"
    return parse_filing(SYNTHETIC_HTML, url=url, title="t", published_date=None)


def loader_for(documents: dict[str, Document]) -> Callable[[str, str], Document]:
    def load(ticker: str, accession: str) -> Document:
        if ticker != TICKER or accession not in documents:
            raise CorpusError(f"{accession} is not pinned in eval/filings.json")
        return documents[accession]

    return load


def case(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "supplier-concentration",
        "ticker": TICKER,
        "filings": [ACCESSION],
        "claim": "The company leans on a handful of outsourced factories overseas.",
        "kind": "answerable",
        "expected": "supports",
        "must_retrieve": [
            {"accession": ACCESSION, "section": "Item 1A", "text": RISK_TEXT[:120]},
        ],
        "why": "The risk factor names the dependence on a few manufacturers.",
    }
    base.update(overrides)
    return base


def golden(*cases: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "status": "test", "cases": list(cases)}


def passage(source: str, number: int, start: int, text: str) -> Passage:
    identifier = f"{source}-p{number}"
    return Passage(id=identifier, source_id=source, locator="Item 7", text=text, start=start)


# The overlap rule


def test_a_passage_holding_half_the_excerpt_counts_and_less_does_not() -> None:
    target = [Span("s1", 100, 200)]  # a 100-character excerpt
    assert is_relevant(passage("s1", 1, 150, "x" * 50), target)  # 50 of 100 inside
    assert not is_relevant(passage("s1", 2, 50, "x" * 80), target)  # 30 inside
    assert not is_relevant(passage("s1", 2, 151, "x" * 100), target)  # 49 inside
    assert not is_relevant(passage("s2", 3, 100, "x" * 100), target)  # other filing


def test_a_passage_containing_the_whole_excerpt_counts() -> None:
    assert is_relevant(passage("s1", 1, 0, "x" * 1000), [Span("s1", 100, 200)])


# Rank and reciprocal rank


def test_rank_is_the_first_relevant_passage_counted_from_one() -> None:
    spans = [Span("s1", 1000, 1100)]
    ranked = [
        passage("s1", 1, 0, "x" * 100),
        passage("s1", 2, 200, "x" * 100),
        passage("s1", 3, 1000, "x" * 100),
        passage("s1", 4, 1050, "x" * 100),
    ]
    assert first_relevant_rank(ranked, spans) == 3
    assert reciprocal_rank(3) == pytest.approx(1 / 3)
    assert reciprocal_rank(None) == 0.0


def test_a_relevant_passage_beyond_the_cut_off_has_no_rank() -> None:
    spans = [Span("s1", 0, 100)]
    ranked = [passage("s1", n, 10_000 + n * 200, "x" * 100) for n in range(1, MAX_RANK + 1)]
    ranked.append(passage("s1", 99, 0, "x" * 100))
    assert first_relevant_rank(ranked, spans) is None
    assert rank_label(None) == NOT_IN_TOP == f"not in top {MAX_RANK}"


# Recall and its denominator


def test_recall_counts_hits_over_every_scored_case() -> None:
    ranks = [1, 3, None, 9, 20]
    at3, at8, at20 = recall_at(ranks, 3), recall_at(ranks, 8), recall_at(ranks, 20)
    assert (at3.hits, at3.total) == (2, 5)
    assert (at8.hits, at8.total) == (2, 5)
    assert (at20.hits, at20.total) == (4, 5)
    assert at20.rate == pytest.approx(0.8)
    assert recall_at([], 3).rate is None


# The pipeline's per-source cap


def capped_index() -> tuple[PassageIndex, list[Span]]:
    """Six strong passages in s1 (the sixth is the one that matters) and a weak one in s2."""
    strong = "export controls restrict sales of accelerators to china "
    passages = [passage("s1", n, n * 1000, strong * (7 - n)) for n in range(1, 7)]
    passages.append(passage("s2", 1, 0, "export rules changed during the quarter"))
    passages.append(passage("s3", 1, 0, "the weather was pleasant"))
    return PassageIndex(passages), [Span("s1", 6000, 6000 + len(strong))]


def test_the_per_source_cap_applies_to_the_pipeline_top_eight() -> None:
    index, spans = capped_index()
    result = score_case("export", TICKER, index, ["export controls China"], spans, extra=False)
    assert result.rank == 6  # in the uncapped ranking it is sixth
    assert limits.MAX_PASSAGES_PER_SOURCE == 5
    assert result.pipeline_position is None  # but the pipeline keeps only five from s1
    summary = summarize([result])
    assert (summary.recall_pipeline.hits, summary.recall_pipeline.total) == (0, 1)
    assert (summary.recall_20.hits, summary.recall_20.total) == (1, 1)


def test_a_case_whose_passage_is_absent_is_a_miss_not_an_error() -> None:
    index, _ = capped_index()
    missing = [Span("s9", 0, 100)]
    result = score_case("absent", TICKER, index, ["export controls China"], missing, extra=False)
    assert result.rank is None and result.pipeline_position is None
    assert rank_label(result.rank) == NOT_IN_TOP
    summary = summarize([result])
    assert (summary.recall_3.hits, summary.recall_3.total) == (0, 1)
    assert summary.mrr == 0.0


# Explaining a rank: the per-term BM25 contributions behind it


def test_explain_shows_the_terms_behind_the_relevant_and_the_first_ranked_passage() -> None:
    index, spans = capped_index()
    queries = ["export controls China", "accelerators"]
    explanation = explain_ranking(index, queries, spans)
    best = index.ranked(queries)
    assert explanation.top is not None and explanation.relevant is not None
    assert explanation.top.passage.id == best[0][0].id == "s1-p1"
    assert explanation.top.rank == 1 and explanation.top.score == pytest.approx(best[0][1])
    assert explanation.relevant.passage.id == "s1-p6" and explanation.relevant.rank == 6
    for side in (explanation.top, explanation.relevant):
        assert side.query == "export controls China"  # the query that gave its best score
        assert sum(term.score for term in side.terms) == pytest.approx(side.score)
    assert explanation.top.terms[0].frequency == 6 > explanation.relevant.terms[0].frequency
    text = render_explanation("export", explanation)
    assert "s1-p6" in text and "rank 6" in text and "export" in text


def test_explain_a_relevant_passage_no_query_matches() -> None:
    index, _ = capped_index()
    explanation = explain_ranking(index, ["export controls China"], [Span("s3", 0, 10)])
    assert explanation.relevant is not None and explanation.relevant.passage.id == "s3-p1"
    assert explanation.relevant.rank is None and explanation.relevant.score == 0.0
    assert "unranked" in render_explanation("weather", explanation)


# Candidate rankings (measured on the golden set, not wired into the pipeline)


def test_rrf_sums_reciprocal_ranks_so_a_passage_several_queries_find_comes_first() -> None:
    only_claim = passage("s1", 1, 0, "counterparty counterparty risk partners")
    many = passage("s1", 2, 100, "purchase obligations and supply commitments")
    filler = passage("s1", 3, 200, "the weather was pleasant")
    index = PassageIndex([only_claim, many, filler])
    queries = ["counterparty risk of purchase", "supply commitments", "purchase obligations"]
    fused = rank_by_rrf(index, queries)
    assert [p.id for p, _ in fused] == ["s1-p2", "s1-p1"]
    assert fused[0][1] == pytest.approx(1 / (RRF_K + 2) + 2 / (RRF_K + 1))
    assert fused[1][1] == pytest.approx(1 / (RRF_K + 1))
    assert rank_by_rrf(index, ["", "the of"]) == []


def test_heading_ranking_scores_the_locator_but_returns_the_exact_passage() -> None:
    audit = Passage(
        id="s1-p1",
        source_id="s1",
        locator="Item 1. Financial Statements › Tax Audits",
        text="The position will be sustained on appeal.",
        start=0,
    )
    cash = Passage(id="s1-p2", source_id="s1", locator="Item 7", text="Cash rose.", start=50)
    index = PassageIndex([audit, cash])
    assert index.ranked(["tax audit"]) == []
    ranked = rank_with_headings(index, ["tax audit"])
    assert [p for p, _ in ranked] == [audit]  # the stored passage, its text unchanged
    assert rank_with_headings(index, ["tax audit"]) == ranked  # cached index, same answer


def test_a_variant_ranking_is_cut_as_the_pipeline_cuts() -> None:
    index, spans = capped_index()
    rrf = VARIANTS["queries-rrf"]
    assert rrf.needs_queries
    result = score_case(
        "export", TICKER, index, ["export controls China"], spans, extra=True, rank=rrf.rank
    )
    assert result.rank == 6 and result.pipeline_position is None  # three sources: capped
    for name in ("queries-rrf", "queries-heading", "queries-rrf-heading"):
        assert VARIANTS[name].needs_queries


# Variants and the queries file


def test_claim_plus_queries_falls_back_to_the_claim_and_says_so() -> None:
    parsed = validate_golden(golden(case()), loader_for({ACCESSION: synthetic_document()}))
    found = parsed.checks[0].case
    assert found is not None
    queries, extra = variant_queries("claim+queries", found, {})
    assert (queries, extra) == ([found.claim], False)
    book = {found.id: ["supplier dependence", "  ", *[f"q{n}" for n in range(9)]]}
    queries, extra = variant_queries("claim+queries", found, book)
    assert extra and queries[0] == found.claim
    assert len(queries) == 1 + limits.MAX_QUERIES_PER_CLAIM and "  " not in queries
    assert variant_queries("claim", found, book) == ([found.claim], False)


def test_a_queries_file_naming_an_unknown_case_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text(json.dumps({"no-such-case": ["x"]}))
    with pytest.raises(ValueError, match="no-such-case"):
        read_queries(path, {"supplier-concentration"})


def test_a_queries_file_is_read_in_the_planned_shape_and_the_flat_shape(tmp_path: Path) -> None:
    ids = {"supplier-concentration"}
    book = {"supplier-concentration": ["contract manufacturers"]}
    flat, planned = tmp_path / "flat.json", tmp_path / "planned.json"
    flat.write_text(json.dumps(book))
    planned.write_text(json.dumps({"provenance": {"golden_sha256": "x"}, "queries": book}))
    assert read_queries(flat, ids) == read_queries(planned, ids) == book
    assert read_queries_file(planned, ids) == (book, {"golden_sha256": "x"})
    assert read_queries_file(flat, ids) == (book, None)
    planned.write_text(json.dumps({"provenance": {}, "queries": {"no-such-case": []}}))
    with pytest.raises(ValueError, match="no-such-case"):
        read_queries(planned, ids)


# Validation


def problems_of(raw: dict[str, Any]) -> list[str]:
    result = validate_golden(raw, loader_for({ACCESSION: synthetic_document()}))
    return [problem for check in result.checks for problem in check.problems] + result.problems


def test_a_correct_case_validates_and_finds_its_span() -> None:
    result = validate_golden(golden(case()), loader_for({ACCESSION: synthetic_document()}))
    assert result.ok, result
    target = result.checks[0].targets[0]
    text = synthetic_document().text
    assert text[target.start : target.end] == RISK_TEXT[:120]
    assert target.section.startswith("Item 1A")


def test_validation_rejects_an_excerpt_that_is_not_in_the_filing() -> None:
    altered = RISK_TEXT[:120].replace("small", "large")
    bad = case(must_retrieve=[{"accession": ACCESSION, "section": "Item 1A", "text": altered}])
    assert any("not found" in problem for problem in problems_of(golden(bad)))


def test_validation_rejects_a_wrong_section_prefix() -> None:
    record = {"accession": ACCESSION, "section": "Item 7", "text": RISK_TEXT[:120]}
    bad = case(must_retrieve=[record])
    assert any("Item 1A. Risk Factors" in problem for problem in problems_of(golden(bad)))


def test_a_section_prefix_must_end_at_a_word_boundary() -> None:
    assert heading_matches("Item 1A. Risk Factors", "Item 1A")
    assert heading_matches("Part II, Item 1A. Risk Factors › Supply", "Part II, Item 1A")
    assert not heading_matches("Item 1A. Risk Factors", "Item 1")
    assert not heading_matches("Part II, Item 1A. Risk Factors", "Part I")


def test_validation_rejects_a_duplicate_id() -> None:
    assert any("duplicate" in problem for problem in problems_of(golden(case(), case())))


def test_validation_rejects_an_unanswerable_case_with_must_retrieve() -> None:
    bad = case(kind="unanswerable", expected="none")
    assert problems_of(golden(bad))
    fixed = case(kind="unanswerable", expected="none", must_retrieve=[])
    assert problems_of(golden(fixed)) == []


def test_validation_rejects_an_unpinned_filing_and_a_short_excerpt() -> None:
    other = case(filings=["0009999999-26-000002"], must_retrieve=[])
    other.update(kind="unanswerable", expected="none")
    assert any("not pinned" in problem for problem in problems_of(golden(other)))
    short = case(must_retrieve=[{"accession": ACCESSION, "section": "Item 1A", "text": "Our"}])
    assert problems_of(golden(short))


# The real golden file, offline


def test_the_nvidia_and_costco_cases_validate_offline() -> None:
    raw = json.loads(GOLDEN_PATH.read_text())
    offline = [c for c in raw["cases"] if c["ticker"] in ("NVDA", "COST")]
    assert len(offline) == 15
    corpus = Corpus(load_pins(), fetch=None)
    result = validate_golden({**raw, "cases": offline}, corpus.load_filing)
    failures = [(check.case_id, check.problems) for check in result.checks if not check.ok]
    assert result.ok and not failures, failures


# Pins


def pin_for(url: str, sha256: str, accession: str = "0001045810-26-000075") -> PinnedFiling:
    return PinnedFiling(
        ticker="NVDA",
        accession=accession,
        form="10-Q",
        period_end="2026-07-26",
        filed_date="2026-08-26",
        url=url,
        sha256=sha256,
    )


NVDA_Q2_URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm"


def test_a_fixture_whose_hash_differs_from_its_pin_is_an_error(tmp_path: Path) -> None:
    pin = pin_for(NVDA_Q2_URL, "0" * 64)
    corpus = Corpus({pin.accession: pin}, cache_dir=tmp_path, fetch=None)
    with pytest.raises(CorpusError, match="not the one pinned"):
        corpus.load_filing("NVDA", pin.accession)


def test_a_cached_filing_whose_hash_differs_from_its_pin_is_an_error(tmp_path: Path) -> None:
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/x.htm"
    pin = pin_for(url, "0" * 64, accession="0000000001-26-000001")
    (tmp_path / f"{pin.accession}.htm.gz").write_bytes(gzip.compress(b"<html>changed</html>"))
    corpus = Corpus({pin.accession: pin}, cache_dir=tmp_path, fetch=None)
    with pytest.raises(CorpusError, match="not the one pinned"):
        corpus.load_filing("NVDA", pin.accession)


def test_a_filing_neither_recorded_nor_cached_needs_a_fetch(tmp_path: Path) -> None:
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/x.htm"
    pin = pin_for(url, "0" * 64, accession="0000000001-26-000001")
    corpus = Corpus({pin.accession: pin}, cache_dir=tmp_path, fetch=None)
    with pytest.raises(CorpusError, match="fetch"):
        corpus.load_filing("NVDA", pin.accession)
    with pytest.raises(CorpusError, match="pinned for NVDA"):
        corpus.load_filing("AAPL", pin.accession)


def test_a_fetched_filing_is_hash_checked_then_cached(tmp_path: Path) -> None:
    body = b"<html><body><p>Item 1. Business</p><p>We sell things.</p></body></html>"
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/x.htm"
    pin = pin_for(url, hashlib.sha256(body).hexdigest(), accession="0000000001-26-000001")
    corpus = Corpus({pin.accession: pin}, cache_dir=tmp_path, fetch=lambda _url: body)
    assert corpus.original(pin) == (body, "edgar")
    offline = Corpus({pin.accession: pin}, cache_dir=tmp_path, fetch=None)
    assert offline.original(pin) == (body, "cache")
    wrong = Corpus({}, cache_dir=tmp_path / "other", fetch=lambda _url: b"tampered")
    with pytest.raises(CorpusError, match="not the one pinned"):
        wrong.original(pin)
