# Architecture

This repository holds independent coursework, capstone pitches, and the Week 2 Industry Flow Explorer. The root Makefile forwards its targets to Homework/Week 2/visualization/. AGENTS.md contains the repository rules.

## Application

- Backend: Python 3.14, FastAPI, Pydantic and openpyxl.
- Frontend: static HTML, CSS and browser-native JavaScript/SVG, with no package dependencies or build step.
- Container: Docker Compose, bound only to 127.0.0.1:8765. Dependencies are installed at image build using docker/pyproject.toml and docker/uv.lock.
- Source: the unchanged official BEA Use_Summary.xlsx in data/raw/bea/, with URL, retrieval date and SHA256 in source.json. The previous supplied NYSE workbook remains untouched but is not used in this visualization.
- Runtime: no external data requests. Startup validates and caches the committed snapshot.

The application layout is:

    docker/                 image, compose definition and dependency lock
    src/app/acquire.py      explicit official data download and inspection
    src/app/flows.py        source validation and research calculations
    src/app/flow_models.py  response types
    src/app/api.py          validated API endpoints and static assets
    src/web/               HTML, CSS and JavaScript/SVG rendering
    data/raw/bea/          official workbook and provenance
    tests/                 independent arithmetic tests and live HTTP checks

## Computation boundary

The BEA use table is commodity-by-industry. Each annual sheet contains 73 product rows and 71 buying-industry columns, followed by published intermediate totals and final uses. The parser locates boundaries by BEA codes T005 and T001, checks consistent classifications and units, preserves negative numbers and ellipses, and reconciles numeric flows to published totals within the rounding bound for independently rounded millions.

The backend computes all rankings, shares, comparison-year changes, annual series and display-unit conversions. Shares use the relevant published intermediate total, including negative adjustments. Missing cells remain null and do not become measured zero. Shares are unavailable for nonpositive or missing denominators; percentage growth requires a positive baseline. Rankings return all numeric flows, including zeros and negative adjustments.

The browser draws bar lengths and time-series geometry, chooses which backend-provided measure to draw, and handles input. It performs no research filtering, statistics or monetary conversion. A request sequence guard prevents stale responses from replacing newer selections; failed requests hide earlier results.

## API and files

- GET /api/catalog: axes, available years and source provenance.
- GET /api/flows: inputs or buyers view, selected year, comparison year, ranking and selected relationship history.
- GET /api/export: CSV of the same computed ranking and denominator.
- GET /: page; /app.js and /styles.css: relative assets also usable by the local-file entry page.
- /docs: generated API documentation.

A direct file:// visit displays a link to the running local app instead of leaving an empty or misleading chart.

## Verification and operation

make data downloads the official BEA bundle only if the local workbook is absent. Existing snapshots are not overwritten. The raw workbook and manifest are committed so make verify does not need a data download or API key. A future data refresh must explicitly update and review the snapshot, provenance and coverage expectations together.

make verify builds the image, lints Python, checks JavaScript syntax in a Node container, runs independent numerical tests and a full-workbook validation, then checks the running HTTP API, CSV, empty selections, input errors and page assets. It stops the service afterward. make up rebuilds and recreates the app so the in-memory snapshot reflects current files.

The tests use an asymmetric synthetic matrix to check direction, denominators, share changes, negative adjustments, undefined growth and missing cells. Snapshot tests independently check specific source values and coverage. Browser layout and interaction checks are separate from this automated gate.

## Scope

This is an annual view of nominal U.S. intermediate purchases, including imported inputs. It excludes final-demand columns such as capital formation, household consumption and exports. It does not infer company suppliers, stock returns, shock transmission or complete capital-expenditure chains. Native SVG is adequate for the ranked bars and annual series; no additional chart dependency is needed.
