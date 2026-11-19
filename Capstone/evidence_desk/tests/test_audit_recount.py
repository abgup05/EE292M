"""The recount of the page's two live samples by today's audit rule (docs/analysis.md).

The samples are records of real runs and are never edited, so these numbers move only
when the audit's rule does: read which sentence moved before changing one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.models import Run
from tests.audit_recount import recount

WEB = Path(__file__).parent.parent / "src" / "web"


@pytest.mark.parametrize(
    ("name", "written", "then", "now", "restating"),
    [("sample-run-live.json", 105, 101, 102, 6), ("sample-run-costco.json", 92, 85, 85, 2)],
)
def test_the_live_samples_recount(
    name: str, written: int, then: int, now: int, restating: int
) -> None:
    run = Run.model_validate_json((WEB / name).read_text(encoding="utf-8"))
    counts, before, _ = recount(run)
    assert (counts.written, before, counts.verified, counts.restating) == (
        written,
        then,
        now,
        restating,
    )


def test_the_one_mark_that_moves_is_the_tests_threshold_beside_its_history() -> None:
    run = Run.model_validate_json((WEB / "sample-run-live.json").read_text(encoding="utf-8"))
    _, _, lines = recount(run)
    moved = [line for line in lines if ": was " in line]
    assert len(moved) == 1
    assert "was marked: writes 70%, which nothing it cites carries; now verified" in moved[0]
    assert "restates a threshold: 70% (test:c2); not checked as a fact" in moved[0]
