"""Local HTTP API for measured BEA industry purchase flows."""

import csv
import io
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.flow_models import FlowView
from app.flows import explore, load_dataset

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate the complete data snapshot before accepting requests."""
    load_dataset()
    yield


app = FastAPI(title="Radius Industry Flow Explorer", version="0.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the visualization."""
    return FileResponse(WEB_DIR / "index.html")


@app.get("/app.js", include_in_schema=False)
def javascript() -> FileResponse:
    """Serve the relative asset used by both local-file and HTTP entry points."""
    return FileResponse(WEB_DIR / "app.js", media_type="text/javascript")


@app.get("/styles.css", include_in_schema=False)
def stylesheet() -> FileResponse:
    """Serve the relative stylesheet."""
    return FileResponse(WEB_DIR / "styles.css", media_type="text/css")


@app.get("/api/catalog")
def catalog() -> dict:
    """Return validated classification choices, years and provenance."""
    data = load_dataset()
    return {
        "industries": [{"id": k, "name": v} for k, v in data.industries.items()],
        "products": [{"id": k, "name": v} for k, v in data.products.items()],
        "years": sorted(data.tables),
        "source": data.source,
    }


@app.get("/api/flows", response_model=FlowView)
def flows(
    mode: Literal["inputs", "buyers"] = "inputs",
    focus: str = Query("334", pattern=r"^[A-Za-z0-9]{1,12}$"),
    year: int = Query(2025, ge=1997, le=2100),
    baseline: int = Query(2019, ge=1997, le=2100),
    sort: Literal["amount", "share_change"] = "amount",
    selected: str | None = Query(None, pattern=r"^[A-Za-z0-9]{1,12}$"),
) -> FlowView:
    """Calculate all rankings and annual series for the current selection."""
    try:
        return explore(load_dataset(), mode, focus, year, baseline, sort, selected)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/export")
def export(
    mode: Literal["inputs", "buyers"] = "inputs",
    focus: str = Query("334", pattern=r"^[A-Za-z0-9]{1,12}$"),
    year: int = Query(2025, ge=1997, le=2100),
    baseline: int = Query(2019, ge=1997, le=2100),
    sort: Literal["amount", "share_change"] = "amount",
) -> Response:
    """Export exactly the displayed ranking and its denominator."""
    result = flows(mode, focus, year, baseline, sort, None)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["BEA Use Summary", result.source["url"]])
    writer.writerow(
        [
            "Mode",
            mode,
            "Focus",
            focus,
            result.focus_name,
            "Year",
            year,
            "Comparison year",
            baseline,
        ]
    )
    writer.writerow(
        ["Denominator (millions USD)", result.total, result.denominator_label]
    )
    writer.writerow(
        [
            "Code",
            "Name",
            "Millions USD",
            "Share percent",
            "Comparison millions USD",
            "Nominal change percent",
            "Share change pp",
        ]
    )
    for row in result.rows:
        writer.writerow(
            [
                row.id,
                row.name,
                row.amount,
                row.share,
                row.baseline_amount,
                row.change_pct,
                row.share_change,
            ]
        )
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="bea-industry-flows.csv"'
        },
    )
