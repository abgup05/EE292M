"""Recorded model answers to this engine's exact prompts still produce the recorded verdicts.

The cassette ``demo/cassettes/nvda-example`` holds answers recorded once for the
example thesis on the recorded NVIDIA filings (see ``docs/cassettes.md``). The
replay builds every prompt afresh, so a changed prompt, schema, passage or figure
no longer finds its answer and the test fails instead of skipping. It does not
call the model and does not exercise the SDK request: it proves that the prompts
are the ones that were answered, and that the gate and verdict rule turn those
answers into the recorded verdicts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.models import Run
from app.store import Store
from tests.golden_run import REPLAY_PATH, replay_copy, replay_record
from tests.replay_run import DEFAULT_CASSETTE

CASSETTE = Path(__file__).parent.parent / DEFAULT_CASSETTE
STALE = (
    "the prompts no longer match the cassette: re-record it (docs/cassettes.md) "
    "and review the new answers"
)


@pytest.fixture(scope="module")
def replayed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Run, list[str], Path]:
    """One replay of a copy of the cassette, shared by the checks below."""
    scratch = tmp_path_factory.mktemp("replay")
    run, pending = replay_copy(CASSETTE, scratch)
    return run, pending, scratch


def test_every_model_request_is_answered_by_the_cassette(
    replayed: tuple[Run, list[str], Path],
) -> None:
    _, pending, _ = replayed
    assert not pending, f"{len(pending)} request(s) pending: {STALE}"


def test_no_engine_step_fell_back(replayed: tuple[Run, list[str], Path]) -> None:
    run, _, _ = replayed
    assert run.engine == "claude"
    assert run.coverage.engine_fallbacks == 0, run.errors


def test_every_replayed_excerpt_is_an_exact_slice_of_its_filing(
    replayed: tuple[Run, list[str], Path],
) -> None:
    run, _, scratch = replayed
    stored = Store(scratch / "replay.sqlite").get_source_texts(run.id)
    assert run.evidence, "the recorded answers quote the filings"
    for item in run.evidence:
        text = stored[item.source_id]
        assert text[item.start : item.start + len(item.excerpt)] == item.excerpt, item.id


def test_each_claim_has_its_recorded_verdict_and_counts(
    replayed: tuple[Run, list[str], Path],
) -> None:
    run, pending, _ = replayed
    assert not pending, STALE
    assert replay_record(run) == json.loads(REPLAY_PATH.read_text()), (
        "the replayed verdicts or finding counts differ from tests/golden/replay.json: the gate "
        "or the verdict rule now reads the same answers differently; if intended, run "
        "`make golden-baseline` and read the diff"
    )
