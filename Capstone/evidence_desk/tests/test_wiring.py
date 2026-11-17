"""The composition root: the environment picks the engine, the EDGAR identity and the store."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from app import wiring
from app.engines.claude import ClaudeAnalyst
from app.engines.extractive import ExtractiveAnalyst
from app.sources.edgar import DEFAULT_USER_AGENT, EdgarClient


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


def test_the_store_lives_in_the_configured_data_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EVIDENCE_DESK_DATA_DIR", str(tmp_path / "runs"))
    assert wiring.store_from_env().path == tmp_path / "runs" / "runs.sqlite"
    monkeypatch.delenv("EVIDENCE_DESK_DATA_DIR")
    assert wiring.data_dir() == Path("data/runs")


def test_importing_the_entry_points_opens_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No module reads the environment or opens a database when it is imported."""
    monkeypatch.setenv("EVIDENCE_DESK_DATA_DIR", str(tmp_path / "runs"))
    for name in ("app.wiring", "app.api", "app.cli"):
        importlib.reload(importlib.import_module(name))
    assert not (tmp_path / "runs").exists()
    assert not hasattr(importlib.import_module("app.api"), "app")
