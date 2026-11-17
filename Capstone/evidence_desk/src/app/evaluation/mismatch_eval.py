"""Planted mismatches: would the meaning check reject quotes that do not support the statement?

The meaning check (:class:`app.engines.checker.ClaudeChecker`) reads each
verified finding's statement, stance, excerpts and cited figures and judges
whether the evidence supports the statement. On the golden set it has only ever
been shown true pairs. This evaluation shows it false ones, on purpose:

1. The golden generation run is replayed exactly as ``generate --check`` runs
   it (:func:`app.evaluation.generation_eval.evaluate_generation`), from a
   cassette opened read-only, so nothing is ever written to it. Its verified
   findings, as the meaning check is shown them
   (:func:`~app.evaluation.generation_eval.verified_check_items`), and the
   golden check's judgement of each, are the material.
2. From every finding with at least one verified quote, mismatches are built
   by keeping its statement and stance (and its claim) and replacing its
   excerpts with those of another verified finding (:data:`DONOR_RULE`):
   ``other-company`` takes them from a case about a different company,
   ``other-claim`` from a different case about the same company. Cited figures
   are dropped from a mismatched item, so the judgement rests on the swapped
   quotes alone.
3. The mismatched items go to the production checker and prompt builder
   through a :class:`~app.engines.cassette.CassetteTransport` on their own
   cassette, one request per (case, kind), as a run sends one per claim.
4. Per kind: how many mismatches were judged not supported (caught), partly,
   supported (missed) or not at all, each over the mismatches built; beside
   them the same counts for the same findings with their own quotes, from the
   golden check.

Nothing here judges a finding itself.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.meaning import IncompleteJudgements, by_index
from app.core.models import Claim, Company, ThesisRequest
from app.core.ports import Checker, CheckItem, SupportVerdict
from app.engines.cassette import CassetteMiss, CassetteTransport
from app.engines.checker import ClaudeChecker
from app.engines.transport import EngineError
from app.evaluation.companies import CompanyFigures
from app.evaluation.generation_eval import (
    GenerationRun,
    case_request,
    evaluate_generation,
    verified_check_items,
    write_record,
)
from app.evaluation.golden import GoldenCase, Target
from app.evaluation.planning import EXIT_PENDING
from app.evaluation.retrieval_eval import Loader, QueryBook

__all__ = [
    "DONOR_RULE",
    "KINDS",
    "OTHER_CLAIM",
    "OTHER_COMPANY",
    "CaseContext",
    "Construction",
    "Counts",
    "Judged",
    "KindSummary",
    "Mismatch",
    "MismatchRun",
    "Skip",
    "SourceFinding",
    "ask_checker",
    "build_mismatches",
    "build_record",
    "render_markdown",
    "run_mismatch",
    "shares_a_quote",
    "source_findings",
    "summarize_mismatch",
]

OTHER_COMPANY = "other-company"
OTHER_CLAIM = "other-claim"
KINDS: tuple[str, ...] = (OTHER_COMPANY, OTHER_CLAIM)
KIND_MEANING = {
    OTHER_COMPANY: "the quotes of a verified finding of a case about a different company",
    OTHER_CLAIM: "the quotes of a verified finding of a different case about the same company",
}
SKIP_NO_DONOR = "no other case of the kind has a verified finding with a quote"
SKIP_SHARED_QUOTE = "every candidate donor shares a quote with the finding"
QUOTE_SHOWN_CHARS = 160
ELLIPSIS = "…"

DONOR_RULE = (
    "The verified findings with at least one quote are sorted by (case id, position of the "
    "finding in its case). For the finding at place k of that order, the candidate donors of a "
    "kind are the findings, in the same order, of every case about a different company "
    "(other-company) or of every other case about the same company (other-claim). The donor is "
    "the first candidate, starting at place k modulo the number of candidates and wrapping "
    "round, that shares no quote with the finding: no whitespace-normalised quote of one equals, "
    "contains or is contained in a quote of the other. A finding with no candidate, or whose "
    "every candidate shares a quote, is skipped and counted. No randomness and no seed."
)
FIGURES_NOTE = (
    "Cited figures are dropped from every mismatched item, so its judgement rests on the "
    "swapped quotes alone; the true pairs were judged with their figures."
)
SHOWS = (
    "Whether the meaning check, shown a verified finding's own statement and stance with real, "
    "verified quotes that belong to another finding, judges the pair not supported; beside it, "
    "how the same check judged the same statements with their own quotes."
)
DOES_NOT_SHOW: tuple[str, ...] = (
    "Swapped quotes are an easy kind of mismatch: they are usually about another topic, and "
    "for other-company about another business, whose name or products may appear in them. "
    "Catching them says little about the hard case, a quote on the right topic that supports "
    "only a weaker or a different statement.",
    "The answers come from whoever answered the cassette, named above from its envelopes "
    "(`via`, `model`). An answer written by a stand-in is not the model a run calls, and a "
    "stand-in that knows it is reading planted mismatches is not a blind reader.",
    "Each request holds only mismatched items (one case, one kind), whereas a run shows the "
    "checker a claim's findings together, most of them true; a reader may judge a batch of "
    "mismatches differently from one mismatch among true pairs.",
    "One recording per request: no variance across samples, and no test of the live API.",
    FIGURES_NOTE,
)


# Material: the golden run's verified findings


@dataclass(frozen=True)
class SourceFinding:
    """One verified finding of the golden generation run, as the meaning check is shown it.

    ``index`` is its position among its case's verified findings; ``true_verdict``
    is the golden check's judgement of it with its own quotes ("" when unjudged).
    """

    case_id: str
    ticker: str
    index: int
    item: CheckItem
    true_verdict: str = ""

    @property
    def key(self) -> tuple[str, int]:
        """(case id, index): the finding's place in the sorted order."""
        return (self.case_id, self.index)


