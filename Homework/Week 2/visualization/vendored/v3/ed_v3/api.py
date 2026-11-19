"""HTTP routes onto the thesis-run use case, plus the static page.

Routes only: the collaborators (store, EDGAR, engine, page fetcher) are handed
to :func:`create_app`, and default to :mod:`app.wiring`. Runs execute in a
worker thread through :func:`app.services.thesis_run.execute_run`, the same
call the command line makes. Start the server with
``uvicorn app.api:create_app --factory``; importing this module builds nothing.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from ed_v3 import __version__, wiring
from ed_v3.core import limits, policy
from ed_v3.core.metric_models import MetricsReport
from ed_v3.core.models import TICKER_PATTERN, Company, Run, ThesisRequest
from ed_v3.core.ports import Analyst, FilingSource, PageFetcher, SourceError, UnknownTicker
from ed_v3.services import thesis_run
from ed_v3.services.examples import EXAMPLE_THESIS
from ed_v3.services.export import render_markdown
from ed_v3.services.numbers import load_numbers
from ed_v3.sources.http import fetch_page as default_fetch_page
from ed_v3.sources.urls import canonicalize, validate_public_url
from ed_v3.store import Store

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
RUN_WORKERS = 2
INVALID_REQUEST = "Invalid request"
CRASH_MESSAGE = "The run stopped because of an internal error."
STATIC_FILES = {
    "/app.js": ("app.js", "text/javascript"),
    "/styles.css": ("styles.css", "text/css"),
}
# Sample records the page can load: src/web/sample-<name>.json, served at /sample-<name>.json.
SAMPLE_NAME = re.compile(r"[a-z0-9-]{1,40}")
TICKER_MESSAGE = (
    "ticker must be 1 to 6 letters or digits, optionally with a class suffix such as BRK.B"
)
log = logging.getLogger(__name__)


class Problem(BaseModel):
    """One reason a request was refused, and the field it concerns."""

    field: str
    message: str


class RequestRefused(Exception):
    """A request that passed the schema but fails a check that needs the API layer."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(f"{len(problems)} problem(s)")
        self.problems = problems


class RunStarted(BaseModel):
    id: str
    status: str


class RunSummary(BaseModel):
    """One line of the run list."""

    id: str
    status: str
    ticker: str
    company: str | None
    started_at: datetime
    claims: int


class RunList(BaseModel):
    runs: list[RunSummary]


def public_limits() -> dict[str, int | float]:
    """Every public constant of :mod:`app.core.limits`, by name."""
    return {name: getattr(limits, name) for name in dir(limits) if name.isupper()}


def check_extra_urls(urls: list[str]) -> list[Problem]:
    """Each extra URL must be a public http(s) address, and distinct once canonicalized.

    This is URL policy, so it lives here at the boundary rather than in the
    request model (review finding F3).
    """
    problems: list[Problem] = []
    seen: dict[str, int] = {}
    for index, url in enumerate(urls):
        field = f"extra_urls.{index}"
        try:
            canonical = canonicalize(validate_public_url(url))
        except ValueError as exc:  # UnsafeURL, or a URL too malformed to parse
            problems.append(Problem(field=field, message=str(exc)))
            continue
        if canonical in seen:
            problems.append(
                Problem(field=field, message=f"Repeats URL {seen[canonical] + 1} (the same page)")
            )
        else:
            seen[canonical] = index
    return problems


def _pydantic_problems(errors: list[dict[str, Any]]) -> list[Problem]:
    problems = []
    for error in errors:
        location = [str(part) for part in error.get("loc", ()) if part != "body"]
        message = str(error.get("msg", "Invalid value")).removeprefix("Value error, ")
        problems.append(Problem(field=".".join(location) or "body", message=message))
    return problems


def _refusal(problems: list[Problem]) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": INVALID_REQUEST, "details": [p.model_dump() for p in problems]},
    )


class MetricsCache:
    """Metrics reports by CIK, each kept for :data:`limits.METRICS_CACHE_SECONDS`.

    Only successful reports are kept, so an EDGAR outage is not remembered.
    Safe to share between threads.
    """

    def __init__(self, monotonic: Callable[[], float]) -> None:
        """Measure age with ``monotonic`` (seconds)."""
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._reports: dict[int, tuple[float, MetricsReport]] = {}

    def get(self, cik: int) -> MetricsReport | None:
        """The cached report for ``cik`` if it is fresh, else None."""
        with self._lock:
            entry = self._reports.get(cik)
            if entry is None or self._monotonic() - entry[0] >= limits.METRICS_CACHE_SECONDS:
                return None
            return entry[1]

    def put(self, cik: int, report: MetricsReport) -> None:
        """Keep ``report`` for ``cik`` from now."""
        with self._lock:
            self._reports[cik] = (self._monotonic(), report)


