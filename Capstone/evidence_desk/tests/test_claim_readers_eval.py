"""The claim-readers evaluation, built and tested with a fake transport only.

For a claim set, the grammar's reading, the model parser's reading and whether they agree
are written to a file with one row per claim, for a judge to mark. The command says how
many calls it will make before it makes any and refuses above the cap.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.claim_reading import as_reading
from app.core.claimtest import compile_claim
from app.engines.transport import ModelRequest
from app.evaluation import claim_readers as harness
from app.evaluation.cli import main as eval_main

CLAIMS = [
    {"id": "x1", "company": "NVDA", "text": "Gross margin is expanding.", "kind": "numeric"},
    {"id": "x2", "company": "NVDA", "text": "Revenue grew more than 50% year over year."},
    {"id": "x3", "company": "AAPL", "text": "The stock is cheap."},
    {"id": "x4", "company": "AAPL", "text": "Revenue is rising, & so is <b>margin</b>."},
]


class FakeLive:
    """A stand-in for the API: reads as the grammar does, except one claim, and counts calls."""

    via = "a fake transport in the tests"
    model = "fake-reader"

    def __init__(self) -> None:
        self.calls: list[ModelRequest] = []

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        self.calls.append(request)
        claim = request.user.split("<claim>")[1].split("</claim>")[0]
        if claim.startswith("Revenue grew"):
            other = compile_claim("Revenue grew more than 40% year over year.")
            return as_reading(other)
        return as_reading(compile_claim(claim.replace("&amp;", "&")))


def _set(tmp_path: Path) -> Path:
    path = tmp_path / "set.json"
    path.write_text(json.dumps({"claims": CLAIMS}), encoding="utf-8")
    return path


def _run(tmp_path: Path, live: FakeLive | None = None, **options: Any) -> int:
    def factory() -> FakeLive:
        if live is None:
            raise AssertionError("the API was asked")
        return live

    return harness.run(
        claims=_set(tmp_path),
        cassette=tmp_path / "cassette",
        out=tmp_path / "results",
        live_factory=factory,
        **options,
    )


def test_it_says_how_many_calls_before_any_and_refuses_above_the_cap(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    live = FakeLive()
    assert _run(tmp_path, live, record=True, max_calls=3) == 2
    out = capsys.readouterr().out
    assert "4 claim(s); 0 answered in the cassette; 4 request(s) to make" in out
    assert "above the cap of 3" in out
    assert live.calls == []
    assert not (tmp_path / "results").exists()


def test_record_needs_a_cap(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    live = FakeLive()
    assert _run(tmp_path, live, record=True) == 2
    assert "--max-calls" in capsys.readouterr().out
    assert live.calls == []


def test_without_record_a_missing_answer_is_saved_as_pending_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    assert _run(tmp_path) == 3
    assert len(list((tmp_path / "cassette" / "pending").glob("*.json"))) == 4
    assert not (tmp_path / "results").exists()


def test_one_row_per_claim_with_both_readings_and_whether_they_agree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    live = FakeLive()
    assert _run(tmp_path, live, record=True, max_calls=4) == 0
    assert len(live.calls) == 4
    (written,) = (tmp_path / "results").glob("claim-readers-set.csv")
    with written.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["id"] for row in rows] == ["x1", "x2", "x3", "x4"]
    first, second, third, fourth = rows
    assert first["grammar"] == first["model"] == "gross_margin[Q] > gross_margin[Q-4]"
    assert first["agree"] == "yes"
    assert second["grammar"] == "yoy(revenue)[Q] > 50%"
    assert second["model"] == "yoy(revenue)[Q] > 40%"
    assert second["agree"] == "no"
    assert third["grammar"] == third["model"] == "none" and third["agree"] == "yes"
    assert third["grammar_reason"] and third["model_reason"]
    assert fourth["claim"] == "Revenue is rising, & so is <b>margin</b>."
    assert "fake-reader via a fake transport in the tests" in first["model_answered_by"]
    for column in ("judge_grammar", "judge_model", "judge_note"):
        assert all(row[column] == "" for row in rows)
    out = capsys.readouterr().out
    assert "agree 3 of 4" in out and "differ 1" in out and "fake-reader" in out

    # A second run replays every answer and asks nothing.
    assert _run(tmp_path, None) == 0


def test_it_runs_from_make_eval(tmp_path: Path) -> None:
    status = eval_main(
        [
            "claim-readers",
            "--set",
            str(_set(tmp_path)),
            "--cassette",
            str(tmp_path / "cassette"),
            "--out",
            str(tmp_path / "results"),
        ]
    )
    assert status == 3  # no --record, so the four requests are pending


def test_the_own_label_file_is_a_claim_set_too() -> None:
    claims = harness.load_claims(Path("eval/claim-tests.json"))
    assert len(claims) == 210 and all(claim.text for claim in claims)
    foreign = harness.load_claims(Path("eval/claim-tests-foreign.json"))
    assert len(foreign) == 120 and foreign[0].id == "f001" and foreign[0].company == "NVDA"
