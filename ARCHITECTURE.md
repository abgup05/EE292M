# Architecture

This repository holds weekly coursework and one built app. AGENTS.md contains the working rules. The root Makefile forwards commands to the Week 2 visualization folder; the other homework files are independent.

## Week 2 visualization

The Radius Dependency Explorer lives entirely under Homework/Week 2/visualization/, except for the root Makefile, README, and this architecture note. It is the first implemented app in the repository.

- Backend: Python 3.14, FastAPI, Pydantic response models, and openpyxl. The API contract is at /docs.
- Frontend: static HTML, CSS, and browser-native JavaScript/SVG. It has no frontend package dependency or build step.
- Container: one Docker Compose project, bound to 127.0.0.1:8765. The base image is pinned to the Python 3.14 minor version. The app runs as the host user with the repository mounted at /work.
- Dependencies: docker/pyproject.toml and docker/uv.lock. A container-only lock stage generates the lock; the app image installs from it at build time. No dependency is fetched when the app starts.
- Data: data/raw/ holds an unchanged copy of the supplied NYSE classification workbook. data/conceptual_links.json holds seven authored sector-level links. There is no company relationship database yet.

The nested app layout is:

    docker/                 Dockerfile, compose.yaml, pyproject.toml, uv.lock
    src/app/                api.py (routes), pipeline.py (data work), models.py (response types)
    src/web/                index.html, app.js, styles.css
    data/raw/               supplied source workbook
    data/conceptual_links.json
    tests/                  pytest pipeline checks
    Makefile                container-backed targets
    README.md               use, data limits, and API description

The API loads and checks the workbook on first request. It verifies that all 50 guide counts match the 2,922 listings before serving results. /api/search performs ticker/name matching and ranking in Python. /api/graph returns the fixed seven-node theme, the selected sector, and which directed sector links touch it. The frontend positions nodes, draws arrows, and handles input, but does not calculate financial or research results. An error hides the earlier graph, so a failed request cannot leave a stale result on screen.

The theme graph is intentionally conceptual. Its edges express potential sector inputs or uses, not documented company trade, revenue shares, or market effects. The search can locate any workbook security, including one outside the seven-node theme, but the page shows that such a sector has no mapped theme connection. Multiple share classes and investment products remain source listings, not distinct business nodes.

## Build and verification

From the repository root or nested app, make help lists commands. make lock resolves dependencies inside Docker; make build installs them into the image; make up and make down manage the loopback-only service. make verify builds the image, runs Ruff, a containerized Node syntax check, and pytest, then starts the app and checks live graph, sector, search, and page responses before stopping it. The pipeline tests check source reconciliation, search membership, edge direction and selection, and unknown-sector rejection. The root Makefile delegates each target to the nested app so the same gate works from a fresh clone.

This structure departs from the original root-level scaffold because the requested Week 2 deliverable belongs in its own homework folder. It uses native SVG instead of D3 because seven fixed sector nodes need no chart package. Node runs only in a verification container; it adds no package or build step to the web app.
