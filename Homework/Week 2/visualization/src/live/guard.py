"""What the public server lets a visitor do: the one place every live version's requests pass.

The versions were written for one trusted person on 127.0.0.1. Online, anyone can call them and
a model-backed run is paid by the site owner's key, so before a request reaches a version:

- only GET and HEAD, and the few writes a version's page makes, are let through; every other
  write is refused (:data:`WRITES`). The one DELETE let through removes a watch, which the
  page offers beside setting one; no address deletes a run, a thesis or a file;
- a request body is at most ``LIVE_MAX_BODY_BYTES`` and a query string at most
  :data:`MAX_QUERY_BYTES`;
- visitor-supplied URLs are refused: ``extra_urls`` must be empty, and version 1's
  ``seed_urls`` may name only the pages of its own example (:data:`V1_EXAMPLE_URLS`);
- a run start is admitted only within the caps of :class:`Caps`; a run that would use the model
  is admitted only when no other model run is in progress on this instance;
- reads that make the server fetch and compare filings (:func:`costly_read`) are capped per
  client and day.

A visitor is told apart by the address Vercel's proxy reports, which a visitor cannot set; a
forwarding header is believed only where Vercel runs the function (:func:`client_of`).

Every count is kept in this process's memory, so every cap is per server instance: a visitor
whose requests reach several instances can start more runs than one cap allows. Each refusal
is ``{"error": ..., "detail": ...}``, the shape every version's page already shows.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from typing import Any, Literal

KEY_VARIABLE = "ANTHROPIC_API_KEY"
USER_AGENT_VARIABLE = "SEC_USER_AGENT"
MAX_QUERY_BYTES = 2048
MAX_HOLD_SECONDS = 790

Era = Literal["research", "thesis"]
#: Version 1 asks a research question over pages; versions 2 and later test a thesis.
RUN_STARTS: dict[Era, list[tuple[re.Pattern[str], str]]] = {
    "research": [(re.compile(r"/api/research"), "/api/research/{id}")],
    "thesis": [
        (re.compile(r"/api/runs"), "/api/runs/{id}"),
        (re.compile(r"/api/theses/[^/]+/runs"), "/api/runs/{id}"),
        (re.compile(r"/api/inbox/[^/]+/run"), "/api/runs/{id}"),
    ],
}
#: Every write a version's page makes, by era; anything else that is not GET or HEAD is refused.
WRITES: dict[Era, list[tuple[str, re.Pattern[str]]]] = {
    "research": [("POST", re.compile(r"/api/research"))],
    "thesis": [
        ("POST", re.compile(r"/api/runs")),
        ("POST", re.compile(r"/api/theses")),
        ("POST", re.compile(r"/api/theses/[^/]+/runs")),
        ("POST", re.compile(r"/api/inbox/[^/]+/run")),
        ("POST", re.compile(r"/api/inbox/read")),
        ("PUT", re.compile(r"/api/runs/[^/]+/findings/[^/]+/decision")),
        ("PUT", re.compile(r"/api/theses/[^/]+/watch")),
        ("DELETE", re.compile(r"/api/theses/[^/]+/watch")),
    ],
}
#: Reads that make the server fetch and compare whole filings from EDGAR.
COSTLY_READS = re.compile(r"/api/companies/.*|/api/runs/[^/]+/changes")
#: A brief asked for with its changed paragraphs makes the same comparison.
BRIEF = re.compile(r"/api/runs/[^/]+/export\.md")
#: Set by Vercel where it runs the function; only there is a forwarding header believed.
VERCEL_VARIABLE = "VERCEL"
#: The two pages of version 1's own example (its app.js); no other address is fetched for it.
V1_EXAMPLE_URLS = frozenset(
    {
        "https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10",
        "https://www.gao.gov/products/gao-24-106946",
    }
)
TURNED_OFF = "This is turned off on the public server: it would change or delete what other visitors see."
NO_URLS = (
    "Extra web pages are turned off on the public server: it does not fetch addresses a visitor "
    "supplies. Leave this list empty, or run the version locally to use it."
)
V1_URLS = (
    "On the public server, version 1 reads only the two pages of its own example "
    "(Load example); it does not fetch other addresses a visitor supplies."
)


@dataclass(frozen=True)
class Caps:
    """The limits of the public server, each from an environment variable of the same name."""

    LIVE_MODEL_RUNS_PER_DAY: int = 20
    LIVE_MODEL_RUNS_PER_CLIENT_PER_DAY: int = 3
    LIVE_RUNS_PER_DAY: int = 300
    LIVE_RUNS_PER_CLIENT_PER_DAY: int = 20
    LIVE_RUNS_AT_ONCE: int = 2
    LIVE_READS_PER_CLIENT_PER_DAY: int = 120
    LIVE_MAX_BODY_BYTES: int = 16384
    LIVE_HOLD_SECONDS: int = 285

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> tuple[Caps, list[str]]:
        """The caps the environment sets, and the names whose value was not a whole number.

        A missing variable keeps its default; an unreadable one keeps its default and is named.
        ``LIVE_HOLD_SECONDS`` is held to at most :data:`MAX_HOLD_SECONDS`.
        """
        environ = os.environ if environ is None else environ
        values: dict[str, int] = {}
        invalid: list[str] = []
        for spec in fields(cls):
            text = environ.get(spec.name, "").strip()
            if not text:
                continue
            if not text.isdigit():
                invalid.append(spec.name)
                continue
            values[spec.name] = int(text)
        if "LIVE_HOLD_SECONDS" in values:
            values["LIVE_HOLD_SECONDS"] = max(
                10, min(values["LIVE_HOLD_SECONDS"], MAX_HOLD_SECONDS)
            )
        return cls(**values), invalid

    def as_dict(self) -> dict[str, int]:
        return {spec.name: getattr(self, spec.name) for spec in fields(self)}


def key_present(environ: Mapping[str, str] | None = None) -> bool:
    """True when a non-blank model key is set. The key itself is never read out."""
    return bool(
        (os.environ if environ is None else environ).get(KEY_VARIABLE, "").strip()
    )


def user_agent_present(environ: Mapping[str, str] | None = None) -> bool:
    """True when a non-blank SEC contact string is set. The string itself is never read out."""
    return bool(
        (os.environ if environ is None else environ)
        .get(USER_AGENT_VARIABLE, "")
        .strip()
    )


@dataclass(frozen=True)
class Refusal:
    """A request the public server does not pass on: its status and the message shown."""

    status: int
    message: str
    details: list[dict[str, str]] | None = None

    def body(self) -> bytes:
        content: dict[str, Any] = {"error": self.message, "detail": self.message}
        if self.details:
            content = {
                "error": "Invalid request",
                "detail": self.message,
                "details": self.details,
            }
        return json.dumps(content).encode()


def client_of(
    headers: Mapping[str, str], fallback: str, environ: Mapping[str, str] | None = None
) -> str:
    """The visitor's address: on Vercel the one its proxy reports, else the connection's.

    Vercel's proxy writes ``x-vercel-forwarded-for``, ``x-real-ip`` and ``x-forwarded-for``
    itself, over whatever the visitor sent. Anywhere else nothing stands between the visitor
    and this process, so a header would be the visitor's own word and is not read.
    """
    environ = os.environ if environ is None else environ
    if environ.get(VERCEL_VARIABLE, "").strip():
        for name in ("x-vercel-forwarded-for", "x-real-ip", "x-forwarded-for"):
            value = headers.get(name, "").split(",")[0].strip()
            if value:
                return value[:64]
    return fallback


def costly_read(method: str, path: str, query: bytes) -> bool:
    """True for a read that makes the server fetch and compare filings from EDGAR."""
    if method != "GET":
        return False
    if COSTLY_READS.fullmatch(path):
        return True
    return bool(BRIEF.fullmatch(path)) and b"changes" in query


def run_start(era: Era, method: str, path: str) -> str | None:
    """The address that answers for the started run (``/api/runs/{id}``), if this starts one."""
    if method != "POST":
        return None
    for pattern, poll in RUN_STARTS[era]:
        if pattern.fullmatch(path):
            return poll
    return None


def check_request(
    era: Era, method: str, path: str, query: bytes, caps: Caps
) -> Refusal | None:
    """Refuse a write the page does not make, any DELETE, and an over-long query string."""
    if len(query) > MAX_QUERY_BYTES:
        return Refusal(414, f"The query string is longer than {MAX_QUERY_BYTES} bytes.")
    if method in ("GET", "HEAD"):
        return None
    if any(
        method == allowed and pattern.fullmatch(path)
        for allowed, pattern in WRITES[era]
    ):
        return None
    return Refusal(405, TURNED_OFF)


def check_body(era: Era, method: str, path: str, body: bytes) -> Refusal | None:
    """Refuse visitor-supplied URLs; anything else about the body is the version's to judge."""
    if method != "POST" or not body:
        return None
    try:
        payload = json.loads(body)
    except ValueError:
        return None  # the version refuses it in its own words
    if not isinstance(payload, dict):
        return None
    if era == "research":
        urls = payload.get("seed_urls")
        if path == "/api/research" and isinstance(urls, list):
            bad = [
                i
                for i, url in enumerate(urls)
                if not isinstance(url, str) or url.strip() not in V1_EXAMPLE_URLS
            ]
            if bad:
                details = [{"field": f"seed_urls.{i}", "message": V1_URLS} for i in bad]
                return Refusal(422, V1_URLS, details)
        return None
    if path == "/api/runs":
        urls, prefix = payload.get("extra_urls"), ""
    elif path == "/api/theses" and isinstance(payload.get("request"), dict):
        urls, prefix = payload["request"].get("extra_urls"), "request."
    else:
        return None
    if isinstance(urls, list) and urls:
        details = [
            {"field": f"{prefix}extra_urls.{i}", "message": NO_URLS}
            for i in range(len(urls))
        ]
        return Refusal(422, NO_URLS, details)
    return None


