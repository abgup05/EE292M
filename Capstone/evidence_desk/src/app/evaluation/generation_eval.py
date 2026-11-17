"""Score generation on the golden set: given the passages offered, is the answer right?

Every case is run as a one-claim thesis run would run it. The passages of its
filings are built as in :mod:`app.evaluation.retrieval_eval` (sources ``s1``,
``s2``, ... in the case's filing order); the claim and its planned queries
(``python -m app.evaluation plan``) choose the passages offered with
:meth:`PassageIndex.search` (top 8, at most 5 per filing); the company's
reported figures are those :func:`app.services.numbers.select_figures` picks;
:meth:`app.engines.claude.ClaudeAnalyst.assess` drafts the findings through a
cassette; :func:`app.core.gate.gate_claim` checks them against the stored text,
and :func:`app.core.policy.claim_verdict` decides the verdict. Nothing here
judges a stance itself.

The scores, each with its denominator:

- answerable cases: verdict agreement ("supports" with supported, "challenges"
  with challenged, "mixed" with mixed) and the table of expected against
  obtained verdicts; the share of cases where a verified excerpt holds at least
  half of a must-retrieve excerpt (the retrieval overlap rule,
  :func:`~app.evaluation.retrieval_eval.holds_half`); both split by whether a
  must-retrieve passage was among the passages offered, so a generation failure
  is not blamed for a retrieval failure;
- unanswerable cases: refusal, meaning no verified finding and the verdict
  not_addressed;
- all cases: quotes offered, verified and rejected; numbers checked and
  unmatched; findings proposed, verified and withheld, with the reasons.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core import limits, policy
from app.core.documents import Passage
from app.core.gate import NUMBER_REASON, RunIds, StoredSource, gate_claim
from app.core.models import Claim, Company, ThesisRequest, Verdict
from app.core.ports import ClaimDraft
from app.engines.cassette import CassetteMiss, CassetteTransport
from app.engines.claude import ClaudeAnalyst
from app.engines.transport import EngineError, Transport
from app.evaluation.companies import CompanyFigures
from app.evaluation.golden import GoldenCase, Target
from app.evaluation.planning import DECISION, EXIT_PENDING
from app.evaluation.retrieval_eval import (
    Loader,
    QueryBook,
    Span,
    first_relevant_rank,
    holds_half,
    is_relevant,
    limits_snapshot,
    rank_label,
    spans_for,
)
from app.retrieval.chunk import chunk_document
from app.retrieval.search import PassageIndex

__all__ = [
    "CaseOutcome",
    "CompanyFigures",
    "GenerationRun",
    "GenerationSummary",
    "Rate",
    "build_record",
    "evaluate_generation",
    "render_markdown",
    "run_generation",
    "summarize_generation",
    "write_record",
]

EXPECTED_VERDICT: dict[str, Verdict] = {
    "supports": Verdict.supported,
    "challenges": Verdict.challenged,
    "mixed": Verdict.mixed,
}
VERDICTS: tuple[str, ...] = tuple(verdict.value for verdict in Verdict)
NUMBER_REASON_KIND = NUMBER_REASON.split(":")[0]
STAND_IN_NOTE = (
    "A recording answered by a stand-in (any `via` other than the model a run calls) is an "
    "upper bound for quote validity: a stand-in that copies from the prompt in front of it "
    "quotes more exactly than a model may, so the quote and citation scores may be lower live."
)


@dataclass(frozen=True)
class Rate:
    """Cases that met a condition, over the cases it applies to."""

    hits: int
    total: int

    @property
    def rate(self) -> float | None:
        """hits / total, or None when nothing applies."""
        return self.hits / self.total if self.total else None

    def as_dict(self) -> dict[str, Any]:
        """The rate with its denominator, for the JSON record."""
        return {"hits": self.hits, "total": self.total, "rate": self.rate}

    def fraction(self) -> str:
        """``hits / total``."""
        return f"{self.hits} / {self.total}"

    def percent(self) -> str:
        """The rate as a percentage, or n/a."""
        return "n/a" if self.rate is None else f"{self.rate:.1%}"


def _rate(flags: Sequence[bool]) -> Rate:
    return Rate(sum(1 for flag in flags if flag), len(flags))


@dataclass(frozen=True)
class CaseOutcome:
    """What one case's run produced, and how it compares with the golden set."""

    case_id: str
    ticker: str
    kind: str
    expected: str
    verdict: str
    queries: tuple[str, ...]
    passages_offered: int
    offered_position: int | None  # position of the first must-retrieve passage among those offered
    rank: int | None  # its rank in the uncapped ranking, within MAX_RANK
    cited_right_passage: bool  # a verified excerpt holds half of a must-retrieve excerpt
    findings_verified: int
    findings_withheld: int
    withheld_reasons: tuple[str, ...]
    verified_stances: tuple[str, ...]
    quotes_offered: int
    quotes_rejected: int
    excerpts_kept: int
    numbers_checked: int
    numbers_unmatched: int
    figures_offered: int
    figures_cited: int
    engine_error: str = ""
    problems: tuple[str, ...] = field(default_factory=tuple)

    @property
    def answerable(self) -> bool:
        """True for a case the filings can answer."""
        return self.kind == "answerable"

    @property
    def retrieval_hit(self) -> bool:
        """True when a must-retrieve passage was among the passages offered."""
        return self.offered_position is not None

    @property
    def agrees(self) -> bool:
        """True when the verdict is the one the expected stance calls for."""
        wanted = EXPECTED_VERDICT.get(self.expected)
        return wanted is not None and self.verdict == wanted.value

    @property
    def refused(self) -> bool:
        """True when nothing was verified and the verdict is not_addressed."""
        return self.findings_verified == 0 and self.verdict == Verdict.not_addressed.value


