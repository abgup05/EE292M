"""Compiler against model on the golden computed claims (evaluation only, never in a run).

``make eval ARGS='compiler-vs-model --record --max-calls 70'`` gives a model, for each
case of ``eval/claim-results.json``, the reported-figure lines a run would offer for
that company as of the case's date (the same lines an assessment prompt shows, plus
the filing's tagged figures for a share of revenue) and the claim, and asks through
:class:`~app.engines.cassette.CassetteTransport` for "holds", "fails" or
"cannot_tell" with a JSON schema. The claim compiler's own outcome
(:mod:`app.core.claim_eval`) is scored beside it against the same key.

Before any call it prints how many requests are already answered in the cassette
and how many it would make; with ``--record`` it refuses to start when that is more
than ``--max-calls`` (which ``--record`` requires). Without ``--record`` a missing
answer is saved under ``pending/`` (``docs/cassettes.md``) and the command exits 3,
writing nothing. Every score says where the model's answers came from.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ed_v14.core.claim_eval import evaluate
from ed_v14.core.claimtest import ClaimTest, compile_claim
from ed_v14.core.facts import FactBook
from ed_v14.core.metrics import build_report
from ed_v14.core.periods import fiscal_calendar
from ed_v14.core.tagged_figures import select_tagged, tagged_units
from ed_v14.engines.cassette import RESPONSES, Cassette, CassetteMiss, CassetteTransport, request_key
from ed_v14.engines.claude import figure_lines
from ed_v14.engines.transport import AnthropicTransport, EngineError, ModelRequest, Transport
from ed_v14.evaluation.claim_oracle import (
    CIKS,
    load_payload,
    recorded_annual_report,
    recorded_report,
)
from ed_v14.services.numbers import select_figures

KEY = Path("eval/claim-results.json")
CASSETTE = Path("eval/cassettes/compiler-vs-model")
RESULTS = Path("eval/results")
STEP = "judge"
MAX_TOKENS = 600
ANSWERS = ("holds", "fails", "cannot_tell")
AS_KEY = {"holds": "holds", "fails": "fails", "cannot_tell": "cannot_compute"}
SYSTEM = (
    "You check one claim about a company against its reported figures. Use only the "
    "figures given, each with its period; do not use anything you know about the company. "
    "Answer holds when the figures show the claim is true, fails when they show it is "
    "false, and cannot_tell when they do not settle it. Give a one-sentence reason that "
    "names the figures you used."
)
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "enum": list(ANSWERS)},
        "reason": {"type": "string"},
    },
    "required": ["answer", "reason"],
    "additionalProperties": False,
}
NAMES = {"NVDA": "NVIDIA CORP", "AAPL": "Apple Inc.", "MSFT": "MICROSOFT CORP"}


def _shares(test: ClaimTest) -> bool:
    return test.from_filing


def build_requests(cases: Sequence[dict[str, Any]]) -> list[tuple[dict[str, Any], ModelRequest]]:
    """One request per case: the company's figures as of the case's date, and the claim."""
    payloads = {ticker: load_payload(ticker) for ticker in {c["ticker"] for c in cases}}
    reports: list[Any] = []
    requests = []
    for case in cases:
        day = date.fromisoformat(case["as_of"])
        figures = select_figures(build_report(FactBook(payloads[case["ticker"]], as_of=day)))
        test = compile_claim(case["claim"])
        if isinstance(test, ClaimTest) and _shares(test):
            reports = reports or _recorded_reports()
            units, _ = tagged_units(reports)
            figures = [*figures, *select_tagged(units)[0]]
        user = (
            f"<company>{NAMES[case['ticker']]} ({case['ticker']}, CIK {CIKS[case['ticker']]})"
            f"</company>\n<as_of>{case['as_of']}</as_of>\n"
            f"<figures>\n{figure_lines(figures)}\n</figures>\n<claim>{case['claim']}</claim>"
        )
        requests.append((case, ModelRequest(STEP, SYSTEM, user, SCHEMA, MAX_TOKENS)))
    return requests


def compiler_outcome(case: dict[str, Any]) -> str:
    """What the claim compiler and evaluator give for a case, as of its date."""
    test = compile_claim(case["claim"])
    if not isinstance(test, ClaimTest):
        return "cannot_compute"
    payload = load_payload(case["ticker"])
    day = date.fromisoformat(case["as_of"])
    result = evaluate(
        test,
        FactBook(payload, as_of=day),
        calendar=fiscal_calendar(payload, as_of=day),
        reports=_recorded_reports() if _shares(test) else [],
    )
    return result.outcome


def _recorded_reports() -> list[Any]:
    """NVIDIA's recorded 10-Q and 10-K tags, as a run reads the newest of each."""
    return [recorded_report(), recorded_annual_report()]


