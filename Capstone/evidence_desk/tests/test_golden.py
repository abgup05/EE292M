"""The tripwire: the whole offline example run must match the checked-in golden record.

Any upstream change (a parser tweak, a limit, a prompt, the ranking, the gate,
the verdict rule, the figures) moves ``tests/golden/golden.json``. The failure
names the first stage that moved, in pipeline order, and shows the first
entries that differ. See ``docs/testing.md`` for when a new baseline is legitimate.
"""

from __future__ import annotations

import json

from tests.golden_run import GOLDEN_PATH, STAGES, build_golden, changed_stages

HOW_TO_PROCEED = (
    "If the change was intended, run `make golden-baseline`, read the diff of "
    "tests/golden/golden.json stage by stage, and commit it with the change that caused it. "
    "If it was not intended, the change altered an answer: start at the '{stage}' stage, "
    "since every stage before it still matches."
)
SHOWN = 3


def first_differences(golden: object, current: object) -> list[str]:
    """Up to :data:`SHOWN` lines naming the first keys or positions where two values differ."""
    if isinstance(golden, dict) and isinstance(current, dict):
        keys = sorted(set(golden) | set(current))
        pairs = [(str(k), golden.get(k), current.get(k)) for k in keys]
    elif isinstance(golden, list) and isinstance(current, list):
        length = max(len(golden), len(current))
        pad = [None] * length
        pairs = [
            (f"[{i}]", (golden + pad)[i], (current + pad)[i])
            for i in range(length)
            if i >= min(len(golden), len(current)) or golden[i] != current[i]
        ]
    else:
        pairs = [("value", golden, current)]
    lines = [
        f"  {where}: golden {json.dumps(old, sort_keys=True)[:300]}\n"
        f"  {' ' * len(where)}  now    {json.dumps(new, sort_keys=True)[:300]}"
        for where, old, new in pairs
        if old != new
    ]
    return lines[:SHOWN]


def test_the_example_run_matches_the_golden_record() -> None:
    golden = json.loads(GOLDEN_PATH.read_text())
    current = build_golden()
    moved = changed_stages(golden, current)
    if moved:
        first = moved[0]
        others = f" (later stages that also differ: {', '.join(moved[1:])})" if moved[1:] else ""
        details = "\n".join(first_differences(golden.get(first), current.get(first)))
        raise AssertionError(
            f"The tripwire moved: the first stage that differs is '{first}'{others}.\n"
            f"{details}\n" + HOW_TO_PROCEED.format(stage=first)
        )
    assert set(current) == {*STAGES, "sha256"}, "the golden record has an unexpected shape"
    assert current["sha256"] == golden["sha256"], (
        "Every stage matches but the sha256 does not: tests/golden/golden.json was edited by hand "
        "or holds a key outside the stages. Rewrite it with `make golden-baseline`."
    )
