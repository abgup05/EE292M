"""Score the claim compiler on claims its author did not write (``make claim-foreign``).

``eval/claim-tests-foreign.json`` holds 120 analyst claims written by another model
without sight of the grammar, each marked by that author "numeric" or "not_numeric".
Odd ids (f001, f003, ...) are the development half, even ids the held-out half.

The compiler's reading of a claim is judged by hand in
``eval/claim-tests-foreign-judgements.json``, one entry per claim and reading: for a
canonical test the compiler printed, ``right`` or ``wrong`` (it compiled to a test that
does not mean what the sentence says); for no test, ``not_compiled`` with a cause when
the author marked the claim numeric (``metric``: a measure the tool does not have;
``form``: a comparison the grammar does not have; ``period``: a period it cannot place;
``phrasing``: something it supports, worded in a way it misses). Every judgement has a
one-line reason. The judge is the grammar's author, so every line is there to be audited.

A reading is looked up by the claim's id and the canonical test printed now ("none"
when nothing compiled). A reading that has not been judged is reported as unjudged and
the command exits 1: a change to the grammar cannot be scored until what it now prints
has been read.

``python -m app.evaluation.foreign_claims [--write PATH]`` prints, for all 120 and for
each half: of the numeric claims, compiled and right, compiled and wrong, not compiled
by cause; of the not_numeric claims, compiled wrongly and compiled where the author's
label was wrong; then every claim with its reading. ``--write`` also writes that text.
Offline and deterministic: no model, no network.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ed_v14.core.claimtest import NotNumeric, compile_claim

CLAIMS = Path("eval/claim-tests-foreign.json")
JUDGEMENTS = Path("eval/claim-tests-foreign-judgements.json")
HALVES = ("development", "held_out")
CAUSES = ("metric", "form", "period", "phrasing")
Reading = Literal["right", "wrong", "not_compiled", "unjudged"]


@dataclass(frozen=True)
class Claim:
    """One foreign claim: id, company, text and the author's kind."""

    id: str
    company: str
    text: str
    kind: str

    @property
    def half(self) -> str:
        """``development`` for an odd id, ``held_out`` for an even one (set A's halves).

        The id's letter prefix ("f" in set A, "g" in set B) is ignored.
        """
        number = int(self.id.lstrip("abcdefghijklmnopqrstuvwxyz"))
        return "development" if number % 2 else "held_out"


@dataclass(frozen=True)
class Judged:
    """A claim, what the compiler printed now, and the judgement of that reading."""

    claim: Claim
    canonical: str
    reading: Reading
    cause: str
    label_right: bool | None
    why: str
    refusal: str = ""


@dataclass
class Tally:
    """The counts the brief asks for, over one set of judged claims."""

    claims: int = 0
    numeric: int = 0
    right: int = 0
    wrong: int = 0
    not_compiled: Counter[str] = field(default_factory=Counter)
    not_numeric: int = 0
    not_numeric_compiled_wrongly: int = 0
    not_numeric_label_wrong: int = 0
    not_numeric_not_compiled: int = 0
    unjudged: int = 0