def withheld_kind(reason: str) -> str:
    """A withheld finding's reason without its particulars (the numbers it names)."""
    return NUMBER_REASON_KIND if reason.startswith(NUMBER_REASON_KIND) else reason


@dataclass
class _Material:
    """One case's filings as a run holds them: the passage index and the stored texts."""

    index: PassageIndex
    stored: dict[str, StoredSource]


class _Materials:
    """One :class:`_Material` per (ticker, filings in order), built once."""

    def __init__(self, loader: Loader) -> None:
        self._loader = loader
        self._built: dict[tuple[str, tuple[str, ...]], _Material] = {}

    def get(self, case: GoldenCase) -> _Material:
        key = (case.ticker, tuple(case.filings))
        if key not in self._built:
            passages: list[Passage] = []
            stored: dict[str, StoredSource] = {}
            for number, accession in enumerate(case.filings, start=1):
                document = self._loader(case.ticker, accession)
                source_id = f"s{number}"
                passages.extend(chunk_document(source_id, document))
                stored[source_id] = StoredSource(document.text, document.url)
            self._built[key] = _Material(PassageIndex(passages), stored)
        return self._built[key]


@dataclass
class GenerationRun:
    """The cases scored, and the ids of the cases whose model answer is still pending."""

    outcomes: list[CaseOutcome] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    assessed: int = 0  # cases that asked the model (every case with a passage offered)


