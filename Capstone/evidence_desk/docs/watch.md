# The standing watch (version 13)

A saved thesis can be put on watch. A second process, the watcher, then reads the
company's filing index on EDGAR every fifteen minutes. When a 10-K, 10-Q or 8-K
appears that it has not seen, it decides by rule, without a model, whether the
filing bears on any of the thesis's claims. If it does, the watcher either runs the
thesis again and says what moved, or leaves the run waiting for the owner. Either
way the inbox says what arrived and why it matters or does not.

Example payloads of every route, with a README naming every field:
[`docs/examples/v13/`](examples/v13/README.md).

## Using it

| | |
| --- | --- |
| Put a thesis on watch | `PUT /api/theses/{id}/watch` `{"policy": "ask"}` or `"auto"`. 201 when new, 200 when only the policy changed |
| Take it off | `DELETE /api/theses/{id}/watch`. Its inbox and jobs stay |
| The watches | `GET /api/watch`: policy, last and next check, last error, jobs, unread |
| The inbox | `GET /api/inbox?limit=20&offset=0&thesis_id=` (unread first, then newest first); `GET /api/inbox/{id}`; `POST /api/inbox/read` `{"ids": [...], "read": true}` |
| Start a waiting run | `POST /api/inbox/{id}/run` (202; 409 if nothing waits) |
| Is the watcher alive | `GET /api/watch/health`; `make watch-status` prints the same and each watch |
| One cycle by hand | `make watch-once` |
| The labels the page uses | `GET /api/watch/meta` |

`make up` starts the watcher as the `watch` service of `docker/compose.yaml`
(`python -m app.watch`), beside the app, on the same data directory and with no
port. It stops on SIGTERM between cycles.

Settings, from the environment (`.env.example`):

- `EVIDENCE_DESK_WATCH_INTERVAL_SECONDS`, default 900 (15 minutes), never less than
  300: a shorter value is raised to 300 with a warning, and anything that is not a
  whole number stops the watcher with a configuration error.
- `EVIDENCE_DESK_WATCH_AUTO_RUNS_PER_DAY`, default 5: automatic runs across all
  watches per UTC day. After that, runs wait as if the policy were `ask`. 0 makes
  every run wait.

**Why 15 minutes, and a floor of 5.** One cycle costs one request per watched
company (the submissions index), however many theses watch it. EDGAR allows 10
requests a second, so the request rate is not the limit even at the floor. The
floor is set by courtesy and by what the filings need: an 8-K is due four business
days after its event, and a 10-Q forty days after the quarter, so nothing is gained
by asking more than a few times an hour. The floor also stops a mistyped setting
(`30` meant as minutes) from polling SEC every 30 seconds for as long as the
container runs. 15 minutes means a filing reaches the inbox within about a quarter
of an hour of SEC listing it.

## What happens to a filing

1. **Seen.** Each cycle lists the company's filings of the four watched forms
   (`10-K`, `10-Q`, `8-K`, `8-K/A`) from EDGAR's index, through the same client and
   rate limit as a run. For each watching thesis, a filing not seen before is marked
   seen and a job is queued for it, both in one transaction; a job is unique per
   (thesis, accession), so it is never queued twice. On the first watch, every
   filing already listed is marked seen with no job: the watch reports what is new
   from then on. Watching again only changes the policy.
2. **Triaged** (`app/core/triage.py`, pure, no model):
   - a **10-K or 10-Q** bears on every claim. It is compared with the one of the same
     form before it (`core/filing_diff`), and under each claim the changed paragraphs
     that share words with it are named (`core/claim_changes`, at most three);
   - an **8-K with Item 2.02** bears on every claim: "new results announced; the
     figures arrive with the quarterly report";
   - an **8-K item whose category is one of the claim's** (`core/events`: a 5.02 and a
     claim about the chief executive, a 1.01 and a claim about a deal) bears on that
     claim;
   - an **8-K of only routine items** (exhibits, a shareholder vote, a Regulation FD
     release, other events) bears on nothing, and says so;
   - an 8-K of a substantive item that no claim is about bears on nothing;
   - an 8-K whose index lists no items bears on every claim, to be safe.

   **The extension point for version 14** is `EXTRA_TRIAGE_RULES` in
   `app/watch/service.py`, passed to `triage(..., extra_rules=...)` and marked
   `# EXTENSION POINT (version 14)` in `core/triage.py`. A rule there is given the
   claims and the filing and returns (claim id, reason) pairs; a claim it names
   bears, under the rule `extension`. It is meant for "a compiled claim's computed
   outcome flipped" and is empty today.
3. **Nothing bears:** the inbox gets a collapsed "seen, not relevant" item with the
   reason. No run.
4. **It bears:** with policy `auto` and the day's cap not reached, the thesis is run
   (`services/theses`, the same run as the run button), compared with its previous
   finished run (`core/compare`), and the item says what moved: verdicts that
   changed, new cautions, new 8-K notes, new 8-Ks on the timeline, or "Nothing
   moved." With policy `ask`, or the cap reached, the item holds a waiting run with
   the reason; the owner starts it from the inbox, and the item says what moved when
   it ends.

The inbox has six kinds: `not_relevant`, `waiting`, `running`, `moved`,
`nothing_moved`, `failed`. Every headline, label and count is written by the
backend; the page draws them.

## Jobs

A job is a row in the record (`watch_jobs`) in one of four states: queued, running,
done, failed. Waiting for the owner is not a job state; the job is done and the
inbox item holds the waiting run.

- **Claimed in one statement.** A worker takes the oldest ready job with
  `UPDATE ... WHERE id = (SELECT ... LIMIT 1) AND state = 'queued' RETURNING`, so two
  workers can never take the same job (`tests/test_watch_store.py` races two
  processes on one file for this).
