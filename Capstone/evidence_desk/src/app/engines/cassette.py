"""Record and replay of model answers, so model-backed runs are reproducible.

A cassette is a directory. ``responses/<key>.json`` holds one recorded answer
in an envelope that names who produced it; ``pending/<key>.json`` holds a
request no answer has been recorded for yet, written out in full so it can be
answered through another channel. ``<key>`` depends only on what the model is
asked (step, system prompt, user prompt, schema), so the same request always
finds the same answer. ``docs/cassettes.md`` describes the answer loop.

Nothing about the transport that produced an answer is stored: no header, no
key, only the answer object itself and who produced it.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.engines.transport import STEPS, EngineError, ModelRequest, Transport

KEY_CHARS = 24
RESPONSES = "responses"
PENDING = "pending"
ENVELOPE_FIELDS = ("key", "step", "via", "model", "recorded_at", "response")
UNKNOWN = "unknown"
HOW_TO_ANSWER = (
    "Respond exactly as the model would to this system and user prompt, as one JSON object "
    "that satisfies the schema. Save it as responses/<key>.json in the envelope described "
    "in docs/cassettes.md."
)


class CassetteMiss(EngineError):
    """No answer is recorded for a request and none could be obtained."""


def request_key(request: ModelRequest) -> str:
    """The first 24 hex characters of the SHA-256 of the request's canonical JSON.

    Canonical: the object ``{step, system, user, schema}`` with sorted keys,
    no whitespace, non-ASCII characters kept, encoded as UTF-8. ``max_tokens``
    is left out: it bounds an answer but does not change the question.
    """
    canonical = json.dumps(
        {
            "step": request.step,
            "system": request.system,
            "user": request.user,
            "schema": request.schema,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:KEY_CHARS]


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` to ``path`` atomically, creating the directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_envelope(path: Path) -> dict[str, Any]:
    """The envelope stored at ``path``; anything unusable raises :class:`EngineError`."""
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EngineError(f"The recorded response {path.name} cannot be read as JSON") from exc
    if not isinstance(envelope, dict) or "response" not in envelope:
        raise EngineError(f"The recorded response {path.name} has no response field")
    return envelope


def _step_rank(step: str) -> int | None:
    return STEPS.index(step) if step in STEPS else None


@dataclass
class _RunState:
    """What one run has missed so far; shared by the transports of one run (see ``sibling``)."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    missed_step: str | None = None
    pending_keys: list[str] = field(default_factory=list)


