"""The readers of a claim set side by side, one row per claim, for a judge to mark.

``make eval ARGS='claim-readers --set eval/claim-tests-foreign.json --record --max-calls 240'``
reads every claim of a set with the grammar (:func:`app.core.claimtest.compile_claim`)
and with up to two model readers of different models
(:class:`app.engines.claim_reader.ModelClaimReader`: ``$ANTHROPIC_READER_MODEL`` and
``$ANTHROPIC_READER_MODEL_2``), each through
:class:`~app.engines.cassette.CassetteTransport` under its own step, and writes
``eval/results/claim-readers-<set>.csv``: the claim; each reader's normal form
(:func:`app.core.claim_normal.normal_form`) or ``none`` and why; who answered for each
model (from the cassette); which pairs of readers agree; the counting rule's conclusion
(:func:`app.core.policy.reading_agreement`), the test it would count and any dissent;
and three empty columns for the judge. Nothing is scored here.

``--readers`` is ``models`` (the grammar and both models, the default), ``model`` (the
grammar and the first) or ``grammar`` (the grammar alone: nothing is asked, and every
compiled test counts as one reader's). ``--judge`` also writes
``claim-readers-<set>-for-judge.md``: the notation in plain words, then every reading
the rule would count, with its sentence and normal form, and no judgement. The judge is
not told which readings had a dissent.

A set is either a file with ``claims`` (``id``, ``text`` and optionally ``company``), as
the foreign sets are, or the own label file with ``development`` and ``held_out``
(``id``, ``claim``). Before any call it prints, for each model, how many requests are
already answered in the cassette and how many it would make; with ``--record`` it refuses
to start when the total is more than ``--max-calls`` (which ``--record`` requires).
Answers are kept as they arrive, so a run stopped part way resumes without asking again.
Without ``--record`` a missing answer is saved under ``pending/`` (``docs/cassettes.md``)
and the command exits 3, writing nothing. A normal form here knows no newest fiscal year
(no facts are read), so a named year stays named.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import get_args

from ed_v14.core import policy
from ed_v14.core.claim_normal import normal_form
from ed_v14.core.claimtest import FORMS, ClaimTest, Function, NotNumeric, PeriodKind, compile_claim
from ed_v14.core.measures import CATALOGUE, PART_MEASURES
from ed_v14.engines.cassette import RESPONSES, Cassette, CassetteMiss, CassetteTransport, request_key
from ed_v14.engines.claim_reader import (
    READ_STEP,
    SECOND_READ_STEP,
    ModelClaimReader,
    first_model,
    read_request,
    second_model,
)
from ed_v14.engines.transport import AnthropicTransport, EngineError, Transport

CASSETTE = Path("eval/cassettes/claim-readers")
RESULTS = Path("eval/results")
READER_SETS = {
    "grammar": (),
    "model": (policy.MODEL_READER,),
    "models": (policy.MODEL_READER, policy.SECOND_MODEL_READER),
}
STEP_OF = {policy.MODEL_READER: READ_STEP, policy.SECOND_MODEL_READER: SECOND_READ_STEP}
JUDGE_COLUMNS = ("judge_counted", "judge_dissent", "judge_note")


@dataclass(frozen=True)
class SetClaim:
    """One claim of a set: its id, the company it is about ("" when the set does not say)."""

    id: str
    text: str
    company: str = ""


def load_claims(path: Path) -> list[SetClaim]:
    """The claims of a set file, in order; a malformed file is a ValueError."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: not a JSON object")
    if "claims" in payload:
        entries, field = payload["claims"], "text"
    else:
        entries, field = [*payload["development"], *payload["held_out"]], "claim"
    claims = []
    for entry in entries:
        if not isinstance(entry.get("id"), str) or not isinstance(entry.get(field), str):
            raise ValueError(f"{path}: every claim needs an id and its {field}")
        claims.append(SetClaim(entry["id"], entry[field], str(entry.get("company", ""))))
    if len({claim.id for claim in claims}) != len(claims):
        raise ValueError(f"{path}: the ids are not distinct")
    return claims


