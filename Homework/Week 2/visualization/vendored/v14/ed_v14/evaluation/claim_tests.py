"""Score the claim compiler against hand-labelled claims (``make claim-labels``).

``python -m app.evaluation.claim_tests [--set development|held_out]`` compiles every
labelled claim of ``eval/claim-tests.json`` with :func:`app.core.claimtest.compile_claim`
and prints how many print exactly the expected canonical test ("none" included), split
into the claims expected to compile and those expected not to, then every mismatch.
Offline and deterministic: no model, no network.

The held-out set is scored at most twice, at the first working grammar and at the
final one, so that it is never tuned on: each scoring of it is written to
``eval/results/claim-tests-held_out-<UTC>.txt``, and a third is refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ed_v14.core.claimtest import FORMS, NotNumeric, compile_claim

DEFAULT_LABELS = Path("eval/claim-tests.json")
RESULTS = Path("eval/results")
SETS = ("development", "held_out")
HELD_OUT_SCORINGS = 2


@dataclass(frozen=True)
class Label:
    """One labelled claim: its id, its text, the expected canonical test or "none"."""

    id: str
    claim: str
    expected: str
    form: str


@dataclass
class Score:
    """Exact matches over the set, by whether the claim was expected to compile."""

    total: int = 0
    exact: int = 0
    compiled_expected: int = 0
    compiled_right: int = 0
    none_expected: int = 0
    none_right: int = 0
    mismatches: list[tuple[str, str, str, str]] = field(default_factory=list)


def load_labels(path: Path) -> tuple[list[Label], list[Label]]:
    """The development and held-out labels; a malformed one is a ValueError."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    sets: list[list[Label]] = []
    for name in SETS:
        labels: list[Label] = []
        for entry in payload[name]:
            label = Label(entry["id"], entry["claim"], entry["expected"], entry["form"])
            if label.form != "none" and label.form not in FORMS:
                raise ValueError(f"unknown form {label.form!r} for {label.id}")
            if (label.form == "none") != (label.expected == "none"):
                raise ValueError(f"{label.id}: form and expected disagree about 'none'")
            labels.append(label)
        sets.append(labels)
    return sets[0], sets[1]


def compiled_text(claim: str) -> str:
    """What the compiler prints for a claim: its canonical test, or "none"."""
    result = compile_claim(claim)
    return "none" if isinstance(result, NotNumeric) else result.canonical


def score(labels: Sequence[Label]) -> Score:
    """Compile every claim and count exact agreement with its label."""
    result = Score(total=len(labels))
    for label in labels:
        got = compiled_text(label.claim)
        right = got == label.expected
        result.exact += right
        if label.expected == "none":
            result.none_expected += 1
            result.none_right += right
        else:
            result.compiled_expected += 1
            result.compiled_right += right
        if not right:
            result.mismatches.append((label.id, label.claim, label.expected, got))
    return result


def render(result: Score, name: str) -> str:
    """The score as plain text, then each mismatch with what was expected and what came out."""
    lines = [
        f"Claim compiler on the {name} labels: {result.exact} of {result.total} exact.",
        f"  expected to compile: {result.compiled_right} of {result.compiled_expected} exact",
        f"  expected none:       {result.none_right} of {result.none_expected} exact",
    ]
    if result.mismatches:
        lines += ["", "Mismatches:"]
        for label_id, claim, expected, got in result.mismatches:
            lines += [f"  {label_id} {claim}", f"    expected {expected}", f"    got      {got}"]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, *, results: Path = RESULTS) -> int:
    """Score one set and print it; 2 when a third held-out scoring is asked for."""
    parser = argparse.ArgumentParser(prog="python -m app.evaluation.claim_tests")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--set", choices=SETS, default="development", dest="which")
    args = parser.parse_args(argv)
    development, held_out = load_labels(args.labels)
    if args.which == "held_out":
        done = sorted(results.glob("claim-tests-held_out-*.txt"))
        if len(done) >= HELD_OUT_SCORINGS:
            print(
                f"The held-out set has been scored {len(done)} times "
                f"({', '.join(p.name for p in done)}); it is not scored again.",
                file=sys.stderr,
            )
            return 2
    labels = development if args.which == "development" else held_out
    text = render(score(labels), args.which)
    print(text)
    if args.which == "held_out":
        results.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = results / f"claim-tests-held_out-{stamp}.txt"
        path.write_text(text + "\n", encoding="utf-8")
        print(f"\nWrote {path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
