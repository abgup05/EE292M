"""Which recorded excerpts would the quote gate refuse today? (sixth referee, finding 1)

Since version 14.3 a quote may not end between a number and its scale word or unit,
nor begin between a sign or currency symbol and its number
(:func:`app.core.gate.is_whole`). A recorded run was gated by the rule of its day,
and every evidence item it kept carries its excerpt with the text just before and
just after it, so the rule of today can be asked about each one without the filing:
``context_before + excerpt + context_after`` is the stored text around the span.

``make gate-edge-audit`` runs this over every committed JSON record that holds
evidence (the recorded runs under ``demo/``, the examples under ``docs/examples/``,
the page's samples under ``src/web/``, the tripwire's baselines) and prints, per
file, how many excerpts it holds and each one today's gate would refuse, with the
characters on both sides of the boundary. It reads and changes nothing: a record of
a run is not edited because a later rule would have decided otherwise. Exit code 0
whatever it finds.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.core.gate import _splits, is_whole
from app.core.numcheck import quantity_cut

DEFAULT_ROOTS = ("demo", "docs/examples", "src/web", "tests/golden", "eval/results")
SHOWN = 24


def evidence_items(node: Any) -> Iterator[dict[str, Any]]:
    """Every evidence item under ``node``: a mapping with an excerpt and both contexts."""
    if isinstance(node, dict):
        fields = [node.get(name) for name in ("excerpt", "context_before", "context_after")]
        if all(isinstance(value, str) for value in fields):
            yield node
        for value in node.values():
            yield from evidence_items(value)
    elif isinstance(node, list):
        for value in node:
            yield from evidence_items(value)


def refusal(item: dict[str, Any]) -> str:
    """Why today's gate would refuse ``item``'s span, or "" when it would keep it."""
    before, excerpt, after = item["context_before"], item["excerpt"], item["context_after"]
    text = before + excerpt + after
    begin, end = len(before), len(before) + len(excerpt)
    if is_whole(text, begin, end):
        return ""
    reasons = []
    if _splits(text, begin):
        reasons.append("begins inside a word or a number")
    elif quantity_cut(text, begin) == "head":
        reasons.append("begins between a sign or currency symbol and its number")
    if _splits(text, end):
        reasons.append("ends inside a word or a number")
    elif quantity_cut(text, end) == "tail":
        reasons.append("ends between a number and its scale word or unit")
    return "; ".join(reasons)


def audit(path: Path) -> tuple[int, list[str]]:
    """How many evidence items ``path`` holds, and a line for each today's gate would refuse."""
    items = list(evidence_items(json.loads(path.read_text(encoding="utf-8"))))
    lines: list[str] = []
    for item in items:
        why = refusal(item)
        if why:
            before, after = item["context_before"][-SHOWN:], item["context_after"][:SHOWN]
            excerpt = item["excerpt"]
            shown = excerpt
            if len(excerpt) > 2 * SHOWN:
                shown = f"{excerpt[:SHOWN]}…{excerpt[-SHOWN:]}"
            name = f"{item.get('id', '?')} of {item.get('finding_id', '?')}"
            lines.append(f"  {name}: {why}: {before!r} | {shown!r} | {after!r}")
    return len(items), lines


def main(argv: list[str] | None = None) -> int:
    """Audit the JSON files under the given roots and print the result."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("roots", nargs="*", type=Path, default=[Path(r) for r in DEFAULT_ROOTS])
    args = parser.parse_args(argv)
    paths = sorted(
        path for root in args.roots for path in ([root] if root.is_file() else root.rglob("*.json"))
    )
    files = excerpts = refused = 0
    for path in paths:
        try:
            count, lines = audit(path)
        except (OSError, ValueError) as exc:
            print(f"{path}: not read ({type(exc).__name__})")
            continue
        if not count:
            continue
        files += 1
        excerpts += count
        refused += len(lines)
        print(f"{path}: {count} excerpts, {len(lines)} refused today")
        for line in lines:
            print(line)
    print(f"{files} files with evidence, {excerpts} excerpts, {refused} refused by today's gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
