"""The analysis examples in docs/examples/analysis are what the code gives today.

``make examples-analysis`` makes them offline from the recorded fixtures; this test makes
them again and compares, so a change to a shape cannot leave the examples behind.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests import examples_analysis


def test_the_examples_on_disk_are_what_the_generator_makes(tmp_path: Path) -> None:
    written = examples_analysis.write(tmp_path)
    assert sorted(path.name for path in written) == sorted(examples_analysis.FILES)
    for path in written:
        committed = examples_analysis.OUT / path.name
        assert committed.exists(), f"{committed} is missing: run make examples-analysis"
        assert committed.read_text(encoding="utf-8") == path.read_text(encoding="utf-8"), (
            f"{committed} is out of date: run make examples-analysis and read the diff"
        )


def test_the_computed_example_says_who_wrote_what(tmp_path: Path) -> None:
    examples_analysis.write(tmp_path)
    run = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    analysis = run["analysis"]
    assert analysis["analytics_by"] == "code" and analysis["argument_by"] == "none"
    assert analysis["argument_note"] and analysis["headline"]
    assert all(item["reading_origin"] == "code" for item in analysis["analytics"])
    built = json.loads((tmp_path / "run-hand-built-argument.json").read_text(encoding="utf-8"))
    assert built["analysis"]["argument_detail"] == examples_analysis.HAND_BUILT
    assert "no model wrote them" in built["analysis"]["argument_detail"]
    statuses = {
        item["status"] for claim in built["claims"] for item in claim["analysis"]["corollaries"]
    }
    assert {"agreed", "not_agreed", "proposer_only", "not_computable"} <= statuses
    assert all(item["question"] and item["claim_ids"] for item in analysis["analytics"])


def test_the_replayed_example_exists_exactly_when_its_answers_are_recorded() -> None:
    committed = examples_analysis.OUT / examples_analysis.REPLAYED
    run = examples_analysis.replayed()
    if not examples_analysis.analysis_recorded(run):
        assert not committed.exists(), f"{committed} is stale: its answers are not recorded"
        return
    assert committed.exists(), "run make examples-analysis"
