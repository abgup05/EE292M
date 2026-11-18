# The capstone's versions, running live on the website

The website (<https://ee292m-visualization.vercel.app>, the Vercel project of the Week 2 app) serves every tagged version of Evidence Desk at `/vN/` as that version's own app, running: its page, its API, its engine. Before this, `/vN/` was a recorded, read-only snapshot with the banner "Live runs need the app running locally." The recordings are still in the repository and still served, but only as a fallback (see "When a version cannot run live").

Nothing here is deployed by a command in this repository. Vercel deploys `Homework/Week 2/visualization` when a pull request is merged to `main`.

## Design

**One function, every version.** Every version's Python package is called `app`, as is the Week 2 app's, and one process can hold one package of a name. `make site-vendor` copies each version's `Capstone/evidence_desk/src` out of git (`git archive` of the ref named in `tools/live/versions.map`, never a working tree) into `Homework/Week 2/visualization/vendored/vN/`, with one mechanical change made by `tools/live/vendor.py`: the package `app` becomes `ed_vN`. Only two kinds of token change, and each change is counted in `vendored/vN/VENDORED.json`: a module name in an `import` or `from` statement, and a string literal that is exactly a module name of the package (`"app."`, `"app.watch"`). The web files are copied byte for byte. The Week 2 app (`src/app/api.py`) mounts `live.site.LiveVersionApp` at each `/vN`; a version is imported and built on its first request.

**Why the vendored tree is committed, not built on Vercel.** Vercel's build has a shallow clone without the tags, so it cannot read `capstone-v9` out of git; and a rename that runs only on Vercel could not be reviewed in a pull request or tested by `make verify`. The cost is 32 MB of working tree (`du -sk vendored`), about 6 MB as a gzip archive (`git archive HEAD vendored | gzip -9 | wc -c`).

**Read-only disk.** On Vercel only `/tmp` is writable; it is not shared between instances and is not kept. Each version is built with `EVIDENCE_DESK_DATA_DIR=/tmp/evidence-desk/vN` (the variable every version already reads), so its record, cache and facts databases are created there, empty. No checkout's `data/record/record.sqlite` is read, copied or shipped: the function bundle holds no database at all. A version's samples are static files of its own page (`web/sample-*.json`) and need no seeding.

**EDGAR and the seed.** Versions 2 and later get their own EDGAR client (its host allow-list, rate limit, size cap and parsing unchanged) over `live.seed.SeedTransport`. It answers a filed document (`/Archives/edgar/data/...`, which never changes) from `vendored/seed/` when the recording is whole, and sends every other request to EDGAR, falling back to the seed only when EDGAR does not answer (no connection, timeout, HTTP 403, 429, 5xx). The seed is the 23 recorded answers of `capstone-v14`'s test fixtures (`vendored/seed/seed.json`; 18 whole, 5 trimmed when they were recorded, as `make site-vendor` prints): enough for a run of the page's own NVIDIA example with EDGAR out of reach, which is what `make site-live-test` proves. **It does not cover the eight probe companies**: for any company but NVIDIA the function depends on EDGAR answering. Recording more needs requests to EDGAR under the owner's contact string, which this work did not have.

**Runs that outlive a request.** Every version answers a run start with an id and works in a background thread while the page polls. A serverless instance may be frozen once the response is sent, and the next request may reach another instance. So `LiveVersionApp` holds the run-start request open until the run has finished (or `LIVE_HOLD_SECONDS`, default 285, under the function's `maxDuration` of 300 seconds, which is the Hobby plan's limit). To the shim (`src/live/shim.js`, served as `/vN/live-shim.js` and loaded before the page's script) the answer is a stream of JSON lines: `started` (the version's own answer and the run as first saved), `progress` when the run record changes, `tick` every 5 seconds, then `finished` (the run, its review and its brief) or `timeout`. The shim hands the page the version's own first answer at once, answers the page's polling from the lines that follow, and keeps a finished run in `sessionStorage`, so the run is still readable when a later request reaches an instance that never saw it. A caller without the shim gets the version's own answer, sent once the run has finished.

**The guard** (`src/live/guard.py`) is in front of every request to every version, whoever sends it; it is on the server, so calling a version's API directly does not go round it.

- Writes: only the writes a version's page makes are let through (start a run, save a thesis, decide a finding, mark inbox items read, set or remove a watch). Anything else that is not GET or HEAD is refused with 405. No address deletes a run, a thesis or a file.
- Visitor-supplied URLs are refused: `extra_urls` must be empty (422), and version 1's `seed_urls` may name only the two pages of its own example. Behind that, the version is built with a page fetcher that refuses every address, so a request that got past the check still fetches nothing.
- Caps, counted per UTC day: model runs in all and per visitor, runs in all and per visitor, reads that make the server fetch filings per visitor; at most two runs at once, and one at a time when the model engine is on. A request body is at most 16,384 bytes and a query string 2,048.
- A visitor is told apart by the address Vercel's proxy reports. A forwarding header is believed only where Vercel runs the function (the `VERCEL` variable it sets); anywhere else the connection's own address is used.

**The caps are per server instance.** The function has no shared storage, so every count is in one process's memory. A visitor whose requests reach several instances, or who waits for an instance to recycle, can start more runs than one cap allows. The page says so. A hard total needs a shared store (Redis from the Vercel Marketplace), or a spend limit on the key itself, which is the limit that does not depend on this code: **set one in the Anthropic console.**

**The banner.** Each live page starts with one line: the version and its tag, "running live on a shared public server", whether the model engine is on, "runs are not kept", and for versions 13 and later "no watcher runs online"; then "What is different here" with each point in full, and links to `/versions` and the tag. The vendored `index.html` is not changed on disk: the banner, the shim and relative references are added as the page is served.

## Environment variables to set in Vercel

Project → Settings → Environment Variables, for Production. Redeploy after changing one.

| Variable | Needed | What it does |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | for the model engine | With it every version uses Claude as it does locally. Without it each version uses its own engine without a model, and the banner says "model engine off". |
| `SEC_USER_AGENT` | yes | The contact string SEC asks of anyone reading EDGAR; each version sends it as its `User-Agent`. Without it the versions send their generic default and EDGAR may refuse them. |
| `LIVE_MODEL_RUNS_PER_DAY` | no, default 20 | Model runs an instance starts per UTC day. |
| `LIVE_MODEL_RUNS_PER_CLIENT_PER_DAY` | no, default 3 | The same, per visitor. |
| `LIVE_RUNS_PER_DAY` | no, default 300 | Runs of any kind an instance starts per day. |
| `LIVE_RUNS_PER_CLIENT_PER_DAY` | no, default 20 | The same, per visitor. |
| `LIVE_RUNS_AT_ONCE` | no, default 2 | Runs in progress on an instance (with the model engine on, one). |
| `LIVE_READS_PER_CLIENT_PER_DAY` | no, default 120 | Reads per visitor that make the server fetch filings. |
| `LIVE_MAX_BODY_BYTES` | no, default 16384 | Longest request body. |
| `LIVE_HOLD_SECONDS` | no, default 285 | Longest a run-start request is held. Keep it under `maxDuration` in `vercel.json` (300 on Hobby; a Pro plan allows 800). |
| `LIVE_VERSIONS` | no | `off` serves every version's recorded snapshot and runs nothing: the switch to pull if the key is being spent. |

A cap that is not a whole number is ignored and named in `/live/status` (`caps_invalid`). The versions also read `ANTHROPIC_MODEL`, `ANTHROPIC_CHECK_MODEL`, `ANTHROPIC_READER_MODEL`, `ANTHROPIC_READER_MODEL_2` and `EVIDENCE_DESK_CLAIM_READER` as they do locally; leave them unset to run each version with the models its tag names. A "model run" is one run; a version makes several requests to the API within it (versions 5 and later also check each finding with a second model). `EVIDENCE_DESK_CASSETTE` and `EVIDENCE_DESK_CASSETTE_RECORD` are blanked while a version is built, and version 1's web search is off whatever `BRAVE_SEARCH_API_KEY` says.

`GET /live/status` reports whether the key and the contact string are present (booleans), the caps, the counts of the instance that answered, the seed's use, and for each version whether it is served live or recorded. It never returns the key, the contact string or a visitor's address. `?imports=true` builds every version first.

## What differs from a version run locally

The source of each version is as tagged apart from the rename. These differences are made around it, by `src/live`:

1. Visitor-supplied URLs are refused (`extra_urls`; version 1's `seed_urls` beyond its example), and version 1 has no web search.
2. A run-start request is answered when the run has finished, not at once (the shim hides this from the page).
3. Every write the page does not make is refused; the caps above apply.
4. Data is in `/tmp` and is not kept; other visitors of the same instance see the same runs and saved theses.
5. No watcher process runs (versions 13 and later): a watch can be set and removed, the page's own header says "Watch not running", and nothing checks for new filings.
6. Each version's `/docs` and `/openapi.json` are served under `/vN/` as they are locally.
7. The fingerprint versions 4 and later take of their own parser source (a cache key) differs from the tag's, because the source differs by the rename. Nothing is compared against it across installations.

## When a version cannot run live

If a version cannot be imported or built on the server, `/vN/` is answered by its recorded snapshot (`snapshots/vN`, with the recorded banner), and `/live/status` names the version, `"serving": "recorded"` and the error's type. Under the emulation all 14 versions run live, so today no version is known to need this. `make site-check URL=...` reports each version as LIVE or RECORDED and fails on a vendored version that is served recorded.

## Proof before `main`, and what it does not prove

- `make site-live-test` runs the function as Vercel does, twice (`docker/compose.yaml`, services `live` and `live-fresh`): `main.py` with no `PYTHONPATH`, the source tree and root filesystem read-only, a private `/tmp` each, no key, no contact string, and `www.sec.gov`, `data.sec.gov` and the two sites of version 1's example unreachable. For every version it loads the page, starts a run of the version's own example through the shim, requires a finished run that read at least one source and holds at least one verified finding, then asks the second process (which answers 404 for the run) through a new copy of the shim with the same session storage, and requires the finished run (and from version 4 its review) back. It also reads one held run start line by line and requires the first line to arrive before the last.
- `make site-live-shots` writes pictures of each live page (as opened, its sample, a finished run) from headless Chromium, for a person to look at. `make site-live-up` leaves the emulation at <http://127.0.0.1:8790/versions>.
- `make APP=week2 verify` imports every module of every vendored version under its new name in a process that has no `app` package, builds each version as the website does, and tests the guard, the hold and the fallback.

Only a real deployment can show: that the function builds and starts inside Vercel's limits with these dependencies; how long the first request to a version takes while it is imported; that Vercel's Python runtime sends the held answer as a stream (if it buffered it, the page would still get its run, at the end, as long as the run fits in 300 seconds); that EDGAR answers requests from Vercel's addresses under the contact string; that the forwarding headers are as described; and a run with the key, which nothing here has made: every run in these checks was keyless, and no request was sent to the Anthropic API.

## Adding version 15, or moving a version to a point release

```text
make site-version N=15                      # capstone-v15
make site-version N=13 REF=capstone-v13.1
```

This points the version at the ref in `tools/live/versions.map`, vendors every version in the map again from git (the others come out unchanged), imports them all, and runs the new version under the emulation. Then: add the version's row to `docs/versions.md` and run `make site-index`; record its fallback snapshot with `make versions-up VERSIONS=15` and `make site-export VERSIONS=15`; run `make APP=week2 verify`; commit, open the pull request, and after the merge run `make site-check URL=https://ee292m-visualization.vercel.app`.

A new version whose page makes a write no earlier version made (a new POST, PUT or DELETE address) is refused that write until it is added to `WRITES` in `src/live/guard.py`; a new address that starts a run must be added to `RUN_STARTS` as well: an address in `WRITES` alone would start runs that are neither capped nor held. `make site-live-test` only exercises `POST /api/runs`.
