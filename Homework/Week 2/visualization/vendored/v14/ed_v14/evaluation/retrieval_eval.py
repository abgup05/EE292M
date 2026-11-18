"""Score retrieval on the golden set: where does the passage that matters land?

For each answerable case the passages of its filings are built exactly as a
thesis run builds them (:func:`app.sources.filing.parse_filing`, then
:func:`app.retrieval.chunk.chunk_document` with source ids ``s1``, ``s2``, ... in
the order the case lists its filings) and ranked by
:class:`app.retrieval.search.PassageIndex` for the queries a *variant* makes
from the case. A passage is relevant when it lies in the excerpt's filing and
holds at least half of a must-retrieve excerpt's characters (by offsets in the
document text). The case's rank is that of the first relevant passage in the
uncapped ranking, counted from 1; beyond :data:`MAX_RANK` it is "not in top 50"
and counts as a miss.

Metrics, each over the answerable cases scored: recall@3, recall@8 and recall@20
(share of cases with a relevant passage at that rank or better) and the mean
reciprocal rank (a miss counts 0). recall@8 is the pipeline's own cut-off
(``limits.PASSAGES_PER_CLAIM``) and, as in :meth:`PassageIndex.search`, applies
the per-filing cap ``limits.MAX_PASSAGES_PER_SOURCE`` when a case has more than one
filing; the other numbers use the uncapped ranking.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from weakref import WeakKeyDictionary

from ed_v14.core import limits
from ed_v14.core.documents import Document, Passage
from ed_v14.core.text import tokenize
from ed_v14.evaluation.golden import GoldenCase, Target
from ed_v14.retrieval.bm25 import Bm25Index, TermScore
from ed_v14.retrieval.chunk import chunk_document
from ed_v14.retrieval.search import PassageIndex

MAX_RANK = 50
NOT_IN_TOP = f"not in top {MAX_RANK}"
SHORT_K = 3
PIPELINE_K = limits.PASSAGES_PER_CLAIM
LONG_K = 20
LOCATOR_CHARS = 70

QueryBook = Mapping[str, Sequence[str]]
Loader = Callable[[str, str], Document]
Ranker = Callable[[PassageIndex, list[str]], list[tuple[Passage, float]]]
RRF_K = 60  # Cormack, Clarke and Büttcher (2009); the published constant, not tuned here


@dataclass(frozen=True)
class Span:
    """A must-retrieve excerpt's place: the source id it was given and its offsets."""

    source_id: str
    start: int
    end: int


def overlap(start: int, end: int, other_start: int, other_end: int) -> int:
    """Characters shared by the half-open ranges [start, end) and [other_start, other_end)."""
    return max(0, min(end, other_end) - max(start, other_start))


def holds_half(source_id: str, start: int, end: int, spans: Sequence[Span]) -> bool:
    """True when [start, end) of ``source_id`` holds at least half of one of ``spans``.

    The one overlap rule of the evaluation: a retrieved passage and a verified
    excerpt are both judged by it.
    """
    return any(
        source_id == span.source_id
        and 2 * overlap(start, end, span.start, span.end) >= span.end - span.start
        for span in spans
    )


def is_relevant(passage: Passage, spans: Sequence[Span]) -> bool:
    """True when ``passage`` holds at least half the characters of one of ``spans``."""
    return holds_half(passage.source_id, passage.start, passage.start + len(passage.text), spans)


def first_relevant_rank(
    ranked: Sequence[Passage], spans: Sequence[Span], max_rank: int = MAX_RANK
) -> int | None:
    """The 1-based rank of the first relevant passage within ``max_rank``, else None."""
    for rank, passage in enumerate(ranked[:max_rank], start=1):
        if is_relevant(passage, spans):
            return rank
    return None


def reciprocal_rank(rank: int | None) -> float:
    """1 / rank, or 0.0 for a miss."""
    return 0.0 if rank is None else 1.0 / rank


def rank_label(rank: int | None) -> str:
    """The rank as shown in the per-case table."""
    return NOT_IN_TOP if rank is None else str(rank)


@dataclass(frozen=True)
class Recall:
    """Cases with a relevant passage within the cut-off, over the cases scored."""

    hits: int
    total: int

    @property
    def rate(self) -> float | None:
        """hits / total, or None when nothing was scored."""
        return self.hits / self.total if self.total else None

    def as_dict(self) -> dict[str, Any]:
        """The recall with its denominator, for the JSON record."""
        return {"hits": self.hits, "total": self.total, "rate": self.rate}


