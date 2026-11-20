# Architecture

This repository holds independent coursework, the capstone plan and app, and the Week 2 Industry Flow Explorer. The root Makefile forwards its targets to one app: `make <target>` runs the capstone in Capstone/evidence_desk/ and `make APP=week2 <target>` runs Homework/Week 2/visualization/. AGENTS.md contains the repository rules.

## Capstone: Evidence Desk

Capstone/evidence_desk/ tests the claims of an investment thesis against a company's SEC filings: a ticker, a decision and one to six claims go in; a verdict per claim comes out, each backed by exact excerpts that the backend verified against the stored filing text. It keeps the stack of the Week 2 app (Python 3.14 / FastAPI, uv lock, Docker Compose on loopback with the port printed by Make, static frontend, ruff and pytest) and the same invariants: the backend computes everything, dependencies install at image build, and all commands run through the Makefile. Its layout, pipeline, patterns and boundary are described in Capstone/evidence_desk/ARCHITECTURE.md; the build prompt for the current milestone is Capstone/PROMPT.md.

## Week 2: Industry Flow Explorer

## Application

- Backend: Python 3.14, FastAPI, Pydantic and openpyxl.
- Frontend: static HTML, CSS and browser-native JavaScript/SVG, with no package dependencies or build step.
- Container: Docker Compose, bound only to 127.0.0.1:8765. Dependencies are installed at image build using docker/pyproject.toml and docker/uv.lock.
- Source: the unchanged official BEA Use_Summary.xlsx in data/raw/bea/, with URL, retrieval date and SHA256 in source.json. The previous supplied NYSE workbook remains untouched but is not used in this visualization.
- Runtime: no external data requests. Startup validates and caches the committed snapshot.

The application layout is:

    main.py                 Vercel entrypoint for the existing FastAPI app
    requirements.txt        runtime dependencies exported from the Docker lock
    .python-version         Python 3.14 for hosted builds
    vercel.json             FastAPI hosting configuration and bundle exclusions
    .vercelignore           CLI upload exclusions
    docker/                 image, compose definition and dependency lock
    src/app/acquire.py      explicit official data download and inspection
    src/app/flows.py        source validation and research calculations
    src/app/flow_models.py  response types
    src/app/api.py          validated API endpoints and static assets
    src/web/               HTML, CSS and JavaScript/SVG rendering
    data/raw/bea/          official workbook and provenance
    tests/                 independent arithmetic tests and live HTTP checks
    snapshots/             the capstone's version history for the website (below)

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
- GET /versions, /vN/ and /live/status: the capstone's versions table, version N of the capstone running live from vendored/vN (or its recorded snapshot from snapshots/vN when it cannot run), and what the live versions run with (see "The website's capstone versions" below); /vN redirects to /vN/.

A direct file:// visit displays a link to the running local app instead of leaving an empty or misleading chart.

## Verification and operation

make data downloads the official BEA bundle only if the local workbook is absent. Existing snapshots are not overwritten. The raw workbook and manifest are committed so make verify does not need a data download or API key. A future data refresh must explicitly update and review the snapshot, provenance and coverage expectations together.

make verify builds the image, lints Python, checks JavaScript syntax in a Node container, runs independent numerical tests and a full-workbook validation, then checks the running HTTP API, CSV, empty selections, input errors and page assets. It stops the service afterward. make up rebuilds and recreates the app so the in-memory snapshot reflects current files.

The tests use an asymmetric synthetic matrix to check direction, denominators, share changes, negative adjustments, undefined growth and missing cells. Snapshot tests independently check specific source values and coverage. Browser layout and interaction checks are separate from this automated gate.

## Optional Vercel hosting

Vercel's project root is Homework/Week 2/visualization/. Its native Python runtime imports main.py, which adds the local src/ directory to the import path and exposes the same FastAPI instance used by Docker. All file reads resolve from source file locations, so no hosted working-directory override is needed. Python 3.14 is selected by .python-version. Runtime dependencies are exported from docker/uv.lock by make vercel-deps; no packages are installed on the host.

The hosted function includes the BEA snapshot and web assets. Bundle/upload exclusions omit the unused NYSE workbook, development tests and Docker files. The Week 2 application has no writable data store and no runtime secrets; the capstone versions mounted in it write under /tmp and read a model key and an SEC contact string from Vercel's environment (below). Cold starts validate and cache the workbook inside each function process. Local Docker remains bound to 127.0.0.1; an eventual Vercel deployment serves through Vercel's HTTPS endpoint, as requested by the user.

