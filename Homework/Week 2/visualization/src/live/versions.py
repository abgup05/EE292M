"""The vendored versions, and how one is built on its first request.

``vendored/vN/`` holds version N's package as ``ed_vN`` and its page as ``web/`` (written by
``make site-vendor``; ``VENDORED.json`` names the git ref and commit). :meth:`Version.load`
imports the package and calls its own ``create_app`` once, with only these collaborators
chosen here, all through parameters every version already has:

- its data directory is ``$LIVE_DATA_ROOT/vN`` (default ``/tmp/evidence-desk/vN``), set as
  ``EVIDENCE_DESK_DATA_DIR`` while the version is built (the name every version reads);
- versions 2 and later get their own EDGAR client over :class:`live.seed.SeedTransport`,
  identified by ``SEC_USER_AGENT`` as their own client would be, and a page fetcher that
  refuses every address (visitor-supplied ``extra_urls`` are off online). The client is
  subclassed in one place (:func:`live_edgar`): an unknown ticker is reported as EDGAR being
  out of reach when the company list it was looked up in was the seed's short recording;
- version 1 gets its store in that directory, a fetcher that reads only its example's two
  pages (live, or from the seed when the page cannot be fetched) and no web search.

The model engine, the checker and the readers are each version's own choice from the
environment, as they are locally; the cassette variables are blanked while it is built.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from live.guard import NO_URLS, USER_AGENT_VARIABLE, V1_EXAMPLE_URLS, V1_URLS, Era
from live.seed import Seed, SeedTransport

VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendored"
DATA_ROOT_VARIABLE = "LIVE_DATA_ROOT"
DEFAULT_DATA_ROOT = "/tmp/evidence-desk"
DATA_DIR_VARIABLE = "EVIDENCE_DESK_DATA_DIR"
#: Blanked while a version is built: a cassette or a recording mode has no place online.
BLANKED = ("EVIDENCE_DESK_CASSETTE", "EVIDENCE_DESK_CASSETTE_RECORD")
# Building a version sets the process environment for a moment; one at a time.
_BUILD_LOCK = threading.Lock()


@dataclass(frozen=True)
class Vendored:
    """One vendored version as ``make site-vendor`` wrote it."""

    number: int
    ref: str
    commit: str
    package: str
    directory: Path
    era: Era
    watch: bool

    @property
    def web_dir(self) -> Path:
        return self.directory / "web"


def discover(vendor_dir: Path = VENDOR_DIR) -> dict[int, Vendored]:
    """Every vendored version, by number."""
    found: dict[int, Vendored] = {}
    if not vendor_dir.is_dir():
        return found
    for manifest_path in sorted(vendor_dir.glob("v*/VENDORED.json")):
        manifest = json.loads(manifest_path.read_text())
        directory = manifest_path.parent
        package = directory / manifest["package"]
        api_source = (package / "api.py").read_text(encoding="utf-8")
        found[int(manifest["version"])] = Vendored(
            number=int(manifest["version"]),
            ref=manifest["ref"],
            commit=manifest["commit"],
            package=manifest["package"],
            directory=directory,
            era="research" if '"/api/research"' in api_source else "thesis",
            watch=(package / "watch").is_dir(),
        )
    return dict(sorted(found.items()))


def data_root() -> Path:
    return Path(os.environ.get(DATA_ROOT_VARIABLE, "").strip() or DEFAULT_DATA_ROOT)


def refusing_fetcher(error: type[Exception]) -> Callable[..., Any]:
    """A page fetcher that refuses every address with the version's own fetch error."""

    def refuse(url: str, *args: object, **kwargs: object) -> Any:
        raise error(NO_URLS)

    return refuse


def example_fetcher(fetch: Any, seed: Seed) -> Callable[..., Any]:
    """Version 1's fetcher online: only its example's pages, live or else from the seed."""

    def fetch_example(url: str, *args: object, **kwargs: object) -> Any:
        if url.strip() not in V1_EXAMPLE_URLS:
            raise fetch.FetchError(V1_URLS)
        try:
            return fetch.fetch_page(url)
        except fetch.FetchError:
            recording = seed.get(url.strip())
            if recording is None:
                raise
            seed.stand_in(url.strip(), "the page could not be fetched")
            return fetch.FetchedPage(
                requested_url=url,
                final_url=recording.url,
                status_code=200,
                content_type=recording.content_type,
                html=recording.body().decode("utf-8", errors="replace"),
                retrieved_at=datetime.fromisoformat(recording.retrieved_at),
            )

    return fetch_example