@dataclass(frozen=True)
class CaseContext:
    """What a check request about one case names: the run's request, company and claim."""

    request: ThesisRequest
    company: Company
    claim: Claim


def source_findings(
    cases: Sequence[GoldenCase], run: GenerationRun, figures: Mapping[str, CompanyFigures]
) -> list[SourceFinding]:
    """Every verified finding of ``run``, in case order, with the golden check's judgement."""
    outcomes = {outcome.case_id: outcome for outcome in run.outcomes}
    found: list[SourceFinding] = []
    for case in cases:
        result = run.gated.get(case.id)
        if result is None:
            continue
        items = verified_check_items(result, figures.get(case.ticker, CompanyFigures()))
        outcome = outcomes.get(case.id)
        check = outcome.check if outcome is not None else None
        judged = check.judged if check is not None and not check.error else ()
        found += [
            SourceFinding(
                case_id=case.id,
                ticker=case.ticker,
                index=index,
                item=item,
                true_verdict=judged[index] if index < len(judged) else "",
            )
            for index, item in enumerate(items)
        ]
    return found


def case_contexts(
    cases: Sequence[GoldenCase], companies: Mapping[str, Company]
) -> dict[str, CaseContext]:
    """Each case's request, company and claim, as :func:`case_request` builds them for a run."""
    contexts: dict[str, CaseContext] = {}
    for case in cases:
        request, claim = case_request(case)
        contexts[case.id] = CaseContext(request, companies[case.ticker], claim)
    return contexts


# Construction


@dataclass(frozen=True)
class Mismatch:
    """A finding's statement and stance with another finding's quotes, and no figures."""

    kind: str
    recipient: SourceFinding
    donor: SourceFinding
    item: CheckItem

    @property
    def figures_dropped(self) -> int:
        """How many cited figures the recipient had, all left out of ``item``."""
        return len(self.recipient.item.figures)


@dataclass(frozen=True)
class Skip:
    """A finding that got no mismatch of ``kind``, and why."""

    kind: str
    case_id: str
    index: int
    reason: str


