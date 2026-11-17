"""Record and replay of model answers: a cassette directory of responses and pending requests.

No network: a stub stands in for the SDK client, and live transports are plain functions.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.models import Claim, Company, ThesisRequest
from app.engines.cassette import Cassette, CassetteMiss, CassetteTransport, request_key
from app.engines.claude import ClaudeAnalyst, EngineError
from app.engines.transport import AnthropicTransport, ModelRequest

REQUEST = ModelRequest(
    step="plan",
    system="You plan.",
    user='<claims>\n<claim number="1">Revenue grows</claim>\n</claims>',
    schema={"type": "object", "properties": {"claims": {"type": "array"}}},
    max_tokens=16_000,
)
ANSWER = {"claims": [{"claim_number": 1, "queries": ["revenue increase", "revenue decline"]}]}
SECRET = "sk-ant-test-secret-never-recorded"


def write_response(directory: Path, request: ModelRequest, response: Any, **fields: Any) -> Path:
    envelope = {
        "key": request_key(request),
        "step": request.step,
        "via": "hand",
        "model": "m",
        "recorded_at": "2026-11-17T10:00:00+00:00",
        "response": response,
    } | fields
    path = directory / "responses" / f"{request_key(request)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope))
    return path


# The key


def test_the_key_is_stable_and_ignores_max_tokens() -> None:
    key = request_key(REQUEST)
    assert len(key) == 24 and int(key, 16) >= 0
    assert request_key(ModelRequest(**{**REQUEST.__dict__, "max_tokens": 5})) == key
    reordered = ModelRequest(
        step="plan",
        system="You plan.",
        user=REQUEST.user,
        schema={"properties": {"claims": {"type": "array"}}, "type": "object"},
        max_tokens=1,
    )
    assert request_key(reordered) == key


@pytest.mark.parametrize("field", ["step", "system", "user"])
def test_the_key_changes_with_every_prompt_field(field: str) -> None:
    changed = ModelRequest(**{**REQUEST.__dict__, field: getattr(REQUEST, field) + "x"})
    assert request_key(changed) != request_key(REQUEST)


def test_the_key_changes_with_the_schema() -> None:
    changed = ModelRequest(**{**REQUEST.__dict__, "schema": {"type": "object"}})
    assert request_key(changed) != request_key(REQUEST)


def test_the_key_is_the_sha256_of_canonical_json() -> None:
    import hashlib

    canonical = json.dumps(
        {
            "step": REQUEST.step,
            "system": REQUEST.system,
            "user": REQUEST.user,
            "schema": REQUEST.schema,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert request_key(REQUEST) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


# Hit, miss with a live transport, miss without one


def test_a_hit_returns_the_stored_response_without_calling_live(tmp_path: Path) -> None:
    write_response(tmp_path, REQUEST, ANSWER)

    def live(request: ModelRequest) -> dict[str, Any]:
        raise AssertionError("live must not be called on a hit")

    assert CassetteTransport(tmp_path, live=live)(REQUEST) == ANSWER


def test_a_hit_removes_a_stale_pending_file(tmp_path: Path) -> None:
    with pytest.raises(CassetteMiss):
        CassetteTransport(tmp_path)(REQUEST)
    write_response(tmp_path, REQUEST, ANSWER)
    assert CassetteTransport(tmp_path)(REQUEST) == ANSWER
    assert Cassette(tmp_path).pending() == []


def test_a_miss_with_live_records_the_answer_and_removes_the_pending_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(CassetteMiss):
        CassetteTransport(tmp_path)(REQUEST)
    assert len(Cassette(tmp_path).pending()) == 1

    calls: list[ModelRequest] = []

    def live(request: ModelRequest) -> dict[str, Any]:
        calls.append(request)
        return ANSWER

    live.model = "claude-test"  # type: ignore[attr-defined]
    transport = CassetteTransport(tmp_path, live=live, via="the Anthropic API")
    assert transport(REQUEST) == ANSWER
    assert calls == [REQUEST]
    key = request_key(REQUEST)
    envelope = json.loads((tmp_path / "responses" / f"{key}.json").read_text())
    assert set(envelope) == {"key", "step", "via", "model", "recorded_at", "response"}
    assert envelope["key"] == key and envelope["step"] == "plan"
    assert envelope["via"] == "the Anthropic API" and envelope["model"] == "claude-test"
    assert envelope["recorded_at"].endswith("+00:00")
    assert envelope["response"] == ANSWER
    assert Cassette(tmp_path).pending() == []
    # The second call replays.
    assert transport(REQUEST) == ANSWER and len(calls) == 1


def test_a_miss_without_live_writes_the_exact_request_as_pending(tmp_path: Path) -> None:
    transport = CassetteTransport(tmp_path)
    key = request_key(REQUEST)
    with pytest.raises(CassetteMiss) as caught:
        transport(REQUEST)
    assert isinstance(caught.value, EngineError)
    assert str(caught.value) == (
        f"no recorded response for plan; request saved as pending/{key}.json"
    )
    pending = json.loads((tmp_path / "pending" / f"{key}.json").read_text())
    assert pending["key"] == key and pending["step"] == "plan"
    assert pending["system"] == REQUEST.system and pending["user"] == REQUEST.user
    assert pending["schema"] == REQUEST.schema
    assert "responses/" in pending["how_to_answer"]
    assert "docs/cassettes.md" in pending["how_to_answer"]
    assert transport.pending_keys == [key]
    assert not (tmp_path / "responses").exists() or not list((tmp_path / "responses").iterdir())


def test_a_miss_blocks_later_steps_without_writing_them(tmp_path: Path) -> None:
    """An assessment built on an unanswered plan would be the wrong request; it is not saved."""
    transport = CassetteTransport(tmp_path)
    with pytest.raises(CassetteMiss):
        transport(REQUEST)
    later = ModelRequest(**{**REQUEST.__dict__, "step": "assess", "user": "claim one"})
    sibling = ModelRequest(**{**REQUEST.__dict__, "user": "another plan"})
    with pytest.raises(CassetteMiss, match="earlier plan request"):
        transport(later)
    with pytest.raises(CassetteMiss):
        transport(sibling)
    assert sorted(path.stem for path in Cassette(tmp_path).pending()) == sorted(
        [request_key(REQUEST), request_key(sibling)]
    )


def test_a_new_plan_starts_a_new_run(tmp_path: Path) -> None:
    transport = CassetteTransport(tmp_path)
    assess = ModelRequest(**{**REQUEST.__dict__, "step": "assess"})
    summary = ModelRequest(**{**REQUEST.__dict__, "step": "summarize"})
    write_response(tmp_path, REQUEST, ANSWER)
    with pytest.raises(CassetteMiss):
        transport(assess)
    with pytest.raises(CassetteMiss, match="earlier assess request"):
        transport(summary)
    assert transport(REQUEST) == ANSWER
    write_response(tmp_path, assess, {"findings": []})
    assert transport(assess) == {"findings": []}
    with pytest.raises(CassetteMiss, match="pending/"):
        transport(summary)


def test_a_pending_check_blocks_the_summary_but_not_the_next_claims_assessment(
    tmp_path: Path,
) -> None:
    """Claims are assessed and checked in turn; assessing after a pending check is no new run."""
    transport = CassetteTransport(tmp_path)
    assess_1 = ModelRequest(**{**REQUEST.__dict__, "step": "assess", "user": "claim one"})
    assess_2 = ModelRequest(**{**REQUEST.__dict__, "step": "assess", "user": "claim two"})
    check_1 = ModelRequest(**{**REQUEST.__dict__, "step": "check", "user": "check one"})
    check_2 = ModelRequest(**{**REQUEST.__dict__, "step": "check", "user": "check two"})
    summary = ModelRequest(**{**REQUEST.__dict__, "step": "summarize"})
    for request in (REQUEST, assess_1, assess_2):
        write_response(tmp_path, request, ANSWER)
    assert transport(REQUEST) == ANSWER and transport(assess_1) == ANSWER
    with pytest.raises(CassetteMiss, match="pending/"):
        transport(check_1)
    assert transport(assess_2) == ANSWER
    with pytest.raises(CassetteMiss, match="pending/"):
        transport(check_2)
    with pytest.raises(CassetteMiss, match="earlier check request"):
        transport(summary)
    assert transport.pending_keys == [request_key(check_1), request_key(check_2)]
    assert sorted(p.stem for p in Cassette(tmp_path).pending()) == sorted(transport.pending_keys)


def test_a_check_built_on_a_missing_assessment_is_not_saved(tmp_path: Path) -> None:
    transport = CassetteTransport(tmp_path)
    assess = ModelRequest(**{**REQUEST.__dict__, "step": "assess"})
    check = ModelRequest(**{**REQUEST.__dict__, "step": "check"})
    with pytest.raises(CassetteMiss, match="pending/"):
        transport(assess)
    with pytest.raises(CassetteMiss, match="earlier assess request"):
        transport(check)
    assert transport.pending_keys == [request_key(assess)]


def test_a_sibling_shares_the_run_so_the_engines_miss_blocks_its_check(tmp_path: Path) -> None:
    engine = CassetteTransport(tmp_path)
    sibling = engine.sibling()
    assess = ModelRequest(**{**REQUEST.__dict__, "step": "assess"})
    check = ModelRequest(**{**REQUEST.__dict__, "step": "check"})
    with pytest.raises(CassetteMiss):
        engine(assess)
    with pytest.raises(CassetteMiss, match="earlier assess request"):
        sibling(check)
    assert sibling.pending_keys == engine.pending_keys == [request_key(assess)]
    assert sibling.detail == engine.detail and sibling.directory == engine.directory


def test_a_recording_sibling_records_with_its_own_model(tmp_path: Path) -> None:
    def engine_model(request: ModelRequest) -> dict[str, Any]:
        return ANSWER

    def check_model(request: ModelRequest) -> dict[str, Any]:
        return {"judgements": []}

    engine_model.model = "claude-engine-test"  # type: ignore[attr-defined]
    check_model.model = "claude-check-test"  # type: ignore[attr-defined]
    engine = CassetteTransport(tmp_path, live=engine_model, via="the Anthropic API")
    sibling = engine.sibling(live=check_model, via="the Anthropic API")
    check = ModelRequest(**{**REQUEST.__dict__, "step": "check"})
    assert engine(REQUEST) == ANSWER and sibling(check) == {"judgements": []}
    envelope = json.loads((tmp_path / "responses" / f"{request_key(check)}.json").read_text())
    assert envelope["model"] == "claude-check-test" and envelope["step"] == "check"
    plan = json.loads((tmp_path / "responses" / f"{request_key(REQUEST)}.json").read_text())
    assert plan["model"] == "claude-engine-test"


@pytest.mark.parametrize(
    "content",
    ["not json", json.dumps([1, 2]), json.dumps({"key": "k"})],
)
def test_a_malformed_response_file_is_an_engine_error(tmp_path: Path, content: str) -> None:
    path = tmp_path / "responses" / f"{request_key(REQUEST)}.json"
    path.parent.mkdir(parents=True)
    path.write_text(content)
    with pytest.raises(EngineError, match="recorded response"):
        CassetteTransport(tmp_path)(REQUEST)


@pytest.mark.parametrize("response", [[1, 2], "text", None, 3])
def test_a_stored_response_that_is_not_an_object_is_an_engine_error(
    tmp_path: Path, response: object
) -> None:
    write_response(tmp_path, REQUEST, response)
    with pytest.raises(EngineError, match="not a JSON object"):
        CassetteTransport(tmp_path)(REQUEST)


# Describing a cassette


def test_describe_names_who_recorded_what_and_when(tmp_path: Path) -> None:
    directory = tmp_path / "nvda-example"
    other = ModelRequest(**{**REQUEST.__dict__, "user": "two"})
    third = ModelRequest(**{**REQUEST.__dict__, "user": "three"})
    write_response(directory, REQUEST, ANSWER, via="Claude Code", model="claude-opus-5-5")
    write_response(
        directory,
        other,
        ANSWER,
        via="the Anthropic API",
        model="claude-opus-5-5",
        recorded_at="2026-11-19T08:00:00+00:00",
    )
    write_response(
        directory, third, ANSWER, via="Claude Code", model="claude-fable-5", recorded_at=""
    )
    cassette = Cassette(directory)
    assert cassette.responses() == 3
    assert cassette.describe() == (
        "replayed from cassette nvda-example: 3 responses recorded via Claude Code and "
        "the Anthropic API with claude-fable-5 and claude-opus-5-5, 2026-11-17 to 2026-11-19"
    )


def test_describe_an_empty_cassette(tmp_path: Path) -> None:
    assert Cassette(tmp_path / "fresh").describe() == (
        "replayed from cassette fresh: no responses recorded"
    )
    assert Cassette(tmp_path / "fresh").pending() == []


def test_the_engine_detail_in_cassette_mode_is_the_description(tmp_path: Path) -> None:
    write_response(tmp_path, REQUEST, ANSWER)
    engine = ClaudeAnalyst(transport=CassetteTransport(tmp_path))
    assert engine.detail == Cassette(tmp_path).describe()
    assert engine.detail.startswith("replayed from cassette ")


# No secret is ever written


def test_no_secret_is_ever_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    answer = {"claims": [], "note": "verbatim"}

    def live(request: ModelRequest) -> dict[str, Any]:
        return answer

    transport = CassetteTransport(tmp_path, live=live)
    with pytest.raises(CassetteMiss):
        CassetteTransport(tmp_path)(ModelRequest(**{**REQUEST.__dict__, "user": "pending"}))
    assert transport(REQUEST) == answer
    [recorded] = (tmp_path / "responses").iterdir()
    envelope = json.loads(recorded.read_text())
    assert envelope["response"] == answer
    assert set(envelope) == {"key", "step", "via", "model", "recorded_at", "response"}
    for path in tmp_path.rglob("*.json"):
        text = path.read_text().lower()
        assert SECRET.lower() not in text
        assert "authorization" not in text and "x-api-key" not in text and "api_key" not in text


# The engine over a cassette parses exactly as over the API


class StubMessages:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def create(self, **kwargs: object) -> object:
        self.calls += 1
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(self.payload))],
        )


THESIS = ThesisRequest(
    ticker="NVDA",
    decision="Keep the position into the next earnings report",
    claims=["Data center revenue is still growing"],
)
COMPANY = Company(cik=1045810, ticker="NVDA", name="NVIDIA CORP")


def test_the_engine_over_a_cassette_parses_exactly_as_over_the_api(tmp_path: Path) -> None:
    from app.core.documents import Passage

    payload = {
        "findings": [
            {
                "statement": "Data Center revenue grew 56%.",
                "stance": "supports",
                "confidence": "high",
                "rationale": "The filing reports growth.",
                "quotes": [{"passage_id": "p1", "text": "Data Center revenue grew 56%"}],
                "figure_ids": ["m-1"],
            }
        ],
        "rationale": "Read it.",
        "unknowns": ["Next quarter."],
    }
    claim = Claim(id="c-1", text=THESIS.claims[0])
    text = "Data Center revenue grew 56%."
    passages = [Passage(id="p1", source_id="s1", locator="L", text=text, start=0)]
    messages = StubMessages(payload)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    over_api = ClaudeAnalyst(client=client, model="m").assess(THESIS, COMPANY, claim, passages)

    recording = ClaudeAnalyst(
        transport=CassetteTransport(tmp_path, live=AnthropicTransport(client=client, model="m"))
    )
    assert recording.assess(THESIS, COMPANY, claim, passages) == over_api
    replay = ClaudeAnalyst(transport=CassetteTransport(tmp_path))
    assert replay.assess(THESIS, COMPANY, claim, passages) == over_api
    assert messages.calls == 2
    [recorded] = (tmp_path / "responses").iterdir()
    assert json.loads(recorded.read_text())["model"] == "m"
