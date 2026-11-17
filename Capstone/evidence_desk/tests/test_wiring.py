"""The composition root: the environment picks the engine, the EDGAR identity and the store."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

import pytest

from app import wiring
from app.engines.cassette import CassetteTransport
from app.engines.checker import ClaudeChecker, NoChecker
from app.engines.claude import ClaudeAnalyst
from app.engines.extractive import ExtractiveAnalyst
from app.engines.transport import AnthropicTransport
from app.sources.edgar import DEFAULT_USER_AGENT, EdgarClient


@pytest.fixture(autouse=True)
def no_cassette(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts without the cassette variables, whatever the host's .env says."""
    monkeypatch.delenv("EVIDENCE_DESK_CASSETTE", raising=False)
    monkeypatch.delenv("EVIDENCE_DESK_CASSETTE_RECORD", raising=False)


@pytest.mark.parametrize("key", [None, "", "   "])
def test_no_model_key_means_the_extractive_engine(
    monkeypatch: pytest.MonkeyPatch, key: str | None
) -> None:
    if key is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    assert isinstance(wiring.analyst_from_env(), ExtractiveAnalyst)


def test_a_model_key_means_the_claude_engine_with_the_configured_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test-model")
    analyst = wiring.analyst_from_env()
    assert isinstance(analyst, ClaudeAnalyst) and analyst.model == "claude-test-model"


def test_an_engine_can_be_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(wiring.analyst_named("extractive"), ExtractiveAnalyst)
    assert isinstance(wiring.analyst_named("auto"), ExtractiveAnalyst)
    with pytest.raises(wiring.ConfigurationError, match="ANTHROPIC_API_KEY"):
        wiring.analyst_named("claude")
    with pytest.raises(wiring.ConfigurationError, match="unknown engine"):
        wiring.analyst_named("oracle")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    assert isinstance(wiring.analyst_named("claude"), ClaudeAnalyst)


def test_filings_identify_themselves_to_edgar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", "Example Research ops@example.com")
    with wiring.filings_from_env() as client:
        assert isinstance(client, EdgarClient)
        assert client.user_agent == "Example Research ops@example.com"
    monkeypatch.delenv("SEC_USER_AGENT")
    with wiring.filings_from_env() as client:
        assert client.user_agent == DEFAULT_USER_AGENT


def test_the_record_and_the_cache_live_apart_in_the_configured_data_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EVIDENCE_DESK_DATA_DIR", str(tmp_path / "data"))
    assert wiring.store_from_env().path == tmp_path / "data" / "record" / "record.sqlite"
    assert wiring.cache_from_env().path == tmp_path / "data" / "cache" / "filings.sqlite"
    monkeypatch.delenv("EVIDENCE_DESK_DATA_DIR")
    assert wiring.data_dir() == Path("data")
    assert wiring.record_path() == Path("data/record/record.sqlite")


def test_a_version_3_database_is_mentioned_once_and_left_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    old = tmp_path / "runs" / "runs.sqlite"
    old.parent.mkdir()
    old.write_bytes(b"a version 3 database")
    monkeypatch.setenv("EVIDENCE_DESK_DATA_DIR", str(tmp_path))
    with caplog.at_level(logging.WARNING, logger="app.wiring"):
        wiring.store_from_env()
        wiring.store_from_env()
    notes = [r.getMessage() for r in caplog.records if "version 3" in r.getMessage()]
    assert notes == [f"found a version 3 database at {old}; it is not read"]
    assert old.read_bytes() == b"a version 3 database"


