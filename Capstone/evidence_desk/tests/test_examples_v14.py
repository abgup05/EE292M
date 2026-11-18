"""The version 14 example payloads in docs/examples/v14 are what the code gives today.

They are made offline from the recorded fixtures by ``make examples``; this test makes
them again and compares, so a change to a shape cannot leave the examples behind.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests import examples_v14


def test_the_examples_on_disk_are_what_the_generator_makes(tmp_path: Path) -> None:
    written = examples_v14.write(tmp_path)
    assert sorted(path.name for path in written) == sorted(examples_v14.FILES)
    for path in written:
        committed = examples_v14.OUT / path.name
        assert committed.exists(), f"{committed} is missing: run make examples"
        assert committed.read_text(encoding="utf-8") == path.read_text(encoding="utf-8"), (
            f"{committed} is out of date: run make examples and read the diff"
        )


def test_the_examples_show_compiled_claims_histories_and_a_date(tmp_path: Path) -> None:
    examples_v14.write(tmp_path)
    run = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    computed = [claim["computed"] for claim in run["claims"] if claim["computed"]]
    assert {test["outcome"] for test in computed} == {"holds", "fails", "cannot_compute"}
    assert any(test["history"] for test in computed)
    assert any(claim["compile_note"] for claim in run["claims"])
    dated = json.loads((tmp_path / "as-of-run.json").read_text(encoding="utf-8"))
    assert dated["inputs"]["as_of"] == examples_v14.AS_OF
    assert dated["as_of"]["requested"] == examples_v14.AS_OF
    ledger = json.loads((tmp_path / "restatements.json").read_text(encoding="utf-8"))
    assert ledger["periods_restated"] > 0 and ledger["entries"]


# The example run with two model readers (run-readers.json)


def test_the_readers_example_exists_exactly_when_its_answers_are_recorded(tmp_path: Path) -> None:
    committed = examples_v14.OUT / examples_v14.READERS_FILE
    if examples_v14.unrecorded_reads():
        assert not committed.exists(), f"{committed} is stale: its answers are not recorded"
        assert examples_v14.write_readers(tmp_path) is None
        return
    written = examples_v14.write_readers(tmp_path)
    assert written is not None and committed.exists(), "run make examples"
    assert committed.read_text(encoding="utf-8") == written.read_text(encoding="utf-8")


def _fake_cassette(directory: Path) -> None:
    """A cassette answering every read of the example's claims: the grammar's own JSON, or a
    refusal, under the requests a run makes (a stand-in for a recording)."""
    from app.core.claim_reading import as_reading
    from app.core.claimtest import compile_claim
    from app.engines.cassette import request_key
    from app.engines.claim_reader import READ_STEP, SECOND_READ_STEP, read_request

    refuse = {"computable": False, "reason": "not one test", "tests": []}
    responses = directory / "responses"
    responses.mkdir(parents=True)
    for claim in examples_v14.reader_claims():
        compiled = compile_claim(claim)
        answer = as_reading(compiled) if not hasattr(compiled, "reason") else refuse
        for step in (READ_STEP, SECOND_READ_STEP):
            key = request_key(read_request(claim, step))
            envelope = {
                "key": key,
                "step": step,
                "via": "a fake in the tests",
                "model": "fake",
                "recorded_at": "2026-11-18T12:00:00+00:00",
                "response": answer,
            }
            (responses / f"{key}.json").write_text(json.dumps(envelope), encoding="utf-8")


def test_the_readers_example_is_a_run_read_by_the_grammar_and_two_models(tmp_path: Path) -> None:
    cassette = tmp_path / "cassette"
    _fake_cassette(cassette)
    assert examples_v14.unrecorded_reads(cassette) == 0
    written = examples_v14.write_readers(tmp_path / "out", cassette)
    assert written is not None and written.name == examples_v14.READERS_FILE
    run = json.loads(written.read_text(encoding="utf-8"))
    assert run["claim_readers"] == "grammar, model and model_2"
    assert run["claim_reading_rule"].startswith("Three readers")
    assert [claim["text"] for claim in run["claims"]] == examples_v14.reader_claims()
    for claim in run["claims"]:
        assert [r["reader"] for r in claim["readings"]] == ["grammar", "model", "model_2"]
    assert run["errors"] == [] or all("reader" not in error for error in run["errors"])


def test_the_readers_example_writes_nothing_while_a_read_is_unrecorded(tmp_path: Path) -> None:
    empty = tmp_path / "cassette"
    (empty / "responses").mkdir(parents=True)
    assert examples_v14.unrecorded_reads(empty) == 2 * len(examples_v14.reader_claims())
    assert examples_v14.write_readers(tmp_path / "out", empty) is None
    assert not (empty / "pending").exists()  # the example never writes into a cassette
