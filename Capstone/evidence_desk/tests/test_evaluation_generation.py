"""The plan and generate commands of the evaluation, and the generation scores.

Offline: model answers come from a scripted transport or a cassette in a temporary
directory, filings from small synthetic documents or the recorded NVIDIA fixtures.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core import limits
from app.core.models import Company
from app.core.periods import FiscalCalendar
from app.engines.cassette import Cassette, CassetteMiss
from app.engines.checker import ClaudeChecker
from app.engines.transport import ModelRequest
from app.evaluation.cli import normalize_argv
from app.evaluation.companies import (
    FACTS_FIXTURES,
    company_for,
    figures_for,
    pin_companies,
    read_facts,
)
from app.evaluation.corpus import (
    Corpus,
    CorpusError,
    PinnedFacts,
    load_facts_pins,
    load_pins,
    save_pins,
)
from app.evaluation.generation_eval import (
    CompanyFigures,
    build_record,
    evaluate_generation,
    render_markdown,
    run_generation,
    summarize_generation,
)
from app.evaluation.golden import GOLDEN_PATH, GoldenCase, Target, validate_golden
from app.evaluation.planning import DECISION, group_cases, run_plan
from app.evaluation.retrieval_eval import read_queries
from tests.fakes import NVIDIA
from tests.test_evaluation import (
    ACCESSION,
    MDA_TEXT,
    RISK_TEXT,
    TICKER,
    golden,
    loader_for,
    synthetic_document,
)

COMPANY = Company(cik=99, ticker=TICKER, name="Test Corp")
STATED_NUMBER = "The company relies on suppliers for $4.5 billion of products."


# Helpers: synthetic cases, scripted answers, a cassette answered in place


def raw_case(case_id: str, claim: str, *, expected: str = "none", target: str = "") -> dict:
    """An answerable case when ``target`` names an excerpt, otherwise an unanswerable one."""
    record: dict[str, Any] = {
        "id": case_id,
        "ticker": TICKER,
        "filings": [ACCESSION],
        "claim": claim,
        "kind": "answerable" if target else "unanswerable",
        "expected": expected if target else "none",
        "must_retrieve": (
            [
                {
                    "accession": ACCESSION,
                    "section": "Item 1A" if target == RISK_TEXT else "Item 7",
                    # Up to 120 characters, cut after a whole word as a quote must be.
                    "text": target[:121].rsplit(" ", 1)[0],
                }
            ]
            if target
            else []
        ),
        "why": "A synthetic case for the generation tests.",
    }
    return record


def checked(*raw: dict) -> list[tuple[GoldenCase, list[Target]]]:
    """Validate synthetic cases against the synthetic filing; fail loudly if one is invalid."""
    result = validate_golden(golden(*raw), loader_for({ACCESSION: synthetic_document()}))
    assert result.ok, [(c.case_id, c.problems) for c in result.checks if not c.ok]
    return result.cases()


def passage_holding(user: str, needle: str) -> str:
    """The id of the offered passage whose text contains ``needle``."""
    for match in re.finditer(r'<passage id="([^"]+)"[^>]*>(.*?)</passage>', user, re.DOTALL):
        if needle[:40] in match.group(2):
            return match.group(1)
    raise AssertionError(f"no offered passage holds {needle[:40]!r}")


def claim_of(user: str) -> str:
    match = re.search(r"<claim>(.*?)</claim>", user, re.DOTALL)
    assert match is not None
    return match.group(1)


def finding(statement: str, stance: str, quotes: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "statement": statement,
        "stance": stance,
        "confidence": "medium",
        "rationale": "scripted",
        "quotes": quotes,
        "figure_ids": [],
    }


Script = Callable[[str], list[dict[str, Any]]]


def scripted(answers: dict[str, Script]) -> Callable[[ModelRequest], dict[str, Any]]:
    """A transport answering each assess request by claim text; an unknown claim is a miss."""

    def transport(request: ModelRequest) -> dict[str, Any]:
        assert request.step == "assess"
        script = answers.get(claim_of(request.user))
        if script is None:
            raise CassetteMiss("no scripted answer")
        return {"findings": script(request.user), "rationale": "scripted", "unknowns": []}

    return transport


def quote(user: str, text: str) -> dict[str, str]:
    return {"passage_id": passage_holding(user, text), "text": text}


# The synthetic golden set: one case per behaviour the scores must get right.

SUPPLIER_QUERIES = ["contract manufacturers Asia", "supplier disruption shipments"]
SALES_QUERIES = ["services segment unit volumes", "favourable pricing"]

CASES = [
    # (id, claim, expected, must-retrieve, queries, answer)
    (
        "supports-right",
        "The firm leans on a few outsourced plants abroad.",
        "supports",
        RISK_TEXT,
        SUPPLIER_QUERIES,
        lambda u: [finding("It depends on manufacturers.", "supports", [quote(u, RISK_TEXT)])],
    ),
    (
        "challenges-read-as-support",
        "The firm has no exposure to outside factories.",
        "challenges",
        RISK_TEXT,
        SUPPLIER_QUERIES,
        lambda u: [finding("It depends on manufacturers.", "supports", [quote(u, RISK_TEXT)])],
    ),
    (
        "mixed-unanswered",
        "Outsourcing both helps and hurts the firm.",
        "mixed",
        RISK_TEXT,
        SUPPLIER_QUERIES,
        lambda u: [],
    ),
    (
        "retrieval-miss",
        "Sales rose on stronger services volumes.",
        "supports",
        RISK_TEXT,  # the must-retrieve passage is the risk factor, which these queries miss
        SALES_QUERIES,
        lambda u: [finding("Revenue rose.", "supports", [quote(u, MDA_TEXT)])],
    ),
    (
        "withheld-right-passage",
        "Plants overseas make most of the products.",
        "supports",
        RISK_TEXT,
        SUPPLIER_QUERIES,
        lambda u: [finding(STATED_NUMBER, "supports", [quote(u, RISK_TEXT)])],
    ),
    (
        "unanswerable-context",
        "The firm plans to open a bank in orbit.",
        "none",
        "",
        SUPPLIER_QUERIES,
        lambda u: [finding("Suppliers are in Asia.", "context", [quote(u, RISK_TEXT)])],
    ),
    (
        "unanswerable-withheld",
        "The firm will be sold to a rival next year.",
        "none",
        "",
        SUPPLIER_QUERIES,
        lambda u: [
            finding(
                "Suppliers are in Asia.",
                "supports",
                [{"passage_id": passage_holding(u, RISK_TEXT), "text": "Words not in the filing."}],
            )
        ],
    ),
]


def synthetic_cases() -> list[tuple[GoldenCase, list[Target]]]:
    return checked(
        *(raw_case(cid, claim, expected=exp, target=t) for cid, claim, exp, t, _, _ in CASES)
    )


def synthetic_book() -> dict[str, list[str]]:
    return {cid: list(queries) for cid, _, _, _, queries, _ in CASES}


def synthetic_answers() -> dict[str, Script]:
    return {claim: answer for _, claim, _, _, _, answer in CASES}


LOADER = loader_for({ACCESSION: synthetic_document()})
NO_FIGURES = {TICKER: CompanyFigures([], "no figures in this test")}


@pytest.fixture(scope="module")
def scored() -> list:
    run = evaluate_generation(
        synthetic_cases(),
        LOADER,
        synthetic_book(),
        {TICKER: COMPANY},
        NO_FIGURES,
        scripted(synthetic_answers()),
    )
    assert run.pending == []
    return run.outcomes


def by_id(outcomes: list) -> dict[str, Any]:
    return {outcome.case_id: outcome for outcome in outcomes}


# Grouping the plan requests


def plan_case(number: int, ticker: str) -> GoldenCase:
    return GoldenCase(
        id=f"case-{number}",
        ticker=ticker,
        filings=[ACCESSION],
        claim=f"Claim number {number} about the business of {ticker}.",
        kind="unanswerable",
        expected="none",
        why="A synthetic case for grouping.",
    )


def test_cases_are_grouped_by_ticker_in_file_order_at_most_six_per_request() -> None:
    tickers = ["AAA", "BBB", "AAA", "AAA", "AAA", "AAA", "BBB", "AAA", "AAA", "AAA"]
    cases = [plan_case(n, ticker) for n, ticker in enumerate(tickers, start=1)]
    groups = group_cases(cases)
    assert limits.MAX_CLAIMS == 6
    assert [(g.ticker, list(g.case_ids)) for g in groups] == [
        ("AAA", ["case-1", "case-3", "case-4", "case-5", "case-6", "case-8"]),
        ("AAA", ["case-9", "case-10"]),
        ("BBB", ["case-2", "case-7"]),
    ]
    request = groups[0].request()
    assert request.ticker == "AAA" and request.decision == DECISION
    assert request.claims == [case.claim for case in cases if case.id in groups[0].case_ids]


# The plan command


def answer_pending(cassette: Path, respond: Callable[[dict[str, Any]], dict[str, Any]]) -> int:
    """Answer every pending request in ``cassette`` with ``respond``; return how many."""
    pending = Cassette(cassette).pending()
    for path in pending:
        request = json.loads(path.read_text())
        envelope = {
            "key": request["key"],
            "step": request["step"],
            "via": "a test script",
            "model": "none",
            "recorded_at": "2026-11-17T00:00:00+00:00",
            "response": respond(request),
        }
        (cassette / "responses").mkdir(parents=True, exist_ok=True)
        (cassette / "responses" / path.name).write_text(json.dumps(envelope))
    return len(pending)


def plan_answer(request: dict[str, Any]) -> dict[str, Any]:
    numbers = [int(n) for n in re.findall(r'<claim number="(\d+)">', request["user"])]
    return {"claims": [{"claim_number": n, "queries": [f"q{n} one", f"q{n} two"]} for n in numbers]}


def test_plan_exits_3_without_output_until_answered_then_writes_the_queries_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cases = [case for case, _ in synthetic_cases()]
    cassette, out = tmp_path / "cassette", tmp_path / "queries.json"
    inputs = {"golden_sha256": "f" * 64}
    assert run_plan(cases, {TICKER: COMPANY}, cassette, out, inputs=inputs) == 3
    assert not out.exists()
    printed = capsys.readouterr().out
    assert "2 of 2 plan request(s) pending" in printed  # 7 cases: six, then one
    pending = Cassette(cassette).pending()
    assert len(pending) == 2
    first = json.loads(pending[0].read_text())
    assert first["step"] == "plan" and f'cik="{COMPANY.cik}"' in first["user"]

    assert answer_pending(cassette, plan_answer) == 2
    assert run_plan(cases, {TICKER: COMPANY}, cassette, out, inputs=inputs) == 0
    payload = json.loads(out.read_text())
    assert set(payload) == {"provenance", "queries"}
    assert list(payload["queries"]) == [case.id for case in cases]
    assert payload["queries"][cases[6].id] == ["q1 one", "q1 two"]  # first of the second request
    provenance = payload["provenance"]
    assert provenance["golden_sha256"] == "f" * 64
    assert provenance["decision"] == DECISION
    assert "2 responses recorded via a test script" in provenance["cassette_description"]
    assert {r["key"] for r in provenance["requests"]} == {path.stem for path in pending}
    assert [len(r["case_ids"]) for r in provenance["requests"]] == [6, 1]
    assert read_queries(out, {case.id for case in cases}) == payload["queries"]


def test_a_malformed_plan_answer_fails_the_plan_without_output(tmp_path: Path) -> None:
    cases = [case for case, _ in synthetic_cases()][:2]
    cassette, out = tmp_path / "cassette", tmp_path / "queries.json"
    assert run_plan(cases, {TICKER: COMPANY}, cassette, out, inputs={}) == 3
    answer_pending(cassette, lambda request: {"claims": []})  # no queries for either claim
    assert run_plan(cases, {TICKER: COMPANY}, cassette, out, inputs={}) == 1
    assert not out.exists()


def test_the_nvidia_plan_requests_name_the_company_and_split_ten_claims_six_and_four(
    tmp_path: Path,
) -> None:
    raw = json.loads(GOLDEN_PATH.read_text())
    nvidia = [GoldenCase.model_validate(c) for c in raw["cases"] if c["ticker"] == "NVDA"]
    assert [len(g.case_ids) for g in group_cases(nvidia)] == [6, 4]
    cassette = tmp_path / "cassette"
    assert run_plan(nvidia, {"NVDA": NVIDIA}, cassette, tmp_path / "q.json", inputs={}) == 3
    users = [json.loads(p.read_text())["user"] for p in Cassette(cassette).pending()]
    assert len(users) == 2
    assert all('cik="1045810"' in user and DECISION in user for user in users)
    assert sorted(user.count("<claim number=") for user in users) == [4, 6]


# The generate command: pending requests


def test_generate_exits_3_and_writes_nothing_while_answers_are_pending(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cassette, out = tmp_path / "cassette", tmp_path / "results"
    args = (synthetic_cases(), LOADER, synthetic_book(), {TICKER: COMPANY}, NO_FIGURES)
    assert run_generation(*args, cassette=cassette, out_dir=out, inputs={}) == 3
    assert not out.exists() or not any(out.iterdir())
    assert "7 of 7 assess request(s) pending" in capsys.readouterr().out
    assert len(Cassette(cassette).pending()) == 7

    answers = synthetic_answers()

    def respond(request: dict[str, Any]) -> dict[str, Any]:
        found = answers[claim_of(request["user"])](request["user"])
        return {"findings": found, "rationale": "scripted", "unknowns": []}

    answer_pending(cassette, respond)
    assert run_generation(*args, cassette=cassette, out_dir=out, inputs={}) == 0
    written = sorted(path.name for path in out.iterdir())
    assert len(written) == 2 and written[0].startswith("generation-")
    assert {Path(name).suffix for name in written} == {".json", ".md"}
    markdown = (out / written[1]).read_text()
    head = markdown[: markdown.index("## ")]
    assert "7 of its 7 recorded answers used (assess), recorded via a test script" in head
    assert "upper bound for quote validity" in head
    record = json.loads((out / written[0]).read_text())
    assert record["summary"]["answerable"]["verdict_agreement"]["total"] == 5


def test_the_nvidia_cases_offer_passages_and_figures_from_the_recorded_fixtures(
    tmp_path: Path,
) -> None:
    raw = json.loads(GOLDEN_PATH.read_text())
    offline = [c for c in raw["cases"] if c["ticker"] == "NVDA"]
    corpus = Corpus(load_pins(), fetch=None)
    validation = validate_golden({**raw, "cases": offline}, corpus.load_filing)
    assert validation.ok
    facts = read_facts("NVDA", NVIDIA, None, cache_dir=tmp_path, fetch=None)
    figures = figures_for(facts)
    assert facts.origin == "fixture" and figures.figures, figures.note
    book: dict[str, list[str]] = {case["id"]: [] for case in offline}
    cassette = tmp_path / "cassette"
    code = run_generation(
        validation.cases(),
        corpus.load_filing,
        book,
        {"NVDA": NVIDIA},
        {"NVDA": figures},
        cassette=cassette,
        out_dir=tmp_path / "results",
        inputs={},
    )
    assert code == 3 and not (tmp_path / "results").exists()
    pending = [json.loads(p.read_text()) for p in Cassette(cassette).pending()]
    assert len(pending) == 10
    assert all("<reported_figures>" in p["user"] and "<passages>" in p["user"] for p in pending)


# The scores


def test_verdict_agreement_and_the_confusion_table(scored: list) -> None:
    summary = summarize_generation(scored)
    agreement = summary.verdict_agreement
    assert (agreement.hits, agreement.total) == (2, 5)
    assert summary.confusion["supports"] == {
        "supported": 2,
        "challenged": 0,
        "mixed": 0,
        "unjudged": 0,
        "not_addressed": 1,
    }
    assert summary.confusion["challenges"]["supported"] == 1
    assert summary.confusion["mixed"]["not_addressed"] == 1
    assert sum(sum(row.values()) for row in summary.confusion.values()) == 5


def test_scores_are_split_by_whether_retrieval_offered_the_passage(scored: list) -> None:
    outcomes = by_id(scored)
    assert outcomes["retrieval-miss"].offered_position is None
    assert outcomes["supports-right"].offered_position == 1
    summary = summarize_generation(scored)
    hit, miss = summary.by_retrieval["hit"], summary.by_retrieval["miss"]
    assert (hit.verdict_agreement.hits, hit.verdict_agreement.total) == (1, 4)
    assert (hit.citation.hits, hit.citation.total) == (2, 4)
    assert (miss.verdict_agreement.hits, miss.verdict_agreement.total) == (1, 1)
    assert (miss.citation.hits, miss.citation.total) == (0, 1)
    assert (summary.citation.hits, summary.citation.total) == (2, 5)


def test_refusal_counts_only_when_no_finding_is_verified(scored: list) -> None:
    outcomes = by_id(scored)
    assert outcomes["unanswerable-context"].verdict == "unjudged"
    assert not outcomes["unanswerable-context"].refused
    assert outcomes["unanswerable-withheld"].verdict == "not_addressed"
    assert outcomes["unanswerable-withheld"].refused
    refusal = summarize_generation(scored).refusal
    assert (refusal.hits, refusal.total) == (1, 2)


def test_a_withheld_finding_never_counts_as_citing_the_right_passage(scored: list) -> None:
    withheld = by_id(scored)["withheld-right-passage"]
    assert (withheld.findings_verified, withheld.findings_withheld) == (0, 1)
    assert withheld.quotes_offered == 1 and withheld.quotes_rejected == 0  # the quote was real
    assert not withheld.cited_right_passage
    assert withheld.verdict == "not_addressed"
    assert by_id(scored)["supports-right"].cited_right_passage


def test_totals_count_quotes_numbers_and_withheld_reasons(scored: list) -> None:
    totals = summarize_generation(scored).totals
    assert (totals.findings_proposed, totals.findings_verified, totals.findings_withheld) == (
        6,
        4,
        2,
    )
    assert (totals.quotes_offered, totals.quotes_verified, totals.quotes_rejected) == (6, 5, 1)
    assert totals.numbers_checked >= 1 and totals.numbers_unmatched == 1
    assert totals.withheld_reasons == {
        "no verified quote or reported figure": 1,
        "a number in the statement is not in its quotes or cited figures": 1,
    }


def test_the_report_prints_every_denominator(scored: list) -> None:
    markdown = render_markdown(
        {"generated_at": "2026-11-17T00:00:00+00:00", "inputs": {}, "models": "a script"},
        scored,
    )
    for fraction in ("2 / 5", "1 / 4", "2 / 4", "1 / 1", "0 / 1", "1 / 2", "5 / 6", "4 / 6"):
        assert fraction in markdown, fraction
    assert "| withheld-right-passage |" in markdown
    assert "not offered" in markdown  # the retrieval miss


# Companies and reported figures


def test_companies_are_pinned_once_and_read_back(tmp_path: Path) -> None:
    path = tmp_path / "filings.json"
    pins = load_pins()
    save_pins(pins.values(), path, facts={})
    stripped = {a: p.model_copy(update={"cik": None, "name": None}) for a, p in pins.items()}
    with pytest.raises(CorpusError, match="cik"):
        company_for("NVDA", stripped)
    looked_up: list[str] = []

    def lookup(ticker: str) -> Company:
        looked_up.append(ticker)
        return Company(cik=1045810 if ticker == "NVDA" else 1, ticker=ticker, name=f"{ticker} CO")

    filled, changed = pin_companies(["NVDA"], stripped, lookup)
    assert changed == ["NVDA"] and looked_up == ["NVDA"]
    assert company_for("NVDA", filled) == Company(cik=1045810, ticker="NVDA", name="NVDA CO")
    again, changed = pin_companies(["NVDA"], filled, lookup)
    assert changed == [] and looked_up == ["NVDA"]  # pinned: not looked up again
    facts = {"NVDA": PinnedFacts(cik=1045810, url="https://data.sec.gov/x", sha256="0" * 64)}
    save_pins(again.values(), path, facts=facts)
    assert load_facts_pins(path) == facts
    save_pins(again.values(), path)  # facts left out: the file's facts are kept
    assert load_facts_pins(path) == facts
    assert load_pins(path)["0001045810-26-000075"].cik == 1045810


def test_facts_come_from_the_fixture_and_a_changed_body_is_refused(tmp_path: Path) -> None:
    body = gzip.decompress(FACTS_FIXTURES["NVDA"].read_bytes())
    facts = read_facts("NVDA", NVIDIA, None, cache_dir=tmp_path, fetch=None)
    assert facts.pin is not None and facts.pin.sha256 == hashlib.sha256(body).hexdigest()
    assert read_facts("NVDA", NVIDIA, facts.pin, cache_dir=tmp_path, fetch=None).error is None
    wrong = facts.pin.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(CorpusError, match="not the ones pinned"):
        read_facts("NVDA", NVIDIA, wrong, cache_dir=tmp_path, fetch=None)


def test_facts_are_fetched_once_cached_and_without_them_a_company_runs_without_figures(
    tmp_path: Path,
) -> None:
    other = Company(cik=1, ticker="ZZZ", name="ZZZ CO")
    offline = read_facts("ZZZ", other, None, cache_dir=tmp_path, fetch=None)
    assert offline.payload is None and offline.error
    figures = figures_for(offline)
    assert figures.figures == [] and "without reported figures" in figures.note
    body = json.dumps({"cik": 1, "entityName": "ZZZ CO", "facts": {}}).encode()
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return body

    fetched = read_facts("ZZZ", other, None, cache_dir=tmp_path, fetch=fetch)
    assert fetched.origin == "edgar" and fetched.pin is not None
    assert fetched.pin.sha256 == hashlib.sha256(body).hexdigest()
    cached = read_facts("ZZZ", other, fetched.pin, cache_dir=tmp_path, fetch=fetch)
    assert cached.origin == "cache" and len(calls) == 1


def test_make_eval_reaches_the_new_commands_with_global_options() -> None:
    assert normalize_argv(["run", "plan", "--cassette", "c"]) == ["plan", "--cassette", "c"]
    assert normalize_argv(["run", "--offline", "generate"]) == ["--offline", "generate"]
    assert normalize_argv(["run", "--golden", "g.json", "plan"]) == ["--golden", "g.json", "plan"]
    assert normalize_argv(["run", "--variant", "claim"]) == ["run", "--variant", "claim"]


# The meaning check (generate --check)

CHECKED_ANSWERS: dict[str, Script] = {
    **synthetic_answers(),
    # Supports-right now also offers a challenge, so it reads mixed until the check rejects it.
    CASES[0][1]: lambda u: [
        finding("It depends on manufacturers.", "supports", [quote(u, RISK_TEXT)]),
        finding("Revenue fell.", "challenges", [quote(u, MDA_TEXT)]),
    ],
}
JUDGED: dict[str, list[str]] = {
    CASES[0][1]: ["supported", "not_supported"],  # mixed -> supported: now agrees
    CASES[1][1]: ["not_supported"],  # supported -> not_addressed: still disagrees
    CASES[3][1]: ["not_supported"],  # supported -> not_addressed: an agreeing case broken
    CASES[5][1]: ["partly"],  # unanswerable: kept
}


def scripted_with_checks(
    answers: dict[str, Script], judged: dict[str, list[str]]
) -> Callable[[ModelRequest], dict[str, Any]]:
    """Assess as :func:`scripted` does; answer each check request with ``judged`` by claim."""
    assess = scripted(answers)

    def transport(request: ModelRequest) -> dict[str, Any]:
        if request.step == "assess":
            return assess(request)
        assert request.step == "check"
        assert "scripted" not in request.user, "the engine's rationale must not reach the checker"
        verdicts = judged[claim_of(request.user)]
        assert request.user.count("<finding number=") == len(verdicts)
        return {
            "judgements": [
                {"finding_number": n, "verdict": v, "reason": f"Judged {v}."}
                for n, v in enumerate(verdicts, start=1)
            ]
        }

    return transport


@pytest.fixture(scope="module")
def checked_outcomes() -> list:
    transport = scripted_with_checks(CHECKED_ANSWERS, JUDGED)
    run = evaluate_generation(
        synthetic_cases(),
        LOADER,
        synthetic_book(),
        {TICKER: COMPANY},
        NO_FIGURES,
        transport,
        ClaudeChecker(transport=transport),
    )
    assert run.pending == [] and run.check_pending == []
    assert run.checks_asked == 4
    return run.outcomes


def test_the_check_counts_findings_and_moves_verdicts(checked_outcomes: list) -> None:
    meaning = summarize_generation(checked_outcomes).meaning
    assert meaning is not None
    assert (meaning.findings_verified, meaning.findings_checked) == (5, 5)
    assert (meaning.passed, meaning.partly, meaning.failed, meaning.unchecked) == (1, 1, 3, 0)
    outcomes = by_id(checked_outcomes)
    assert (outcomes["supports-right"].verdict, outcomes["supports-right"].verdict_after_check) == (
        "mixed",
        "supported",
    )
    assert outcomes["retrieval-miss"].verdict_after_check == "not_addressed"
    assert outcomes["unanswerable-context"].verdict_after_check == "unjudged"  # partly is kept


def test_agreement_before_and_after_the_check(checked_outcomes: list) -> None:
    meaning = summarize_generation(checked_outcomes).meaning
    assert meaning is not None
    before, after = meaning.agreement_before, meaning.agreement_after
    assert (before.hits, before.total) == (1, 5) and (after.hits, after.total) == (1, 5)
    assert (meaning.disagreed_before, meaning.now_agree, meaning.still_disagree) == (4, 1, 3)
    assert (meaning.agreed_before, meaning.broken) == (1, 1)
    # The existing score is the verdict before the check, unchanged by it.
    assert summarize_generation(checked_outcomes).verdict_agreement == before


def test_the_report_adds_the_check_with_its_denominators(checked_outcomes: list) -> None:
    record = build_record(
        checked_outcomes,
        models="a script",
        inputs={},
        figures={},
        generated_at=datetime(2026, 11, 17, tzinfo=UTC),
    )
    markdown = render_markdown(record, checked_outcomes)
    section = markdown.split("## The meaning check", 1)[1].split("## How to read it", 1)[0]
    for text in (
        "5 / 5 verified",
        "1 / 5 checked",
        "3 / 5 checked",
        "1 / 4 disagreeing before",
        "3 / 4 disagreeing before",
        "1 / 1 agreeing before",
    ):
        assert text in section, text
    assert "After the meaning check" in markdown
    assert "supported (1 supported, 0 partly, 1 failed)" in markdown
    assert record["summary"]["meaning_check"]["broken"] == 1
    cases = {case["case_id"]: case for case in record["cases"]}
    assert list(cases["supports-right"]["check"]["judged"]) == ["supported", "not_supported"]
    assert cases["supports-right"]["agrees_after_check"] is True


def test_without_the_check_the_record_and_report_are_unchanged(scored: list) -> None:
    record = build_record(
        scored, models="a script", inputs={}, figures={}, generated_at=datetime(2026, 11, 17)
    )
    markdown = render_markdown(record, scored)
    assert "meaning" not in markdown.lower()
    assert "meaning_check" not in record["summary"]
    assert all("check" not in case and "agrees_after_check" not in case for case in record["cases"])
    assert summarize_generation(scored).meaning is None
    header = markdown.split("\n## Per case\n", 1)[1].splitlines()[1]
    assert header == (
        "| Case | Ticker | Expected | Obtained | Must-retrieve passage | Cited it | "
        "Findings verified / withheld |"
    )


def test_a_malformed_check_answer_leaves_the_case_unchecked(tmp_path: Path) -> None:
    transport = scripted_with_checks(synthetic_answers(), {})

    def malformed(request: ModelRequest) -> dict[str, Any]:
        return {"judgements": []} if request.step == "check" else transport(request)

    cases = [case for case in synthetic_cases() if case[0].id == "supports-right"]
    run = evaluate_generation(
        cases,
        LOADER,
        synthetic_book(),
        {TICKER: COMPANY},
        NO_FIGURES,
        malformed,
        ClaudeChecker(transport=malformed),
    )
    [outcome] = run.outcomes
    assert outcome.check is not None and "did not judge" in outcome.check.error
    assert outcome.verdict_after_check == outcome.verdict == "supported"
    meaning = summarize_generation(run.outcomes).meaning
    assert meaning is not None and (meaning.unchecked, meaning.cases_check_failed) == (1, 1)


def test_generate_with_the_check_waits_for_the_checks_then_writes_its_own_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cassette, out = tmp_path / "cassette", tmp_path / "results"
    args = (synthetic_cases(), LOADER, synthetic_book(), {TICKER: COMPANY}, NO_FIGURES)
    answers = synthetic_answers()

    def respond(request: dict[str, Any]) -> dict[str, Any]:
        if request["step"] == "check":
            count = request["user"].count("<finding number=")
            return {
                "judgements": [
                    {"finding_number": n, "verdict": "supported", "reason": "It says so."}
                    for n in range(1, count + 1)
                ]
            }
        found = answers[claim_of(request["user"])](request["user"])
        return {"findings": found, "rationale": "scripted", "unknowns": []}

    assert run_generation(*args, cassette=cassette, out_dir=out, inputs={}, check=True) == 3
    assert "7 of 7 assess request(s) pending" in capsys.readouterr().out
    assert answer_pending(cassette, respond) == 7
    assert run_generation(*args, cassette=cassette, out_dir=out, inputs={}, check=True) == 3
    printed = capsys.readouterr().out
    assert "4 of 4 check request(s) unanswered; 4 saved" in printed
    assert not out.exists() or not any(out.iterdir())
    steps = [json.loads(p.read_text())["step"] for p in Cassette(cassette).pending()]
    assert steps == ["check"] * 4
    assert answer_pending(cassette, respond) == 4
    assert run_generation(*args, cassette=cassette, out_dir=out, inputs={}, check=True) == 0
    printed = capsys.readouterr().out
    assert "all 4 check request(s) answered" in printed
    [written] = [p for p in out.iterdir() if p.suffix == ".json"]
    assert written.name.startswith("generation-checked-")
    record = json.loads(written.read_text())
    assert record["inputs"]["meaning_check"] == "claude"
    assert record["summary"]["meaning_check"]["findings_checked"] == 4


# The period check: every year a verified finding names, against its evidence

PERIOD_ANSWERS: dict[str, Script] = {
    **synthetic_answers(),
    CASES[0][1]: lambda u: [
        finding("In fiscal 2023 it depended on manufacturers.", "supports", [quote(u, RISK_TEXT)]),
        finding("In fiscal 2025 it depended on manufacturers.", "context", [quote(u, RISK_TEXT)]),
    ],
    CASES[3][1]: lambda u: [
        finding("Revenue rose in fiscal 2026.", "supports", [quote(u, MDA_TEXT)])
    ],
}
NVIDIA_LIKE = FiscalCalendar(end_month=1, end_day=25, label_offset=0)
PERIOD_FIGURES = {TICKER: CompanyFigures([], "no figures in this test", calendar=NVIDIA_LIKE)}
FILING_PERIODS = {ACCESSION: date(2026, 1, 25)}
NOT_IN_EVIDENCE = "is not in the quotes, the cited figures or the period of a filing quoted"


def period_run(
    checker_judged: dict[str, list[str]] | None = None,
    *,
    answers: dict[str, Script] = PERIOD_ANSWERS,
    figures: dict[str, CompanyFigures] = PERIOD_FIGURES,
) -> list:
    transport = (
        scripted(answers)
        if checker_judged is None
        else scripted_with_checks(answers, checker_judged)
    )
    run = evaluate_generation(
        synthetic_cases(),
        LOADER,
        synthetic_book(),
        {TICKER: COMPANY},
        figures,
        transport,
        None if checker_judged is None else ClaudeChecker(transport=transport),
        filing_periods=FILING_PERIODS,
    )
    assert run.pending == [] and run.check_pending == []
    return run.outcomes


def test_the_period_check_counts_each_year_verified_findings_name() -> None:
    periods = summarize_generation(period_run()).periods
    assert periods is not None
    counts = (periods.checked, periods.passed, periods.unverified, periods.comparative)
    assert counts == (3, 1, 2, 1)
    assert [(m.case_id, m.mention, m.comparative) for m in periods.mentions] == [
        ("supports-right", "fiscal 2023", False),
        ("supports-right", "fiscal 2025", True),
    ]


def test_a_finding_the_meaning_check_rejects_is_not_period_checked() -> None:
    judged = {
        CASES[0][1]: ["supported", "not_supported"],
        CASES[1][1]: ["supported"],
        CASES[3][1]: ["supported"],
        CASES[5][1]: ["partly"],
    }
    periods = summarize_generation(period_run(judged)).periods
    assert periods is not None
    counts = (periods.checked, periods.passed, periods.unverified, periods.comparative)
    assert counts == (2, 1, 1, 0)


def test_the_report_lists_every_unverified_year_with_its_statement() -> None:
    outcomes = period_run()
    record = build_record(
        outcomes, models="a script", inputs={}, figures={}, generated_at=datetime(2026, 11, 17)
    )
    markdown = render_markdown(record, outcomes)
    section = markdown.split("## Periods named in findings", 1)[1].split("## How to read it", 1)[0]
    for text in ("1 / 3 checked", "2 / 3 checked", "1 / 2 unverified"):
        assert text in section, text
    assert (
        f"| supports-right | fiscal 2023 | no | fiscal 2023 {NOT_IN_EVIDENCE} | "
        "In fiscal 2023 it depended on manufacturers. |"
    ) in section
    assert "| supports-right | fiscal 2025 | yes | fiscal 2025 " in section
    summary = record["summary"]["periods"]
    assert (summary["checked"], summary["unverified"], summary["comparative"]) == (3, 2, 1)
    assert [m["mention"] for m in summary["unverified_mentions"]] == ["fiscal 2023", "fiscal 2025"]
    cases = {case["case_id"]: case for case in record["cases"]}
    assert cases["supports-right"]["periods_checked"] == 2
    assert cases["retrieval-miss"]["periods_checked"] == 1
    assert list(cases["retrieval-miss"]["periods_unverified"]) == []
    [unplaced, comparative] = cases["supports-right"]["periods_unverified"]
    assert unplaced["mention"] == "fiscal 2023" and comparative["comparative"] is True


def test_planted_wrong_years_are_counted_by_how_far_the_year_was_moved() -> None:
    """Every finding that names a year has its years moved, and the check is run again.

    The evidence is left as it is. A finding is flagged when the check then finds a year
    its evidence does not carry. This measures what the check catches, on real findings,
    without a model.
    """
    periods = summarize_generation(period_run()).periods
    assert periods is not None
    by_shift = {row.shift: row for row in periods.planted_by_shift()}
    assert sorted(by_shift) == [-3, -2, -1, 1]
    # Three findings of the scripted run name a year.
    assert {row.findings for row in by_shift.values()} == {3}
    for row in by_shift.values():
        assert 0 <= row.flagged <= row.findings
        assert row.flagged + len(row.not_flagged) == row.findings
    # Moving a year three back puts it outside everything a filing prints beside its own.
    assert by_shift[-3].flagged >= by_shift[-1].flagged
    for planted in periods.planted:
        assert planted.statement != "" and planted.shift in (-3, -2, -1, 1)
        assert planted.flagged == any("is not in the quotes" in d for d in planted.details)


def test_the_report_has_the_planted_years_table_and_lists_what_was_not_flagged() -> None:
    outcomes = period_run()
    record = build_record(
        outcomes, models="a script", inputs={}, figures={}, generated_at=datetime(2026, 11, 17)
    )
    markdown = render_markdown(record, outcomes)
    section = markdown.split("### Planted wrong years", 1)[1].split("## How to read it", 1)[0]
    assert "| Years moved by | Findings that name a year | Flagged | Not flagged |" in section
    for shift in ("-1", "-2", "-3", "+1"):
        assert f"| {shift} | 3 | " in section, shift
    planted = record["summary"]["periods"]["planted"]
    assert [row["shift"] for row in planted["by_shift"]] == [-1, -2, -3, 1]
    assert all(row["findings"] == 3 for row in planted["by_shift"])
    missed = sum(row["findings"] - row["flagged"] for row in planted["by_shift"])
    assert len(planted["not_flagged"]) == missed
    if missed:
        assert "Every planted error that was not flagged" in section


def test_the_recorded_nvidia_facts_give_the_figures_a_fiscal_calendar(tmp_path: Path) -> None:
    figures = figures_for(read_facts("NVDA", NVIDIA, None, cache_dir=tmp_path, fetch=None))
    assert figures.calendar is not None
    assert figures.calendar.fiscal_year(date(2026, 7, 26)) == 2027


# One wrong year beside right ones: each year of a statement naming two or more moved alone

# Without a calendar the 10-K for the year ended 2026-01-25 may be fiscal 2026 or fiscal 2027,
# so moving "fiscal 2027" back one year still passes and moving "fiscal 2026" back does not.
SINGLE_YEAR_ANSWERS: dict[str, Script] = {
    **PERIOD_ANSWERS,
    CASES[3][1]: lambda u: [
        finding("Revenue rose in fiscal 2027 and in fiscal 2026.", "supports", [quote(u, MDA_TEXT)])
    ],
}
NO_CALENDAR_FIGURES = {TICKER: CompanyFigures([], "no figures in this test", calendar=None)}


def single_year_run() -> list:
    return period_run(answers=SINGLE_YEAR_ANSWERS, figures=NO_CALENDAR_FIGURES)


def test_one_year_at_a_time_is_moved_in_findings_that_name_two_or_more() -> None:
    periods = summarize_generation(single_year_run()).periods
    assert periods is not None
    # Only the retrieval-miss finding names two years; the others name one and are left out.
    single = periods.single_year
    assert [(s.case_id, s.moved) for s in single] == [
        ("retrieval-miss", "fiscal 2027"),
        ("retrieval-miss", "fiscal 2026"),
    ]
    assert [s.statement for s in single] == [
        "Revenue rose in fiscal 2026 and in fiscal 2026.",
        "Revenue rose in fiscal 2027 and in fiscal 2025.",
    ]
    assert [s.flagged for s in single] == [False, True]
    counts = periods.single_year_counts()
    assert (counts.findings, counts.statements, counts.flagged) == (1, 2, 1)
    assert [s.moved for s in counts.not_flagged] == ["fiscal 2027"]
    # The existing measurement, every year moved together, is unchanged by the new one.
    assert {row.findings for row in periods.planted_by_shift()} == {3}


def test_the_report_has_the_single_year_table_beside_the_all_years_one() -> None:
    outcomes = single_year_run()
    record = build_record(
        outcomes, models="a script", inputs={}, figures={}, generated_at=datetime(2026, 11, 17)
    )
    markdown = render_markdown(record, outcomes)
    assert markdown.index("### Planted wrong years") < markdown.index(
        "### One planted wrong year beside right ones"
    )
    section = markdown.split("### One planted wrong year beside right ones", 1)[1]
    section = section.split("## How to read it", 1)[0]
    assert (
        "| Findings that name two or more years | Statements planted | Flagged | Not flagged |"
    ) in section
    assert "| 1 | 2 | 1 | 1 |" in section
    assert "| retrieval-miss | fiscal 2027 | Revenue rose in fiscal 2026 and in fiscal 2026. |" in (
        section
    )
    single = record["summary"]["periods"]["planted_single_year"]
    assert (single["shift"], single["findings"], single["statements"], single["flagged"]) == (
        -1,
        1,
        2,
        1,
    )
    assert [s["moved"] for s in single["not_flagged"]] == ["fiscal 2027"]
    # The all-years measurement keeps its own key.
    assert [row["shift"] for row in record["summary"]["periods"]["planted"]["by_shift"]] == [
        -1,
        -2,
        -3,
        1,
    ]


def test_with_no_finding_naming_two_years_the_single_year_table_says_so() -> None:
    outcomes = period_run()
    record = build_record(
        outcomes, models="a script", inputs={}, figures={}, generated_at=datetime(2026, 11, 17)
    )
    single = record["summary"]["periods"]["planted_single_year"]
    assert (single["findings"], single["statements"], single["flagged"]) == (0, 0, 0)
    section = render_markdown(record, outcomes).split(
        "### One planted wrong year beside right ones", 1
    )[1]
    assert "No verified finding names two or more years." in section