def recall_at(ranks: Sequence[int | None], k: int) -> Recall:
    """Recall@k over ``ranks`` (one per case; None is a miss)."""
    return Recall(sum(1 for rank in ranks if rank is not None and rank <= k), len(ranks))


# Rankings: the pipeline's, and candidates measured here before any is wired in.


def rank_by_best_score(index: PassageIndex, queries: list[str]) -> list[tuple[Passage, float]]:
    """The pipeline's ranking: each passage's best BM25 score over the queries."""
    return index.ranked(queries)


def rank_by_rrf(index: PassageIndex, queries: list[str]) -> list[tuple[Passage, float]]:
    """Reciprocal-rank fusion: each query ranks alone; a passage sums 1 / (RRF_K + rank).

    Only queries that give the passage a positive score count. Ties go to the
    passage that comes first in the index.
    """
    return _fuse(index.passages, [index.ranked([query]) for query in queries])


def _fuse(
    passages: Sequence[Passage], rankings: Sequence[list[tuple[Passage, float]]]
) -> list[tuple[Passage, float]]:
    order = {passage.id: n for n, passage in enumerate(passages)}
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, (passage, _score) in enumerate(ranking, start=1):
            fused[passage.id] = fused.get(passage.id, 0.0) + 1.0 / (RRF_K + rank)
    ids = sorted(fused, key=lambda pid: (-fused[pid], order[pid]))
    return [(passages[order[pid]], fused[pid]) for pid in ids]


_HEADED: WeakKeyDictionary[PassageIndex, PassageIndex] = WeakKeyDictionary()


def _headed_index(index: PassageIndex) -> PassageIndex:
    """An index over the same passages scored as "locator, newline, text" (built once)."""
    if index not in _HEADED:
        headed = [replace(p, text=f"{p.locator}\n{p.text}") for p in index.passages]
        _HEADED[index] = PassageIndex(headed)
    return _HEADED[index]


def _restore(
    index: PassageIndex, ranked: list[tuple[Passage, float]]
) -> list[tuple[Passage, float]]:
    stored = {passage.id: passage for passage in index.passages}
    return [(stored[passage.id], score) for passage, score in ranked]


def rank_with_headings(index: PassageIndex, queries: list[str]) -> list[tuple[Passage, float]]:
    """Best score over the queries, each passage scored with its section locator before it.

    Returns the stored passages, so every offset and quote is unchanged.
    """
    return _restore(index, _headed_index(index).ranked(queries))


def rank_by_rrf_with_headings(
    index: PassageIndex, queries: list[str]
) -> list[tuple[Passage, float]]:
    """Reciprocal-rank fusion of per-query rankings that score the locator with the text."""
    return _restore(index, rank_by_rrf(_headed_index(index), queries))


# Variants: how a case becomes queries, and how they rank. Add one here and it is
# available everywhere.


@dataclass(frozen=True)
class Variant:
    """A named way of turning a case into retrieval queries and ranking the passages.

    ``build`` returns the queries and whether queries beyond the claim were used;
    ``rank`` orders the passages (the pipeline's ranking unless a candidate says otherwise).
    """

    name: str
    description: str
    build: Callable[[GoldenCase, QueryBook], tuple[list[str], bool]]
    needs_queries: bool = False
    rank: Ranker = rank_by_best_score


def _claim_only(case: GoldenCase, book: QueryBook) -> tuple[list[str], bool]:
    return [case.claim], False


def _claim_plus_queries(case: GoldenCase, book: QueryBook) -> tuple[list[str], bool]:
    extra = [query for query in book.get(case.id, ()) if query.strip()]
    extra = extra[: limits.MAX_QUERIES_PER_CLAIM]  # the pipeline keeps at most this many
    return ([case.claim, *extra], True) if extra else ([case.claim], False)


_WITH_QUERIES = (
    f"the claim plus up to {limits.MAX_QUERIES_PER_CLAIM} queries per case from --queries "
    "(a case without an entry falls back to the claim alone)"
)