@dataclass
class Construction:
    """The mismatches built from a pool of findings, and every finding skipped.

    ``eligible`` are the findings with at least one quote, sorted;
    ``without_quotes`` counts those left out for having none.
    """

    eligible: list[SourceFinding]
    without_quotes: int
    mismatches: list[Mismatch] = field(default_factory=list)
    skips: list[Skip] = field(default_factory=list)

    def built(self, kind: str) -> list[Mismatch]:
        """The mismatches of ``kind``, in order."""
        return [m for m in self.mismatches if m.kind == kind]

    def skipped(self, kind: str) -> list[Skip]:
        """The findings skipped for ``kind``, in order."""
        return [s for s in self.skips if s.kind == kind]


def _normalized(text: str) -> str:
    return " ".join(text.split())


def shares_a_quote(first: CheckItem, second: CheckItem) -> bool:
    """True when a quote of one equals, holds or is held by a quote of the other (spaces collapsed).

    Such a pair is never a mismatch: the swapped evidence would still hold the finding's own quote.
    """
    ours = [_normalized(excerpt.text) for excerpt in first.excerpts]
    theirs = [_normalized(excerpt.text) for excerpt in second.excerpts]
    return any(a in b or b in a for a in ours for b in theirs)


def _may_donate(kind: str, recipient: SourceFinding, donor: SourceFinding) -> bool:
    if donor.case_id == recipient.case_id:
        return False
    if kind == OTHER_COMPANY:
        return donor.ticker != recipient.ticker
    return donor.ticker == recipient.ticker


def build_mismatches(findings: Sequence[SourceFinding]) -> Construction:
    """Every mismatch of every kind under :data:`DONOR_RULE`; the same for any input order.

    Raises ValueError when two findings share a (case id, index).
    """
    keys = Counter(finding.key for finding in findings)
    repeated = sorted(key for key, count in keys.items() if count > 1)
    if repeated:
        raise ValueError(f"findings repeat a (case, index): {repeated[0]}")
    eligible = sorted((f for f in findings if f.item.excerpts), key=lambda f: f.key)
    construction = Construction(eligible=eligible, without_quotes=len(findings) - len(eligible))
    for kind in KINDS:
        for place, recipient in enumerate(eligible):
            candidates = [d for d in eligible if _may_donate(kind, recipient, d)]
            count = len(candidates)
            rotation = [candidates[(place + step) % count] for step in range(count)]
            donor = next((d for d in rotation if not shares_a_quote(recipient.item, d.item)), None)
            if donor is None:
                reason = SKIP_SHARED_QUOTE if candidates else SKIP_NO_DONOR
                construction.skips.append(Skip(kind, recipient.case_id, recipient.index, reason))
                continue
            item = replace(recipient.item, excerpts=donor.item.excerpts, figures=())
            construction.mismatches.append(Mismatch(kind, recipient, donor, item))
    return construction


# The checker


@dataclass(frozen=True)
class Judged:
    """The checker's judgement of one mismatch: a verdict and its reason, or why there is none.

    ``verdict`` is "" when nothing was judged: the request is ``pending`` (no
    answer recorded yet) or the answer was unusable (``error``).
    """

    mismatch: Mismatch
    verdict: str
    reason: str
    error: str = ""
    pending: bool = False


@dataclass
class MismatchRun:
    """Every mismatch's judgement, and how many requests were made and are still pending."""

    judged: list[Judged] = field(default_factory=list)
    batches: int = 0
    pending_batches: int = 0


def _batches(mismatches: Sequence[Mismatch]) -> dict[tuple[str, str], list[Mismatch]]:
    """The mismatches grouped by (case, kind), in the order they first appear."""
    groups: dict[tuple[str, str], list[Mismatch]] = {}
    for mismatch in mismatches:
        groups.setdefault((mismatch.recipient.case_id, mismatch.kind), []).append(mismatch)
    return groups