def columns(readers: Sequence[str]) -> list[str]:
    """The file's columns for the grammar and ``readers`` (the model readers)."""
    names = ["id", "company", "claim", "grammar", "grammar_reason"]
    for reader in readers:
        names += [reader, f"{reader}_reason", f"{reader}_answered_by"]
    return [*names, "agree", "conclusion", "counted", "dissent", *JUDGE_COLUMNS]


def _form(result: ClaimTest | NotNumeric) -> tuple[str, str]:
    if isinstance(result, NotNumeric):
        return policy.NO_TEST, result.reason
    return normal_form(result), ""


def _answered_by(cassette: Path, key: str) -> str:
    envelope = json.loads((cassette / RESPONSES / f"{key}.json").read_text(encoding="utf-8"))
    return f"{envelope['model']} via {envelope['via']}, recorded {envelope['recorded_at']}"


def _row(
    claim: SetClaim, forms: dict[str, tuple[str, str]], answered_by: dict[str, str]
) -> dict[str, str]:
    """One claim's row: each reader's form, the pairs that agree, the rule's conclusion."""
    row = {"id": claim.id, "company": claim.company, "claim": claim.text}
    for reader, (form, reason) in forms.items():
        row[reader], row[f"{reader}_reason"] = form, reason
        if reader in answered_by:
            row[f"{reader}_answered_by"] = answered_by[reader]
    tests = {reader: form for reader, (form, _) in forms.items() if form != policy.NO_TEST}
    pairs = [f"{a}={b}" for a, b in combinations(tests, 2) if tests[a] == tests[b]]
    rule = policy.reading_agreement({reader: form for reader, (form, _) in forms.items()})
    row["agree"] = "; ".join(pairs)
    row["conclusion"] = policy.AGREEMENT_LABELS[rule.conclusion]
    row["counted"] = rule.form if rule.counts else ""
    row["dissent"] = "; ".join(f"{reader}: {tests[reader]}" for reader in rule.dissenting)
    return row | dict.fromkeys(JUDGE_COLUMNS, "")


def run(
    *,
    claims: Path,
    cassette: Path = CASSETTE,
    record: bool = False,
    max_calls: int | None = None,
    out: Path = RESULTS,
    readers: str = "models",
    judge: bool = False,
    models: tuple[str, str] | None = None,
    live_factory: Callable[[str], Transport] | None = None,
) -> int:
    """Read, compare and write; 2 when the calls would pass the cap, 3 while any is missing.

    ``models`` are the two readers' model ids (from the environment when None);
    ``live_factory`` makes the live transport for a model id (the API when None).
    """
    claim_set = load_claims(claims)
    chosen = READER_SETS[readers]
    model_of = dict(
        zip(
            (policy.MODEL_READER, policy.SECOND_MODEL_READER),
            models or (first_model(), second_model()),
            strict=True,
        )
    )
    keys = {
        reader: [request_key(read_request(c.text, STEP_OF[reader])) for c in claim_set]
        for reader in chosen
    }
    to_make: dict[str, int] = {}
    for reader in chosen:
        answered = sum((cassette / RESPONSES / f"{key}.json").exists() for key in keys[reader])
        to_make[reader] = len(claim_set) - answered
        print(
            f"claim-readers: {reader} ({model_of[reader]}): {len(claim_set)} claim(s); "
            f"{answered} answered in the cassette; {to_make[reader]} to make"
            + ("" if record else " (saved as pending: no --record)")
        )
    total = sum(to_make.values())
    if not chosen:
        print(f"claim-readers: {len(claim_set)} claim(s), read by the grammar alone; no call.")
    if record and max_calls is None:
        print("claim-readers: --record needs --max-calls N; nothing was asked.")
        return 2
    if record and max_calls is not None and total > max_calls:
        print(f"claim-readers: {total} call(s) is above the cap of {max_calls}; nothing was asked.")
        return 2
    factory = live_factory or (lambda model: AnthropicTransport(model=model))
    model_readers = {
        reader: ModelClaimReader(
            CassetteTransport(
                cassette, live=factory(model_of[reader]) if record and to_make[reader] else None
            ),
            model_of[reader],
            name=reader,
            step=STEP_OF[reader],
        )
        for reader in chosen
    }
    rows: list[dict[str, str]] = []
    pending = 0
    for index, claim in enumerate(claim_set):
        forms = {policy.GRAMMAR_READER: _form(compile_claim(claim.text))}
        answered_by: dict[str, str] = {}
        missed = False
        for reader, model_reader in model_readers.items():
            try:
                forms[reader] = _form(model_reader.read(claim.text))
            except CassetteMiss:
                pending += 1
                missed = True
                continue
            except EngineError as exc:
                print(f"claim-readers: {claim.id} ({reader}): {exc}")
                return 1
            answered_by[reader] = _answered_by(cassette, keys[reader][index])
        if not missed:
            rows.append(_row(claim, forms, answered_by))
    if pending:
        print(
            f"claim-readers: {pending} request(s) pending in "
            f"{(cassette / 'pending').as_posix()}; answer them and run again. Nothing was written."
        )
        return 3
    if chosen:
        print(f"Answers from: {Cassette(cassette).describe()}")
    print("claim-readers: " + policy.reading_rule([policy.GRAMMAR_READER, *chosen]))
    by_conclusion: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        by_conclusion[row["conclusion"]].append(row["id"])
    for label in policy.AGREEMENT_LABELS.values():
        ids = by_conclusion.get(label, [])
        print(f"claim-readers: {label}: {len(ids)}" + (f" ({', '.join(ids)})" if ids else ""))
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"claim-readers-{claims.stem}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns(chosen))
        writer.writeheader()
        writer.writerows(rows)
    print(f"claim-readers: wrote {path.as_posix()}")
    if judge:
        judge_path = out / f"claim-readers-{claims.stem}-for-judge.md"
        judge_path.write_text(judge_file(claims.stem, rows), encoding="utf-8")
        print(f"claim-readers: wrote {judge_path.as_posix()}")
    return 0


