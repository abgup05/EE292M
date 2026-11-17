# Review 3: speed, the system, and what cannot be rebuilt

- **Session:** Week 7A, "Design Your System for Your Problem" (review of the capstone)
- **Reviewed:** commit `1ecfcf1`: tag `capstone-v3` plus the system drawing added to the README, from a clean checkout
- **Reviewer:** Claude Sonnet 5.5, in a fresh context with read-only tools. It did not write the code and was not shown the work logs, the homework files, the earlier reviews or any conversation. There was no colleague review for this session.
- **Run on:** 17 November 2026
- **Checklist given to the reviewer:** the session's four items: the speed, the system, what cannot be rebuilt, one suggestion (a boundary to add, merge or remove).

The reviewer's text follows unedited. My decision on each finding is in `Homework/Week 7/W7L1.md`.

---

## Findings

**F1. [speed]** The profile covers only the offline replay of three recorded NVIDIA filings, 0.41 s end to end. The one live measurement is 3.2 s for three filings, fetched and parsed. A model-backed run adds several seconds per claim. The header cut saves about 19 ms of parse time, which is under 1% of a live run. speed.md ranks the parse first, but never says that most of a real run's time is EDGAR and model latency, which were not profiled. Evidence: speed.md:14, 54, 66-69; README.md:104. Suggested change: say that the 8% applies to the offline path only, and rank EDGAR and the model as the unmeasured bulk.

**F2. [speed]** The "8%" does not follow from the stage table. Parse fell 286.5 to 267.7 ms (-18.8 ms). The whole run fell 435.9 to 384.6 ms in the profile files, so half of the saving is not in the parse. "Other" alone dropped 106.5 to 74.0 ms, and the header cut cannot touch that stage. The same-profile gain is 12%, the bench gain is 7.6%, and the parse-only gain is 4.3%. The three numbers are not reconciled. Evidence: profile-before.txt:5-11; profile-after.txt:5-11; speed.md:36-40; README.md:104. Suggested change: claim "parse -19 ms (-6.5%)" and call the rest noise, or repeat the bench alternately before and after.

**F3. [speed]** The 24% "Other" bucket (assess, gate, 24 SQLite saves) is never broken down. The top-25 listing cuts off before it. The "24 SQLite saves" figure appears in no profile file. Each `save_run` opens a connection, runs the WAL pragma and re-serialises the whole record. This is the stage that moved most between runs, and it is not explained. Evidence: speed.md:15; store.py:51-76; speed_run.py:96-98. Suggested change: time `save_run` and `gate_claim` as their own stages.

**F4. [speed]** "No answer changed" is shown only for the three recorded NVIDIA filings (tripwire hash `fd8760cb…` in both profile files). Item-coverage differences on other companies' filings were not re-checked after the change, although `make probe` exists for that. The regex cut is `<ix:header\b.*?</ix:header>`. Evidence: filing.py:101, 279-287; speed.md:41. Suggested change: rerun `make probe` on the eight companies and compare Item coverage before and after, or narrow the claim to "on the NVIDIA fixtures".

**F5. [speed]** The concurrency gain is a sleep-based stand-in, and the doc says so. Its "no answer changed" check uses the deterministic engine, so it proves ordering and ids, not model behaviour. The ratio 0.44 is mostly the sleeps overlapping. Thread-safety of the real transport is only asserted in comments (lock at transport.py:88, cassette.py:113), and rate-limit behaviour is unmeasured. This is honestly flagged at speed.md:64-67, but README.md:104 presents it next to measured results. Suggested change: label it "mechanism tested, gain unmeasured".

**F6. [system]** The drawing shows only SEC and Anthropic as outside parties. It omits arbitrary public pages (`extra_urls`, up to five, fetched by `sources/web.py` and `urls.py`). It also omits PyPI, ghcr.io and Docker Hub (the `uv` image, `node:24-slim`, `zenika/alpine-chrome`), which the image build and the tool containers pull from. README line 72 says "nothing is ever written to EDGAR" but never mentions the extra-page path. Evidence: api.py:97-106, 212; Dockerfile:1-12; compose.yaml:31, 37. Suggested change: add "public web pages (user-supplied)" and "package and image registries (build time)".