class CassetteTransport:
    """A :data:`~app.engines.transport.Transport` that answers from a cassette directory.

    On a hit the stored answer is returned. On a miss with ``live``, ``live``
    answers, and the answer is recorded with ``via`` (default: ``live.via``)
    and ``live.model``. On a miss without ``live``, the request is written to
    ``pending/<key>.json`` and :class:`CassetteMiss` is raised. A ``read_only``
    cassette answers what it holds and never writes: a miss raises
    :class:`CassetteMiss` and saves nothing (for replaying a cassette that must
    stay as recorded, such as the golden set's).

    The steps of a run depend on each other (:data:`~app.engines.transport.STEPS`):
    once a request is missing, a request for a later step was built on a
    stand-in answer, so it raises :class:`CassetteMiss` without being saved.
    A request for the first step (a plan) after a later step was missed starts
    a new run and lifts that block. Within one run claims are assessed and
    checked in turn, so an assessment after a pending check does not.
    """

    def __init__(
        self,
        directory: Path | str,
        live: Transport | None = None,
        via: str = "",
        *,
        read_only: bool = False,
    ) -> None:
        if read_only and live is not None:
            raise ValueError("a read-only cassette cannot record live answers")
        self.directory = Path(directory)
        self.live = live
        self.read_only = read_only
        self.via = via or str(getattr(live, "via", "")) or UNKNOWN
        self._run = _RunState()

    def sibling(self, live: Transport | None = None, via: str = "") -> CassetteTransport:
        """A transport over the same cassette and the same run, with its own ``live`` answerer.

        The meaning checker uses one: its misses block the summary built on
        them, as the engine's own would, while a recorded answer names the
        checker's model rather than the engine's.
        """
        twin = CassetteTransport(self.directory, live=live, via=via, read_only=self.read_only)
        twin._run = self._run
        return twin

    @property
    def pending_keys(self) -> list[str]:
        """The keys saved to ``pending/`` in the current run, in the order they were saved."""
        return self._run.pending_keys

    @property
    def _lock(self) -> threading.Lock:
        return self._run.lock

    @property
    def detail(self) -> str:
        """The cassette's description, shown on the run record as the engine detail."""
        return Cassette(self.directory).describe()

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        """The recorded answer to ``request``, or a live one recorded now."""
        key = request_key(request)
        response_path = self.directory / RESPONSES / f"{key}.json"
        pending_path = self.directory / PENDING / f"{key}.json"
        with self._lock:
            self._start_new_run_if_earlier(request.step)
            if response_path.exists():
                answer = self._stored_answer(response_path)
                if not self.read_only:
                    pending_path.unlink(missing_ok=True)
                return answer
            if self.read_only:
                raise CassetteMiss(
                    f"no recorded response for {request.step}; the cassette is read-only, "
                    "so nothing was saved"
                )
            if self.live is None:
                raise self._miss(request, key, pending_path)
        answer = self.live(request)
        if not isinstance(answer, dict):
            raise EngineError("The live transport returned a non-object answer")
        envelope = {
            "key": key,
            "step": request.step,
            "via": self.via,
            "model": str(getattr(self.live, "model", "") or UNKNOWN),
            "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "response": answer,
        }
        with self._lock:
            _write_json(response_path, envelope)
            pending_path.unlink(missing_ok=True)
        return answer

    def _start_new_run_if_earlier(self, step: str) -> None:
        rank, missed = _step_rank(step), self._run.missed_step
        if rank == 0 and missed is not None and rank < STEPS.index(missed):
            self._run.missed_step = None
            self._run.pending_keys.clear()

    @staticmethod
    def _stored_answer(path: Path) -> dict[str, Any]:
        answer = _read_envelope(path)["response"]
        if not isinstance(answer, dict):
            raise EngineError(f"The recorded response {path.name} is not a JSON object")
        return answer

    def _miss(self, request: ModelRequest, key: str, pending_path: Path) -> CassetteMiss:
        rank, missed = _step_rank(request.step), self._run.missed_step
        if rank is not None and missed is not None and rank > STEPS.index(missed):
            return CassetteMiss(
                f"no recorded response for {request.step}; not saved, because an earlier "
                f"{missed} request is pending and this one depends on its answer"
            )
        _write_json(
            pending_path,
            {
                "key": key,
                "step": request.step,
                "system": request.system,
                "user": request.user,
                "schema": request.schema,
                "how_to_answer": HOW_TO_ANSWER,
            },
        )
        if rank is not None and (missed is None or rank < STEPS.index(missed)):
            # The earliest step missed is what later requests may depend on.
            self._run.missed_step = request.step
        if key not in self._run.pending_keys:
            self._run.pending_keys.append(key)
        return CassetteMiss(
            f"no recorded response for {request.step}; request saved as pending/{key}.json"
        )


def _distinct(values: list[str]) -> str:
    """Sorted distinct values joined with commas and a final "and"."""
    items = sorted(set(values))
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


class Cassette:
    """Read-only view of a cassette directory: what is recorded and what is pending."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def pending(self) -> list[Path]:
        """The pending request files, sorted by name."""
        return sorted((self.directory / PENDING).glob("*.json"))

    def _response_paths(self) -> list[Path]:
        return sorted((self.directory / RESPONSES).glob("*.json"))

    def responses(self) -> int:
        """How many responses are recorded."""
        return len(self._response_paths())

    def describe(self) -> str:
        """Who recorded the responses, with which models, over which dates.

        An unreadable response file is counted and named as unreadable rather
        than hidden; a missing field reads as "unknown".
        """
        paths = self._response_paths()
        name = self.directory.name
        if not paths:
            return f"replayed from cassette {name}: no responses recorded"
        vias: list[str] = []
        models: list[str] = []
        dates: list[str] = []
        unreadable = 0
        for path in paths:
            try:
                envelope = _read_envelope(path)
            except EngineError:
                unreadable += 1
                continue
            vias.append(str(envelope.get("via") or UNKNOWN))
            models.append(str(envelope.get("model") or UNKNOWN))
            recorded = str(envelope.get("recorded_at") or "")
            if recorded[:10]:
                dates.append(recorded[:10])
        description = f"replayed from cassette {name}: {len(paths)} responses recorded"
        if vias:
            description += f" via {_distinct(vias)} with {_distinct(models)}"
        if dates:
            description += f", {min(dates)} to {max(dates)}"
        if unreadable:
            description += f" ({unreadable} unreadable)"
        return description