def test_importing_the_entry_points_opens_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No module reads the environment or opens a database when it is imported."""
    monkeypatch.setenv("EVIDENCE_DESK_DATA_DIR", str(tmp_path / "runs"))
    for name in ("app.wiring", "app.api", "app.cli"):
        importlib.reload(importlib.import_module(name))
    assert not (tmp_path / "runs").exists()
    assert not hasattr(importlib.import_module("app.api"), "app")


def cassette_of(analyst: object) -> CassetteTransport:
    assert isinstance(analyst, ClaudeAnalyst)
    assert isinstance(analyst.transport, CassetteTransport)
    return analyst.transport


@pytest.mark.parametrize("key", [None, "test-key-not-real"])
def test_a_cassette_replays_without_recording_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, key: str | None
) -> None:
    monkeypatch.setenv("EVIDENCE_DESK_CASSETTE", str(tmp_path / "cassette"))
    if key is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    transport = cassette_of(wiring.analyst_from_env())
    assert transport.directory == tmp_path / "cassette"
    assert transport.live is None


def test_a_cassette_records_only_with_a_key_and_the_record_switch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EVIDENCE_DESK_CASSETTE", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_DESK_CASSETTE_RECORD", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cassette_of(wiring.analyst_from_env()).live is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test-model")
    live = cassette_of(wiring.analyst_from_env()).live
    assert isinstance(live, AnthropicTransport) and live.model == "claude-test-model"
    monkeypatch.setenv("EVIDENCE_DESK_CASSETTE_RECORD", "yes")
    assert cassette_of(wiring.analyst_from_env()).live is None


def test_the_cassette_engine_replays_the_named_directory_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("EVIDENCE_DESK_CASSETTE_RECORD", "1")
    transport = cassette_of(wiring.analyst_named("cassette", cassette=tmp_path))
    assert transport.directory == tmp_path and transport.live is None
    with pytest.raises(wiring.ConfigurationError, match="cassette directory"):
        wiring.analyst_named("cassette")


# The meaning checker


def checker_transport(checker: object) -> CassetteTransport:
    assert isinstance(checker, ClaudeChecker)
    assert isinstance(checker.transport, CassetteTransport)
    return checker.transport


@pytest.mark.parametrize("key", [None, "", "   "])
def test_no_key_and_no_cassette_means_no_checker(
    monkeypatch: pytest.MonkeyPatch, key: str | None
) -> None:
    if key is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    assert isinstance(wiring.checker_from_env(), NoChecker)


def test_a_key_means_the_claude_checker_on_its_own_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-engine-model")
    monkeypatch.setenv("ANTHROPIC_CHECK_MODEL", "claude-check-model")
    checker = wiring.checker_from_env(wiring.analyst_from_env())
    assert isinstance(checker, ClaudeChecker) and checker.model == "claude-check-model"
    assert isinstance(checker.transport, AnthropicTransport)
    assert checker.transport.model == "claude-check-model"


def test_with_a_cassette_the_checker_shares_the_engines_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EVIDENCE_DESK_CASSETTE", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    analyst = wiring.analyst_from_env()
    engine = cassette_of(analyst)
    shared = checker_transport(wiring.checker_from_env(analyst))
    assert shared is not engine and shared.directory == tmp_path and shared.live is None
    assert shared.pending_keys is engine.pending_keys  # one run: a pending check blocks the summary
    alone = checker_transport(wiring.checker_from_env())
    assert alone.directory == tmp_path and alone.live is None


def test_a_recording_cassette_records_checks_with_the_check_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EVIDENCE_DESK_CASSETTE", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_DESK_CASSETTE_RECORD", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-engine-model")
    monkeypatch.setenv("ANTHROPIC_CHECK_MODEL", "claude-check-model")
    live = checker_transport(wiring.checker_from_env(wiring.analyst_from_env())).live
    assert isinstance(live, AnthropicTransport) and live.model == "claude-check-model"


def test_each_named_engine_has_its_checker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    replaying = wiring.analyst_named("cassette", cassette=tmp_path)
    over_cassette = checker_transport(wiring.checker_named("cassette", replaying))
    assert (
        over_cassette.live is None
        and over_cassette.pending_keys is cassette_of(replaying).pending_keys
    )
    assert isinstance(wiring.checker_named("extractive", ExtractiveAnalyst()), NoChecker)
    over_api = wiring.checker_named("claude", wiring.analyst_named("claude"))
    assert isinstance(over_api, ClaudeChecker)
    assert isinstance(over_api.transport, AnthropicTransport)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert isinstance(wiring.checker_named("auto", ExtractiveAnalyst()), NoChecker)