**F7. [system]** `TOOLS -->|"http://app:8000"| APP` is true only for `shots`. `jscheck` mounts the repo read-only and never calls the app. `lock` writes `docker/uv.lock` into the clone and contacts PyPI. `shots` writes `docs/screenshots` into the clone. Many `make` targets (`run`, `test`, `probe`, `replay`, `fixtures`, `bench`) start separate `app`-image containers with `--no-deps`. These bypass the served container and write the same SQLite file. `probe`, `demo` and `fixtures` also reach EDGAR from those containers. Evidence: compose.yaml:19-44; Makefile:47, 68-101. Suggested change: draw a "one-off app-image containers (make run, probe, fixtures)" box with arrows to DB, EDGAR and the clone.

**F8. [what cannot be rebuilt]** The table omits `results/`. It is gitignored (`.gitignore` line 3), and holds CLI run exports, `make demo` output, probe reports and screenshots' DOM dumps. These are single-copy files that a person might rely on. The only files kept from it are those copied by hand into `demo/` and `docs/`. Evidence: .gitignore; cli.py:43; Makefile:64, 68. Suggested change: add a row for it, or say it is disposable.

**F9. [what cannot be rebuilt]** "Filings and XBRL facts: yes, a filing never changes" is too strong. SEC `companyfacts` is a live aggregate: restatements and new filings change it, and "latest 10-K plus later 10-Qs" changes as new filings arrive. A later run therefore cannot reproduce the reported figures or even the filing set. The stored text is the output of this repo's parser, so a re-run after a parser change gives different text. The README's reason for losing run records, "model answers cannot be reproduced", is also incomplete. An extractive run is deterministic only while EDGAR and the parser stay fixed. Evidence: edgar.py:130-138; filing.py:513-536; store.py:22-34. Suggested change: say that run records are unrecoverable because of the moving inputs, not only the model.

**F10. [what cannot be rebuilt]** The fixtures are recorded EDGAR responses, and the golden hash depends on them. The README rates them "Yes" rebuildable, but a re-record would give a different `companyfacts` and a moved tripwire. Evidence: README.md:79; Makefile:85-104. Suggested change: mark the fixtures "rebuildable only as a new baseline".

## The drawing, corrected

- Add public web pages, PyPI and the image registries as external parties (F6).
- Split TOOLS: `shots` calls the app; `jscheck` is read-only on the clone; `lock` writes `uv.lock` and reaches PyPI (F7).
- Add the one-off app containers for `run`, `probe`, `fixtures` and `test`, with their arrows to the SQLite file and EDGAR.
- Add an arrow from `app` to the browser for the page's JavaScript. At present only browser to app is drawn.
- Label `APP <-> DB` "bind mount `/work/data/runs`". Add `results/`, gitignored, inside the clone (F8).
- Add the built image, as a rebuildable artefact made from `uv.lock`.

## If the disk failed today

- Lost: every run record and its stored filing text (`runs.sqlite`, with its WAL file), `results/*`, `.env` (the keys can be reissued), and any unpushed commits or untracked files.
- Not lost, provided pushed: code, fixtures, the cassette, golden records and `demo/`, held in GitHub. The cassette cannot be re-recorded, because the API account has no credit.
- No reviewer decisions exist yet (milestone 4), so none are lost.

## One suggestion

Split SQLite into two files. `cache.sqlite` holds filing text keyed by `content_hash` (the `Document` already has this), is disposable, and is stored once per filing instead of once per run (`save_source_text` currently copies it per run). `record.sqlite` holds runs and the future decisions, and is the only file that gets backed up, with a documented restore (the plan already lists "backup with a tested restore" for milestone 4). The cost is a schema change, a cache lookup in `ingest.py`, and a parser-version key in the cache so stale text is never quoted.

## What I could not judge from the repository alone

- Whether the private GitHub copy exists and is current, and whether any backup of `data/runs` exists outside the repository.
- Whether the profile numbers are stable on other hardware. Each profile file comes from a single run.
- Whether the real Anthropic path works under three parallel calls.
