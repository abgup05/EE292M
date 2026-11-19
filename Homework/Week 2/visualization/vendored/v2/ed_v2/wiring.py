"""The composition root: the one place that reads the environment and builds collaborators.

The HTTP API and the command line ask this module for an engine, an EDGAR
client and a store; nothing else reads configuration. Nothing here runs at
import time: each function builds its object when it is called.
"""

from __future__ import annotations

import os
from pathlib import Path

from ed_v2.core.ports import Analyst
from ed_v2.engines.claude import ClaudeAnalyst
from ed_v2.engines.extractive import ExtractiveAnalyst
from ed_v2.sources.edgar import EdgarClient
from ed_v2.store import Store

DATA_DIR_VARIABLE = "EVIDENCE_DESK_DATA_DIR"
DEFAULT_DATA_DIR = "data/runs"
DATABASE_NAME = "runs.sqlite"
KEY_VARIABLE = "ANTHROPIC_API_KEY"
ENGINE_CHOICES = ("auto", "claude", "extractive")


class ConfigurationError(RuntimeError):
    """The requested configuration cannot be built; the message names what is missing."""


def model_key_present() -> bool:
    """True when a non-blank Anthropic API key is configured (the key itself is never read out)."""
    return bool(os.environ.get(KEY_VARIABLE, "").strip())


def analyst_from_env() -> Analyst:
    """Claude when ``ANTHROPIC_API_KEY`` is set and non-blank, otherwise the extractive engine."""
    if model_key_present():
        return ClaudeAnalyst()
    return ExtractiveAnalyst()


def analyst_named(engine: str) -> Analyst:
    """The engine called ``engine`` ("auto", "claude" or "extractive").

    Raises :class:`ConfigurationError` for an unknown name, or for "claude"
    without a key.
    """
    if engine == "auto":
        return analyst_from_env()
    if engine == "extractive":
        return ExtractiveAnalyst()
    if engine == "claude":
        if not model_key_present():
            raise ConfigurationError(f"The claude engine needs {KEY_VARIABLE} to be set")
        return ClaudeAnalyst()
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
