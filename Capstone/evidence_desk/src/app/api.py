"""HTTP API and static assets.

The backend is the authority for what counts as a verified finding: runs are
executed server-side and only the verified record is returned. Credentials
are read from the environment here and never reach the client.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from app.claude import ClaudeSynthesizer
from app.export import render_markdown
from app.fetch import fetch_page
from app.models import ResearchRequest, Run
from app.pipeline import Fetcher, Searcher, execute_run, new_run
from app.search import searcher_from_env
from app.store import Store
from app.synthesize import ExtractiveSynthesizer, Synthesizer

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
DEFAULT_DATA_DIR = Path(os.environ.get("EVIDENCE_DESK_DATA_DIR", "data/runs"))
log = logging.getLogger(__name__)
_FROM_ENV: Any = object()


def synthesizer_from_env() -> Synthesizer:
    """Claude when a key is configured, otherwise the deterministic extractive backend."""
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return ClaudeSynthesizer()
    return ExtractiveSynthesizer()


def create_app(
    store: Store | None = None,
    fetcher: Fetcher = fetch_page,
    synthesizer: Synthesizer | None = None,
    searcher: Searcher | None = _FROM_ENV,
) -> FastAPI:
    """Build the application; every collaborator is injectable for tests."""
    app = FastAPI(title="Evidence Desk", version="0.1.0", docs_url="/docs")
    state = {
        "store": store or Store(DEFAULT_DATA_DIR / "runs.sqlite"),
        "fetcher": fetcher,
        "synthesizer": synthesizer or synthesizer_from_env(),
        "searcher": searcher_from_env() if searcher is _FROM_ENV else searcher,
        "executor": ThreadPoolExecutor(max_workers=2, thread_name_prefix="run"),
    }

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body") or "body",
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422, content={"error": "Invalid request", "details": details}
        )

    def _run_in_background(run: Run) -> None:
        try:
            execute_run(
                run,
                state["store"],
                fetcher=state["fetcher"],
                synthesizer=state["synthesizer"],
                searcher=state["searcher"],
            )
        except Exception:  # noqa: BLE001 - last resort: never leave a run stuck in "running"
            log.exception("run %s crashed", run.id)
            run.status = "failed"
            run.errors.append("The run stopped because of an internal error.")
            state["store"].save_run(run)

    @app.post("/api/research", status_code=202)
    def start_research(request: ResearchRequest) -> dict[str, str]:
        run = new_run(request)
        state["store"].save_run(run)
        state["executor"].submit(_run_in_background, run)
        return {"id": run.id, "status": run.status}

    @app.get("/api/research")
    def list_research() -> dict[str, list[dict[str, Any]]]:
        return {
            "runs": [
                {
                    "id": run.id,
                    "status": run.status,
                    "question": run.inputs.question,
                    "started_at": run.started_at.isoformat(),
                }
                for run in state["store"].list_runs()
            ]
        }

    def _load(run_id: str) -> Run:
        run = state["store"].get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @app.get("/api/research/{run_id}")
    def get_research(run_id: str) -> Run:
        return _load(run_id)

    @app.get("/api/research/{run_id}/export.md")
    def export_research(run_id: str) -> PlainTextResponse:
        return PlainTextResponse(render_markdown(_load(run_id)), media_type="text/markdown")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/app.js", include_in_schema=False)
    def script() -> FileResponse:
        return FileResponse(WEB_DIR / "app.js", media_type="text/javascript")

    @app.get("/styles.css", include_in_schema=False)
    def styles() -> FileResponse:
        return FileResponse(WEB_DIR / "styles.css", media_type="text/css")

    return app


app = create_app()