def load_claims(path: Path = CLAIMS) -> list[Claim]:
    """The foreign claims; malformed or duplicated ones are a ValueError."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    claims = [Claim(c["id"], c["company"], c["text"], c["kind"]) for c in payload["claims"]]
    if len({c.id for c in claims}) != len(claims):
        raise ValueError("duplicate claim ids")
    if len({c.text.strip().lower() for c in claims}) != len(claims):
        raise ValueError("duplicate claim texts")
    if {c.kind for c in claims} - {"numeric", "not_numeric"}:
        raise ValueError("a claim kind is neither numeric nor not_numeric")
    return claims


def load_judgements(path: Path = JUDGEMENTS) -> dict[tuple[str, str], dict[str, object]]:
    """Every judged reading, keyed by (claim id, canonical test or "none").

    The file is only appended to. A reading judged a second time (a later rule made the
    compiler print it again, for another cause) needs ``revision``, saying what changed; the
    later judgement counts and the earlier one stays in the file.
    """
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    judged: dict[tuple[str, str], dict[str, object]] = {}
    for entry in payload["judgements"]:
        key = (str(entry["id"]), str(entry["canonical"]))
        revision = str(entry.get("revision", "")).strip()
        if key in judged and not revision:
            raise ValueError(f"{key} is judged twice")
        if revision and key not in judged:
            raise ValueError(f"{key}: a revision revises nothing judged before it")
        reading = entry["reading"]
        if reading not in ("right", "wrong", "not_compiled"):
            raise ValueError(f"{key}: unknown reading {reading!r}")
        if (reading == "not_compiled") != (key[1] == "none"):
            raise ValueError(f"{key}: not_compiled must go with no canonical test")
        if not str(entry.get("why", "")).strip():
            raise ValueError(f"{key}: a judgement needs its reason")
        judged[key] = entry
    return judged


def judge(
    claims: Sequence[Claim], judgements: dict[tuple[str, str], dict[str, object]]
) -> list[Judged]:
    """Compile each claim now and attach the judgement of what it printed."""
    result = []
    for claim in claims:
        compiled = compile_claim(claim.text)
        canonical = "none" if isinstance(compiled, NotNumeric) else compiled.canonical
        refusal = compiled.reason if isinstance(compiled, NotNumeric) else ""
        entry = judgements.get((claim.id, canonical))
        if entry is None:
            result.append(Judged(claim, canonical, "unjudged", "", None, "", refusal))
            continue
        cause = str(entry.get("cause", ""))
        if entry["reading"] == "not_compiled" and claim.kind == "numeric" and cause not in CAUSES:
            raise ValueError(f"{claim.id}: a numeric claim not compiled needs a cause in {CAUSES}")
        label_right = entry.get("label_right")
        if claim.kind == "not_numeric" and canonical != "none" and label_right is None:
            raise ValueError(f"{claim.id}: say whether the author's label or the compile is right")
        result.append(
            Judged(
                claim,
                canonical,
                entry["reading"],  # type: ignore[arg-type]
                cause,
                label_right if isinstance(label_right, bool) else None,
                str(entry["why"]),
                refusal,
            )
        )
    return result


def tally(judged: Sequence[Judged]) -> Tally:
    """Count the readings of ``judged``."""
    t = Tally(claims=len(judged))
    for j in judged:
        if j.reading == "unjudged":
            t.unjudged += 1
            continue
        if j.claim.kind == "numeric":
            t.numeric += 1
            if j.reading == "right":
                t.right += 1
            elif j.reading == "wrong":
                t.wrong += 1
            else:
                t.not_compiled[j.cause] += 1
        else:
            t.not_numeric += 1
            if j.canonical == "none":
                t.not_numeric_not_compiled += 1
            elif j.label_right is False and j.reading == "right":
                t.not_numeric_label_wrong += 1
            else:
                t.not_numeric_compiled_wrongly += 1
    return t


def _summary(name: str, t: Tally) -> list[str]:
    causes = ", ".join(f"{cause} {t.not_compiled[cause]}" for cause in CAUSES)
    missed = sum(t.not_compiled.values())
    lines = [
        f"{name}: {t.claims} claims",
        f"  numeric (author's label) {t.numeric}: compiled and right {t.right}, "
        f"compiled and wrong {t.wrong}, not compiled {missed} ({causes})",
        f"  not_numeric (author's label) {t.not_numeric}: "
        f"not compiled {t.not_numeric_not_compiled}, "
        f"compiled wrongly {t.not_numeric_compiled_wrongly}, "
        f"compiled rightly (the author's label is wrong) {t.not_numeric_label_wrong}",
    ]
    if t.unjudged:
        lines.append(f"  unjudged readings: {t.unjudged}")
    return lines


def render(judged: Sequence[Judged]) -> str:
    """The summary for all claims and each half, then one line per claim."""
    lines = ["Claim compiler on the foreign claims (judged by the grammar's author)", ""]
    lines += _summary("all", tally(judged))
    for half in HALVES:
        lines += _summary(half, tally([j for j in judged if j.claim.half == half]))
    lines += [
        "",
        "id | half | company | kind | reading | cause | canonical | claim | why | "
        "the compiler's refusal",
    ]
    for j in judged:
        cause = j.cause or ("label wrong" if j.label_right is False else "")
        lines.append(
            f"{j.claim.id} | {j.claim.half} | {j.claim.company} | {j.claim.kind} | {j.reading} | "
            f"{cause} | {j.canonical} | {j.claim.text} | {j.why} | {j.refusal}"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Print the scoring; 1 while any reading is unjudged."""
    parser = argparse.ArgumentParser(prog="python -m app.evaluation.foreign_claims")
    parser.add_argument("--claims", type=Path, default=CLAIMS)
    parser.add_argument("--judgements", type=Path, default=JUDGEMENTS)
    parser.add_argument("--write", type=Path, help="also write the text to this file")
    args = parser.parse_args(argv)
    judged = judge(load_claims(args.claims), load_judgements(args.judgements))
    text = render(judged)
    print(text, end="")
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(text, encoding="utf-8")
        print(f"Wrote {args.write.as_posix()}")
    return 1 if any(j.reading == "unjudged" for j in judged) else 0


if __name__ == "__main__":
    sys.exit(main())