def ask_checker(
    construction: Construction, contexts: Mapping[str, CaseContext], checker: Checker
) -> MismatchRun:
    """Put each (case, kind) batch of mismatched items to ``checker``, as a run puts a claim's.

    A missing answer (:class:`CassetteMiss`) leaves the batch pending; an
    unusable one (:class:`EngineError`, :class:`IncompleteJudgements`) leaves it
    unjudged with the error, as a run leaves a claim unchecked.
    """
    run = MismatchRun()
    for (case_id, _kind), members in _batches(construction.mismatches).items():
        context = contexts[case_id]
        items = [mismatch.item for mismatch in members]
        run.batches += 1
        try:
            judgements = checker.check(context.request, context.company, context.claim, items)
            keyed = by_index(judgements, len(items))
        except CassetteMiss as exc:
            run.pending_batches += 1
            run.judged += [Judged(m, "", "", error=str(exc), pending=True) for m in members]
            continue
        except (EngineError, IncompleteJudgements) as exc:
            run.judged += [Judged(m, "", "", error=str(exc)) for m in members]
            continue
        run.judged += [
            Judged(m, keyed[n].verdict.value, keyed[n].reason) for n, m in enumerate(members)
        ]
    return run


# Scores


@dataclass(frozen=True)
class Counts:
    """How many of ``total`` pairs were judged each way; ``unjudged`` got no judgement."""

    total: int
    not_supported: int
    partly: int
    supported: int
    unjudged: int

    @classmethod
    def of(cls, verdicts: Sequence[str]) -> Counts:
        """The counts over ``verdicts`` ("" for no judgement)."""
        tally = Counter(verdicts)
        judged = {verdict.value: tally[verdict.value] for verdict in SupportVerdict}
        return cls(
            total=len(verdicts),
            not_supported=judged[SupportVerdict.not_supported.value],
            partly=judged[SupportVerdict.partly.value],
            supported=judged[SupportVerdict.supported.value],
            unjudged=len(verdicts) - sum(judged.values()),
        )


@dataclass(frozen=True)
class KindSummary:
    """One kind's mismatches and, for the same findings, the true pairs."""

    kind: str
    mismatched: Counts
    true_pairs: Counts
    skipped: int
    skip_reasons: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        """The summary for the JSON record."""
        return asdict(self)


def summarize_mismatch(construction: Construction, judged: Sequence[Judged]) -> list[KindSummary]:
    """Per kind, the counts of the mismatches and of the same findings' true pairs.

    Every count is over the mismatches built for the kind: a mismatch with no
    entry in ``judged`` counts as unjudged.
    """
    verdicts = {(j.mismatch.kind, j.mismatch.recipient.key): j.verdict for j in judged}
    summaries: list[KindSummary] = []
    for kind in KINDS:
        built = construction.built(kind)
        skipped = construction.skipped(kind)
        summaries.append(
            KindSummary(
                kind=kind,
                mismatched=Counts.of([verdicts.get((kind, m.recipient.key), "") for m in built]),
                true_pairs=Counts.of([m.recipient.true_verdict for m in built]),
                skipped=len(skipped),
                skip_reasons=dict(sorted(Counter(s.reason for s in skipped).items())),
            )
        )
    return summaries


# The record


def _quotes(item: CheckItem) -> list[str]:
    return [excerpt.text for excerpt in item.excerpts]


def _judged_record(judged: Judged) -> dict[str, Any]:
    m = judged.mismatch
    return {
        "kind": m.kind,
        "case_id": m.recipient.case_id,
        "ticker": m.recipient.ticker,
        "finding_index": m.recipient.index,
        "statement": m.item.statement,
        "stance": m.item.stance.value,
        "donor_case_id": m.donor.case_id,
        "donor_ticker": m.donor.ticker,
        "donor_finding_index": m.donor.index,
        "swapped_quotes": _quotes(m.item),
        "own_quotes": _quotes(m.recipient.item),
        "figures_dropped": m.figures_dropped,
        "verdict": judged.verdict or None,
        "reason": judged.reason,
        "error": judged.error,
        "true_verdict": m.recipient.true_verdict or None,
    }