- **Retried with backoff.** A job that raises (EDGAR unreachable, a run that
  failed) is queued again after 60 s, 300 s and 1,800 s; after the fourth attempt
  it stays failed with its reason, and the inbox item says "Gave up after 4
  attempts: ...". A retry happens at the first cycle after its wait.
- **Leased.** A claimed job holds a lease of 900 s (a run is cut off at 300 s). A job
  still running when its lease runs out (the watcher was killed) is put back in the
  queue by the next cycle, or failed if it has used its attempts.
- **Daily cap** in one conditional statement: an automatic run takes a slot only
  while fewer than the cap were taken that UTC day.

Why SQLite and the standard library, not Celery, Redis or APScheduler: there is one
watcher, a queue of a few jobs a day, and the record is already SQLite in WAL mode
with one writer per process. A queue table with an atomic claim and a lease gives
the same guarantees with no new service to install, back up or secure.

## Where the state lives

- **The record** (`data/record/record.sqlite`) gains four tables, created when the
  app or the watcher first opens it: `watches` (one per watched thesis: policy,
  company, since when), `watch_seen` (the filings each watch has seen), `watch_jobs`,
  and `inbox`. They are backed up with the rest and compared by `make
  restore-check`. A record from before version 13 has none of them and still loads
  (`tests/test_watch_store.py`).
- **The cache** (`data/cache/filings.sqlite`) gains `watcher_beats` (the heartbeat:
  each cycle's counts and time) and `watch_checks` (each company's last and next
  check and last error). These change every cycle, can be lost without harm, and
  kept out of the record so that a backup still matches the live record a minute
  later.

## Measured

- **A run and the watcher write one record at once and both succeed**
  (`tests/test_watch_contention.py`, in `make verify`): the example run in one
  process while another does watcher cycles on the same files, each writing a seen
  filing, a job, an inbox item and a heartbeat; both finish and the file passes
  `PRAGMA integrity_check`. `make watch-contention` times it, 6 pairs alternated,
  offline, on this laptop on 18 November: median 299 ms alone (268 to 329), 318 ms
  with a watcher doing a median of 199 cycles meanwhile (282 to 483). The ranges
  overlap; the slowest contended run was 483 ms
  ([`docs/evidence/watch-contention.txt`](evidence/watch-contention.txt)). It says
  nothing about EDGAR's latency, which a live run is dominated by.
- **Triage on a year of NVIDIA's real filings** (`make watch-replay`, live EDGAR, no
  model, policy `ask` so no run). The 19 filings of 19 Nov 2025 to 17 Nov 2026 (15
  8-Ks, 3 10-Qs and a 10-K) were fed one at a time to a real watcher
  for a five-claim thesis (the chief executive, data centre growth, little debt,
  acquisitions, margins). The labels (`eval/watch-replay-nvda.json`) were written
  from each filing's items and opening sentences and committed before the replay
  ran; they were written by the agent that built the watch, not by a person.
  Triage flagged 16 of 19; it agreed with the label on 12 of 19; of the 13 filings
  labelled as bearing, it flagged 11
  ([`docs/evidence/watch-replay-nvda.md`](evidence/watch-replay-nvda.md)). The
  seven disagreements:
  - **Five false alarms, all Item 5.02.** A director resigning, a director appointed,
    the chief accounting officer retiring, the head of field operations retiring,
    and an officers' bonus plan were each flagged for the claim about the chief
    executive. The category rule cannot tell one officer from another.
  - **Two misses, both Item 8.01.** A $25 billion note issue (against "little debt")
    and the agreement to buy Hugging Face for $11.9 billion (an acquisition) were
    filed under "Other events", which the 8-K rules treat as routine. Both are
    filings a holder of this thesis would want to see.
  - At the claim level, a results 8-K, 10-Q or 10-K is flagged for every claim, by
    design; the labels name two or three.

  The rules were not changed after the replay: a fix fitted to these seven would be
  measured on the filings it was fitted to. Both failures are in `core/events.py`'s
  categories, shared with the run; changing them is a change to the 8-K rules
  (`ARCHITECTURE.md`, "Where a change goes") and should be measured with `make
  event-categories` and a replay of another company.

## What it does not do, and what can go wrong

- **It does not notify.** The inbox is read when the page is opened.
- **A failed attempt is a run in the thesis's history.** A job that fails because
  its run failed is retried as a new run, so one filing with EDGAR down can leave up
  to four failed runs on the thesis. Each is a true record of an attempt; none is
  deleted.
- **A watcher killed mid-run leaves that run `running` in the record** (as the app
  does if it is killed mid-run: nothing marks such runs at start-up), and the retry
  starts another.
- **Only what EDGAR's index lists.** The submissions index lists about the latest
  thousand filings of a company; a filer with more than that between two cycles
  would lose the oldest. Amended 10-Ks and 10-Qs (`10-K/A`, `10-Q/A`) are not
  watched; amended 8-Ks are.
- **Policy `auto` spends model calls.** With the Claude engine, each automatic run is
  a paid run of every claim. The daily cap bounds it; the default, 5, is a guess,
  not a measurement.
- **The watcher's health is its heartbeat.** It is alive if its last cycle finished
  within two intervals and a minute. A watcher stuck inside a cycle (a run that does
  not return) shows as not alive after that, which is the intended reading.
- **Untested here:** the watcher as a compose service under `make up` (this branch
  tested it through `make watch-once` and the tests only), a watcher running for
  days, two watcher containers at once (the claim is safe for it; nothing else was
  tried), and the page, which version 13's page work builds on these payloads.
