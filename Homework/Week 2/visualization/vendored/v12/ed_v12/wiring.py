"""The composition root: the one place that reads the environment and builds collaborators.

The HTTP API and the command line ask this module for an engine, a meaning
checker, an EDGAR client, the record store and the filing cache; nothing else reads
configuration. Nothing here runs at import time: each function builds its
object when it is called.

The data directory (``$EVIDENCE_DESK_DATA_DIR``, default ``data``) holds
``record/record.sqlite`` (the record: back it up) and ``cache/filings.sqlite``
(disposable). A version 3 database at ``runs/runs.sqlite`` is left alone, not read.
"""

from __future__ import annotations

import functools
import logging
import os
from pathlib import Path

from ed_v12.core.ports import Analyst, Checker
from ed_v12.engines.cassette import CassetteTransport
from ed_v12.engines.checker import ClaudeChecker, NoChecker, configured_check_model
from ed_v12.engines.claude import ClaudeAnalyst
from ed_v12.engines.extractive import ExtractiveAnalyst
from ed_v12.engines.transport import AnthropicTransport
from ed_v12.sources.edgar import EdgarClient
from ed_v12.store import FilingCache, Store

log = logging.getLogger(__name__)
DATA_DIR_VARIABLE = "EVIDENCE_DESK_DATA_DIR"
DEFAULT_DATA_DIR = "data"
RECORD_PATH = Path("record") / "record.sqlite"
CACHE_PATH = Path("cache") / "filings.sqlite"
VERSION_3_DATABASE = Path("runs") / "runs.sqlite"
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


def _cassette_of(analyst: Analyst | None) -> CassetteTransport | None:
    """The cassette transport ``analyst`` replays, if it is the Claude engine over one."""
    transport = analyst.transport if isinstance(analyst, ClaudeAnalyst) else None
    return transport if isinstance(transport, CassetteTransport) else None


def cassette_checker(directory: Path, *, record: bool = False) -> ClaudeChecker:
    """The meaning checker answering from the cassette at ``directory``.

    With ``record`` a request the cassette lacks is sent to the Anthropic API,
    to the check model, and its answer recorded; without it, saved as pending.
    """
    live = AnthropicTransport(model=configured_check_model()) if record else None
    return ClaudeChecker(transport=CassetteTransport(directory, live=live))


def _checker_beside(transport: CassetteTransport) -> ClaudeChecker:
    """A checker over the engine's own cassette and run, recording only when the engine does.

    Sharing the run means a pending check blocks the summary built on it; a
    recorded check names the check model, not the engine's.
    """
    live = AnthropicTransport(model=configured_check_model()) if transport.live else None
    return ClaudeChecker(transport=transport.sibling(live=live))


def checker_from_env(analyst: Analyst | None = None) -> Checker:
    """The meaning checker the environment configures.

    With ``EVIDENCE_DESK_CASSETTE`` set: Claude over that cassette (over
    ``analyst``'s own cassette transport when it replays one), recording as the
    engine does (``ANTHROPIC_API_KEY`` and ``EVIDENCE_DESK_CASSETTE_RECORD=1``).
    Otherwise Claude over the API when ``ANTHROPIC_API_KEY`` is set, with
    ``ANTHROPIC_CHECK_MODEL``; else :class:`NoChecker`. Never falls back from
    one to another once a run has started.
    """
    cassette = os.environ.get(CASSETTE_VARIABLE, "").strip()
    if cassette:
        shared = _cassette_of(analyst)
        if shared is not None:
            return _checker_beside(shared)
        record = model_key_present() and os.environ.get(RECORD_VARIABLE, "").strip() == "1"
        return cassette_checker(Path(cassette), record=record)
    if model_key_present():
        return ClaudeChecker()
    return NoChecker()


def checker_named(engine: str, analyst: Analyst) -> Checker:
    """The meaning checker that goes with the engine called ``engine`` (see :func:`analyst_named`).

    "cassette" checks over the engine's own cassette and never calls the API;
    "claude" over the API; "extractive" not at all; "auto" as the environment
    says (:func:`checker_from_env`).
    """
    shared = _cassette_of(analyst)
    if engine == "cassette" and shared is not None:
        return _checker_beside(shared)
    if engine == "claude":
        return ClaudeChecker()
    if engine == "auto":
        return checker_from_env(analyst)
    return NoChecker()


def filings_from_env() -> EdgarClient:
    """An EDGAR client identifying itself with ``SEC_USER_AGENT`` (or the default)."""
    return EdgarClient.from_env()


def data_dir() -> Path:
    """The parent of the record and the cache: ``$EVIDENCE_DESK_DATA_DIR``, default ``data``."""
    return Path(os.environ.get(DATA_DIR_VARIABLE, "").strip() or DEFAULT_DATA_DIR)


def record_path() -> Path:
    """The record database: ``data_dir()/record/record.sqlite``."""
    return data_dir() / RECORD_PATH


@functools.cache
def _note_version_3_database(directory: Path) -> None:
    """Say once per process that a version 3 database exists and is not read."""
    old = directory / VERSION_3_DATABASE
    if old.exists():
        log.warning("found a version 3 database at %s; it is not read", old)


def store_from_env() -> Store:
    """The record store at ``data_dir()/record/record.sqlite``, created if needed."""
    _note_version_3_database(data_dir())
    return Store(record_path())


def cache_from_env() -> FilingCache:
    """The disposable filing cache at ``data_dir()/cache/filings.sqlite``, created if needed."""
    return FilingCache(data_dir() / CACHE_PATH)