def _outcome(
    case: GoldenCase,
    spans: Sequence[Span],
    queries: Sequence[str],
    offered: Sequence[Passage],
    ranked: Sequence[Passage],
    draft: ClaimDraft,
    material: _Material,
    figures: CompanyFigures,
    engine_error: str,
) -> CaseOutcome:
    """Gate the draft as the pipeline does and compare the result with the case."""
    offered_figures = {figure.id: figure for figure in figures.figures}
    result = gate_claim(
        "c1", draft, {p.id: p for p in offered}, material.stored, RunIds(), figures=offered_figures
    )
    verdict = policy.claim_verdict(result.findings)
    cited = any(
        holds_half(e.source_id, e.start, e.start + len(e.excerpt), spans) for e in result.evidence
    )
    position = next((n for n, p in enumerate(offered, start=1) if is_relevant(p, spans)), None)
    return CaseOutcome(
        case_id=case.id,
        ticker=case.ticker,
        kind=case.kind,
        expected=case.expected,
        verdict=verdict.value,
        queries=tuple(queries),
        passages_offered=len(offered),
        offered_position=position,
        rank=first_relevant_rank(ranked, spans) if spans else None,
        cited_right_passage=cited,
        findings_verified=len(result.findings),
        findings_withheld=len(result.unsupported),
        withheld_reasons=tuple(withheld_kind(f.withheld_reason) for f in result.unsupported),
        verified_stances=tuple(f.stance.value for f in result.findings),
        quotes_offered=result.quotes_offered,
        quotes_rejected=result.quotes_rejected,
        excerpts_kept=len(result.evidence),
        numbers_checked=result.numbers_checked,
        numbers_unmatched=result.numbers_unmatched,
        figures_offered=len(figures.figures),
        figures_cited=result.figures_cited,
        engine_error=engine_error,
        problems=tuple(result.problems),
    )


def evaluate_generation(
    cases: Sequence[tuple[GoldenCase, list[Target]]],
    loader: Loader,
    book: QueryBook,
    companies: Mapping[str, Company],
    figures: Mapping[str, CompanyFigures],
    transport: Transport,
) -> GenerationRun:
    """Run every case through retrieval, the model (via ``transport``), the gate and the rule.

    A case whose model answer is missing (:class:`CassetteMiss`) is skipped and
    listed in ``pending``. An answer that cannot be parsed is kept as an empty
    draft with ``engine_error`` set (a run would fall back to the extractive
    engine; the evaluation scores the model, so it does not). Raises
    ValueError when ``book`` has no entry for a case.
    """
    analyst = ClaudeAnalyst(transport=transport)
    materials = _Materials(loader)
    run = GenerationRun()
    for case, targets in cases:
        if case.id not in book:
            raise ValueError(f"the queries file has no entry for {case.id}; run plan again")
        request = ThesisRequest(ticker=case.ticker, decision=DECISION, claims=[case.claim])
        claim = Claim(id="c1", text=request.claims[0])
        queries = [query for query in book[case.id] if query.strip()][
            : limits.MAX_QUERIES_PER_CLAIM
        ]
        material = materials.get(case)
        company_figures = figures.get(case.ticker, CompanyFigures())
        offered = material.index.search([claim.text, *queries])
        ranked = [passage for passage, _ in material.index.ranked([claim.text, *queries])]
        engine_error = ""
        if offered:
            run.assessed += 1
            try:
                draft = analyst.assess(
                    request, companies[case.ticker], claim, offered, company_figures.figures
                )
            except CassetteMiss:
                run.pending.append(case.id)
                continue
            except EngineError as exc:
                draft, engine_error = ClaimDraft(), str(exc)
        else:
            draft = ClaimDraft()  # a run does not ask the model when no passage is offered
        spans = spans_for(case, targets)
        run.outcomes.append(
            _outcome(
                case,
                spans,
                queries,
                offered,
                ranked,
                draft,
                material,
                company_figures,
                engine_error,
            )
        )
    return run


# Scores


@dataclass(frozen=True)
class Split:
    """Verdict agreement and citation over one subset of the answerable cases."""

    verdict_agreement: Rate
    citation: Rate

    def as_dict(self) -> dict[str, Any]:
        """Both rates with their denominators."""
        return {
            "verdict_agreement": self.verdict_agreement.as_dict(),
            "citation": self.citation.as_dict(),
        }


@dataclass(frozen=True)
class Totals:
    """Counts over every case scored."""

    cases: int
    findings_proposed: int
    findings_verified: int
    findings_withheld: int
    withheld_reasons: dict[str, int]
    quotes_offered: int
    quotes_verified: int
    quotes_rejected: int
    excerpts_kept: int
    numbers_checked: int
    numbers_unmatched: int
    figures_cited: int
    unusable_answers: int
    cases_without_passages: int


