# Evidence Desk

A web tool that turns one research question into a source-backed decision
brief. Every factual finding links to an exact excerpt from a page the backend
retrieved, verified as a substring of the stored text before it reaches the
browser or the Markdown export. When evidence is thin the brief says
**PARTIAL**; when nothing usable was retrieved it says **FAILED** and gives no
synthetic answer.

This is the first working slice described in [`../PROMPT.md`](../PROMPT.md).
The `starting_point` fork named there does not exist in this repository, so
the app was built on the stack and conventions of the Week 2 app instead
(Python 3.14 / FastAPI, Docker Compose on `127.0.0.1`, static frontend,
Makefile-only execution). See [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Run it

You need Docker running and Make. From this directory (or from the
repository root, where `make` targets the capstone by default):

```sh
cp .env.example .env   # optional: add ANTHROPIC_API_KEY and/or BRAVE_SEARCH_API_KEY
make build
make up                # http://127.0.0.1:8766
make down
```

Without credentials the app still works: planning uses a template and
synthesis is a deterministic extractive mode that quotes exact sentences with
`low` confidence. With `ANTHROPIC_API_KEY`, Claude plans the subquestions and
drafts findings from the stored text; the same verification gate applies.
With `BRAVE_SEARCH_API_KEY`, up to 30 search results are merged with the seed
URLs; otherwise the run records that only seed URLs were considered.

## Demo path

1. `make up`, open http://127.0.0.1:8766, click **Load seed example**.
2. Click **Run research**. The banner shows RUNNING, then PARTIAL.
3. Open a finding: each evidence block shows its stance, the section heading
   it sits under, the exact excerpt, and a link to the source page.
4. The sources table shows publisher, publication date (or "not available")
   and the UTC retrieval time separately. Failed pages show their error.
5. **Download Markdown brief** exports the same verified record.

`make demo` runs the same seed case against the live container without a
browser and writes `results/demo-<UTC>.md` with a measured summary and the
exported brief. The record behind the numbers below is committed as
[`demo/demo-2026-10-22.md`](demo/demo-2026-10-22.md).

## Measured results (demo, 2026-10-22)

Run with `ANTHROPIC_API_KEY` set (model `claude-opus-5-5`), no search key:

- Status **PARTIAL**, wall time 38 s, 6 subquestions planned by Claude.
- NIST AI RMF 1.0 page: retrieved and extracted; title, publisher `NIST` and
  publication date `2023-01-26` came from the page's metadata, retrieval time
  recorded separately in UTC.
- GAO `gao-24-106946`: **HTTP 403** from the server to this fetcher (bot
  protection). Recorded as a failed source; the run continued.
- 4 findings, 4 evidence excerpts, all verified as exact substrings of the
  stored NIST text; every finding is flagged single-source. 0 withheld.
- 2 of 6 subquestions answered (governance obligations; pilot scoping); the
  other 4 are listed as unanswered.
- Coverage limits recorded: no search provider; fewer than six sources;
  4 subquestions unanswered. Hence PARTIAL, not complete.

An earlier demo run exposed a real extraction bug: the NIST abstract is loose
text in a `<div>` outside the page's `<article>`, and the first extractor
dropped it, leaving only the citation block. Claude then produced 3 findings
whose excerpts were not in the stored text, and the verification gate
withheld all 3 (0 verified). The extractor was fixed with a failing test
first; the next run verified 4 of 4.

## Verification

```sh
make verify   # build, ruff lint/format, node --check, 110 offline tests, live smoke
make test     # offline unit tests only
make fixtures # record the real seed pages under tests/fixtures (REFRESH=1 to overwrite)
```

Tests cover request validation, URL safety (private and local addresses,
embedded credentials, redirects to private hosts, non-HTML, size cap,
timeouts, redirect loops), canonicalization and deduplication (mirrors and
identical content count once), exact-excerpt verification (a corrupted excerpt
removes its finding; a bad evidence ID marks the finding unsupported),
partial/failed status rules, the time budget, the Claude backend with a stub
client (page text passed as data, JSON schema requested, refusal and
truncation raise), the extractive backend, Markdown export, the API, and the
recorded NIST fixture. The smoke test exercises the live container without
internet access.

## Known limitations

- GAO.gov answers this fetcher with HTTP 403. The app reports that honestly;
  it does not emulate a browser to get around it.
- Only public HTML. PDFs (including the full AI RMF PDF), authenticated pages
  and private drives are out of scope for this slice.
- With no search provider, coverage is limited to the seed URLs, so a
  two-seed run is always partial by design.
- The Claude backend was exercised in the demo runs above; the Brave search
  backend was tested only against a mock transport, not the live API.
- Runs execute in a worker thread inside the API process; there is no queue
  or resume after a restart.