VARIANTS: dict[str, Variant] = {
    variant.name: variant
    for variant in (
        Variant(
            "claim",
            "the claim text alone (the pipeline with no model key)",
            _claim_only,
        ),
        Variant("claim+queries", _WITH_QUERIES, _claim_plus_queries, needs_queries=True),
        Variant(
            "queries-rrf",
            f"{_WITH_QUERIES}; ranked by reciprocal-rank fusion of the per-query rankings "
            f"(k = {RRF_K}) instead of the best score over queries",
            _claim_plus_queries,
            needs_queries=True,
            rank=rank_by_rrf,
        ),
        Variant(
            "queries-heading",
            f"{_WITH_QUERIES}; best score over queries, each passage scored with its "
            "section locator before its text",
            _claim_plus_queries,
            needs_queries=True,
            rank=rank_with_headings,
        ),
        Variant(
            "queries-rrf-heading",
            f"{_WITH_QUERIES}; reciprocal-rank fusion (k = {RRF_K}) of per-query rankings "
            "that score each passage with its section locator",
            _claim_plus_queries,
            needs_queries=True,
            rank=rank_by_rrf_with_headings,
        ),
    )
}


def get_variant(name: str) -> Variant:
    """The registered variant called ``name``. Raises ValueError for an unknown name."""
    try:
        return VARIANTS[name]
    except KeyError:
        raise ValueError(f"unknown variant {name!r}; known: {', '.join(VARIANTS)}") from None


def variant_queries(name: str, case: GoldenCase, book: QueryBook) -> tuple[list[str], bool]:
    """The queries variant ``name`` sends for ``case``, and whether extra queries were used."""
    return get_variant(name).build(case, book)


def read_queries(path: Path, case_ids: set[str]) -> dict[str, list[str]]:
    """The queries of a queries file, checked against the golden set's ids.

    See :func:`read_queries_file` for the two shapes accepted.
    """
    return read_queries_file(path, case_ids)[0]