# The file a judge reads


def _measures_in_words() -> str:
    lines = []
    for key, measure in CATALOGUE.items():
        explained = " ".join(text for text in (measure.definition, measure.note) if text)
        line = f"- `{key}`: {measure.label}"
        lines.append(f"{line}. {explained}" if explained else f"{line}.")
    return "\n".join(lines)


_PART_MEASURES = ", ".join(f"`{key}` ({label})" for key, label in PART_MEASURES.items())
# The notation is built from these tables and the grammar's own lists, so a form, function or
# period kind added to the grammar without an explanation here fails the judge's file's tests
# (tests/test_judge_notation.py) instead of reaching a judge unexplained.
CONSTRUCT_NOTES: dict[str, str] = {
    "value": "`measure[P]`: its value for period P (an amount over the period, or a balance at its "
    "end).",
    "yoy": "`yoy(measure)[P]`: its growth over the same period a year earlier, in percent.",
    "qoq": "`qoq(measure)[P]`: its growth over the previous quarter, in percent.",
    "streak": "`streak(measure)[P]`: how many periods in a row up to P it rose.",
    "cagr": "`cagr(measure, Ny)[P]`: its compound annual growth over the N years to P, in percent.",
    "change": "`change(measure, B)[P]`: its growth from period B to period P, in percent: the "
    "value at P less the value at B, over the value at B. `change(revenue, FY2023)[FY] > 100%` "
    "says revenue in the latest fiscal year is more than double fiscal 2023's.",
    "share": '`share(segment "X")[P]` or `share(geography "X")[P]`: the share of total revenue '
    "of the one segment or geographic area named X, in percent, from the company's tagged "
    "breakdown for period P.",
    "max_share": "`max(share(customer))[P]`: the largest single customer's share of revenue, in "
    "percent.",
    "part": '`revenue(segment "X")[filing]` (or `geography`): a part of the company\'s own '
    "figure, here the revenue of the segment, product line or area named X, as the newest filing "
    'tags it; `yoy(revenue(segment "X"))[filing]` its change on a year earlier as the filing '
    f"tags it. The measures a part has: {_PART_MEASURES}; only a segment has an operating income.",
    "part at a period": 'A part at a period other than `filing` (`revenue(segment "X")[FY2026]`, '
    "`[FY]`, `[Q]`): the part's figure for that fiscal year or quarter, read from the column for "
    "that period of a 10-K or 10-Q that reports it.",
    "period Q": "`Q`: the latest quarter. `Q-1` is the quarter before it; `Q-4` the same quarter "
    "a year earlier.",
    "period FY": "`FY`: the latest fiscal year. `FY-3` is three fiscal years before it.",
    "period named year": "`FY2025`: the fiscal year the company calls 2025.",
    "period named quarter": "`Q2 FY2027`: the second quarter of fiscal 2027.",
    "period TTM": "`TTM`: the four latest quarters together (the trailing twelve months); "
    "`TTM-4` the four quarters a year before.",
    "period filing": "`filing`: the newest period of the newest 10-K or 10-Q filing (for a "
    "share, or a part's figure).",
    "each": "`each(N): T`: the test T holds in each of the N latest periods: T as written, and T "
    "with every period moved one step earlier (a quarter for `Q`, a fiscal year for `FY`), and "
    "so on, N times in all. `each(4): gross_margin[Q] > 70%` says gross margin was above 70% in "
    "each of the last four quarters.",
    "each since": "`each(since FY2023): T`: the test T holds in every fiscal year after fiscal "
    "2023 up to the latest. `each(since FY2023): revenue[FY] > revenue[FY-1]` says revenue rose "
    "in every fiscal year since fiscal 2023.",
    "and": "`(A) and (B)`: both tests hold; the claim fails when either does.",
}
# Each form, with a sentence the grammar reads as that form (the test checks it does).
FORM_NOTES: dict[str, tuple[str, str]] = {
    "direction": ("Gross margin is expanding.", "a measure against itself at an earlier period"),
    "acceleration": ("Revenue growth is accelerating.", "a growth rate against the one before"),
    "streak": ("Revenue has grown for four consecutive quarters.", "a count of rises in a row"),
    "threshold": ("Gross margin is above 70%.", "a value against a constant"),
    "growth_threshold": (
        "Revenue grew more than 50% year over year.",
        "a growth rate against a percent",
    ),
    "faster_than": (
        "Payables are growing faster than cost of revenue.",
        "one measure's growth against another's over the same span",
    ),
    "compound": (
        "Revenue compounded at more than 30% a year over the last three years.",
        "a compound annual growth rate against a percent",
    ),
    "share": ("Data center is more than 80% of revenue.", "a part's share of revenue"),
    "compare": (
        "Operating cash flow was above net income in the latest fiscal year.",
        "two different measures of the same kind in the same period",
    ),
}
_PART = re.compile(r'(?<![(\w])(?:yoy\()?(\w+)\((?:segment|geography) "[^"]*"\)\)?\[([^\]]+)\]')
_TOKEN = re.compile(r"\b(yoy|qoq|streak|cagr|change|share|max)\(")
_PERIOD = re.compile(r"\[([^\]]+)\]")


