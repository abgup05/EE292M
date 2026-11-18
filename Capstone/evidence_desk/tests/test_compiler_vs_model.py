"""The compiler-vs-model harness, built and tested with a fake transport only.

A model is given the same reported-figure lines a run offers plus one claim of the
golden computed claims, and asked for holds, fails or cannot tell, through the
cassette. The harness says how many calls it will make before it makes any, and
refuses to start above the cap given on the command line.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from app.engines.transport import ModelRequest
from app.evaluation import compiler_vs_model as harness

KEY = Path("eval/claim-results.json")


class FakeLive:
    """A stand-in for the API: answers "holds" to everything, and counts its calls."""

    via = "a fake transport in the tests"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls: list[ModelRequest] = []

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        self.calls.append(request)
        return {"answer": "holds", "reason": "The figures show it."}


def _cases() -> list[dict[str, Any]]:
    return json.loads(KEY.read_text())["cases"]


def test_each_case_becomes_one_request_with_the_figures_and_the_claim() -> None:
    cases = _cases()
    requests = harness.build_requests(cases)
    assert len(requests) == len(cases)
    case, request = requests[0]
    assert request.step == harness.STEP
    assert "<figure id=" in request.user and case["claim"] in request.user
    assert set(request.schema["properties"]["answer"]["enum"]) == {"holds", "fails", "cannot_tell"}
    # The figures are those of the company as of the case's date: nothing later.
    for case, request in requests:
        assert case["as_of"] in request.user
    late = [
        case["id"]
        for case, request in requests
        for line in request.user.splitlines()
        if 'period="' in line and _period_end(line) > case["as_of"]
    ]
    assert late == []


def _period_end(line: str) -> str:
    period = line.split('period="', 1)[1].split('"', 1)[0]
    return period.rsplit(" ", 1)[-1]


def test_it_says_how_many_calls_it_will_make_and_stops_above_the_cap(
    tmp_path: Path, capsys
) -> None:
    live = FakeLive()
    code = harness.run(
        key=KEY,
        cassette=tmp_path / "cassette",
        record=True,
        max_calls=10,
        out=tmp_path / "results",
        live_factory=lambda: live,
    )
    out = capsys.readouterr().out
    assert code == 2 and live.calls == []
    assert f"{len(_cases())} request(s) to make" in out and "cap of 10" in out


def test_recording_needs_a_cap(tmp_path: Path) -> None:
    live = FakeLive()
    code = harness.run(
        key=KEY,
        cassette=tmp_path / "c",
        record=True,
        max_calls=None,
        out=tmp_path,
        live_factory=lambda: live,
    )
    assert code == 2 and live.calls == []


def test_without_record_the_requests_are_left_pending_and_nothing_is_scored(
    tmp_path: Path, capsys
) -> None:
    code = harness.run(
        key=KEY, cassette=tmp_path / "c", record=False, max_calls=None, out=tmp_path / "r"
    )
    assert code == 3
    assert len(list((tmp_path / "c" / "pending").glob("*.json"))) == len(_cases())
    assert not (tmp_path / "r").exists()
    assert "pending" in capsys.readouterr().out


def test_recorded_answers_are_scored_beside_the_compiler(tmp_path: Path, capsys) -> None:
    live = FakeLive()
    cases = _cases()
    code = harness.run(
        key=KEY,
        cassette=tmp_path / "c",
        record=True,
        max_calls=len(cases),
        out=tmp_path / "r",
        live_factory=lambda: live,
    )
    assert code == 0 and len(live.calls) == len(cases)
    out = capsys.readouterr().out
    holds = sum(case["expected"]["outcome"] == "holds" for case in cases)
    assert f"compiler: {len(cases)} of {len(cases)}" in out
    assert f"model: {holds} of {len(cases)}" in out
    assert "a fake transport in the tests" in out
    [record] = (tmp_path / "r").glob("compiler-vs-model-*.json")
    body = json.loads(record.read_text())
    assert body["model"]["agree"] == holds and body["compiler"]["agree"] == len(cases)
    assert body["answers_from"].startswith("replayed from cassette c")
    # A second run makes no call: every answer is in the cassette.
    again = FakeLive()
    assert (
        harness.run(
            key=KEY,
            cassette=tmp_path / "c",
            record=True,
            max_calls=0,
            out=tmp_path / "r",
            live_factory=lambda: again,
        )
        == 0
    )
    assert again.calls == []
    assert "0 request(s) to make" in capsys.readouterr().out
    assert date.today().isoformat()[:4] in record.name


def test_make_eval_reaches_it_without_contacting_edgar(tmp_path: Path, monkeypatch) -> None:
    from app.evaluation import cli

    def no_edgar(*args: object, **kwargs: object) -> None:
        raise AssertionError("the harness must not contact EDGAR")

    monkeypatch.setattr(cli.EdgarClient, "from_env", no_edgar)
    argv = ["run", "compiler-vs-model", "--cassette", str(tmp_path / "c"), "--out", str(tmp_path)]
    assert cli.main(argv) == 3
