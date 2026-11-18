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

With the meaning check (``generate --check``), every case's verified findings
are also read by :class:`app.engines.checker.ClaudeChecker` through the same
cassette, as a run would, and the report adds: findings checked, passed,
partly supported and failed; verdict agreement before and after the check (a
failed finding drops out of the verdict); and, of the cases whose verdict
disagreed with the expected stance before the check, how many now agree and
how many still disagree, and how many agreeing cases the check broke. Without
it the record and the report are what they were.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ed_v10.core import limits, policy
from ed_v10.core.documents import Passage
from ed_v10.core.gate import NUMBER_REASON, GateResult, RunIds, StoredSource, gate_claim
from ed_v10.core.meaning import IncompleteJudgements, by_index, check_items
from ed_v10.core.models import Claim, Company, ThesisRequest, Verdict
from ed_v10.core.ports import Checker, CheckItem, ClaimDraft, SupportVerdict
from ed_v10.engines.cassette import CassetteMiss, CassetteTransport
from ed_v10.engines.checker import ClaudeChecker
from ed_v10.engines.claude import ClaudeAnalyst
from ed_v10.engines.transport import EngineError, Transport
from ed_v10.evaluation.companies import CompanyFigures
from ed_v10.evaluation.golden import GoldenCase, Target
from ed_v10.evaluation.planning import DECISION, EXIT_PENDING
from ed_v10.evaluation.retrieval_eval import (
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
from ed_v10.retrieval.chunk import chunk_document
from ed_v10.retrieval.search import PassageIndex

__all__ = [
    "CaseOutcome",
    "CheckOutcome",
    "CompanyFigures",
    "GenerationRun",
    "GenerationSummary",
    "MeaningSummary",
    "Rate",
    "build_record",
    "case_request",
    "evaluate_generation",
    "render_markdown",
    "run_generation",
    "summarize_generation",
    "verified_check_items",
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
class CheckOutcome:
    """What the meaning check made of one case's verified findings.

    ``judged`` holds one verdict per verified finding, in order ("supported",
    "partly", "not_supported"); ``verdict_after`` is the claim's verdict once
    the findings judged unsupported drop out. ``error`` says why the check
    could not run; then nothing was judged and the verdict stands.
    """

    judged: tuple[str, ...]
    verdict_after: str
    error: str = ""

    def count(self, verdict: SupportVerdict) -> int:
        """How many findings received ``verdict``."""
        return sum(1 for judged in self.judged if judged == verdict.value)


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
    check: CheckOutcome | None = None  # set only when the meaning check ran

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
    def verdict_after_check(self) -> str:
        """The verdict once the meaning check has run (the verdict itself without one)."""
        return self.check.verdict_after if self.check is not None else self.verdict

    @property
    def agrees_after_check(self) -> bool:
        """True when the verdict after the meaning check is the one the expected stance wants."""
        wanted = EXPECTED_VERDICT.get(self.expected)
        return wanted is not None and self.verdict_after_check == wanted.value

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
    """The cases scored, and the ids of the cases whose model answer is still pending.

    ``gated`` keeps each case's gated result (its verified findings and their
    excerpts) for an evaluation that builds on them; the record never reads it.
    """

    outcomes: list[CaseOutcome] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    assessed: int = 0  # cases that asked the model (every case with a passage offered)
    check_pending: list[str] = field(default_factory=list)  # cases whose check is unanswered
    checks_asked: int = 0  # cases that asked the checker (every case with a verified finding)
    gated: dict[str, GateResult] = field(default_factory=dict)  # each gated case, by id


def case_request(case: GoldenCase) -> tuple[ThesisRequest, Claim]:
    """The one-claim request a run would make for ``case``, and its claim (id ``c1``)."""
    request = ThesisRequest(ticker=case.ticker, decision=DECISION, claims=[case.claim])
    return request, Claim(id="c1", text=request.claims[0])


def verified_check_items(result: GateResult, figures: CompanyFigures) -> list[CheckItem]:
    """What the meaning check is shown of ``result``'s verified findings, in order."""
    return check_items(
        result.findings,
        {item.id: item for item in result.evidence},
        {figure.id: figure for figure in figures.figures},
    )


def _gate(
    draft: ClaimDraft, offered: Sequence[Passage], material: _Material, figures: CompanyFigures
) -> GateResult:
    """Gate the draft as the pipeline does."""
    offered_figures = {figure.id: figure for figure in figures.figures}
    return gate_claim(
        "c1", draft, {p.id: p for p in offered}, material.stored, RunIds(), figures=offered_figures
    )


def _check(
    checker: Checker,
    request: ThesisRequest,
    company: Company,
    claim: Claim,
    result: GateResult,
    figures: CompanyFigures,
) -> CheckOutcome:
    """Have ``checker`` read the verified findings; the verdict without those it rejects.

    A missing answer (:class:`CassetteMiss`) propagates; any other failure is
    kept as the outcome's ``error``, with nothing judged, as a run would.
    """
    before = policy.claim_verdict(result.findings).value
    if not result.findings:
        return CheckOutcome(judged=(), verdict_after=before)
    items = verified_check_items(result, figures)
    try:
        keyed = by_index(checker.check(request, company, claim, items), len(items))
    except CassetteMiss:
        raise
    except (EngineError, IncompleteJudgements) as exc:
        return CheckOutcome(judged=(), verdict_after=before, error=str(exc))
    judged = tuple(keyed[index].verdict for index in range(len(items)))
    kept = [
        finding
        for finding, verdict in zip(result.findings, judged, strict=True)
        if verdict != SupportVerdict.not_supported
    ]
    return CheckOutcome(
        judged=tuple(verdict.value for verdict in judged),
        verdict_after=policy.claim_verdict(kept).value,
    )


def _outcome(
    case: GoldenCase,
    spans: Sequence[Span],
    queries: Sequence[str],
    offered: Sequence[Passage],
    ranked: Sequence[Passage],
    result: GateResult,
    figures: CompanyFigures,
    engine_error: str,
    check: CheckOutcome | None = None,
) -> CaseOutcome:
    """Compare one case's gated result (and its meaning check, if any) with the case."""
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
        check=check,
    )


def evaluate_generation(
    cases: Sequence[tuple[GoldenCase, list[Target]]],
    loader: Loader,
    book: QueryBook,
    companies: Mapping[str, Company],
    figures: Mapping[str, CompanyFigures],
    transport: Transport,
    checker: Checker | None = None,
) -> GenerationRun:
    """Run every case through retrieval, the model (via ``transport``), the gate and the rule.

    A case whose model answer is missing (:class:`CassetteMiss`) is skipped and
    listed in ``pending``. An answer that cannot be parsed is kept as an empty
    draft with ``engine_error`` set (a run would fall back to the extractive
    engine; the evaluation scores the model, so it does not). With ``checker``
    each case's verified findings are read again (:func:`_check`); a case whose
    check answer is missing is skipped and listed in ``check_pending``. Raises
    ValueError when ``book`` has no entry for a case.
    """
    analyst = ClaudeAnalyst(transport=transport)
    materials = _Materials(loader)
    run = GenerationRun()
    for case, targets in cases:
        if case.id not in book:
            raise ValueError(f"the queries file has no entry for {case.id}; run plan again")
        request, claim = case_request(case)
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
        result = _gate(draft, offered, material, company_figures)
        run.gated[case.id] = result
        check: CheckOutcome | None = None
        if checker is not None:
            if result.findings:
                run.checks_asked += 1
            company = companies[case.ticker]
            try:
                check = _check(checker, request, company, claim, result, company_figures)
            except CassetteMiss:
                run.check_pending.append(case.id)
                continue
        spans = spans_for(case, targets)
        run.outcomes.append(
            _outcome(
                case,
                spans,
                queries,
                offered,
                ranked,
                result,
                company_figures,
                engine_error,
                check,
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
class MeaningSummary:
    """What the meaning check did to the findings and to verdict agreement.

    Findings are counted over every case; the agreement figures over the
    answerable cases: ``disagreed_before`` cases did not agree before the
    check, of which ``now_agree`` agree after it and ``still_disagree`` do not;
    ``broken`` cases agreed before the check and no longer do.
    """

    findings_verified: int
    findings_checked: int
    passed: int
    partly: int
    failed: int
    unchecked: int
    cases_check_failed: int
    agreement_before: Rate
    agreement_after: Rate
    disagreed_before: int
    now_agree: int
    still_disagree: int
    agreed_before: int
    broken: int

    def as_dict(self) -> dict[str, Any]:
        """The meaning-check scores for the JSON record."""
        record = asdict(self)
        record["agreement_before"] = self.agreement_before.as_dict()
        record["agreement_after"] = self.agreement_after.as_dict()
        return record


def summarize_meaning(outcomes: Sequence[CaseOutcome]) -> MeaningSummary | None:
    """The meaning-check scores, or None when the check did not run on these outcomes."""
    checked = [o for o in outcomes if o.check is not None]
    if not checked:
        return None
    answerable = [o for o in outcomes if o.answerable]
    judged = [o.check for o in checked if o.check is not None]
    disagreed = [o for o in answerable if not o.agrees]
    agreed = [o for o in answerable if o.agrees]
    return MeaningSummary(
        findings_verified=sum(o.findings_verified for o in outcomes),
        findings_checked=sum(len(c.judged) for c in judged),
        passed=sum(c.count(SupportVerdict.supported) for c in judged),
        partly=sum(c.count(SupportVerdict.partly) for c in judged),
        failed=sum(c.count(SupportVerdict.not_supported) for c in judged),
        unchecked=sum(o.findings_verified for o in checked if o.check and o.check.error),
        cases_check_failed=sum(1 for c in judged if c.error),
        agreement_before=_rate([o.agrees for o in answerable]),
        agreement_after=_rate([o.agrees_after_check for o in answerable]),
        disagreed_before=len(disagreed),
        now_agree=sum(1 for o in disagreed if o.agrees_after_check),
        still_disagree=sum(1 for o in disagreed if not o.agrees_after_check),
        agreed_before=len(agreed),
        broken=sum(1 for o in agreed if not o.agrees_after_check),
    )


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
    meaning: MeaningSummary | None = None

    def as_dict(self) -> dict[str, Any]:
        """The summary for the JSON record; the meaning check only when it ran."""
        record: dict[str, Any] = {
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
        if self.meaning is not None:
            record["meaning_check"] = self.meaning.as_dict()
        return record


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
        meaning=summarize_meaning(outcomes),
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
        "cases": [_case_record(outcome) for outcome in outcomes],
    }


def _case_record(outcome: CaseOutcome) -> dict[str, Any]:
    """One case for the JSON record; the meaning check's fields only when it ran."""
    record = {
        **asdict(outcome),
        "retrieval_hit": outcome.retrieval_hit,
        "agrees": outcome.agrees if outcome.answerable else None,
        "refused": outcome.refused if not outcome.answerable else None,
    }
    if outcome.check is None:
        del record["check"]
    else:
        record["agrees_after_check"] = outcome.agrees_after_check if outcome.answerable else None
    return record


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


def _check_cell(outcome: CaseOutcome) -> str:
    """ "mixed -> supported (2 supported, 0 partly, 1 failed)", or why the check did not run."""
    check = outcome.check
    if check is None:
        return "n/a"
    if check.error:
        return f"not checked ({check.error})"
    if not check.judged:
        return "nothing to check"
    counts = (
        f"{check.count(SupportVerdict.supported)} supported, "
        f"{check.count(SupportVerdict.partly)} partly, "
        f"{check.count(SupportVerdict.not_supported)} failed"
    )
    return f"{check.verdict_after} ({counts})"


def render_cases(outcomes: Sequence[CaseOutcome]) -> str:
    """The per-case Markdown table; a column for the meaning check when it ran."""
    checked = any(o.check is not None for o in outcomes)
    headings = [
        "Case",
        "Ticker",
        "Expected",
        "Obtained",
        "Must-retrieve passage",
        "Cited it",
        "Findings verified / withheld",
    ]
    if checked:
        headings.append("After the meaning check")
    lines = [_row(*headings), "|" + "---|" * len(headings)]
    for o in outcomes:
        cited = ("yes" if o.cited_right_passage else "no") if o.answerable else "n/a"
        obtained = o.verdict + (" (answer unusable)" if o.engine_error else "")
        cells: list[object] = [
            o.case_id,
            o.ticker,
            o.expected,
            obtained,
            _retrieval_cell(o),
            cited,
            f"{o.findings_verified} / {o.findings_withheld}",
        ]
        if checked:
            cells.append(_check_cell(o))
        lines.append(_row(*cells))
    return "\n".join(lines) + "\n"


def _meaning_section(meaning: MeaningSummary) -> list[str]:
    """The meaning check's counts and its effect on verdict agreement, each with a denominator."""
    m = meaning
    rows: list[tuple[str, str, str]] = [
        (
            "Findings checked",
            str(m.findings_checked),
            f"{m.findings_checked} / {m.findings_verified} verified",
        ),
        ("  supported (passed)", str(m.passed), f"{m.passed} / {m.findings_checked} checked"),
        ("  partly supported (kept)", str(m.partly), f"{m.partly} / {m.findings_checked} checked"),
        (
            "  not supported (failed, withheld)",
            str(m.failed),
            f"{m.failed} / {m.findings_checked} checked",
        ),
        (
            "Findings left unchecked (the check could not run)",
            str(m.unchecked),
            f"{m.unchecked} / {m.findings_verified} verified",
        ),
        (
            "Verdict agreement before the check",
            m.agreement_before.percent(),
            m.agreement_before.fraction(),
        ),
        (
            "Verdict agreement after the check",
            m.agreement_after.percent(),
            m.agreement_after.fraction(),
        ),
        (
            "Disagreeing cases that now agree",
            str(m.now_agree),
            f"{m.now_agree} / {m.disagreed_before} disagreeing before",
        ),
        (
            "Disagreeing cases that still disagree",
            str(m.still_disagree),
            f"{m.still_disagree} / {m.disagreed_before} disagreeing before",
        ),
        (
            "Agreeing cases the check broke",
            str(m.broken),
            f"{m.broken} / {m.agreed_before} agreeing before",
        ),
    ]
    lines = [
        "## The meaning check",
        "",
        "A second model read each verified finding's excerpts and cited figures, without the "
        "engine's rationale or confidence. A finding it judged not supported drops out of the "
        "verdict; one it judged partly supported is kept. Agreement is over the answerable cases.",
        "",
        "| Score | Value | Of |",
        "|---|---|---|",
    ]
    lines += [_row(name, value, whole) for name, value, whole in rows]
    return lines


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
    if summary.meaning is not None:
        lines.append(
            "The meaning check ran: a second model read every case's verified findings through "
            "the same cassette (step `check`), as a run would."
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
    meaning = [*_meaning_section(summary.meaning), ""] if summary.meaning is not None else []
    lines += [
        "",
        *_answerable_section(summary),
        "",
        *unanswerable,
        "",
        *_totals_section(summary.totals),
        "",
        *meaning,
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
    record: Mapping[str, Any],
    markdown: str,
    out_dir: Path,
    when: datetime,
    name: str = "generation",
) -> tuple[Path, Path]:
    """Write ``<name>-<UTC date>.json`` and ``.md`` under ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{name}-{when.strftime('%Y-%m-%d')}"
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
    check: bool = False,
) -> int:
    """Assess every case through ``cassette``; write the record only when nothing is pending.

    With ``check`` the meaning checker reads every case's verified findings
    through the same cassette. Returns 0 when written and 3 while assess or
    check requests are pending.
    """
    transport = CassetteTransport(cassette)
    checker = ClaudeChecker(transport=transport) if check else None
    run = evaluate_generation(cases, loader, book, companies, figures, transport, checker)
    if run.pending or run.check_pending:
        if run.pending:
            print(
                f"generate: {len(run.pending)} of {run.assessed} assess request(s) pending in "
                f"{cassette}/pending."
            )
        if run.check_pending:
            assess_keys = len(run.pending)
            saved = max(0, len(transport.pending_keys) - assess_keys)
            waiting = len(run.check_pending) - saved
            print(
                f"generate: {len(run.check_pending)} of {run.checks_asked} check request(s) "
                f"unanswered; {saved} saved in {cassette}/pending"
                + (f", {waiting} wait on earlier answers" if waiting > 0 else "")
                + "."
            )
        print("generate: answer them (docs/cassettes.md) and run again. Nothing was written.")
        return EXIT_PENDING
    when = now or datetime.now(UTC)
    record_inputs = {**inputs, "meaning_check": checker.name} if checker else inputs
    record = build_record(
        run.outcomes,
        models=transport.detail,
        inputs=record_inputs,
        figures={ticker: f.note for ticker, f in figures.items()},
        generated_at=when,
    )
    markdown = render_markdown(record, run.outcomes)
    name = "generation-checked" if checker is not None else "generation"
    json_path, md_path = write_record(record, markdown, out_dir, when, name)
    print(markdown)
    print(f"generate: all {run.assessed} assess request(s) answered")
    if checker is not None:
        print(f"generate: all {run.checks_asked} check request(s) answered")
    print(f"generate: wrote {json_path} and {md_path}")
    return 0