def constructs(reading: str) -> set[str]:
    """The names, in :data:`CONSTRUCT_NOTES`, of every construct ``reading`` uses."""
    found = {"value"}
    found |= {"max_share" if token == "max" else token for token in _TOKEN.findall(reading)}
    if "each(since " in reading:
        found.add("each since")
    elif "each(" in reading:
        found.add("each")
    if ") and (" in reading:
        found.add("and")
    for subject, period in _PART.findall(reading):
        if subject != "share":
            found.add("part" if period == "filing" else "part at a period")
    for period in _PERIOD.findall(reading):
        if re.fullmatch(r"Q\d FY\d{4}", period):
            found.add("period named quarter")
        elif re.fullmatch(r"FY\d{4}", period):
            found.add("period named year")
        else:
            found.add("period " + period.split("-")[0])
    return found


def notation() -> str:
    """The judge's notation, from the catalogue, the grammar's lists and the tables above."""
    notes = CONSTRUCT_NOTES
    functions = "\n".join(f"- {notes[fn]}" for fn in get_args(Function))
    periods = "\n".join(
        f"- {notes[name]}"
        for name in (
            *(f"period {kind}" for kind in get_args(PeriodKind)),
            "period named year",
            "period named quarter",
        )
    )
    forms = "\n".join(
        f'- {what} ({form}): "{sentence}" is `{_example(sentence)}`.'
        for form, (sentence, what) in ((form, FORM_NOTES[form]) for form in FORMS)
    )
    return f"""## How to read a test

A test is written `left operator right`. It holds when the comparison is true.

**Operators.** `>` more than; `>=` at least; `<` less than; `<=` at most.

**Measures**, each for one company as a whole, with how a derived one is computed:

{_measures_in_words()}

**Functions of a measure.**

{functions}
- {notes["part"]}
- {notes["part at a period"]}

**Periods** (the company's own fiscal calendar).

{periods}

**Constants.** `40%` is a percent; `$100B` is 100 billion US dollars; a plain number is a count
(of periods, or of shares for the diluted share count).

**Tests over several periods, and two tests in one claim.**

- {notes["each"]}
- {notes["each since"]}
- {notes["and"]}

**The kinds of test**, each with a sentence and how it is written:

{forms}

**One way of writing.** Each test is written one way: the more recent period on the left, growth
above zero as a rise (`revenue[Q] > revenue[Q-4]` rather than `yoy(revenue)[Q] > 0%`), a count
of periods as "at least" (`>= 4` rather than `> 3`), two measures of one period in one order
(`net_income[FY] < operating_cash_flow[FY]` rather than `operating_cash_flow[FY] > net_income[FY]`),
and the two tests of an "and" in one order.
"""