@dataclass(frozen=True)
class GenerationSummary:
    """Every score of one generation run, each with its denominator."""

    answerable: int
    unanswerable: int
    verdict_agreement: Rate
    confusion: dict[str, dict[str, int]]
    citation: Rate
    by_retrieval: dict[str, Split]
    refusal: Rate
    totals: Totals

    def as_dict(self) -> dict[str, Any]:
        """The summary for the JSON record."""
        return {
            "answerable": {
                "cases": self.answerable,
                "verdict_agreement": self.verdict_agreement.as_dict(),
                "confusion_expected_by_obtained": self.confusion,
                "citation": self.citation.as_dict(),
                "by_retrieval": {k: v.as_dict() for k, v in self.by_retrieval.items()},
            },
            "unanswerable": {"cases": self.unanswerable, "refusal": self.refusal.as_dict()},
            "all": asdict(self.totals),
        }


def summarize_generation(outcomes: Sequence[CaseOutcome]) -> GenerationSummary:
    """The scores over ``outcomes``."""
    answerable = [o for o in outcomes if o.answerable]
    unanswerable = [o for o in outcomes if not o.answerable]
    confusion = {expected: {verdict: 0 for verdict in VERDICTS} for expected in EXPECTED_VERDICT}
    for outcome in answerable:
        confusion[outcome.expected][outcome.verdict] += 1
    by_retrieval = {}
    for name, flag in (("hit", True), ("miss", False)):
        subset = [o for o in answerable if o.retrieval_hit is flag]
        by_retrieval[name] = Split(
            _rate([o.agrees for o in subset]), _rate([o.cited_right_passage for o in subset])
        )
    reasons = Counter(reason for o in outcomes for reason in o.withheld_reasons)
    offered = sum(o.quotes_offered for o in outcomes)
    rejected = sum(o.quotes_rejected for o in outcomes)
    verified = sum(o.findings_verified for o in outcomes)
    withheld = sum(o.findings_withheld for o in outcomes)
    totals = Totals(
        cases=len(outcomes),
        findings_proposed=verified + withheld,
        findings_verified=verified,
        findings_withheld=withheld,
        withheld_reasons=dict(sorted(reasons.items())),
        quotes_offered=offered,
        quotes_verified=offered - rejected,
        quotes_rejected=rejected,
        excerpts_kept=sum(o.excerpts_kept for o in outcomes),
        numbers_checked=sum(o.numbers_checked for o in outcomes),
        numbers_unmatched=sum(o.numbers_unmatched for o in outcomes),
        figures_cited=sum(o.figures_cited for o in outcomes),
        unusable_answers=sum(1 for o in outcomes if o.engine_error),
        cases_without_passages=sum(1 for o in outcomes if o.passages_offered == 0),
    )
    return GenerationSummary(
        answerable=len(answerable),
        unanswerable=len(unanswerable),
        verdict_agreement=_rate([o.agrees for o in answerable]),
        confusion=confusion,
        citation=_rate([o.cited_right_passage for o in answerable]),
        by_retrieval=by_retrieval,
        refusal=_rate([o.refused for o in unanswerable]),
        totals=totals,
    )


# The record


def build_record(
    outcomes: Sequence[CaseOutcome],
    *,
    models: str,
    inputs: Mapping[str, Any],
    figures: Mapping[str, str],
    generated_at: datetime,
) -> dict[str, Any]:
    """The JSON record of one generation run: where the answers came from, scores, cases."""
    return {
        "kind": "generation-evaluation",
        "generated_at": generated_at.isoformat(),
        "models": models,
        "stand_in_note": STAND_IN_NOTE,
        "decision": DECISION,
        "inputs": {**inputs, "limits": limits_snapshot()},
        "figures": dict(figures),
        "summary": summarize_generation(outcomes).as_dict(),
        "cases": [
            {
                **asdict(outcome),
                "retrieval_hit": outcome.retrieval_hit,
                "agrees": outcome.agrees if outcome.answerable else None,
                "refused": outcome.refused if not outcome.answerable else None,
            }
            for outcome in outcomes
        ],
    }


def _cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def _row(*cells: object) -> str:
    return "| " + " | ".join(_cell(cell) for cell in cells) + " |"