@dataclass
class Ticket:
    """An admitted run start: counted once the version accepts it, released when it ends."""

    guard: Guard
    client: str
    model: bool
    accepted: bool = False
    released: bool = False

    def accept(self) -> None:
        """The version started the run: it counts against the day's caps."""
        self.guard._count(self)
        self.accepted = True

    def release(self) -> None:
        """The run is over (or was never started): free its place."""
        if not self.released:
            self.released = True
            self.guard._free(self)


class Guard:
    """The caps of one server instance, counted in memory per UTC day.

    ``today`` and ``environ`` are injectable for tests.
    """

    def __init__(
        self,
        caps: Caps,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.caps = caps
        self._today = today
        self._environ = environ
        self._lock = threading.Lock()
        self._day: date | None = None
        self.model_runs_today = 0
        self.runs_today = 0
        self._client_model: dict[str, int] = {}
        self._client_runs: dict[str, int] = {}
        self._client_reads: dict[str, int] = {}
        self.held = 0
        self.model_held = 0

    def model_engine(self) -> bool:
        """True when a run started now would use the model (and so the owner's key)."""
        return key_present(self._environ)

    def _roll(self) -> None:
        today = self._today()
        if today != self._day:
            self._day = today
            self.model_runs_today = self.runs_today = 0
            self._client_model.clear()
            self._client_runs.clear()
            self._client_reads.clear()

    def admit_run(self, client: str) -> Ticket | Refusal:
        """Admit a run start for ``client`` or say which cap stops it; reserve its place."""
        caps = self.caps
        model = self.model_engine()
        with self._lock:
            self._roll()
            if self.held >= caps.LIVE_RUNS_AT_ONCE:
                return Refusal(
                    429,
                    f"{self.held} runs are in progress on this server, its limit at once. "
                    "Try again in a few minutes.",
                )
            if self.runs_today >= caps.LIVE_RUNS_PER_DAY:
                return Refusal(
                    429,
                    f"This server has started its {caps.LIVE_RUNS_PER_DAY} runs for today "
                    "(UTC). Try again tomorrow, or run the version locally.",
                )
            if model:
                if self.model_held >= 1:
                    return Refusal(
                        429,
                        "A model run is in progress on this server, and it runs one at a time "
                        "(each is paid by the site's owner). Try again in a few minutes.",
                    )
                if self.model_runs_today >= caps.LIVE_MODEL_RUNS_PER_DAY:
                    return Refusal(
                        429,
                        f"This server has started its {caps.LIVE_MODEL_RUNS_PER_DAY} model runs "
                        "for today (UTC). Try again tomorrow, or run the version locally.",
                    )
                if (
                    self._client_model.get(client, 0)
                    >= caps.LIVE_MODEL_RUNS_PER_CLIENT_PER_DAY
                ):
                    return Refusal(
                        429,
                        f"You have started {caps.LIVE_MODEL_RUNS_PER_CLIENT_PER_DAY} model runs on "
                        "this server today (UTC), its limit per visitor. Try again tomorrow.",
                    )
            elif self._client_runs.get(client, 0) >= caps.LIVE_RUNS_PER_CLIENT_PER_DAY:
                return Refusal(
                    429,
                    f"You have started {caps.LIVE_RUNS_PER_CLIENT_PER_DAY} runs on this server "
                    "today (UTC), its limit per visitor. Try again tomorrow.",
                )
            self.held += 1
            self.model_held += model
            return Ticket(self, client, model)

    def _count(self, ticket: Ticket) -> None:
        with self._lock:
            self._roll()
            self.runs_today += 1
            self._client_runs[ticket.client] = (
                self._client_runs.get(ticket.client, 0) + 1
            )
            if ticket.model:
                self.model_runs_today += 1
                self._client_model[ticket.client] = (
                    self._client_model.get(ticket.client, 0) + 1
                )

    def _free(self, ticket: Ticket) -> None:
        with self._lock:
            self.held -= 1
            self.model_held -= ticket.model

    def admit_read(self, client: str) -> Refusal | None:
        """Count one costly read for ``client``; refuse it past the day's cap."""
        with self._lock:
            self._roll()
            count = self._client_reads.get(client, 0)
            if count >= self.caps.LIVE_READS_PER_CLIENT_PER_DAY:
                return Refusal(
                    429,
                    f"You have made {count} requests that read filings from EDGAR on this server "
                    "today (UTC), its limit per visitor. Try again tomorrow.",
                )
            self._client_reads[client] = count + 1
            return None

    def counts(self) -> dict[str, int]:
        """The counts of this instance: no address, no key, no contact string."""
        with self._lock:
            self._roll()
            return {
                "model_runs_today": self.model_runs_today,
                "runs_today": self.runs_today,
                "runs_in_progress": self.held,
                "model_runs_in_progress": self.model_held,
                "clients_today": len(
                    self._client_runs.keys() | self._client_reads.keys()
                ),
            }
