# Radius Industry Flow Explorer

A research visualization for asking **what an industry buys**, **who buys a product**, and **which relationships are changing**. It uses official BEA data across 1997–2025, rather than an authored network.

## Use it

Run `make up` from this folder or the repository root, then open <http://127.0.0.1:8765>. Opening index.html directly shows a link to this local service.

1. Try a starting question, or choose an industry/product from the dropdown.
2. Set the year and comparison year.
3. Rank by purchase amount or by gain in share. Shares use the complete published intermediate total, not only the largest rows.
4. Click a relationship to see its annual purchases and share. The comparison year is marked in amber; the selected year in green. Click a chart point to inspect that year.
5. Expand Annual values for exact numbers, or download the ranked data as CSV.

For example, use computer manufacturing inputs to inspect its largest production costs. Use electrical equipment buyers to identify industrial demand categories. Compare petroleum-product buyers to explore customer mix. These are starting questions, not claims that particular stocks will benefit.

## Data and interpretation

Source: [BEA Supply–Use Tables](https://www.bea.gov/itable/input-output), official [workbook bundle](https://apps.bea.gov/industry/release/zip/SUPPLY-USE.zip), and [table definitions](https://www.bea.gov/resources/guide-interactive-industry-input-output-accounts-tables).

The committed Use_Summary.xlsx has 29 annual sheets, 73 product categories and 71 buying industries. data/raw/bea/source.json records its original download URL, retrieval time and SHA256. The backend verifies the checksum, axes, units and published totals on startup. No network call or API key is needed to explore the snapshot.

- These are commodity-to-industry purchases across the U.S. economy, including imported inputs. Product categories are not individual supplier companies.
- Values are millions of current U.S. dollars in the source; the API formats billions/trillions for display. Changes combine price and quantity effects.
- Industry-input shares divide by all intermediate inputs purchased by that industry (T005). Product-buyer shares divide by intermediate use of that product across all industries (T001).
- Final uses are excluded: this is not a full map of equipment investment, construction capex, household purchases or exports.
- Negative adjustments are retained. Individual positive shares can therefore sum above 100%.
- Ellipses remain unreported cells, excluded from numeric rankings and drawn as gaps in history. Numeric zero remains zero. A missing/nonpositive total has no percentage share, and a missing/nonpositive comparison amount has no percentage-growth result.
- Share changes are percentage points. A move from 10% to 15% is +5 pp.
- BEA values are independently rounded; displayed shares need not add to exactly 100%.

The original NYSE workbook remains unchanged in data/raw/ but is no longer used by the app. The old illustrative links have been removed.

## Run and verify

Docker and Make are required. Nothing is installed on the host.

```text
make help
make verify
make up
make down
```

make verify builds the image, lints Python, checks JavaScript syntax, runs numerical/source tests and real HTTP checks, then stops the service. Use make up afterward. The service binds only to 127.0.0.1. API documentation: <http://127.0.0.1:8765/docs>.

make data acquires the official workbook only when absent, then inspects it. It never silently updates an existing snapshot. Dependencies are locked in docker/uv.lock and installed at image build. make lock updates the lock inside Docker.

## API

- GET /api/catalog
- GET /api/flows?mode=inputs&focus=334&year=2025&baseline=2019&sort=amount
- GET /api/flows?mode=buyers&focus=335&year=2025&baseline=2019&sort=share_change
- GET /api/export with the same selection parameters

The backend computes all research results; the frontend handles interaction and chart geometry only. Calculations are covered by independent synthetic examples, full-source reconciliation, known source-cell checks and live endpoint validation. Visual browser checks are not part of make verify.

## Deploy on Vercel

The app is prepared for Vercel's native FastAPI/Python runtime. Vercel runs the Python app directly; the Docker setup remains for local development.

1. Push the committed app to GitHub. The implementation is on `codex/week2-radius-visualization`; deploy that branch, or merge it through a reviewed pull request before deploying `main`.
2. In [Vercel New Project](https://vercel.com/new), import `abgup05/EE292M`. Select the branch containing these files. If the import screen starts from `main`, use the branch's GitHub URL or create a deployment from the feature branch after import.
3. Set **Root Directory** to `Homework/Week 2/visualization` (the entire app folder, not `src/web`).
4. Use the **FastAPI** framework preset. Leave Build Command, Install Command and Output Directory at their framework defaults. No environment variables or API keys are needed for this app.
5. Deploy, then check the homepage, switch between both views, change a year, and download a CSV. `/api/catalog` should return the categories and years; `/docs` should show the API.
6. Paste the working website URL into the Website field in [W2L2.md](../W2L2.md). Check the link in a signed-out browser before submitting it so you know whether your Vercel project's access settings allow your reviewer to open it.

Deployment files:

- `main.py` exposes the existing app and supplies the source import path that Docker normally provides.
- `.python-version` selects Python 3.14.
- `requirements.txt` contains pinned runtime dependencies exported from the existing Docker lock. After changing dependencies, run `make lock` and `make vercel-deps`, and commit both the lock and exported requirements.
- `vercel.json` selects FastAPI and excludes tests, Docker files and the unused NYSE workbook from the function bundle. `.vercelignore` also excludes those files from CLI uploads.
- The official BEA workbook, provenance file and web assets stay in the deployment so the app can read them without a separate storage service.

Local checks validate the entrypoint without Docker's `PYTHONPATH`, source loading, static files and API behavior. A live Vercel build and deployment have not yet been verified.

Official references: [FastAPI on Vercel](https://vercel.com/docs/frameworks/backend/fastapi), [Python runtime](https://vercel.com/docs/functions/runtimes/python), and [Git deployments](https://vercel.com/docs/git).
