"""The composition root: the one place that reads the environment and builds collaborators.

The HTTP API and the command line ask this module for an engine, an EDGAR
client and a store; nothing else reads configuration. Nothing here runs at
import time: each function builds its object when it is called.
"""

from __future__ import annotations

import os
from pathlib import Path

from ed_v3.core.ports import Analyst
from ed_v3.engines.cassette import CassetteTransport
from ed_v3.engines.claude import ClaudeAnalyst
from ed_v3.engines.extractive import ExtractiveAnalyst
from ed_v3.engines.transport import AnthropicTransport
from ed_v3.sources.edgar import EdgarClient
from ed_v3.store import Store

DATA_DIR_VARIABLE = "EVIDENCE_DESK_DATA_DIR"
DEFAULT_DATA_DIR = "data/runs"
DATABASE_NAME = "runs.sqlite"
KEY_VARIABLE = "ANTHROPIC_API_KEY"
CASSETTE_VARIABLE = "EVIDENCE_DESK_CASSETTE"
RECORD_VARIABLE = "EVIDENCE_DESK_CASSETTE_RECORD"
ENGINE_CHOICES = ("auto", "claude", "extractive", "cassette")


class ConfigurationError(RuntimeError):
    """The requested configuration cannot be built; the message names what is missing."""


def model_key_present() -> bool:
    """True when a non-blank Anthropic API key is configured (the key itself is never read out)."""
    return bool(os.environ.get(KEY_VARIABLE, "").strip())


def cassette_analyst(directory: Path, *, record: bool = False) -> ClaudeAnalyst:
    """The Claude engine answering from the cassette at ``directory``.

    With ``record`` a request the cassette lacks is sent to the Anthropic API
    and its answer recorded; without it the request is saved as pending.
    """
    live = AnthropicTransport() if record else None
    return ClaudeAnalyst(transport=CassetteTransport(directory, live=live))


def analyst_from_env() -> Analyst:
    """The engine the environment configures.

    With ``EVIDENCE_DESK_CASSETTE`` set: the Claude engine over that cassette,
    recording from the API only when ``ANTHROPIC_API_KEY`` is set and
    ``EVIDENCE_DESK_CASSETTE_RECORD`` is ``1``. Otherwise Claude when
    ``ANTHROPIC_API_KEY`` is set and non-blank, else the extractive engine.
    """
    cassette = os.environ.get(CASSETTE_VARIABLE, "").strip()
    if cassette:
        record = model_key_present() and os.environ.get(RECORD_VARIABLE, "").strip() == "1"
        return cassette_analyst(Path(cassette), record=record)
    if model_key_present():
        return ClaudeAnalyst()
    return ExtractiveAnalyst()


def analyst_named(engine: str, cassette: Path | None = None) -> Analyst:
    """The engine called ``engine`` ("auto", "claude", "extractive" or "cassette").

    "cassette" replays the cassette at ``cassette`` and never calls the API.
    Raises :class:`ConfigurationError` for an unknown name, for "claude"
    without a key, or for "cassette" without a directory.
    """
    if engine == "auto":
        return analyst_from_env()
    if engine == "extractive":
        return ExtractiveAnalyst()
    if engine == "claude":
        if not model_key_present():
            raise ConfigurationError(f"The claude engine needs {KEY_VARIABLE} to be set")
        return ClaudeAnalyst()
    if engine == "cassette":
        if cassette is None:
            raise ConfigurationError("The cassette engine needs a cassette directory (--cassette)")
        return cassette_analyst(cassette)
    raise ConfigurationError(
        f"unknown engine {engine!r}; choose one of {', '.join(ENGINE_CHOICES)}"
    )


def filings_from_env() -> EdgarClient:
    """An EDGAR client identifying itself with ``SEC_USER_AGENT`` (or the default)."""
    return EdgarClient.from_env()


def data_dir() -> Path:
    """Where runs are stored: ``$EVIDENCE_DESK_DATA_DIR``, default ``data/runs``."""
    return Path(os.environ.get(DATA_DIR_VARIABLE, "").strip() or DEFAULT_DATA_DIR)


def store_from_env() -> Store:
    """The SQLite store at ``data_dir()/runs.sqlite``, created if needed."""
    return Store(data_dir() / DATABASE_NAME)
