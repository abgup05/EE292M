"""The recount of four live runs by today's audit rule (docs/analysis.md).

Two are the page's live samples of version 14.2, kept under tests/fixtures/audit_recount when
the page's samples were made again on version 14.3's code; two are the page's samples now.
A record of a real run is never edited, so these numbers move only when the audit's rule
does: read which sentence moved before changing one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.models import Run
from tests.audit_recount import recount

ROOT = Path(__file__).parent.parent
OLD = ROOT / "tests" / "fixtures" / "audit_recount"
WEB = ROOT / "src" / "web"


RECOUNTS = [
    (OLD / "run-8a12ef614117.json", 105, 101, 102, 6),
    (OLD / "run-72359824897a.json", 92, 85, 88, 2),
    (WEB / "sample-run-live.json", 108, 107, 107, 9),
    (WEB / "sample-run-costco.json", 92, 88, 88, 1),
]


@pytest.mark.parametrize(
    ("name", "written", "then", "now", "restating"),
    RECOUNTS,
)
def test_the_live_samples_recount(
    name: Path, written: int, then: int, now: int, restating: int
) -> None:
    run = Run.model_validate_json(name.read_text(encoding="utf-8"))
    counts, before, _ = recount(run)
    assert (counts.written, before, counts.verified, counts.restating) == (
        written,
        then,
        now,
        restating,
    )


def test_the_one_mark_that_moves_is_the_tests_threshold_beside_its_history() -> None:
    run = Run.model_validate_json((OLD / "run-8a12ef614117.json").read_text(encoding="utf-8"))
    _, _, lines = recount(run)
    moved = [line for line in lines if ": was " in line]
    assert len(moved) == 1
    assert "was marked: writes 70%, which nothing it cites carries; now verified" in moved[0]
    assert "restates a threshold: 70% (test:c2); not checked as a fact" in moved[0]