def create_app(
    store: Store | None = None,
    filings: FilingSource | None = None,
    analyst: Analyst | None = None,
    fetch_page: PageFetcher = default_fetch_page,
    monotonic: Callable[[], float] = time.monotonic,
) -> FastAPI:
    """Build the application. Collaborators not given are built by :mod:`app.wiring`.

    ``monotonic`` is the clock of the metrics cache (injectable for tests).
    """
    store = store or wiring.store_from_env()
    filings = filings or wiring.filings_from_env()
    analyst = analyst or wiring.analyst_from_env()
    executor = ThreadPoolExecutor(max_workers=RUN_WORKERS, thread_name_prefix="run")
    metrics_cache = MetricsCache(monotonic)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Evidence Desk", version=__version__, docs_url="/docs", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def schema_refused(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _refusal(_pydantic_problems(list(exc.errors())))

    @app.exception_handler(RequestRefused)
    async def check_refused(_: Request, exc: RequestRefused) -> JSONResponse:
        return _refusal(exc.problems)

    @app.exception_handler(SourceError)
    async def source_unavailable(_: Request, exc: SourceError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"error": str(exc)})

    def execute(run: Run) -> None:
        try:
            thesis_run.execute_run(
                run, store, filings=filings, analyst=analyst, fetch_page=fetch_page
            )
        except Exception:  # noqa: BLE001 - last resort: a run must never stay "running"
            log.exception("Run %s crashed", run.id)
            thesis_run.fail_run(run, store, CRASH_MESSAGE)

    @app.post("/api/runs", status_code=202)
    def start_run(request: ThesisRequest) -> RunStarted:
        """Validate, resolve the ticker, then execute the run in the background."""
        problems = check_extra_urls(request.extra_urls)
        if problems:
            raise RequestRefused(problems)
        try:
            filings.company(request.ticker)
        except UnknownTicker as exc:
            raise RequestRefused([Problem(field="ticker", message=str(exc))]) from exc
        run = thesis_run.new_run(request)
        store.save_run(run)
        executor.submit(execute, run)
        return RunStarted(id=run.id, status=run.status)

    @app.get("/api/runs")
    def list_runs() -> RunList:
        """Recent runs, newest first."""
        return RunList(
            runs=[
                RunSummary(
                    id=run.id,
                    status=run.status,
                    ticker=run.inputs.ticker,
                    company=run.company.name if run.company else None,
                    started_at=run.started_at,
                    claims=len(run.inputs.claims),
                )
                for run in store.list_runs()
            ]
        )

    def load(run_id: str) -> Run:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> Run:
        """The full run record."""
        return load(run_id)

    @app.get("/api/runs/{run_id}/export.md")
    def export_run(run_id: str) -> PlainTextResponse:
        """The run as a Markdown brief."""
        return PlainTextResponse(render_markdown(load(run_id)), media_type="text/markdown")

    def resolve(ticker: str) -> Company:
        """The company for a ticker in a path, or a 422 naming the ticker field."""
        cleaned = ticker.strip().upper()
        if not TICKER_PATTERN.fullmatch(cleaned):
            raise RequestRefused([Problem(field="ticker", message=TICKER_MESSAGE)])
        try:
            return filings.company(cleaned)
        except UnknownTicker as exc:
            raise RequestRefused([Problem(field="ticker", message=str(exc))]) from exc

    @app.get("/api/companies/{ticker}/metrics")
    def company_metrics(ticker: str) -> MetricsReport:
        """The reported-numbers report for a ticker, without starting a run.

        422 for a malformed or unknown ticker, 503 when EDGAR cannot be read or its
        facts cannot be; a report is cached per company for 15 minutes.
        """
        company = resolve(ticker)
        cached = metrics_cache.get(company.cik)
        if cached is not None:
            return cached
        result = load_numbers(company, filings)
        if result.report is None:
            raise SourceError(result.error or "The XBRL company facts could not be read")
        metrics_cache.put(company.cik, result.report)
        return result.report

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        """The limits and wording every view uses, so the page and the export agree."""
        return {
            "version": __version__,
            "figures_note": policy.FIGURES_NOTE,
            "limits": public_limits(),
            "status_notes": {status.value: note for status, note in policy.STATUS_NOTES.items()},
            "verdict_labels": {v.value: label for v, label in policy.VERDICT_LABELS.items()},
            "verdict_notes": {v.value: note for v, note in policy.VERDICT_NOTES.items()},
            "provenance_note": policy.PROVENANCE_NOTE,
            "engine": analyst.name,
            "example": EXAMPLE_THESIS.model_dump(mode="json"),
        }

    @app.get("/api/health")
    def health() -> dict[str, str | None]:
        """Liveness, the version, the engine and (for a model engine) its model."""
        model = getattr(analyst, "model", None)
        return {
            "status": "ok",
            "version": __version__,
            "engine": analyst.name,
            "model": model if isinstance(model, str) else None,
        }

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", media_type="text/html")

    for path, (name, media_type) in STATIC_FILES.items():
        app.add_api_route(
            path,
            _static(WEB_DIR / name, media_type),
            methods=["GET"],
            include_in_schema=False,
        )

    @app.get("/sample-{name}.json", include_in_schema=False)
    def sample(name: str) -> FileResponse:
        """A recorded sample record, src/web/sample-<name>.json; the name is allow-listed."""
        if not SAMPLE_NAME.fullmatch(name):
            raise HTTPException(status_code=404, detail="Not found")
        file = WEB_DIR / f"sample-{name}.json"
        if not file.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(file, media_type="application/json")

    return app


def _static(file: Path, media_type: str) -> Any:
    def serve() -> FileResponse:
        return FileResponse(file, media_type=media_type)

    return serve