The entrypoint test imports the app in a subprocess with Python environment overrides ignored, then checks source loading and the HTML file. This verifies independence from Docker's PYTHONPATH; it does not replace a live Vercel deployment check.

## The website's capstone versions

`/vN/` is version N of Evidence Desk, running. docs/site-live.md has the design, the limits and the environment variables; in outline:

- `tools/live/versions.map` names the git ref of each version. `make site-vendor` (`tools/live/vendor.py`, standard library, in a `python:3.14-slim` container) copies each ref's `Capstone/evidence_desk/src` out of git into `Homework/Week 2/visualization/vendored/vN/` with the package `app` renamed `ed_vN`, and writes `vendored/seed/` from the newest ref's recorded EDGAR fixtures. The vendored tree is committed: Vercel's build has no tags to vendor from, and a committed tree is reviewed and tested. `make site-version N=15` adds or repoints a version.
- `src/live/` in the Week 2 app: `versions.py` imports a version on its first request and builds it with its data under `/tmp/evidence-desk/vN`, its own EDGAR client over the seed (`seed.py`) and a page fetcher that refuses every address; `guard.py` is the allow-list of writes, the refusal of visitor-supplied URLs and the caps, all per server instance; `site.py` is the ASGI app mounted at `/vN` (the version's page with a banner and `shim.js`, the held run start, the fallback to the recorded snapshot) and `/live/status`.
- One `requirements.txt` serves the Week 2 app and every version: `docker/pyproject.toml` holds the capstone's runtime dependencies at the versions its lock has at every tag.
- The services `live` and `live-fresh` in `docker/compose.yaml` run the function as Vercel does (read-only source, writable /tmp only, no key, EDGAR unreachable) on 127.0.0.1:8790; `make site-live-test` makes a run with every version through the shim and reads it back from a process that never saw it; `make site-live-shots` takes pictures of the pages.

The recorded snapshots below remain: each is served in its version's place when the version cannot be built on the server, or when `LIVE_VERSIONS=off`.

## The website's capstone snapshots

The Vercel project of this app is the course's public website, so it also carries the capstone's history: `/versions` is the table of versions, and `snapshots/vN/` a recorded, read-only snapshot of Evidence Desk version N, which was what `/vN/` served before the versions ran live and is now the fallback.

- `tools/snapshots/export.py` (repository root, run by `make site-export` in a `python:3.14-slim` container, standard library only) reads each version running locally at `127.0.0.1:87NN` and writes `snapshots/vN/`: the page's own files as served (index.html, app.js, styles.css, every `sample-*.json` the page names), the GET answers its page reads on load and when a stored run or thesis is opened (under `api/`, byte for byte), `snapshot.json` (what was recorded, from where) and `snapshot.js`.
- Only the exported copy is changed: its absolute references become relative, and a banner and `snapshot.js` are added. `snapshot.js` answers the page's `fetch` calls to `/api/...` from the recorded files and answers anything that would start work, or a GET that was not recorded, with an error in the shape the page already shows. It computes nothing.
- `tools/snapshots/versions_page.py` renders `docs/versions.md` as `snapshots/versions.html`. `scan.py` (`make site-scan`, also run by `make site-export`) fails on anything that looks like a secret or personal data in those files. `check.py` (`make site-check URL=...`) checks a deployed site.
- The app serves `/versions`, and `snapshots/vN/` as static files at `/vN/` in the cases above; the existing routes are unchanged. `make site-test` tests the exporter, the scan and the page renderer in Python and the shim in Node; `make site-browse` serves the snapshots with this app on 127.0.0.1:8765 (with `LIVE_VERSIONS=off`) and renders each `/vN/` and `/vN/?sample` in headless Chromium (the image the capstone's page tests use), checking the banner, that every call on load was answered, and that the recorded run is shown; the app's own tests check every snapshot is served whole.

## Scope

This is an annual view of nominal U.S. intermediate purchases, including imported inputs. It excludes final-demand columns such as capital formation, household consumption and exports. It does not infer company suppliers, stock returns, shock transmission or complete capital-expenditure chains. Native SVG is adequate for the ranked bars and annual series; no additional chart dependency is needed.
