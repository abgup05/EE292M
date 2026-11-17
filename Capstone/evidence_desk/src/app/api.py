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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from app import __version__, wiring
from app.core import limits, policy
from app.core.change_models import FilingChanges
from app.core.claim_change_models import RunChanges
from app.core.metric_models import MetricsReport
from app.core.models import (
    TICKER_PATTERN,
    Company,
    Decision,
    DecisionRequest,
    Review,
    Run,
    RunComparison,
    RunStatus,
    Thesis,
    ThesisCreate,
    ThesisRequest,
)
from app.core.ports import (
    Analyst,
    Checker,
    FilingSource,
    PageFetcher,
    SourceError,
    UnknownTicker,
)
from app.core.review import build_review
from app.engines.checker import NoChecker
from app.services import theses, thesis_run
from app.services.claim_changes import run_changes
from app.services.examples import EXAMPLE_THESIS
from app.services.export import render_markdown
from app.services.filing_changes import FORMS as CHANGE_FORMS
from app.services.filing_changes import filing_changes
from app.services.numbers import load_numbers
from app.sources.http import fetch_page as default_fetch_page
from app.sources.urls import canonicalize, validate_public_url
from app.store import FilingCache, Store

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
RUN_WORKERS = 2
INVALID_REQUEST = "Invalid request"
CRASH_MESSAGE = "The run stopped because of an internal error."
STILL_RUNNING = "The run is still running; its findings can be decided once it finishes."
WITHHELD_MESSAGE = "This finding was withheld, so it cannot be decided"
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
    thesis_id: str | None


class RunList(BaseModel):
    runs: list[RunSummary]


class ThesisSummary(BaseModel):
    """One line of the saved-thesis list."""

    id: str
    name: str
    ticker: str
    claims: int
    created_at: datetime
    runs: int
    last_run_id: str | None
    last_status: str | None


class ThesisList(BaseModel):
    theses: list[ThesisSummary]


class ThesisRunSummary(BaseModel):
    """One run of a saved thesis."""

    id: str
    status: str
    started_at: datetime
    finished_at: datetime | None


class ThesisDetail(BaseModel):
    thesis: Thesis
    runs: list[ThesisRunSummary]


class Conflict(Exception):
    """A request that is valid but cannot be carried out in the current state (409)."""


def public_limits() -> dict[str, int | float]:
    """Every public constant of :mod:`app.core.limits`, by name."""
    return {name: getattr(limits, name) for name in dir(limits) if name.isupper()}


def check_extra_urls(urls: list[str], prefix: str = "") -> list[Problem]:
    """Each extra URL must be a public http(s) address, and distinct once canonicalized.

    This is URL policy, so it lives here at the boundary rather than in the
    request model (review finding F3). ``prefix`` is the path of the request
    in the body ("request." inside a saved thesis), so each field is named in full.
    """
    problems: list[Problem] = []
    seen: dict[str, int] = {}
    for index, url in enumerate(urls):
        field = f"{prefix}extra_urls.{index}"
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


class TimedCache[K, V]:
    """Values by key, each kept for :data:`limits.METRICS_CACHE_SECONDS`.

    Only successful results are kept, so an EDGAR outage is not remembered.
    Safe to share between threads.
    """

    def __init__(self, monotonic: Callable[[], float]) -> None:
        """Measure age with ``monotonic`` (seconds)."""
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._values: dict[K, tuple[float, V]] = {}

    def get(self, key: K) -> V | None:
        """The cached value for ``key`` if it is fresh, else None."""
        with self._lock:
            entry = self._values.get(key)
            if entry is None or self._monotonic() - entry[0] >= limits.METRICS_CACHE_SECONDS:
                return None
            return entry[1]

    def put(self, key: K, value: V) -> None:
        """Keep ``value`` for ``key`` from now."""
        with self._lock:
            self._values[key] = (self._monotonic(), value)


MetricsCache = TimedCache[int, MetricsReport]
ChangesCache = TimedCache[tuple[int, str], FilingChanges]
RunChangesCache = TimedCache[str, RunChanges]