def read_queries_file(
    path: Path, case_ids: set[str]
) -> tuple[dict[str, list[str]], dict[str, Any] | None]:
    """A queries file and its provenance (None for a file without one).

    Two shapes: ``{"provenance": {...}, "queries": {case_id: [query, ...]}}``, as
    ``python -m app.evaluation plan`` writes it, and the flat
    ``{case_id: [query, ...]}``. Raises ValueError for a malformed file or a case
    id the golden set does not have.
    """
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ValueError(f"queries file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"queries file {path.name} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("a queries file is a JSON object {case_id: [query, ...]}")
    provenance: dict[str, Any] | None = None
    if set(payload) == {"provenance", "queries"} and isinstance(payload["provenance"], dict):
        provenance = payload["provenance"]
        payload = payload["queries"]
        if not isinstance(payload, dict):
            raise ValueError('"queries" in a planned queries file is {case_id: [query, ...]}')
    return _query_book(payload, case_ids), provenance


def _query_book(payload: dict[str, Any], case_ids: set[str]) -> dict[str, list[str]]:
    book: dict[str, list[str]] = {}
    for case_id, queries in payload.items():
        if case_id not in case_ids:
            raise ValueError(f"queries file names {case_id!r}, which is not a golden case")
        if not isinstance(queries, list) or not all(isinstance(q, str) for q in queries):
            raise ValueError(f"queries for {case_id!r} must be a list of strings")
        book[case_id] = queries
    return book


# Scoring


@dataclass(frozen=True)
class CaseResult:
    """Where the passage that matters landed for one case."""

    case_id: str
    ticker: str
    rank: int | None  # uncapped, within MAX_RANK
    pipeline_position: int | None  # position in the pipeline's capped top 8
    extra_queries: bool
    queries: tuple[str, ...]
    passages: int
    top_passage: str = ""  # source id and locator of the first-ranked passage
    expected: str = ""
    relevant_sections: tuple[str, ...] = field(default_factory=tuple)

    @property
    def reciprocal_rank(self) -> float:
        """1 / rank, or 0 for a miss."""
        return reciprocal_rank(self.rank)


def score_case(
    case_id: str,
    ticker: str,
    index: PassageIndex,
    queries: list[str],
    spans: Sequence[Span],
    *,
    extra: bool,
    expected: str = "",
    relevant_sections: Sequence[str] = (),
    rank: Ranker = rank_by_best_score,
) -> CaseResult:
    """Rank ``index`` for ``queries`` and find the first passage overlapping ``spans``.

    ``rank`` orders the passages (the pipeline's ranking by default); the
    pipeline's cut (:meth:`PassageIndex.cut`) is applied to that order.
    """
    ordered = rank(index, queries)
    ranked = [passage for passage, _score in ordered]
    pipeline = index.cut(ordered)  # top 8, the per-source cap as a run applies it
    position = next(
        (n for n, passage in enumerate(pipeline, start=1) if is_relevant(passage, spans)), None
    )
    top = f"{ranked[0].source_id} {ranked[0].locator}" if ranked else ""
    return CaseResult(
        case_id=case_id,
        ticker=ticker,
        rank=first_relevant_rank(ranked, spans),
        pipeline_position=position,
        extra_queries=extra,
        queries=tuple(queries),
        passages=len(index),
        top_passage=top,
        expected=expected,
        relevant_sections=tuple(relevant_sections),
    )


@dataclass(frozen=True)
class Summary:
    """The metrics of one variant over the answerable cases."""

    cases: int
    recall_3: Recall
    recall_pipeline: Recall
    recall_20: Recall
    mrr: float | None
    extra_query_cases: int

    def as_dict(self) -> dict[str, Any]:
        """The summary for the JSON record, every rate with its denominator."""
        return {
            "cases_scored": self.cases,
            f"recall@{SHORT_K}": self.recall_3.as_dict(),
            f"recall@{PIPELINE_K}_pipeline_capped": self.recall_pipeline.as_dict(),
            f"recall@{LONG_K}": self.recall_20.as_dict(),
            "mrr": {"value": self.mrr, "total": self.cases, "max_rank": MAX_RANK},
            "cases_with_extra_queries": self.extra_query_cases,
        }


def summarize(results: Sequence[CaseResult]) -> Summary:
    """recall@3, the pipeline's capped recall@8, recall@20 and MRR over ``results``."""
    ranks = [result.rank for result in results]
    capped = Recall(sum(1 for r in results if r.pipeline_position is not None), len(results))
    mrr = sum(r.reciprocal_rank for r in results) / len(results) if results else None
    return Summary(
        cases=len(results),
        recall_3=recall_at(ranks, SHORT_K),
        recall_pipeline=capped,
        recall_20=recall_at(ranks, LONG_K),
        mrr=mrr,
        extra_query_cases=sum(1 for r in results if r.extra_queries),
    )


def spans_for(case: GoldenCase, targets: Sequence[Target]) -> list[Span]:
    """The targets as spans under the source ids a run would give the case's filings."""
    return [
        Span(f"s{case.filings.index(target.accession) + 1}", target.start, target.end)
        for target in targets
    ]


class IndexCache:
    """One :class:`PassageIndex` per (ticker, filings in order), built as a run builds it."""

    def __init__(self, loader: Loader) -> None:
        """Load filings through ``loader(ticker, accession)``."""
        self._loader = loader
        self._indexes: dict[tuple[str, tuple[str, ...]], PassageIndex] = {}

    def index(self, case: GoldenCase) -> PassageIndex:
        """The index over every passage of the case's filings, sources ``s1``, ``s2``, ..."""
        key = (case.ticker, tuple(case.filings))
        if key not in self._indexes:
            passages = [
                passage
                for number, accession in enumerate(case.filings, start=1)
                for passage in chunk_document(f"s{number}", self._loader(case.ticker, accession))
            ]
            self._indexes[key] = PassageIndex(passages)
        return self._indexes[key]


def evaluate(
    cases: Sequence[tuple[GoldenCase, list[Target]]],
    loader: Loader,
    variant: str,
    book: QueryBook,
) -> list[CaseResult]:
    """Score every answerable case for ``variant``; unanswerable cases are skipped."""
    indexes = IndexCache(loader)
    results: list[CaseResult] = []
    ranker = get_variant(variant).rank
    for case, targets in cases:
        if case.kind != "answerable":
            continue
        queries, extra = variant_queries(variant, case, book)
        results.append(
            score_case(
                case.id,
                case.ticker,
                indexes.index(case),
                queries,
                spans_for(case, targets),
                extra=extra,
                expected=case.expected,
                relevant_sections=[target.section for target in targets],
                rank=ranker,
            )
        )
    return results


# Explaining a rank: which terms put the first-ranked passage above the one that matters


@dataclass(frozen=True)
class PassageExplanation:
    """One passage's best score over the queries, and the terms that made it."""

    passage: Passage
    rank: int | None  # in the uncapped ranking, from 1; None when no query matches it
    query: str  # the query that gave the best score ("" when none matches)
    score: float
    terms: tuple[TermScore, ...]
    tokens: int  # its length in tokens, which BM25 normalises by


@dataclass(frozen=True)
class Explanation:
    """The first-ranked passage and the first relevant passage, side by side."""

    queries: tuple[str, ...]
    top: PassageExplanation | None
    relevant: PassageExplanation | None


def _explain_passage(
    index: PassageIndex, queries: Sequence[str], passage: Passage, rank: int | None
) -> PassageExplanation:
    best_query, best_terms, best_score = "", [], 0.0
    for query in queries:
        terms = index.contributions(query, passage)
        score = sum(term.score for term in terms)
        if score > best_score:
            best_query, best_terms, best_score = query, terms, score
    return PassageExplanation(
        passage=passage,
        rank=rank,
        query=best_query,
        score=best_score,
        terms=tuple(sorted(best_terms, key=lambda term: -term.score)),
        tokens=len(tokenize(passage.text)),
    )


def explain_ranking(
    index: PassageIndex, queries: Sequence[str], spans: Sequence[Span]
) -> Explanation:
    """Per-term BM25 contributions of the first-ranked and the first relevant passage.

    The relevant passage is the best-ranked one holding half of a span; when no
    query scores any relevant passage, the first relevant passage in document
    order is shown with rank None.
    """
    ranked = [passage for passage, _score in index.ranked(list(queries))]
    top = _explain_passage(index, queries, ranked[0], 1) if ranked else None
    rank = next((n for n, p in enumerate(ranked, start=1) if is_relevant(p, spans)), None)
    if rank is not None:
        relevant: Passage | None = ranked[rank - 1]
    else:
        relevant = next((p for p in index.passages if is_relevant(p, spans)), None)
    return Explanation(
        queries=tuple(queries),
        top=top,
        relevant=None if relevant is None else _explain_passage(index, queries, relevant, rank),
    )


def _render_side(label: str, side: PassageExplanation) -> list[str]:
    rank = "unranked" if side.rank is None else f"rank {side.rank}"
    lines = [
        f"{label}: {side.passage.id} ({rank}, score {side.score:.2f}, {side.tokens} tokens) "
        f"{_shorten(side.passage.locator, 140)}",
        f"  best query: {side.query!r}" if side.query else "  no query term occurs in it",
    ]
    lines.extend(
        f"  {term.term:<16} idf {term.idf:5.2f}  tf {term.frequency:3d}  +{term.score:5.2f}"
        for term in side.terms
    )
    lines.append(f"  text: {_shorten(' '.join(side.passage.text.split()), 240)}")
    return lines


def render_explanation(case_id: str, explanation: Explanation) -> str:
    """The explanation as plain text: one block per passage, terms by contribution."""
    lines = [f"== {case_id}: {len(explanation.queries)} queries"]
    lines.extend(f"  q: {query}" for query in explanation.queries)
    if explanation.top is not None:
        lines.extend(_render_side("first-ranked", explanation.top))
    if explanation.relevant is None:
        lines.append("must-retrieve: no passage holds half of an excerpt")
    else:
        lines.extend(_render_side("must-retrieve", explanation.relevant))
    return "\n".join(lines) + "\n"


# The record


def limits_snapshot() -> dict[str, Any]:
    """Every number the score depends on, so a later run can tell whether they changed."""
    bm25 = Bm25Index([])
    return {
        "PASSAGE_TARGET_CHARS": limits.PASSAGE_TARGET_CHARS,
        "PASSAGE_MAX_CHARS": limits.PASSAGE_MAX_CHARS,
        "PASSAGES_PER_CLAIM": limits.PASSAGES_PER_CLAIM,
        "MAX_PASSAGES_PER_SOURCE": limits.MAX_PASSAGES_PER_SOURCE,
        "MAX_QUERIES_PER_CLAIM": limits.MAX_QUERIES_PER_CLAIM,
        "bm25_k1": bm25.k1,
        "bm25_b": bm25.b,
        "max_rank": MAX_RANK,
    }


def build_record(
    results: Sequence[CaseResult],
    *,
    variant: str,
    inputs: Mapping[str, Any],
    unanswerable: Sequence[str],
    generated_at: datetime,
) -> dict[str, Any]:
    """The JSON record of one scoring run: pinned inputs, summary and every case."""
    summary = summarize(results)
    return {
        "kind": "retrieval-evaluation",
        "generated_at": generated_at.isoformat(),
        "variant": {"name": variant, "description": get_variant(variant).description},
        "inputs": {**inputs, "limits": limits_snapshot()},
        "summary": summary.as_dict(),
        "cases": [
            {
                **asdict(result),
                "queries": list(result.queries),
                "relevant_sections": list(result.relevant_sections),
                "rank_label": rank_label(result.rank),
                "reciprocal_rank": result.reciprocal_rank,
            }
            for result in results
        ],
        "unscored_unanswerable_cases": list(unanswerable),
    }


def _cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def _percent(recall: Recall) -> str:
    return "n/a" if recall.rate is None else f"{recall.rate:.1%}"


def _shorten(text: str, size: int = LOCATOR_CHARS) -> str:
    return text if len(text) <= size else text[: size - 1] + "…"


def render_summary(results: Sequence[CaseResult]) -> str:
    """The metrics as a Markdown table, every rate with its numerator and denominator."""
    summary = summarize(results)
    mrr = "n/a" if summary.mrr is None else f"{summary.mrr:.3f}"
    rows = [
        (f"recall@{SHORT_K}", _percent(summary.recall_3), summary.recall_3),
        (
            f"recall@{PIPELINE_K} (pipeline cut: top {PIPELINE_K}, "
            f"at most {limits.MAX_PASSAGES_PER_SOURCE} per filing when there are several)",
            _percent(summary.recall_pipeline),
            summary.recall_pipeline,
        ),
        (f"recall@{LONG_K}", _percent(summary.recall_20), summary.recall_20),
    ]
    lines = ["| Metric | Value | Cases |", "|---|---|---|"]
    lines.extend(f"| {name} | {value} | {r.hits} / {r.total} |" for name, value, r in rows)
    lines.append(f"| MRR (rank beyond {MAX_RANK} counts 0) | {mrr} | over {summary.cases} |")
    return "\n".join(lines) + "\n"


def render_cases(results: Sequence[CaseResult]) -> str:
    """The per-case Markdown table."""
    lines = [
        f"| Case | Ticker | Expected | Rank | Pipeline top {PIPELINE_K} | Queries | "
        "First-ranked passage |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        pipeline = f"#{r.pipeline_position}" if r.pipeline_position is not None else "no"
        queries = f"claim + {len(r.queries) - 1}" if r.extra_queries else "claim"
        row = [
            r.case_id,
            r.ticker,
            r.expected,
            rank_label(r.rank),
            pipeline,
            queries,
            _shorten(r.top_passage),
        ]
        lines.append("| " + " | ".join(_cell(cell) for cell in row) + " |")
    return "\n".join(lines) + "\n"


def render_markdown(record: Mapping[str, Any], results: Sequence[CaseResult]) -> str:
    """The whole report: inputs, summary, how to read it, and the per-case table."""
    inputs = record["inputs"]
    variant = record["variant"]
    summary = summarize(results)
    fallback = summary.cases - summary.extra_query_cases
    lines = [
        f"# Retrieval evaluation: variant `{variant['name']}`",
        "",
        f"Generated {record['generated_at']}. Queries: {variant['description']}.",
        "",
        f"- Golden set version {inputs['golden_version']}, SHA-256 "
        f"`{inputs['golden_sha256'][:16]}…`; filings pinned in `eval/filings.json` "
        f"(SHA-256 `{inputs['filings_sha256'][:16]}…`).",
        f"- Cases: {inputs['cases_total']} in the set; {summary.cases} answerable cases scored; "
        f"{inputs['cases_unanswerable']} unanswerable cases not scored (retrieval always "
        "returns something; whether the answer says so is a generation question).",
    ]
    if get_variant(variant["name"]).needs_queries:
        lines.append(
            f"- Extra queries from `{inputs.get('queries_file')}` for "
            f"{summary.extra_query_cases} of {summary.cases} cases; {fallback} fell back to "
            "the claim alone."
        )
    lines += [
        "",
        render_summary(results),
        f"Every rate is over the {summary.cases} answerable cases. A case counts as a hit "
        "when a passage holding at least half of one of its must-retrieve excerpts ranks "
        f"within the cut-off. recall@{PIPELINE_K} is what a thesis run would offer the "
        f"engine: the top {PIPELINE_K} with the pipeline's cap of "
        f"{limits.MAX_PASSAGES_PER_SOURCE} passages per filing applied when the case has "
        f"more than one filing, exactly as `PassageIndex.cut`. recall@{SHORT_K}, "
        f"recall@{LONG_K}, the rank and MRR use the "
        f"uncapped ranking; a rank beyond {MAX_RANK} is a miss.",
        "",
        "## Per case",
        "",
        render_cases(results),
    ]
    return "\n".join(lines)


def write_record(
    record: Mapping[str, Any], markdown: str, out_dir: Path, variant: str, when: datetime
) -> tuple[Path, Path]:
    """Write ``retrieval-<variant>-<UTC date>.json`` and ``.md`` under ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"retrieval-{variant}-{when.strftime('%Y-%m-%d')}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(record, indent=2) + "\n")
    md_path.write_text(markdown)
    return json_path, md_path
