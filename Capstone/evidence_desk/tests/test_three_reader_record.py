"""A run made with both model readers on carries, in its stored record, all the page draws.

The page shows who read each claim and whether their readings agree from these fields only:
the run's ``claim_readers`` and ``claim_reading_rule``; each claim's ``readings`` (with
``normal_form``); and its computed test's ``read_by``, ``agreement``, ``agreement_label``,
``dissent``, ``combines`` and ``parts``. The readers here are fake transports answering
with the grammar's own JSON; the run is saved and read back from the store, as the API
serves it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core import policy
from app.core.claim_reading import as_reading
from app.core.claimtest import ClaimTest, compile_claim
from app.core.models import ThesisRequest
from app.core.ports import ClaimDraft
from app.engines.claim_reader import ModelClaimReader, second_reader
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import FakePages, ScriptedAnalyst
from tests.replay_run import recorded_filings
from tests.test_claim_reading import Answers

AGREED = "Gross margin has stayed above 60% for the last four quarters."
JOINED = "Gross margin is above 60% and revenue grew more than 50% year over year."
DISSENT = "Gross margin is expanding."
DIFFER = "Revenue grew more than 200% year over year."
MODELS_ONLY = "Free cash flow per employee is rising."
REFUSE = {"computable": False, "reason": "not one test", "tests": []}


def _reading(text: str) -> dict[str, Any]:
    test = compile_claim(text)
    assert isinstance(test, ClaimTest), text
    return as_reading(test)


def _stored_run(tmp_path: Path) -> dict[str, Any]:
    first = {
        AGREED: _reading(AGREED),
        JOINED: _reading(JOINED),
        DISSENT: _reading(DISSENT),
        DIFFER: _reading("Revenue grew more than 100% year over year."),
        MODELS_ONLY: _reading("Free cash flow is rising."),
    }
    second = {
        AGREED: _reading(AGREED),
        JOINED: REFUSE,
        DISSENT: _reading("Gross margin rose from the previous quarter."),
        DIFFER: _reading("Revenue grew more than 50% year over year."),
        MODELS_ONLY: _reading("Free cash flow is rising."),
    }
    readers = (
        ModelClaimReader(transport=Answers(first)),
        second_reader(transport=Answers(second)),
    )
    request = ThesisRequest(
        ticker="NVDA",
        decision="Whether to keep an overweight position",
        claims=[AGREED, JOINED, DISSENT, DIFFER, MODELS_ONLY],
    )
    store = Store(tmp_path / "record.sqlite")
    try:
        run = execute_run(
            new_run(request),
            store,
            filings=recorded_filings(),
            analyst=ScriptedAnalyst(lambda claim, passages: ClaimDraft()),
            fetch_page=FakePages({}),
            cache=FilingCache(),
            claim_reader=readers,
        )
        stored = store.get_run(run.id)
    finally:
        store.close()
    assert stored is not None
    return json.loads(stored.model_dump_json())


def test_a_three_reader_run_record_carries_every_field_the_page_draws(tmp_path: Path) -> None:
    run = _stored_run(tmp_path)
    assert run["claim_readers"] == "grammar, model and model_2"
    assert run["claim_reading_rule"] == policy.reading_rule(["grammar", "model", "model_2"])
    assert run["claim_reading_rule"].startswith("Three readers")
    claims = {claim["text"]: claim for claim in run["claims"]}
    for claim in claims.values():
        readers = [reading["reader"] for reading in claim["readings"]]
        assert readers == ["grammar", "model", "model_2"], claim["text"]
        assert all(reading["normal_form"] for reading in claim["readings"]), claim["text"]
        computed = claim["computed"]
        assert computed is not None, claim["text"]
        for field in ("read_by", "agreement", "agreement_label", "dissent", "combines", "parts"):
            assert field in computed, field
        assert computed["agreement_label"] == policy.AGREEMENT_LABELS[computed["agreement"]]

    each = claims[AGREED]["computed"]
    assert each["agreement"] == policy.AGREED and each["read_by"] == ["grammar", "model", "model_2"]
    assert each["combines"] == "each" and len(each["parts"]) == 4

    joined = claims[JOINED]["computed"]
    assert joined["agreement"] == policy.AGREED and joined["read_by"] == ["grammar", "model"]
    assert joined["combines"] == "and" and len(joined["parts"]) == 2
    assert claims[JOINED]["readings"][2]["normal_form"] == policy.NO_TEST

    dissent = claims[DISSENT]["computed"]
    assert dissent["agreement"] == policy.AGREED_WITH_DISSENT
    assert [reading["reader"] for reading in dissent["dissent"]] == ["model_2"]

    differ = claims[DIFFER]["computed"]
    assert differ["agreement"] == policy.NOT_AGREED and differ["counted_as"] == ""

    models_only = claims[MODELS_ONLY]["computed"]
    assert models_only["read_by"] == ["model", "model_2"]
    assert claims[MODELS_ONLY]["readings"][0]["normal_form"] == policy.NO_TEST
