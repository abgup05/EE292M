# Radius Dependency Explorer

This Week 2 app visualizes how selected subsectors fit into an AI infrastructure theme. Search any ticker or company in the supplied NYSE workbook, inspect its primary classification, and select a node to see incoming and outgoing theme links. The Python backend reads the raw workbook, validates the category counts, computes search and selection results, and returns them through a documented API. The static page draws the graph and handles interaction.

The arrows are **conceptual sector dependencies** curated for this demonstration. They are not verified commercial links between the example companies. The workbook is a September 24, 2026 snapshot of 2,922 listed securities in 50 categories; listings are not distinct issuers. Preferred shares, funds, SPAC instruments, and multiple share classes remain in the source. If a search result belongs to a sector outside the seven mapped theme slices, the app shows its workbook classification and says that the theme has no mapped connection for it.

## Run and verify

From this folder or the EE292M repository root:

```text
make help
make verify
make up
make down
```

Open <http://127.0.0.1:8765> after `make up`. The API contract is at <http://127.0.0.1:8765/docs>. `make verify` builds the pinned container, runs the pipeline tests, Python lint and JavaScript syntax checks, and checks real HTTP responses. Only Docker, Make, and git are needed on the host. No host packages are installed. The service listens only on `127.0.0.1`.

Change Python dependencies in `docker/pyproject.toml`, then run `make lock` to regenerate `docker/uv.lock` in the lock container. Commit the manifest and lock together. There are no frontend packages: the directed network uses browser-native SVG and JavaScript.

## Source and data rules

- `data/raw/NYSE_50_sector_classification.xlsx` is an unchanged copy of the supplied workbook. Keep it read-only.
- `data/conceptual_links.json` is the seven-category illustration. Each arrow has direction and a short role; none claims company-level evidence.
- The backend checks each guide count against the listings sheet before serving data. It refuses incomplete or changed input rather than silently showing a partial graph.
- Search includes all workbook securities. Example tickers in the inspector are the examples recorded by the workbook, not a complete membership list.

## API

- `GET /api/sectors`: all 50 workbook categories.
- `GET /api/search?q=VRT&limit=10`: ranked ticker/name matches, with security type and classification.
- `GET /api/graph?focus=11`: the seven-node theme and the selected category's incident links. The response labels every link as conceptual.

The app does not estimate company revenue exposure, supplier shares, or stock-price effects. A later evidence-backed company network would require its own relationship table with sources and review dates.