def create_app(
    store: Store | None = None,
    filings: FilingSource | None = None,
    analyst: Analyst | None = None,
    fetch_page: PageFetcher = default_fetch_page,
    monotonic: Callable[[], float] = time.monotonic,
    cache: FilingCache | None = None,
    checker: Checker | None = None,
) -> FastAPI:
    """Build the application. Collaborators not given are built by :mod:`app.wiring`.

    ``monotonic`` is the clock of the metrics cache (injectable for tests).
    ``cache`` is the filing cache every run shares: the configured one when the
    store is the configured one, otherwise one in memory for this application.
    ``checker`` reads every run's findings again: the configured one when the
    engine is the configured one, otherwise none unless one is given.
    """
    if cache is None:
        cache = wiring.cache_from_env() if store is None else FilingCache()
    store = store or wiring.store_from_env()
    filings = filings or wiring.filings_from_env()
    if analyst is None:
        analyst = wiring.analyst_from_env()
        checker = checker or wiring.checker_from_env(analyst)
    checker = checker or NoChecker()
    executor = ThreadPoolExecutor(max_workers=RUN_WORKERS, thread_name_prefix="run")
    metrics_cache = MetricsCache(monotonic)
    changes_cache = ChangesCache(monotonic)
    run_changes_cache = RunChangesCache(monotonic)

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

    @app.exception_handler(Conflict)
    async def conflict(_: Request, exc: Conflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": str(exc)})

    def execute(run: Run) -> None:
        try:
            thesis_run.execute_run(
                run,
                store,
                filings=filings,
                analyst=analyst,
                fetch_page=fetch_page,
                cache=cache,
                checker=checker,
            )
        except Exception:  # noqa: BLE001 - last resort: a run must never stay "running"
            log.exception("Run %s crashed", run.id)
            thesis_run.fail_run(run, store, CRASH_MESSAGE)

    def check_request(request: ThesisRequest, prefix: str = "") -> None:
        """Refuse unsafe extra URLs and a ticker SEC does not list; fields carry ``prefix``."""
        problems = check_extra_urls(request.extra_urls, prefix)
        if problems:
            raise RequestRefused(problems)
        try:
            filings.company(request.ticker)
        except UnknownTicker as exc:
            raise RequestRefused([Problem(field=f"{prefix}ticker", message=str(exc))]) from exc

    def submit(run: Run) -> RunStarted:
        executor.submit(execute, run)
        return RunStarted(id=run.id, status=run.status)

    @app.post("/api/runs", status_code=202)
    def start_run(request: ThesisRequest) -> RunStarted:
        """Validate, resolve the ticker, then execute the run in the background."""
        check_request(request)
        run = thesis_run.new_run(request)
        store.save_run(run)
        return submit(run)

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
                    thesis_id=run.thesis_id,
                )
                for run in store.list_runs()
            ]
        )

    def load(run_id: str) -> Run:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    def review_of(run: Run) -> Review:
        return build_review(run, store.list_decisions(run.id))

    def changes_of(run: Run) -> RunChanges:
        """The run's claim-linked changes, computed once for a finished run and kept a while."""
        cached = run_changes_cache.get(run.id)
        if cached is not None:
            return cached
        result = run_changes(run, filings=filings, cache=cache)
        if run.status != RunStatus.running:
            run_changes_cache.put(run.id, result)
        return result

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> Run:
        """The full run record."""
        return load(run_id)

    @app.get("/api/runs/{run_id}/changes")
    def run_filing_changes(run_id: str) -> RunChanges:
        """For each claim of a run, the paragraphs that changed in the filings it read.

        Each filing the run read is compared with the filing of its form before it, and
        every changed paragraph is ranked against each claim by keyword overlap. No model
        is involved and nothing here is a verdict. 404 for an unknown run. A comparison
        that cannot be made (no earlier filing, EDGAR out of reach, a run still going)
        is a note in the record, never an error. The answer for a finished run is kept
        for 15 minutes.
        """
        return changes_of(load(run_id))

    @app.get("/api/runs/{run_id}/export.md")
    def export_run(
        run_id: str, reviewed: bool = False, changes: bool = False
    ) -> PlainTextResponse:
        """The run as a Markdown brief.

        ``reviewed=true`` adds the reviewer's decisions. ``changes=true`` adds the reading
        list of changed paragraphs under each claim (as ``/api/runs/{id}/changes`` gives it).
        """
        run = load(run_id)
        review = review_of(run) if reviewed else None
        listed = changes_of(run) if changes else None
        return PlainTextResponse(render_markdown(run, review, listed), media_type="text/markdown")

    @app.get("/api/runs/{run_id}/review")
    def get_review(run_id: str) -> Review:
        """Every decision on the run and the verdicts that follow from them."""
        return review_of(load(run_id))

    @app.put("/api/runs/{run_id}/findings/{finding_id}/decision")
    def put_decision(run_id: str, finding_id: str, body: DecisionRequest) -> Review:
        """Accept or reject one verified finding, or clear its decision with a null value.

        404 for an unknown run or a finding the run does not have; 409 while the
        run is still running; 422 (field ``finding_id``) for a withheld finding.
        """
        run = load(run_id)
        if run.status == RunStatus.running:
            raise Conflict(STILL_RUNNING)
        verified = {finding.id for finding in run.findings if finding.verified}
        if finding_id not in verified:
            withheld = {finding.id for finding in [*run.findings, *run.unsupported_findings]}
            if finding_id in withheld:
                raise RequestRefused([Problem(field="finding_id", message=WITHHELD_MESSAGE)])
            raise HTTPException(status_code=404, detail="Finding not found")
        if body.value is None:
            store.clear_decision(run.id, finding_id)
        else:
            store.save_decision(
                Decision(
                    run_id=run.id,
                    finding_id=finding_id,
                    value=body.value,
                    note=body.note,
                    decided_at=datetime.now(UTC),
                )
            )
        return review_of(run)

    # Saved theses

    def load_thesis(thesis_id: str) -> Thesis:
        thesis = store.get_thesis(thesis_id)
        if thesis is None:
            raise HTTPException(status_code=404, detail="Thesis not found")
        return thesis

    @app.post("/api/theses", status_code=201)
    def create_thesis(body: ThesisCreate) -> Thesis:
        """Save a named thesis; its request is checked as a run's would be."""
        check_request(body.request, prefix="request.")
        return theses.create_thesis(store, body)

    @app.get("/api/theses")
    def list_theses() -> ThesisList:
        """Saved theses, newest first, each with its run count and latest run."""
        summaries = []
        for thesis in store.list_theses():
            last = store.get_run(thesis.run_ids[0]) if thesis.run_ids else None
            summaries.append(
                ThesisSummary(
                    id=thesis.id,
                    name=thesis.name,
                    ticker=thesis.request.ticker,
                    claims=len(thesis.request.claims),
                    created_at=thesis.created_at,
                    runs=len(thesis.run_ids),
                    last_run_id=thesis.run_ids[0] if thesis.run_ids else None,
                    last_status=last.status if last else None,
                )
            )
        return ThesisList(theses=summaries)

    @app.get("/api/theses/{thesis_id}")
    def get_thesis(thesis_id: str) -> ThesisDetail:
        """The saved thesis and its runs, newest first."""
        thesis = load_thesis(thesis_id)
        runs = [
            ThesisRunSummary(
                id=run.id, status=run.status, started_at=run.started_at, finished_at=run.finished_at
            )
            for run in store.runs_of_thesis(thesis.id)
        ]
        return ThesisDetail(thesis=thesis, runs=runs)

    @app.post("/api/theses/{thesis_id}/runs", status_code=202)
    def run_thesis(thesis_id: str) -> RunStarted:
        """Run the saved thesis again, in the background like any run."""
        try:
            run = theses.start_thesis_run(store, thesis_id)
        except theses.UnknownThesis as exc:
            raise HTTPException(status_code=404, detail="Thesis not found") from exc
        return submit(run)

    @app.get("/api/theses/{thesis_id}/changes")
    def thesis_changes(thesis_id: str) -> RunComparison:
        """What moved between the two newest finished runs of the thesis."""
        try:
            return theses.latest_comparison(store, thesis_id)
        except theses.UnknownThesis as exc:
            raise HTTPException(status_code=404, detail="Thesis not found") from exc
        except theses.NotEnoughRuns as exc:
            raise Conflict(str(exc)) from exc

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

    @app.get("/api/companies/{ticker}/changes")
    def company_filing_changes(ticker: str, form: str = "10-K") -> FilingChanges:
        """What was added, removed and reworded between a company's two latest ``form`` filings.

        ``form`` is "10-K" or "10-Q". 422 for another form or for a malformed or unknown
        ticker; 503 when EDGAR cannot be read or lists fewer than two such filings. A
        result is cached per company and form for 15 minutes.
        """
        if form not in CHANGE_FORMS:
            raise RequestRefused([Problem(field="form", message="form must be 10-K or 10-Q")])
        company = resolve(ticker)
        cached = changes_cache.get((company.cik, form))
        if cached is not None:
            return cached
        result = filing_changes(company, form, filings=filings, cache=cache)
        changes_cache.put((company.cik, form), result)
        return result

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
            "decision_labels": policy.DECISION_LABELS,
            "review_note": policy.REVIEW_NOTE,
            "engine": analyst.name,
            "checker": {"name": checker.name, "detail": str(checker.detail or "")},
            "support_labels": policy.SUPPORT_LABELS,
            "no_checker_note": policy.NO_CHECKER_NOTE,
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
