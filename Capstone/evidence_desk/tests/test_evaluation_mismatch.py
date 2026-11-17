"""The planted-mismatch evaluation of the meaning check (``python -m app.evaluation mismatch``).

Offline: findings come from hand-made pools or from a synthetic two-company golden set
answered in a temporary cassette; the checker's answers come from a scripted transport or
from that cassette, never the API.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.documents import Document
from app.core.models import Company, Stance
from app.core.ports import CheckExcerpt, CheckFigure, CheckItem
from app.engines.cassette import Cassette, CassetteMiss, CassetteTransport
from app.engines.checker import CHECK_STEP, CHECK_SYSTEM, ClaudeChecker, check_user_prompt
from app.engines.transport import ModelRequest
from app.evaluation.cli import normalize_argv
from app.evaluation.corpus import CorpusError
from app.evaluation.generation_eval import (
    CompanyFigures,
    case_request,
    evaluate_generation,
    run_generation,
)
from app.evaluation.golden import GoldenCase, Target, validate_golden
from app.evaluation.mismatch_eval import (
    OTHER_CLAIM,
    OTHER_COMPANY,
    SKIP_NO_DONOR,
    SKIP_SHARED_QUOTE,
    CaseContext,
    Construction,
    Judged,
    SourceFinding,
    ask_checker,
    build_mismatches,
    render_markdown,
    run_mismatch,
    shares_a_quote,
    summarize_mismatch,
)
from app.sources.filing import parse_filing
from tests.test_evaluation import (
    ACCESSION,
    MDA_TEXT,
    RISK_TEXT,
    TICKER,
    golden,
    synthetic_document,
)
from tests.test_evaluation_generation import answer_pending, claim_of, finding, quote

WHEN = datetime(2026, 11, 17, tzinfo=UTC)

# A hand-made pool of verified findings


def item(statement: str, *quotes: str, figures: int = 0) -> CheckItem:
    """A check item with one excerpt per quote and ``figures`` cited figures."""
    return CheckItem(
        statement=statement,
        stance=Stance.supports,
        excerpts=tuple(CheckExcerpt(text=q, locator="Item 7") for q in quotes),
        figures=tuple(CheckFigure("Revenue", "FY2026", f"${n} billion") for n in range(figures)),
    )


def source(
    case_id: str,
    ticker: str,
    index: int,
    *quotes: str,
    verdict: str = "supported",
    figures: int = 0,
) -> SourceFinding:
    return SourceFinding(
        case_id=case_id,
        ticker=ticker,
        index=index,
        item=item(f"Statement {index} of {case_id}.", *quotes, figures=figures),
        true_verdict=verdict,
    )


ALPHA_ONE = "Alpha revenue grew in every segment this year."
POOL = [
    source("a-one", "AAA", 0, ALPHA_ONE),
    source("a-one", "AAA", 1, "Alpha margins narrowed on input costs.", figures=1),
    source("a-two", "AAA", 0, ALPHA_ONE),  # the same quote as a-one #0, in another case
    source("a-two", "AAA", 1, "Alpha holds no debt at all.", verdict="partly"),
    source("b-one", "BBB", 0, "Beta sells mostly to two customers."),
    source("c-one", "CCC", 0, "Gamma closed its only factory."),  # CCC's only case
    source("c-one", "CCC", 1),  # no quote: neither a recipient nor a donor
]


def donors(construction: Construction, kind: str) -> dict[tuple[str, int], tuple[str, int]]:
    return {
        (m.recipient.case_id, m.recipient.index): (m.donor.case_id, m.donor.index)
        for m in construction.mismatches
        if m.kind == kind
    }


# Construction


def test_the_donors_follow_the_rotation_and_do_not_depend_on_input_order() -> None:
    built = build_mismatches(POOL)
    assert build_mismatches(list(reversed(POOL))) == built
    assert build_mismatches(POOL) == built
    assert donors(built, OTHER_COMPANY) == {
        ("a-one", 0): ("b-one", 0),
        ("a-one", 1): ("c-one", 0),
        ("a-two", 0): ("b-one", 0),
        ("a-two", 1): ("c-one", 0),
        ("b-one", 0): ("c-one", 0),
        ("c-one", 0): ("a-one", 0),
    }
    # a-one #0 and a-two #0 share a quote: the rotation moves past it to the next donor.
    assert donors(built, OTHER_CLAIM) == {
        ("a-one", 0): ("a-two", 1),
        ("a-one", 1): ("a-two", 1),
        ("a-two", 0): ("a-one", 1),
        ("a-two", 1): ("a-one", 1),
    }
    assert len(built.eligible) == 6 and built.without_quotes == 1


def test_a_mismatch_never_carries_its_own_or_an_identical_quote() -> None:
    built = build_mismatches(POOL)
    assert built.mismatches
    for mismatch in built.mismatches:
        recipient, donor = mismatch.recipient, mismatch.donor
        assert (donor.case_id, donor.index) != (recipient.case_id, recipient.index)
        assert donor.case_id != recipient.case_id
        assert mismatch.item.excerpts == donor.item.excerpts
        assert not shares_a_quote(recipient.item, mismatch.item)
        assert mismatch.item.statement == recipient.item.statement
        assert mismatch.item.stance == recipient.item.stance
        if mismatch.kind == OTHER_COMPANY:
            assert donor.ticker != recipient.ticker
        else:
            assert donor.ticker == recipient.ticker


def test_a_quote_inside_another_counts_as_shared() -> None:
    longer = item("x", "  Alpha revenue grew in every segment this year.  And more besides.")
    assert shares_a_quote(item("y", ALPHA_ONE), longer)
    assert not shares_a_quote(item("y", ALPHA_ONE), item("z", "Something else entirely."))


def test_cited_figures_are_dropped_and_counted() -> None:
    built = build_mismatches(POOL)
    with_figure = [m for m in built.mismatches if m.recipient.key == ("a-one", 1)]
    assert len(with_figure) == 2
    assert all(m.item.figures == () and m.figures_dropped == 1 for m in with_figure)


def test_skips_are_counted_with_their_reason() -> None:
    built = build_mismatches(POOL)
    assert [(s.kind, s.case_id, s.index, s.reason) for s in built.skips] == [
        (OTHER_CLAIM, "b-one", 0, SKIP_NO_DONOR),
        (OTHER_CLAIM, "c-one", 0, SKIP_NO_DONOR),
    ]
    shared = build_mismatches(
        [source("d-one", "DDD", 0, "Delta quote."), source("d-two", "DDD", 0, "Delta quote.")]
    )
    assert [(s.kind, s.reason) for s in shared.skips] == [
        (OTHER_COMPANY, SKIP_NO_DONOR),
        (OTHER_COMPANY, SKIP_NO_DONOR),
        (OTHER_CLAIM, SKIP_SHARED_QUOTE),
        (OTHER_CLAIM, SKIP_SHARED_QUOTE),
    ]
    assert shared.mismatches == []


# The requests: the production checker and prompt builder, batched per (case, kind)


def contexts() -> dict[str, CaseContext]:
    """One context per case of the pool, built as a run builds its one-claim request."""
    built: dict[str, CaseContext] = {}
    for n, (case_id, ticker) in enumerate(
        [("a-one", "AAA"), ("a-two", "AAA"), ("b-one", "BBB"), ("c-one", "CCC")], start=1
    ):
        case = GoldenCase(
            id=case_id,
            ticker=ticker,
            filings=[ACCESSION],
            claim=f"The claim of case {case_id} about the business.",
            kind="unanswerable",
            expected="none",
            why="A synthetic case for the mismatch tests.",
        )
        request, claim = case_request(case)
        built[case_id] = CaseContext(
            request=request,
            company=Company(cik=n, ticker=ticker, name=f"{ticker} CORP"),
            claim=claim,
        )
    return built


Verdicts = Callable[[str, int], str]


def judging(verdict_for: Verdicts, seen: list[ModelRequest]) -> Callable[[ModelRequest], dict]:
    """A transport that records each request and judges finding n with ``verdict_for``."""

    def transport(request: ModelRequest) -> dict[str, Any]:
        seen.append(request)
        count = request.user.count("<finding number=")
        return {
            "judgements": [
                {
                    "finding_number": n,
                    "verdict": verdict_for(request.user, n),
                    "reason": f"Scripted reason {n}.",
                }
                for n in range(1, count + 1)
            ]
        }

    return transport


def test_each_case_and_kind_is_one_request_built_by_the_production_prompt_builder() -> None:
    built = build_mismatches(POOL)
    seen: list[ModelRequest] = []
    checker = ClaudeChecker(transport=judging(lambda user, n: "not_supported", seen))
    run = ask_checker(built, contexts(), checker)
    groups: dict[tuple[str, str], list] = {}
    for mismatch in built.mismatches:
        groups.setdefault((mismatch.recipient.case_id, mismatch.kind), []).append(mismatch)
    assert len(seen) == len(groups) == run.batches == 6
    expected = [
        check_user_prompt(
            contexts()[case_id].company, contexts()[case_id].claim, [m.item for m in members]
        )
        for (case_id, _), members in groups.items()
    ]
    assert [request.user for request in seen] == expected
    assert all(r.step == CHECK_STEP and r.system == CHECK_SYSTEM for r in seen)
    # The swapped quote reaches the checker; the finding's own does not.
    first = seen[0].user
    assert "Beta sells mostly to two customers." in first and ALPHA_ONE not in first


# The scores


def judged_pool() -> list[Judged]:
    """Every mismatch of the pool judged by a script: one missed, one partly, one unjudged."""
    built = build_mismatches(POOL)
    verdicts: dict[tuple[str, str, int], str] = {
        (OTHER_COMPANY, "a-one", 0): "supported",
        (OTHER_CLAIM, "a-two", 1): "partly",
    }
    judged: list[Judged] = []
    for m in built.mismatches:
        key = (m.kind, m.recipient.case_id, m.recipient.index)
        if key == (OTHER_CLAIM, "a-one", 1):
            judged.append(Judged(m, verdict="", reason="", error="the checker judged 0 of 2"))
            continue
        judged.append(Judged(m, verdict=verdicts.get(key, "not_supported"), reason="Off topic."))
    return judged


def test_the_three_counts_per_kind_with_their_denominators() -> None:
    summaries = {s.kind: s for s in summarize_mismatch(build_mismatches(POOL), judged_pool())}
    company = summaries[OTHER_COMPANY]
    assert (company.mismatched.total, company.mismatched.not_supported) == (6, 5)
    mismatched = company.mismatched
    assert (mismatched.partly, mismatched.supported, mismatched.unjudged) == (0, 1, 0)
    claim = summaries[OTHER_CLAIM]
    assert (claim.mismatched.total, claim.mismatched.not_supported) == (4, 2)
    assert (claim.mismatched.partly, claim.mismatched.supported, claim.mismatched.unjudged) == (
        1,
        0,
        1,
    )
    assert (company.skipped, claim.skipped) == (0, 2)
    # The true pairs: the same findings with their own quotes, as the golden check judged them.
    assert (company.true_pairs.total, company.true_pairs.supported, company.true_pairs.partly) == (
        6,
        5,
        1,
    )
    true_pairs = claim.true_pairs
    assert (true_pairs.total, true_pairs.supported, true_pairs.partly) == (4, 3, 1)


def test_the_report_lists_every_missed_and_partly_item_with_denominators() -> None:
    built = build_mismatches(POOL)
    models = {"mismatch": "a script", "findings": "a script"}
    record = {"generated_at": WHEN.isoformat(), "models": models}
    markdown = render_markdown(record, built, judged_pool())
    for fraction in ("5 / 6", "1 / 6", "2 / 4", "1 / 4", "5 / 6"):
        assert fraction in markdown, fraction
    missed = markdown.split("## Missed", 1)[1].split("## ", 1)[0]
    assert "a-one" in missed and "Statement 0 of a-one." in missed
    assert "Beta sells mostly to two customers." in missed and "Off topic." in missed
    partly = markdown.split("## Partly", 1)[1].split("## ", 1)[0]
    assert "a-two" in partly and "Statement 1 of a-two." in partly
    assert "a script" in markdown
    assert "swapped" in markdown.lower() and "easy" in markdown.lower()


def test_a_long_swapped_quote_is_cut_to_160_characters_in_the_list() -> None:
    long_quote = "Beta " + "sells widgets " * 30
    pool = [source("a-one", "AAA", 0, "Alpha."), source("b-one", "BBB", 0, long_quote)]
    built = build_mismatches(pool)
    judged = [Judged(m, verdict="supported", reason="Fine.") for m in built.mismatches]
    markdown = render_markdown({"generated_at": WHEN.isoformat(), "models": {}}, built, judged)
    shown = " ".join(long_quote.split())
    assert shown[:160] in markdown and shown[:161] not in markdown


# Seams in the code reused


def test_a_read_only_cassette_answers_what_it_holds_and_saves_nothing_on_a_miss(
    tmp_path: Path,
) -> None:
    request = ModelRequest(step="check", system="s", user="u", schema={}, max_tokens=10)
    transport = CassetteTransport(tmp_path, read_only=True)
    with pytest.raises(CassetteMiss, match="read-only"):
        transport(request)
    assert not any(tmp_path.iterdir())
    writer = CassetteTransport(tmp_path)
    with pytest.raises(CassetteMiss):
        writer(request)
    assert len(Cassette(tmp_path).pending()) == 1  # the default still saves the request


# The command, end to end, on a synthetic two-company golden set

OTHER = "OTHR"
OTHER_ACCESSION = "0009999999-26-000002"
OTHER_RISK = (
    "Our warehouses depend on members renewing each year, and a fall in renewals would cut "
    "membership fee income sharply."
)
OTHER_MDA = (
    "Net sales rose eight percent compared with the prior year, led by gasoline and fresh food, "
    "while new warehouse openings slowed."
)


def other_document() -> Document:
    html = (
        "<html><body><p>PART I</p><p><b>Item 1A. Risk Factors</b></p>"
        f"<p>{OTHER_RISK}</p><p>PART II</p>"
        "<p><b>Item 7. Management's Discussion and Analysis</b></p>"
        f"<p>{OTHER_MDA}</p></body></html>"
    )
    return parse_filing(html, url="https://example.test/o.htm", title="o", published_date=None)


DOCUMENTS = {(TICKER, ACCESSION): synthetic_document(), (OTHER, OTHER_ACCESSION): other_document()}


def load(ticker: str, accession: str) -> Document:
    if (ticker, accession) not in DOCUMENTS:
        raise CorpusError(f"{accession} is not pinned")
    return DOCUMENTS[(ticker, accession)]


E2E = [
    # (id, ticker, claim, statement, quoted text)
    ("t-one", TICKER, "The firm leans on plants abroad.", "It uses manufacturers.", RISK_TEXT),
    ("t-two", TICKER, "Sales rose on stronger services volumes.", "Revenue rose.", MDA_TEXT),
    ("o-one", OTHER, "Members keep renewing every year.", "Renewals drive fees.", OTHER_RISK),
    ("o-two", OTHER, "Warehouse sales are still growing.", "Net sales rose.", OTHER_MDA),
]


def e2e_cases() -> list[tuple[GoldenCase, list[Target]]]:
    raw = [
        {
            "id": case_id,
            "ticker": ticker,
            "filings": [ACCESSION if ticker == TICKER else OTHER_ACCESSION],
            "claim": claim,
            "kind": "unanswerable",
            "expected": "none",
            "must_retrieve": [],
            "why": "A synthetic case for the mismatch tests.",
        }
        for case_id, ticker, claim, _, _ in E2E
    ]
    result = validate_golden(golden(*raw), load)
    assert result.ok, [(c.case_id, c.problems) for c in result.checks if not c.ok]
    return result.cases()


BOOK = {case_id: ["manufacturers revenue members sales"] for case_id, *_ in E2E}
COMPANIES = {
    TICKER: Company(cik=99, ticker=TICKER, name="Test Corp"),
    OTHER: Company(cik=98, ticker=OTHER, name="Other Corp"),
}
FIGURES = {ticker: CompanyFigures([], "no figures in this test") for ticker in COMPANIES}


def answer_golden(cassette: Path) -> None:
    """Record the assess and check answers of the synthetic golden run in ``cassette``."""
    statements = {claim: (statement, text) for _, _, claim, statement, text in E2E}

    def respond(request: dict[str, Any]) -> dict[str, Any]:
        if request["step"] == "check":
            return {
                "judgements": [
                    {"finding_number": 1, "verdict": "supported", "reason": "It says so."}
                ]
            }
        statement, text = statements[claim_of(request["user"])]
        found = [finding(statement, "supports", [quote(request["user"], text)])]
        return {"findings": found, "rationale": "scripted", "unknowns": []}

    args = (e2e_cases(), load, BOOK, COMPANIES, FIGURES)
    options: dict[str, Any] = {"cassette": cassette, "out_dir": cassette / "out", "inputs": {}}
    for _ in range(2):  # the assessments, then the checks
        assert run_generation(*args, **options, check=True) == 3
        answer_pending(cassette, respond)
    assert run_generation(*args, **options, check=True) == 0


def fingerprint(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def golden_cassette(tmp_path: Path) -> Path:
    cassette = tmp_path / "golden"
    answer_golden(cassette)
    return cassette


def test_mismatch_exits_3_writes_nothing_and_leaves_the_findings_cassette_alone(
    tmp_path: Path, golden_cassette: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = fingerprint(golden_cassette)
    mismatch, out = tmp_path / "mismatch", tmp_path / "results"
    code = run_mismatch(
        e2e_cases(),
        load,
        BOOK,
        COMPANIES,
        FIGURES,
        findings_cassette=golden_cassette,
        cassette=mismatch,
        out_dir=out,
        inputs={},
        now=WHEN,
    )
    assert code == 3
    assert not out.exists() or not any(out.iterdir())
    printed = capsys.readouterr().out
    assert "8 of 8 check request(s) pending" in printed
    pending = [json.loads(p.read_text()) for p in Cassette(mismatch).pending()]
    assert len(pending) == 8 and {p["step"] for p in pending} == {"check"}
    assert fingerprint(golden_cassette) == before


def test_mismatch_writes_its_record_once_answered_and_lists_the_missed_item(
    tmp_path: Path, golden_cassette: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mismatch, out = tmp_path / "mismatch", tmp_path / "results"
    kwargs = {
        "findings_cassette": golden_cassette,
        "cassette": mismatch,
        "out_dir": out,
        "inputs": {},
        "now": WHEN,
    }
    assert run_mismatch(e2e_cases(), load, BOOK, COMPANIES, FIGURES, **kwargs) == 3

    def respond(request: dict[str, Any]) -> dict[str, Any]:
        # Missed: t-one's statement with t-two's quote. Partly: o-one's with Test Corp's quote.
        user = request["user"]
        verdict = "not_supported"
        if "It uses manufacturers." in user and "Revenue increased twelve percent" in user:
            verdict = "supported"
        elif "Renewals drive fees." in user and "contract manufacturers" in user:
            verdict = "partly"
        return {
            "judgements": [
                {"finding_number": 1, "verdict": verdict, "reason": f"Planted {verdict}."}
            ]
        }

    assert answer_pending(mismatch, respond) == 8
    assert run_mismatch(e2e_cases(), load, BOOK, COMPANIES, FIGURES, **kwargs) == 0
    names = sorted(path.name for path in out.iterdir())
    assert names == ["mismatch-2026-11-17.json", "mismatch-2026-11-17.md"]
    record = json.loads((out / names[0]).read_text())
    by_kind = {k["kind"]: k for k in record["summary"]["kinds"]}
    assert by_kind[OTHER_CLAIM]["mismatched"]["supported"] == 1
    assert by_kind[OTHER_CLAIM]["mismatched"]["total"] == 4
    assert by_kind[OTHER_COMPANY]["mismatched"]["partly"] == 1
    assert by_kind[OTHER_COMPANY]["true_pairs"]["supported"] == 4
    assert "a test script" in record["models"]["mismatch"]
    markdown = (out / names[1]).read_text()
    missed = markdown.split("## Missed", 1)[1].split("## ", 1)[0]
    assert "t-one" in missed and "It uses manufacturers." in missed
    assert MDA_TEXT[:60] in missed and "Planted supported." in missed


def test_without_every_golden_answer_mismatch_stops_and_saves_nothing_there(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    findings, mismatch = tmp_path / "golden", tmp_path / "mismatch"
    findings.mkdir()
    code = run_mismatch(
        e2e_cases(),
        load,
        BOOK,
        COMPANIES,
        FIGURES,
        findings_cassette=findings,
        cassette=mismatch,
        out_dir=tmp_path / "out",
        inputs={},
    )
    assert code == 1
    assert not any(findings.iterdir()) and not mismatch.exists()
    assert "does not answer" in capsys.readouterr().out


def test_the_generation_run_keeps_each_case_s_gated_result(golden_cassette: Path) -> None:
    transport = CassetteTransport(golden_cassette, read_only=True)
    run = evaluate_generation(
        e2e_cases(), load, BOOK, COMPANIES, FIGURES, transport, ClaudeChecker(transport=transport)
    )
    assert list(run.gated) == [case_id for case_id, *_ in E2E]
    assert all(len(run.gated[o.case_id].findings) == o.findings_verified == 1 for o in run.outcomes)


def test_make_eval_reaches_the_mismatch_command() -> None:
    assert normalize_argv(["run", "mismatch", "--cassette", "c"]) == ["mismatch", "--cassette", "c"]