def live_edgar(edgar: Any, seed: Seed, client: httpx.Client) -> Any:
    """The version's own EDGAR client, honest when the seed's short company list stood in.

    The recorded company list holds a few tickers. When EDGAR refuses the real one and the
    recording answers, the version would say of any other ticker that it "is not in SEC's
    company list", which is false. Here that case becomes the version's own
    ``SourceError`` (its page shows it as EDGAR being out of reach, HTTP 503) and says what
    happened and what a visitor can do. Nothing else of the client is changed.
    """
    tickers_url = edgar.TICKERS_URL

    class LiveEdgarClient(edgar.EdgarClient):  # type: ignore[misc, name-defined]
        def company(self, ticker: str) -> Any:
            try:
                return super().company(ticker)
            except edgar.UnknownTicker as exc:
                reason = seed.stood_in(tickers_url)
                if reason is None:
                    raise
                message = company_list_message(ticker, reason, seed, tickers_url)
                raise edgar.SourceError(message) from exc

    return LiveEdgarClient(
        client=client, user_agent=os.environ.get(USER_AGENT_VARIABLE)
    )


def company_list_message(ticker: str, reason: str, seed: Seed, tickers_url: str) -> str:
    """What a visitor is told when SEC's company list could not be read for their ticker."""
    known = ", ".join(seed.tickers(tickers_url)) or "none"
    contact = (
        ""
        if os.environ.get(USER_AGENT_VARIABLE, "").strip()
        else " This server has no SEC contact string set, which EDGAR asks of every reader."
    )
    shown = ticker.strip().upper()[:12]
    return (
        f"{shown} could not be looked up: EDGAR did not give this server SEC's company list "
        f"({reason}).{contact} A recorded copy of the list stands in, and it holds only "
        f"{known}. Try one of those, try again later, or run this version locally."
    )


def build(
    info: Vendored, seed: Seed, network: httpx.BaseTransport | None = None
) -> Any:
    """Import version ``info`` and build its ASGI app as described in this module."""
    data_dir = data_root() / f"v{info.number}"
    data_dir.mkdir(parents=True, exist_ok=True)
    with _BUILD_LOCK:
        if str(info.directory) not in sys.path:
            sys.path.append(str(info.directory))
        saved = {name: os.environ.get(name) for name in (DATA_DIR_VARIABLE, *BLANKED)}
        os.environ[DATA_DIR_VARIABLE] = str(data_dir)
        for name in BLANKED:
            os.environ[name] = ""
        try:
            api = importlib.import_module(f"{info.package}.api")
            parameters = inspect.signature(api.create_app).parameters
            if info.era == "research":
                fetch = importlib.import_module(f"{info.package}.fetch")
                # Version 1 reads its data directory when its module is first imported, so
                # its store is handed to it: where it writes must not depend on that moment.
                store = importlib.import_module(f"{info.package}.store").Store(
                    data_dir / "runs.sqlite"
                )
                return api.create_app(
                    store=store, fetcher=example_fetcher(fetch, seed), searcher=None
                )
            if "filings" not in parameters or "fetch_page" not in parameters:
                raise RuntimeError(
                    f"version {info.number}'s create_app takes neither filings nor fetch_page"
                )
            edgar = importlib.import_module(f"{info.package}.sources.edgar")
            pages = importlib.import_module(f"{info.package}.sources.http")
            client = httpx.Client(
                transport=SeedTransport(seed, network),
                timeout=getattr(edgar, "TIMEOUT_SECONDS", 30.0),
                follow_redirects=False,
            )
            filings = live_edgar(edgar, seed, client)
            return api.create_app(
                filings=filings, fetch_page=refusing_fetcher(pages.FetchError)
            )
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


@dataclass
class Version:
    """One mounted version: built on first use, and whether that worked."""

    info: Vendored
    seed: Seed
    app: Any = None
    error: str | None = None
    has_recording: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def load(self) -> Any:
        """The version's app, built once; raises :class:`RuntimeError` if it cannot be built."""
        with self._lock:
            if self.app is None and self.error is None:
                try:
                    self.app = build(self.info, self.seed)
                except Exception as exc:
                    self.error = type(exc).__name__
                    raise RuntimeError(self.error) from exc
            if self.app is None:
                raise RuntimeError(self.error or "not built")
            return self.app

    def state(self, enabled: bool = True) -> dict[str, Any]:
        """For /live/status: no path, no message, only what is known."""
        if not enabled and self.has_recording:
            serving = "recorded"
        elif self.app is not None:
            serving = "live"
        elif self.error is None:
            serving = "not asked yet"
        else:
            serving = "recorded" if self.has_recording else "unavailable"
        return {
            "serving": serving,
            "ref": self.info.ref,
            "commit": self.info.commit[:12],
            "mounted": True,
            "imported": self.app is not None or self.error is not None,
            "import_ok": None
            if self.app is None and self.error is None
            else self.error is None,
            "import_error": self.error,
        }