def _score(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    agree = sum(row[field] == row["expected"] for row in rows)
    by: dict[str, dict[str, int]] = {}
    for row in rows:
        tally = by.setdefault(row["expected"], {"cases": 0, "agree": 0})
        tally["cases"] += 1
        tally["agree"] += row[field] == row["expected"]
    return {"agree": agree, "cases": len(rows), "by_expected": by}


def _markdown(record: dict[str, Any]) -> str:
    lines = [
        "# Compiler against model on the golden computed claims",
        "",
        f"Answers from: {record['answers_from']}.",
        "",
        "| | agree with the key | of |",
        "|---|---|---|",
        f"| compiler | {record['compiler']['agree']} | {record['compiler']['cases']} |",
        f"| model | {record['model']['agree']} | {record['model']['cases']} |",
        "",
        "| case | expected | compiler | model | model's reason |",
        "|---|---|---|---|---|",
    ]
    for row in record["rows"]:
        reason = row["reason"].replace("|", "\\|")
        lines.append(
            f"| {row['id']} | {row['expected']} | {row['compiler']} | {row['model']} | {reason} |"
        )
    return "\n".join(lines) + "\n"


def run(
    *,
    key: Path = KEY,
    cassette: Path = CASSETTE,
    record: bool = False,
    max_calls: int | None = None,
    out: Path = RESULTS,
    live_factory: Callable[[], Transport] = AnthropicTransport,
) -> int:
    """Ask, score and write; 2 when the calls would pass the cap, 3 while any answer is missing."""
    cases = json.loads(key.read_text(encoding="utf-8"))["cases"]
    requests = build_requests(cases)
    answered = sum(
        (cassette / RESPONSES / f"{request_key(request)}.json").exists() for _, request in requests
    )
    to_make = len(requests) - answered
    how = "to the model" if record else "(saved as pending: no --record)"
    print(
        f"compiler-vs-model: {len(requests)} case(s); {answered} answered in the cassette; "
        f"{to_make} request(s) to make {how}."
    )
    if record and max_calls is None:
        print("compiler-vs-model: --record needs --max-calls N; nothing was asked.")
        return 2
    if record and max_calls is not None and to_make > max_calls:
        print(
            f"compiler-vs-model: {to_make} call(s) is above the cap of {max_calls}; "
            "nothing was asked."
        )
        return 2
    transport = CassetteTransport(cassette, live=live_factory() if record and to_make else None)
    rows: list[dict[str, Any]] = []
    pending = 0
    for case, request in requests:
        try:
            answer = transport(request)
        except CassetteMiss:
            pending += 1
            continue
        except EngineError as exc:
            print(f"compiler-vs-model: {case['id']}: {exc}")
            return 1
        model = answer.get("answer")
        if model not in ANSWERS:
            print(f"compiler-vs-model: {case['id']}: the answer {model!r} is not one of {ANSWERS}")
            return 1
        rows.append(
            {
                "id": case["id"],
                "ticker": case["ticker"],
                "as_of": case["as_of"],
                "claim": case["claim"],
                "expected": case["expected"]["outcome"],
                "compiler": compiler_outcome(case),
                "model": AS_KEY[model],
                "reason": str(answer.get("reason", "")),
            }
        )
    if pending:
        print(
            f"compiler-vs-model: {pending} request(s) pending in "
            f"{(cassette / 'pending').as_posix()}; answer them and run again. Nothing was scored."
        )
        return 3
    result = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "key": key.as_posix(),
        "answers_from": Cassette(cassette).describe(),
        "compiler": _score(rows, "compiler"),
        "model": _score(rows, "model"),
        "rows": rows,
    }
    print(f"Answers from: {result['answers_from']}")
    print(f"compiler: {result['compiler']['agree']} of {len(rows)} agree with the key")
    print(f"model: {result['model']['agree']} of {len(rows)} agree with the key")
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    path = out / f"compiler-vs-model-{stamp}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    path.with_suffix(".md").write_text(_markdown(result), encoding="utf-8")
    print(f"compiler-vs-model: wrote {path.as_posix()} and .md")
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The command's options, for :mod:`app.evaluation.cli`."""
    parser.add_argument("--key", type=Path, default=KEY, help="the golden computed claims")
    parser.add_argument("--cassette", type=Path, default=CASSETTE, help="the cassette")
    parser.add_argument("--record", action="store_true", help="ask the model for missing answers")
    parser.add_argument("--max-calls", type=int, help="refuse to start above this many calls")
    parser.add_argument("--out", type=Path, default=RESULTS, help="where the record goes")


def main(args: argparse.Namespace) -> int:
    """Run from parsed arguments."""
    return run(
        key=args.key,
        cassette=args.cassette,
        record=args.record,
        max_calls=args.max_calls,
        out=args.out,
    )
