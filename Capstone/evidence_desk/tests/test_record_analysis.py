"""Recording the analysis answers sends only what a cassette lacks, and never past the cap.

A fake live transport stands in for the API (nothing is sent anywhere), and the cassettes are
copies under a temporary directory, so the recorded ones are never written.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.engines.transport import ModelRequest
from tests import examples_analysis
from tests.record_analysis import record
from tests.replay_run import DEFAULT_CASSETTE, CappedTransport

EMPTY_THESIS = {
    "leans_on": [],
    "weakest_link": "",
    "weakest_why": [],
    "strongest_for": [],
    "strongest_against": [],
    "bottom_line": [],
    "scenarios": [],
}


class FakeLive:
    """Answers each step with an empty, well-formed answer and counts the requests."""

    model = "fake-model"
    via = "a fake transport in tests/test_record_analysis.py"

    def __init__(self) -> None:
        self.steps: list[str] = []

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        self.steps.append(request.step)
        if request.step == "propose":
            return {"claims": []}
        return {"claims": [], "thesis": EMPTY_THESIS}


def _cassettes(tmp_path: Path) -> dict[str, Path]:
    example = tmp_path / "example"
    shutil.copytree(DEFAULT_CASSETTE, example)
    return {"example_cassette": example, "analysis_cassette": tmp_path / "analysis"}


def test_only_missing_answers_are_asked_for_and_only_once(tmp_path: Path) -> None:
    cassettes = _cassettes(tmp_path)
    live = FakeLive()
    capped = CappedTransport(live, 4)  # type: ignore[arg-type]
    record(capped, **cassettes)
    assert live.steps == ["propose", "analyse", "propose", "analyse"] and capped.sent == 4
    again = CappedTransport(live, 4)  # type: ignore[arg-type]
    lines = record(again, **cassettes)
    assert again.sent == 0 and len(live.steps) == 4, "recorded answers are not asked for again"
    assert any("argument: by model" in line for line in lines)
    with_answers = examples_analysis.write_model(tmp_path, cassettes["analysis_cassette"])
    assert [path.name for path in with_answers] == list(examples_analysis.MODEL_FILES)
    assert "fake-model" in with_answers[0].read_text(encoding="utf-8")


def test_the_cap_refuses_the_next_request_and_the_run_says_so(tmp_path: Path) -> None:
    cassettes = _cassettes(tmp_path)
    live = FakeLive()
    capped = CappedTransport(live, 1)  # type: ignore[arg-type]
    lines = record(capped, **cassettes)
    assert live.steps == ["propose"] and capped.sent == 1
    assert any("the cap of 1 model request(s) is reached" in line for line in lines)
    assert examples_analysis.write_model(tmp_path, cassettes["analysis_cassette"]) == []