def _example(sentence: str) -> str:
    test = compile_claim(sentence)
    if not isinstance(test, ClaimTest):
        raise ValueError(f"the example {sentence!r} does not compile: {test.reason}")
    return normal_form(test)


def judge_file(set_name: str, rows: Sequence[dict[str, str]]) -> str:
    """The judge's file: the notation, then every reading the rule would count, unjudged."""
    counted = [row for row in rows if row["counted"]]
    head = f"""# The readings that would count, for an independent judge ({set_name})

A program reads each claim an analyst writes about one company and, when it can, turns it into a
test that can be computed from the company's reported figures. Below are the {len(counted)} claims
of the {len(rows)} in this set whose test it would count; for the others it would count none.
For each one, decide whether the test means what the sentence says: **right** if computing the
test would answer exactly the question the sentence asks, **wrong** if it would answer a
different question (a different measure, period, comparison or threshold, or only part of the
sentence). Whether the claim is true is not the question.

"""
    table = [
        "## The tests",
        "",
        "| id | company | claim | test | verdict (right or wrong) | note |",
        "|---|---|---|---|---|---|",
    ]
    for row in counted:
        claim = row["claim"].replace("|", "/")
        table.append(f"| {row['id']} | {row['company']} | {claim} | `{row['counted']}` | | |")
    return head + notation() + "\n" + "\n".join(table) + "\n"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The command's options, for :mod:`app.evaluation.cli`."""
    parser.add_argument("--set", dest="claims", type=Path, required=True, help="the claim set")
    parser.add_argument("--cassette", type=Path, default=CASSETTE, help="the cassette")
    parser.add_argument("--record", action="store_true", help="ask the models for missing answers")
    parser.add_argument("--max-calls", type=int, help="refuse to start above this many calls")
    parser.add_argument("--out", type=Path, default=RESULTS, help="where the rows go")
    parser.add_argument(
        "--readers",
        choices=tuple(READER_SETS),
        default="models",
        help="the grammar alone, with one model reader, or with two (the default)",
    )
    parser.add_argument(
        "--judge", action="store_true", help="also write the file an independent judge reads"
    )


def main(args: argparse.Namespace) -> int:
    """Run from parsed arguments."""
    return run(
        claims=args.claims,
        cassette=args.cassette,
        record=args.record,
        max_calls=args.max_calls,
        out=args.out,
        readers=args.readers,
        judge=args.judge,
    )