def _retrieval_cell(outcome: CaseOutcome) -> str:
    if not outcome.answerable:
        return "n/a"
    if outcome.offered_position is not None:
        return f"offered #{outcome.offered_position} of {outcome.passages_offered}"
    rank = rank_label(outcome.rank)
    return f"not offered (rank {rank})" if outcome.rank is not None else f"not offered ({rank})"


def render_cases(outcomes: Sequence[CaseOutcome]) -> str:
    """The per-case Markdown table."""
    lines = [
        _row(
            "Case",
            "Ticker",
            "Expected",
            "Obtained",
            "Must-retrieve passage",
            "Cited it",
            "Findings verified / withheld",
        ),
        "|---|---|---|---|---|---|---|",
    ]
    for o in outcomes:
        cited = ("yes" if o.cited_right_passage else "no") if o.answerable else "n/a"
        obtained = o.verdict + (" (answer unusable)" if o.engine_error else "")
        lines.append(
            _row(
                o.case_id,
                o.ticker,
                o.expected,
                obtained,
                _retrieval_cell(o),
                cited,
                f"{o.findings_verified} / {o.findings_withheld}",
            )
        )
    return "\n".join(lines) + "\n"


def _answerable_section(summary: GenerationSummary) -> list[str]:
    hit, miss = summary.by_retrieval["hit"], summary.by_retrieval["miss"]
    rows = [
        ("Verdict agreement", summary.verdict_agreement),
        ("  where a must-retrieve passage was offered", hit.verdict_agreement),
        ("  where none was offered", miss.verdict_agreement),
        ("Cites a must-retrieve passage (verified excerpt holds half of it)", summary.citation),
        ("  where a must-retrieve passage was offered", hit.citation),
        ("  where none was offered", miss.citation),
    ]
    lines = [
        f"## Answerable cases ({summary.answerable})",
        "",
        "| Score | Value | Cases |",
        "|---|---|---|",
    ]
    lines += [_row(name, rate.percent(), rate.fraction()) for name, rate in rows]
    lines += [
        "",
        "Expected stance (rows) against the verdict obtained (columns):",
        "",
        _row("Expected", *VERDICTS, "Cases"),
        "|---|" + "---|" * (len(VERDICTS) + 1),
    ]
    for expected, row in summary.confusion.items():
        lines.append(_row(expected, *(row[v] for v in VERDICTS), sum(row.values())))
    return lines


def _totals_section(totals: Totals) -> list[str]:
    t = totals
    rows: list[tuple[str, int, str]] = [
        (
            "Quotes verified (located in the stored text)",
            t.quotes_verified,
            f"{t.quotes_verified} / {t.quotes_offered} offered",
        ),
        ("Quotes rejected", t.quotes_rejected, f"{t.quotes_rejected} / {t.quotes_offered} offered"),
        ("Excerpts kept as evidence (verified findings only)", t.excerpts_kept, ""),
        (
            "Numbers unmatched",
            t.numbers_unmatched,
            f"{t.numbers_unmatched} / {t.numbers_checked} checked",
        ),
        (
            "Findings verified",
            t.findings_verified,
            f"{t.findings_verified} / {t.findings_proposed} proposed",
        ),
        (
            "Findings withheld",
            t.findings_withheld,
            f"{t.findings_withheld} / {t.findings_proposed} proposed",
        ),
    ]
    rows += [
        (f"  withheld: {reason}", count, f"{count} / {t.findings_withheld} withheld")
        for reason, count in t.withheld_reasons.items()
    ]
    rows += [
        ("Reported figures cited by verified findings", t.figures_cited, ""),
        (
            "Model answers that could not be parsed",
            t.unusable_answers,
            f"{t.unusable_answers} / {t.cases} cases",
        ),
        (
            "Cases with no passage offered (model not asked)",
            t.cases_without_passages,
            f"{t.cases_without_passages} / {t.cases} cases",
        ),
    ]
    lines = [f"## All cases ({t.cases})", "", "| Count | Value | Of |", "|---|---|---|"]
    lines += [_row(name, value, whole) for name, value, whole in rows]
    return lines


