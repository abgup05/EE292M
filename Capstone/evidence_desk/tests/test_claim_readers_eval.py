"""The claim-readers evaluation, built and tested with fake transports only.

For a claim set, each reader's normal form (or refusal), which pairs agree, the counting
rule's conclusion and empty judge columns are written with one row per claim. The command
says how many calls it will make to each model before it makes any, refuses above the cap,
and resumes from a partial cassette without asking twice. It also writes the file a judge
reads: the notation in plain words, then every reading the rule would count.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.claim_reading import as_reading
from app.core.claimtest import compile_claim
from app.core.measures import CATALOGUE
from app.engines.transport import ModelRequest
from app.evaluation import claim_readers as harness
from app.evaluation.cli import main as eval_main

CLAIMS = [
    {"id": "x1", "company": "NVDA", "text": "Gross margin is expanding."},
    {"id": "x2", "company": "NVDA", "text": "Revenue grew more than 50% year over year."},
    {"id": "x3", "company": "AAPL", "text": "The stock is cheap."},
    {"id": "x4", "company": "AAPL", "text": "Revenue is rising, & so is <b>margin</b>."},
    {"id": "x5", "company": "AAPL", "text": "Free cash flow per employee is rising."},
]
REFUSE = {"computable": False, "reason": "not one test", "tests": []}


class FakeLive:
    """A stand-in for the API: reads as the grammar does, except where told, and counts calls."""

    via = "a fake transport in the tests"

    def __init__(self, model: str, answers: dict[str, dict[str, Any]]) -> None:
        self.model = model
        self.answers = answers
        self.calls: list[ModelRequest] = []

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        self.calls.append(request)
        claim = request.user.split("<claim>")[1].split("</claim>")[0].replace("&amp;", "&")
        if claim in self.answers:
            return self.answers[claim]
        return as_reading(compile_claim(claim))


def _models() -> dict[str, FakeLive]:
    forty = as_reading(compile_claim("Revenue grew more than 40% year over year."))
    fcf = as_reading(compile_claim("Free cash flow is rising."))
    return {
        "first-model": FakeLive("first-model", {CLAIMS[1]["text"]: forty, CLAIMS[4]["text"]: fcf}),
        "second-model": FakeLive("second-model", {CLAIMS[4]["text"]: REFUSE}),
    }


def _set(tmp_path: Path) -> Path:
    path = tmp_path / "set.json"
    path.write_text(json.dumps({"claims": CLAIMS}), encoding="utf-8")
    return path


def _run(
    tmp_path: Path,
    live: dict[str, FakeLive] | None = None,
    **options: Any,
) -> int:
    def factory(model: str) -> FakeLive:
        if live is None:
            raise AssertionError("the API was asked")
        return live[model]

    return harness.run(
        claims=_set(tmp_path),
        cassette=tmp_path / "cassette",
        out=tmp_path / "results",
        live_factory=factory,
        models=("first-model", "second-model"),
        **options,
    )


def _rows(tmp_path: Path) -> list[dict[str, str]]:
    (written,) = (tmp_path / "results").glob("claim-readers-set.csv")
    with written.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_it_says_how_many_calls_per_model_before_any_and_refuses_above_the_cap(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    live = _models()
    assert _run(tmp_path, live, record=True, max_calls=9) == 2
    out = capsys.readouterr().out
    assert "model (first-model): 5 claim(s); 0 answered in the cassette; 5 to make" in out
    assert "model_2 (second-model): 5 claim(s); 0 answered in the cassette; 5 to make" in out
    assert "10 call(s) is above the cap of 9" in out
    assert all(model.calls == [] for model in live.values())
    assert not (tmp_path / "results").exists()


def test_record_needs_a_cap(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    live = _models()
    assert _run(tmp_path, live, record=True) == 2
    assert "--max-calls" in capsys.readouterr().out


def test_without_record_a_missing_answer_is_saved_as_pending_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    assert _run(tmp_path) == 3
    assert len(list((tmp_path / "cassette" / "pending").glob("*.json"))) == 10
    assert not (tmp_path / "results").exists()


def test_one_row_per_claim_with_each_readers_normal_form_the_pairs_and_the_conclusion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    live = _models()
    assert _run(tmp_path, live, record=True, max_calls=10) == 0
    assert [len(model.calls) for model in live.values()] == [5, 5]
    rows = _rows(tmp_path)
    assert [row["id"] for row in rows] == ["x1", "x2", "x3", "x4", "x5"]
    margin, growth, cheap, escaped, fcf = rows

    assert margin["grammar"] == margin["model"] == margin["model_2"]
    assert margin["agree"] == "grammar=model; grammar=model_2; model=model_2"
    assert margin["conclusion"] == "at least two readers agree"

    assert growth["grammar"] == growth["model_2"] == "yoy(revenue)[Q] > 50%"
    assert growth["model"] == "yoy(revenue)[Q] > 40%"
    assert growth["agree"] == "grammar=model_2"
    assert growth["conclusion"] == "counted, with one dissenting reading"
    assert growth["counted"] == "yoy(revenue)[Q] > 50%"
    assert growth["dissent"] == "model: yoy(revenue)[Q] > 40%"

    assert cheap["conclusion"] == "no test read" and cheap["grammar_reason"]
    assert escaped["claim"] == "Revenue is rising, & so is <b>margin</b>."
    assert fcf["model"] == "free_cash_flow[Q] > free_cash_flow[Q-4]"
    assert fcf["conclusion"] == "not counted: no two readers agree" and fcf["counted"] == ""
    assert "first-model via a fake transport" in margin["model_answered_by"]
    assert "second-model via a fake transport" in margin["model_2_answered_by"]
    for column in ("judge_counted", "judge_dissent", "judge_note"):
        assert all(row[column] == "" for row in rows)
    out = capsys.readouterr().out
    assert "counted, with one dissenting reading: 1 (x2)" in out
    assert "not counted: no two readers agree: 1 (x5)" in out

    # A second run replays every answer and asks nothing.
    assert _run(tmp_path, None) == 0


def test_a_partial_cassette_is_resumed_without_asking_twice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    live = _models()
    assert _run(tmp_path, live, record=True, max_calls=5, readers="model") == 0
    assert len(live["first-model"].calls) == 5
    capsys.readouterr()

    assert _run(tmp_path, live, record=True, max_calls=5, readers="models") == 0
    out = capsys.readouterr().out
    assert "model (first-model): 5 claim(s); 5 answered in the cassette; 0 to make" in out
    assert len(live["first-model"].calls) == 5  # nothing asked again
    assert len(live["second-model"].calls) == 5


def test_with_the_grammar_alone_nothing_is_asked_and_it_is_one_reader(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(tmp_path, None, readers="grammar") == 0
    rows = _rows(tmp_path)
    assert "model" not in rows[0]
    assert rows[0]["conclusion"] == "one reader: the grammar"
    assert "One reader" in capsys.readouterr().out


def test_the_judge_file_has_the_notation_and_every_counted_reading_and_no_judgement(
    tmp_path: Path,
) -> None:
    live = _models()
    assert _run(tmp_path, live, record=True, max_calls=10, judge=True) == 0
    text = (tmp_path / "results" / "claim-readers-set-for-judge.md").read_text()

    for key in CATALOGUE:
        assert f"`{key}`" in text, key
    assert "`>=` at least" in text and "`Q-4`" in text
    assert 'revenue(segment "X")[filing]' in text
    assert "Gross margin is expanding." in text and "`yoy(revenue)[Q] > 50%`" in text
    assert "Free cash flow per employee" not in text  # not counted
    assert "The stock is cheap." not in text
    assert "dissent" not in text.lower()  # the judge reads blind
    assert "| right |" not in text and "| wrong |" not in text


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
    assert status == 3  # no --record, so the requests are pending


def test_the_own_label_file_is_a_claim_set_too() -> None:
    claims = harness.load_claims(Path("eval/claim-tests.json"))
    assert len(claims) == 210 and all(claim.text for claim in claims)
    foreign = harness.load_claims(Path("eval/claim-tests-foreign.json"))
    assert len(foreign) == 120 and foreign[0].id == "f001" and foreign[0].company == "NVDA"
