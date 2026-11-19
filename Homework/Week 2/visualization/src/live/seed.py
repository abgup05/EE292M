"""The EDGAR seed: recorded answers that let a seeded company's run finish when EDGAR does not.

``vendored/seed/`` (written by ``make site-vendor``) holds the EDGAR answers the newest
version's tests were recorded from, each with its URL, its retrieval time and whether it is
whole. :class:`SeedTransport` sits under a version's own EDGAR client (an ``httpx`` transport,
so the client's host allow-list, rate limit, size cap and parsing are all its own) and:

- answers a filing document (``/Archives/edgar/data/...``, which never changes once filed)
  from the seed when it is recorded whole, without a request;
- sends every other request to EDGAR, and answers from the seed only when EDGAR does not
  answer (no connection, a timeout, HTTP 403, 429 or 5xx). Some of those recordings were
  trimmed when they were recorded (SEC's company list to five tickers, an index to its newest
  rows, company facts to a few concepts), so they stand in only when EDGAR cannot.

Each seeded answer carries the header ``x-live-seed`` with its retrieval time, and every use
is counted for ``/live/status``, as is every answer of EDGAR itself by host and status. The
seed also remembers for which URLs it is standing in and why, so that a version is never
left to tell a visitor that SEC lists no such company when all it read was the five tickers
of the recorded list (:func:`live.versions.live_edgar`).
"""

from __future__ import annotations

import gzip
import json
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx

IMMUTABLE_PREFIX = "https://www.sec.gov/Archives/edgar/data/"
FALLBACK_STATUSES = frozenset({403, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class Recording:
    """One recorded answer."""

    url: str
    file: Path
    content_type: str
    retrieved_at: str
    whole: bool

    def body(self) -> bytes:
        return gzip.decompress(self.file.read_bytes())


class Seed:
    """The recorded answers by URL, and how often each kind was used."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.recordings: dict[str, Recording] = {}
        manifest = directory / "seed.json"
        if manifest.is_file():
            for entry in json.loads(manifest.read_text())["entries"]:
                self.recordings[entry["url"]] = Recording(
                    url=entry["url"],
                    file=directory / entry["file"],
                    content_type=entry["content_type"],
                    retrieved_at=entry["retrieved_at"],
                    whole=bool(entry["whole"]),
                )
        self._lock = threading.Lock()
        self.served_first = 0
        self.served_instead = 0
        #: How EDGAR answered this instance, by host: {"www.sec.gov": {"HTTP 403": 2}}.
        self.outcomes: dict[str, dict[str, int]] = {}
        #: URLs whose latest answer came from the seed because EDGAR gave none, and why.
        self._standing_in: dict[str, str] = {}

    def get(self, url: str) -> Recording | None:
        return self.recordings.get(url)

    def count(self, *, instead: bool) -> None:
        with self._lock:
            if instead:
                self.served_instead += 1
            else:
                self.served_first += 1

    def note(self, host: str, outcome: str) -> None:
        """Count one answer (or failure to answer) of ``host``."""
        with self._lock:
            by_outcome = self.outcomes.setdefault(host, {})
            by_outcome[outcome] = by_outcome.get(outcome, 0) + 1

    def stand_in(self, url: str, reason: str) -> None:
        """The seed answered for ``url`` because EDGAR did not (``reason``)."""
        with self._lock:
            self.served_instead += 1
            self._standing_in[url] = reason

    def answered(self, url: str) -> None:
        """EDGAR itself answered for ``url``: the seed no longer stands in for it."""
        with self._lock:
            self._standing_in.pop(url, None)

    def stood_in(self, url: str) -> str | None:
        """Why the seed last answered for ``url`` in EDGAR's place, or None if EDGAR did."""
        with self._lock:
            return self._standing_in.get(url)

    def edgar(self) -> dict[str, dict[str, int]]:
        """How EDGAR answered this instance, by host and outcome: counts only."""
        with self._lock:
            return {
                host: dict(sorted(by.items()))
                for host, by in sorted(self.outcomes.items())
            }

    def tickers(self, url: str) -> list[str]:
        """The tickers of the recorded company list at ``url`` (a trimmed list holds a few)."""
        recording = self.get(url)
        if recording is None:
            return []
        try:
            entries = json.loads(recording.body()).values()
            return [str(entry["ticker"]) for entry in entries]
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            return []

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {
                "recorded_answers": len(self.recordings),
                "whole": sum(r.whole for r in self.recordings.values()),
                "served_without_asking_edgar": self.served_first,
                "served_because_edgar_did_not_answer": self.served_instead,
            }


def answer(recording: Recording, request: httpx.Request) -> httpx.Response:
    """The recorded answer to ``request``."""
    return httpx.Response(
        200,
        headers={
            "content-type": recording.content_type,
            "x-live-seed": f"recorded {recording.retrieved_at}",
        },
        content=recording.body(),
        request=request,
    )


class SeedTransport(httpx.BaseTransport):
    """An ``httpx`` transport: the seed for filed documents, EDGAR for the rest, the seed if not."""

    def __init__(self, seed: Seed, network: httpx.BaseTransport | None = None) -> None:
        self.seed = seed
        self.network = network or httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url.copy_with(query=None, fragment=None))
        recording = self.seed.get(url) if request.method == "GET" else None
        if (
            recording is not None
            and recording.whole
            and url.startswith(IMMUTABLE_PREFIX)
        ):
            self.seed.count(instead=False)
            return answer(recording, request)
        host = request.url.host
        try:
            response = self.network.handle_request(request)
        except httpx.TransportError as exc:
            reason = f"no answer ({type(exc).__name__})"
            self.seed.note(host, reason)
            if recording is None:
                raise
            self.seed.stand_in(url, reason)
            return answer(recording, request)
        self.seed.note(host, f"HTTP {response.status_code}")
        if recording is not None and response.status_code in FALLBACK_STATUSES:
            response.close()
            self.seed.stand_in(url, f"HTTP {response.status_code}")
            return answer(recording, request)
        if response.status_code == 200:
            self.seed.answered(url)
        return response

    def close(self) -> None:
        self.network.close()
