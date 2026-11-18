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
