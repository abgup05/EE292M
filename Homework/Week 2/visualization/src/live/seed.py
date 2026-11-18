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
is counted for ``/live/status``.
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

    def get(self, url: str) -> Recording | None:
        return self.recordings.get(url)

    def count(self, *, instead: bool) -> None:
        with self._lock:
            if instead:
                self.served_instead += 1
            else:
                self.served_first += 1

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
        if recording is not None and recording.whole and url.startswith(IMMUTABLE_PREFIX):
            self.seed.count(instead=False)
            return answer(recording, request)
        try:
            response = self.network.handle_request(request)
        except httpx.TransportError:
            if recording is None:
                raise
            self.seed.count(instead=True)
            return answer(recording, request)
        if recording is not None and response.status_code in FALLBACK_STATUSES:
            response.close()
            self.seed.count(instead=True)
            return answer(recording, request)
        return response

    def close(self) -> None:
        self.network.close()
