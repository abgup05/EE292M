"""The two readers of a claim set side by side, one row per claim, for a judge to mark.

``make eval ARGS='claim-readers --set eval/claim-tests-foreign.json --record --max-calls 120'``
reads every claim of a set with the grammar (:func:`app.core.claimtest.compile_claim`)
and with the model parser (:class:`app.engines.claim_reader.ModelClaimReader`), through
:class:`~app.engines.cassette.CassetteTransport`, and writes
``eval/results/claim-readers-<set>.csv``: the claim, each reader's canonical test (or
``none`` and why), whether they agree, who answered for the model (from the cassette),
and three empty columns for the judge. Nothing is scored here: whether a reading is
right is the judge's to mark.

A set is either a file with ``claims`` (``id``, ``text`` and optionally ``company``), as
the foreign sets are, or the own label file with ``development`` and ``held_out``
(``id``, ``claim``). Before any call it prints how many requests are already answered in
the cassette and how many it would make; with ``--record`` it refuses to start when that
is more than ``--max-calls`` (which ``--record`` requires). Without ``--record`` a
missing answer is saved under ``pending/`` (``docs/cassettes.md``) and the command exits
3, writing nothing.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.core import policy
from app.core.claimtest import ClaimTest, NotNumeric, compile_claim
from app.engines.cassette import RESPONSES, Cassette, CassetteMiss, CassetteTransport, request_key
from app.engines.claim_reader import ModelClaimReader
from app.engines.transport import AnthropicTransport, EngineError, Transport

CASSETTE = Path("eval/cassettes/claim-readers")
RESULTS = Path("eval/results")
COLUMNS = (
    "id",
    "company",
    "claim",
    "grammar",
    "grammar_reason",
    "model",
    "model_reason",
    "agree",
    "model_answered_by",
    "judge_grammar",
    "judge_model",
    "judge_note",
)


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


def _reading(result: ClaimTest | NotNumeric) -> tuple[str, str]:
    if isinstance(result, NotNumeric):
        return policy.NO_TEST, result.reason
    return result.canonical, ""


def _answered_by(cassette: Path, key: str) -> str:
    envelope = json.loads((cassette / RESPONSES / f"{key}.json").read_text(encoding="utf-8"))
    return f"{envelope['model']} via {envelope['via']}, recorded {envelope['recorded_at']}"


def run(
    *,
    claims: Path,
    cassette: Path = CASSETTE,
    record: bool = False,
    max_calls: int | None = None,
    out: Path = RESULTS,
    live_factory: Callable[[], Transport] | None = None,
) -> int:
    """Read, compare and write; 2 when the calls would pass the cap, 3 while any is missing."""
    claim_set = load_claims(claims)
    keys = [request_key(ModelClaimReader.request(claim.text)) for claim in claim_set]
    answered = sum((cassette / RESPONSES / f"{key}.json").exists() for key in keys)
    to_make = len(keys) - answered
    how = "to the model" if record else "(saved as pending: no --record)"
    print(
        f"claim-readers: {len(keys)} claim(s); {answered} answered in the cassette; "
        f"{to_make} request(s) to make {how}."
    )
    if record and max_calls is None:
        print("claim-readers: --record needs --max-calls N; nothing was asked.")
        return 2
    if record and max_calls is not None and to_make > max_calls:
        print(
            f"claim-readers: {to_make} call(s) is above the cap of {max_calls}; nothing was asked."
        )
        return 2
    model = ModelClaimReader(transport=lambda request: {}).model
    factory = live_factory or (lambda: AnthropicTransport(model=model))
    live = factory() if record and to_make else None
    reader = ModelClaimReader(transport=CassetteTransport(cassette, live=live), model=model)
    rows: list[dict[str, str]] = []
    pending = 0
    for claim, key in zip(claim_set, keys, strict=True):
        try:
            model_reading = _reading(reader.read(claim.text))
        except CassetteMiss:
            pending += 1
            continue
        except EngineError as exc:
            print(f"claim-readers: {claim.id}: {exc}")
            return 1
        grammar_reading = _reading(compile_claim(claim.text))
        agree = grammar_reading[0] == model_reading[0]
        rows.append(
            {
                "id": claim.id,
                "company": claim.company,
                "claim": claim.text,
                "grammar": grammar_reading[0],
                "grammar_reason": grammar_reading[1],
                "model": model_reading[0],
                "model_reason": model_reading[1],
                "agree": "yes" if agree else "no",
                "model_answered_by": _answered_by(cassette, key),
                "judge_grammar": "",
                "judge_model": "",
                "judge_note": "",
            }
        )
    if pending:
        print(
            f"claim-readers: {pending} request(s) pending in "
            f"{(cassette / 'pending').as_posix()}; answer them and run again. Nothing was written."
        )
        return 3
    agreed = sum(row["agree"] == "yes" for row in rows)
    both = sum(row["agree"] == "yes" and row["grammar"] != policy.NO_TEST for row in rows)
    print(f"Answers from: {Cassette(cassette).describe()}")
    print(
        f"claim-readers: agree {agreed} of {len(rows)} ({both} on the same test, "
        f"{agreed - both} both reading none); differ {len(rows) - agreed}."
    )
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"claim-readers-{claims.stem}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"claim-readers: wrote {path.as_posix()}")
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The command's options, for :mod:`app.evaluation.cli`."""
    parser.add_argument("--set", dest="claims", type=Path, required=True, help="the claim set")
    parser.add_argument("--cassette", type=Path, default=CASSETTE, help="the cassette")
    parser.add_argument("--record", action="store_true", help="ask the model for missing answers")
    parser.add_argument("--max-calls", type=int, help="refuse to start above this many calls")
    parser.add_argument("--out", type=Path, default=RESULTS, help="where the rows go")


def main(args: argparse.Namespace) -> int:
    """Run from parsed arguments."""
    return run(
        claims=args.claims,
        cassette=args.cassette,
        record=args.record,
        max_calls=args.max_calls,
        out=args.out,
    )
