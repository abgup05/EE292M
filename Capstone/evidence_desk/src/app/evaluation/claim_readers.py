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
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from app.core import policy
from app.core.claim_normal import normal_form
from app.core.claimtest import ClaimTest, NotNumeric, compile_claim
from app.core.measures import CATALOGUE, PART_MEASURES
from app.engines.cassette import RESPONSES, Cassette, CassetteMiss, CassetteTransport, request_key
from app.engines.claim_reader import (
    READ_STEP,
    SECOND_READ_STEP,
    ModelClaimReader,
    first_model,
    read_request,
    second_model,
)
from app.engines.transport import AnthropicTransport, EngineError, Transport

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
        line = f"- `{key}`: {measure.label.lower()}"
        lines.append(f"{line}. {explained}" if explained else f"{line}.")
    return "\n".join(lines)


NOTATION = """## How to read a test

A test is written `left operator right`. It holds when the comparison is true.

**Operators.** `>` more than; `>=` at least; `<` less than; `<=` at most.

**Measures**, each for one company as a whole, with how a derived one is computed:

{measures}

**Functions of a measure.**

- `measure[P]`: its value for period P (an amount over the period, or a balance at its end).
- `yoy(measure)[P]`: its growth over the same period a year earlier, in percent.
- `qoq(measure)[P]`: its growth over the previous quarter, in percent.
- `streak(measure)[P]`: how many periods in a row up to P it rose.
- `cagr(measure, Ny)[P]`: its compound annual growth over the N years to P, in percent.
- `share(segment "X")[filing]` or `share(geography "X")[filing]`: the share of total revenue of
  the one segment or geographic area named X, as the company's newest filing tags it, in percent.
- `max(share(customer))[filing]`: the largest single customer's share of revenue, in percent.
- `revenue(segment "X")[filing]` (or `geography`): a part of the company's own figure, here the
  revenue of the segment, product line or area named X, as the newest filing tags it;
  `yoy(revenue(segment "X"))[filing]` its change on a year earlier as the filing tags it. The
  measures a part has: {parts}; only a segment has an operating income.

**Periods** (the company's own fiscal calendar).

- `Q`: the latest quarter. `Q-1` is the quarter before it; `Q-4` the same quarter a year earlier.
- `FY`: the latest fiscal year. `FY-3` is three fiscal years before it.
- `FY2025`: the fiscal year the company calls 2025. `Q2 FY2027`: the second quarter of fiscal 2027.
- `TTM`: the four latest quarters together (the trailing twelve months); `TTM-4` the four
  quarters a year before.
- `filing`: the newest 10-K or 10-Q filing (for a share, or a part's figure).

**Constants.** `40%` is a percent; `$100B` is 100 billion US dollars; a plain number is a count
(of periods, or of shares for the diluted share count).

**One way of writing.** Each test is written one way: the more recent period on the left, growth
above zero as a rise (`revenue[Q] > revenue[Q-4]` rather than `yoy(revenue)[Q] > 0%`), and a count
of periods as "at least" (`>= 4` rather than `> 3`).

Example: "Gross margin is expanding" becomes `gross_margin[Q] > gross_margin[Q-4]`: the latest
quarter's gross margin is higher than the same quarter's a year earlier.
"""


def judge_file(set_name: str, rows: Sequence[dict[str, str]]) -> str:
    """The judge's file: the notation, then every reading the rule would count, unjudged."""
    counted = [row for row in rows if row["counted"]]
    head = f"""# Set {set_name}: the readings that would count, for an independent judge

A program reads each claim an analyst writes about one company and, when it can, turns it into a
test that can be computed from the company's reported figures. Below are the claims of this set
whose test it would count ({len(counted)} of {len(rows)}; for the others it would count none). For
each one, decide whether the test means what the sentence says: **right** if computing the test
would answer exactly the question the sentence asks, **wrong** if it would answer a different
question (a different measure, period, comparison or threshold, or only part of the sentence).
Whether the claim is true is not the question.

"""
    notation = NOTATION.format(
        measures=_measures_in_words(),
        parts=", ".join(f"`{key}` ({label.lower()})" for key, label in PART_MEASURES.items()),
    )
    table = [
        "## The tests",
        "",
        "| id | company | claim | test | verdict (right or wrong) | note |",
        "|---|---|---|---|---|---|",
    ]
    for row in counted:
        claim = row["claim"].replace("|", "/")
        table.append(f"| {row['id']} | {row['company']} | {claim} | `{row['counted']}` | | |")
    return head + notation + "\n" + "\n".join(table) + "\n"


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