def render_markdown(record: Mapping[str, Any], outcomes: Sequence[CaseOutcome]) -> str:
    """The report: where the answers came from, the scores, how to read them, every case."""
    summary = summarize_generation(outcomes)
    inputs = record.get("inputs", {})
    lines = [
        "# Generation evaluation",
        "",
        f"Model answers: {record.get('models', 'unknown')}.",
        "",
        STAND_IN_NOTE,
        "",
        f"Generated {record.get('generated_at', '')}. Each case is run as a one-claim thesis "
        f'with the decision "{DECISION}"; the gate and the verdict rule are the pipeline\'s own.',
    ]
    if inputs.get("golden_sha256"):
        lines.append(
            f"Golden set SHA-256 `{inputs['golden_sha256'][:16]}…`; queries from "
            f"`{inputs.get('queries_file')}` (SHA-256 `{str(inputs.get('queries_sha256'))[:16]}…`)."
        )
    figures = record.get("figures", {})
    if figures:
        lines += ["", "Reported figures offered with every claim:", ""]
        lines += [f"- {ticker}: {note}" for ticker, note in figures.items()]
    unanswerable = [
        f"## Unanswerable cases ({summary.unanswerable})",
        "",
        "| Score | Value | Cases |",
        "|---|---|---|",
        _row(
            "Refusal (no verified finding, verdict not_addressed)",
            summary.refusal.percent(),
            summary.refusal.fraction(),
        ),
    ]
    lines += [
        "",
        *_answerable_section(summary),
        "",
        *unanswerable,
        "",
        *_totals_section(summary.totals),
        "",
        "## How to read it",
        "",
        "Verdict agreement and citation are over the answerable cases; refusal over the "
        "unanswerable ones; the counts over every case. A must-retrieve passage was offered "
        "when a passage holding half of one of the case's excerpts was among the passages the "
        "model saw; where none was, a wrong verdict is a retrieval failure first. Only verified "
        "findings count: a withheld finding never makes a verdict or a citation. Citing a "
        "must-retrieve excerpt is a strict test: a correct answer may cite other evidence.",
        "",
        "## Per case",
        "",
        render_cases(outcomes),
    ]
    return "\n".join(lines)


def write_record(
    record: Mapping[str, Any], markdown: str, out_dir: Path, when: datetime
) -> tuple[Path, Path]:
    """Write ``generation-<UTC date>.json`` and ``.md`` under ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"generation-{when.strftime('%Y-%m-%d')}"
    json_path, md_path = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    md_path.write_text(markdown)
    return json_path, md_path


def run_generation(
    cases: Sequence[tuple[GoldenCase, list[Target]]],
    loader: Loader,
    book: QueryBook,
    companies: Mapping[str, Company],
    figures: Mapping[str, CompanyFigures],
    *,
    cassette: Path,
    out_dir: Path,
    inputs: Mapping[str, Any],
    now: datetime | None = None,
) -> int:
    """Assess every case through ``cassette``; write the record only when nothing is pending.

    Returns 0 when written and 3 while assess requests are pending.
    """
    transport = CassetteTransport(cassette)
    run = evaluate_generation(cases, loader, book, companies, figures, transport)
    if run.pending:
        print(
            f"generate: {len(run.pending)} of {run.assessed} assess request(s) pending in "
            f"{cassette}/pending. Answer them (docs/cassettes.md) and run again. "
            "Nothing was written."
        )
        return EXIT_PENDING
    when = now or datetime.now(UTC)
    record = build_record(
        run.outcomes,
        models=transport.detail,
        inputs=inputs,
        figures={ticker: f.note for ticker, f in figures.items()},
        generated_at=when,
    )
    markdown = render_markdown(record, run.outcomes)
    json_path, md_path = write_record(record, markdown, out_dir, when)
    print(markdown)
    print(f"generate: all {run.assessed} assess request(s) answered")
    print(f"generate: wrote {json_path} and {md_path}")
    return 0