def build_record(
    construction: Construction,
    judged: Sequence[Judged],
    *,
    models: Mapping[str, str],
    checker: str,
    inputs: Mapping[str, Any],
    generated_at: datetime,
) -> dict[str, Any]:
    """The JSON record: who answered, the rule, the counts per kind, every mismatch and skip."""
    return {
        "kind": "meaning-check-mismatch-evaluation",
        "generated_at": generated_at.isoformat(),
        "models": dict(models),
        "checker": checker,
        "donor_rule": DONOR_RULE,
        "kinds": dict(KIND_MEANING),
        "figures_note": FIGURES_NOTE,
        "shows": SHOWS,
        "does_not_show": list(DOES_NOT_SHOW),
        "inputs": dict(inputs),
        "construction": {
            "findings_verified": len(construction.eligible) + construction.without_quotes,
            "findings_with_a_quote": len(construction.eligible),
            "findings_without_quotes": construction.without_quotes,
            "mismatches": {kind: len(construction.built(kind)) for kind in KINDS},
            "skipped": {kind: len(construction.skipped(kind)) for kind in KINDS},
            "figures_dropped": sum(m.figures_dropped for m in construction.mismatches),
        },
        "summary": {
            "kinds": [summary.as_dict() for summary in summarize_mismatch(construction, judged)],
            "true_pairs_all": asdict(Counts.of([f.true_verdict for f in construction.eligible])),
        },
        "mismatches": [_judged_record(entry) for entry in judged],
        "skips": [asdict(skip) for skip in construction.skips],
    }


def _cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def _row(*cells: object) -> str:
    return "| " + " | ".join(_cell(cell) for cell in cells) + " |"


def _shown(text: str) -> str:
    """The first :data:`QUOTE_SHOWN_CHARS` characters of ``text``, whitespace collapsed."""
    flat = _normalized(text)
    return flat if len(flat) <= QUOTE_SHOWN_CHARS else flat[:QUOTE_SHOWN_CHARS] + ELLIPSIS


def _counts_row(name: str, counts: Counts, skipped: str) -> str:
    whole = counts.total
    return _row(
        name,
        whole,
        f"{counts.not_supported} / {whole}",
        f"{counts.partly} / {whole}",
        f"{counts.supported} / {whole}",
        f"{counts.unjudged} / {whole}",
        skipped,
    )


def _listing(title: str, entries: Sequence[Judged]) -> list[str]:
    """A section listing ``entries``: case, statement, swapped quote, donor, reason."""
    lines = [f"## {title} ({len(entries)})", ""]
    if not entries:
        return [*lines, "None."]
    lines += [
        _row(
            "Kind",
            "Case",
            "Finding",
            "Statement",
            "Swapped quote (first 160 characters)",
            "From",
            "Checker's reason",
        ),
        "|---|---|---|---|---|---|---|",
    ]
    for entry in entries:
        m = entry.mismatch
        first = m.item.excerpts[0].text if m.item.excerpts else ""
        lines.append(
            _row(
                m.kind,
                m.recipient.case_id,
                m.recipient.index + 1,
                m.item.statement,
                _shown(first),
                f"{m.donor.case_id} #{m.donor.index + 1}",
                entry.reason or entry.error,
            )
        )
    return lines


def render_markdown(
    record: Mapping[str, Any], construction: Construction, judged: Sequence[Judged]
) -> str:
    """The report: who answered, the rule, both halves of the table, every miss and partly."""
    models = record.get("models", {})
    summaries = summarize_mismatch(construction, judged)
    lines = [
        "# Planted mismatches: the meaning check",
        "",
        f"Mismatch answers: {models.get('mismatch', 'unknown')}.",
        f"Findings and true-pair judgements: {models.get('findings', 'unknown')}.",
        "",
        f"Generated {record.get('generated_at', '')}. {SHOWS}",
        "",
        "## How the mismatches were built",
        "",
        f"{len(construction.eligible)} verified findings with at least one quote "
        f"({construction.without_quotes} without a quote were left out). Each keeps its claim, "
        "statement and stance; its quotes are replaced by:",
        "",
    ]
    lines += [f"- `{kind}`: {meaning}." for kind, meaning in KIND_MEANING.items()]
    lines += ["", DONOR_RULE, "", FIGURES_NOTE, "", "## Results", ""]
    lines += [
        "Each count is over the pairs in its row: the mismatches of a kind, then the same "
        "findings with their own quotes as the golden check judged them.",
        "",
        _row(
            "Pairs",
            "Count",
            "Not supported (caught)",
            "Partly",
            "Supported (missed)",
            "No judgement",
            "Skipped",
        ),
        "|---|---|---|---|---|---|---|",
    ]
    for summary in summaries:
        skipped = f"{summary.skipped} / {summary.skipped + summary.mismatched.total}"
        lines.append(_counts_row(f"{summary.kind}: swapped quotes", summary.mismatched, skipped))
        lines.append(_counts_row(f"{summary.kind}: own quotes", summary.true_pairs, ""))
    every = Counts.of([finding.true_verdict for finding in construction.eligible])
    lines.append(_counts_row("every finding with a quote: own quotes", every, ""))
    reasons = [
        f"- `{s.kind}`: {count} skipped, {reason}."
        for s in summaries
        for reason, count in s.skip_reasons.items()
    ]
    if reasons:
        lines += ["", *reasons]
    by_verdict = {
        verdict: [j for j in judged if j.verdict == verdict.value] for verdict in SupportVerdict
    }
    unjudged = [j for j in judged if not j.verdict]
    lines += [
        "",
        *_listing("Missed: swapped quotes judged supported", by_verdict[SupportVerdict.supported]),
        "",
        *_listing(
            "Partly: swapped quotes judged partly supported", by_verdict[SupportVerdict.partly]
        ),
        "",
        *_listing("No judgement", unjudged),
        "",
        "## What it does not show",
        "",
        *(f"- {line}" for line in DOES_NOT_SHOW),
        "",
    ]
    return "\n".join(lines)


