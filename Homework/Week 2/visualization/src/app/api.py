"""HTTP routes for the Radius sector dependency visualization."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import GraphResponse, SearchHit, SectorDetail
from app.pipeline import build_graph, project_catalog, search_catalog

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
app = FastAPI(title="Radius Dependency Explorer", version="0.1.0")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the single static web page."""
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/sectors", response_model=list[SectorDetail])
def sectors() -> list[SectorDetail]:
    """List all 50 classifications in source order."""
    try:
        return list(project_catalog().sectors.values())
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=500, detail="Source data is unavailable"
        ) from exc


@app.get("/api/graph", response_model=GraphResponse)
def graph(focus: str = Query("47", pattern=r"^[0-9]{2}$")) -> GraphResponse:
    """Return the theme and the sector selected for inspection."""
    try:
        return build_graph(project_catalog(), focus)
    except (FileNotFoundError, ValueError) as exc:
        if str(exc).startswith("Unknown sector:"):
            raise HTTPException(status_code=404, detail="Sector not found") from exc
        raise HTTPException(
            status_code=500, detail="Source data is unavailable"
        ) from exc


@app.get("/api/search", response_model=list[SearchHit])
def search(
    q: str = Query(min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f]+$"),
    limit: int = Query(10, ge=1, le=25),
) -> list[SearchHit]:
    """Search workbook securities and report their classification."""
    if not q.strip():
        raise HTTPException(status_code=422, detail="Search text is required")
    try:
        return search_catalog(project_catalog(), q, limit)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=500, detail="Source data is unavailable"
        ) from exc