# The command


def run_mismatch(
    cases: Sequence[tuple[GoldenCase, list[Target]]],
    loader: Loader,
    book: QueryBook,
    companies: Mapping[str, Company],
    figures: Mapping[str, CompanyFigures],
    *,
    findings_cassette: Path,
    cassette: Path,
    out_dir: Path,
    inputs: Mapping[str, Any],
    now: datetime | None = None,
) -> int:
    """Build the mismatches from the golden run and put them to the checker through ``cassette``.

    ``findings_cassette`` is replayed read-only; when it does not answer every
    assess and check request of the golden run nothing is asked and 1 is
    returned. Returns 3 while mismatch requests are pending (nothing written),
    0 once ``mismatch-<date>.json`` and ``.md`` are written under ``out_dir``.
    """
    golden_transport = CassetteTransport(findings_cassette, read_only=True)
    golden_cases = [case for case, _ in cases]
    golden = evaluate_generation(
        cases,
        loader,
        book,
        companies,
        figures,
        golden_transport,
        ClaudeChecker(transport=golden_transport),
    )
    if golden.pending or golden.check_pending:
        print(
            f"mismatch: the findings cassette {findings_cassette} does not answer "
            f"{len(golden.pending)} assess and {len(golden.check_pending)} check request(s) of "
            "the golden run; run generate --check on it first. Nothing was saved or written."
        )
        return 1
    construction = build_mismatches(source_findings(golden_cases, golden, figures))
    print(
        f"mismatch: {len(construction.eligible)} verified finding(s) with a quote "
        f"({construction.without_quotes} without); "
        + "; ".join(
            f"{kind}: {len(construction.built(kind))} built, "
            f"{len(construction.skipped(kind))} skipped"
            for kind in KINDS
        )
    )
    transport = CassetteTransport(cassette)
    checker = ClaudeChecker(transport=transport)
    run = ask_checker(construction, case_contexts(golden_cases, companies), checker)
    if run.pending_batches:
        print(
            f"mismatch: {run.pending_batches} of {run.batches} check request(s) pending; "
            f"{len(set(transport.pending_keys))} saved in {cassette}/pending."
        )
        print("mismatch: answer them (docs/cassettes.md) and run again. Nothing was written.")
        return EXIT_PENDING
    when = now or datetime.now(UTC)
    record = build_record(
        construction,
        run.judged,
        models={"mismatch": transport.detail, "findings": golden_transport.detail},
        checker=checker.name,
        inputs=inputs,
        generated_at=when,
    )
    markdown = render_markdown(record, construction, run.judged)
    json_path, md_path = write_record(record, markdown, out_dir, when, "mismatch")
    print(markdown)
    print(f"mismatch: all {run.batches} check request(s) answered")
    print(f"mismatch: wrote {json_path} and {md_path}")
    return 0
