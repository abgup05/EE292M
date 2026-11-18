# Version 13 example payloads: the standing watch

What each watch route answers, for whoever builds the page. Written by
`make watch-examples` (`tests/watch_examples.py`) from an offline scenario: a
fake EDGAR index of made-up NVIDIA filings, a fake clock that starts at
18 Nov 2026 09:00 UTC, and the scripted engine of the service tests (no model,
no cassette: every verdict here was scripted). Ids, and the times a run stamps
itself, change each time the files are written. Design and behaviour:
[`docs/watch.md`](../../watch.md).

The page computes nothing from these. Every count, label, headline and line of
text is in the payload; `GET /api/watch/meta` holds the labels and numbers the
page needs besides.

All times are UTC, ISO 8601 with a `Z`. Absent values are `null`, absent text
is `""`, absent lists are `[]`.

## The files, in the order the scenario writes them

| File | Route | When |
| --- | --- | --- |
| `health-not-running.json` | `GET /api/watch/health` | before any watcher cycle |
| `watch-put.json` | `PUT /api/theses/{id}/watch` `{"policy": "auto"}` | 201: the thesis was not watched |
| `error-422.json` | `PUT /api/theses/{id}/watch` `{"policy": "often"}` | a refused request (every watch route refuses this way) |
| `inbox.json` | `GET /api/inbox` | one item of each of the six kinds |
| `inbox-page-2.json` | `GET /api/inbox?limit=4&offset=4` | the last page |
| `watches.json` | `GET /api/watch` | |
| `health.json` | `GET /api/watch/health` | a watcher is alive |
| `meta.json` | `GET /api/watch/meta` | |
| `waiting-run-started.json` | `POST /api/inbox/{id}/run` | 202: the waiting item's run started |
| `inbox-item-after-run.json` | `GET /api/inbox/{id}` | the same item once that run ended |
| `mark-read.json` | `POST /api/inbox/read` `{"ids": [one id, "ib-gone"]}` | |
| `unwatch.json` | `DELETE /api/theses/{id}/watch` | |

Other answers: 404 `{"detail": "Thesis not found"}` or `{"detail": "Inbox item
not found"}`; 409 `{"error": "..."}` (a thesis not watched, a run not waiting, a
ticker gone from SEC's list); 503 `{"error": ...}` when EDGAR cannot be read to
start a watch (nothing is saved).

## A watch (`watches.json`, `watch-put.json`)

`watches.json` is `{"watches": [...], "interval_seconds"}`: every watch, oldest
first, and how often the watcher polls. `watch-put.json` is `{"created", "watch"}`:
`created` is true when the thesis was not watched (201) and false when only its
policy changed (200). Each watch:

- `thesis_id`, `thesis_name`, `ticker`, `company_name`: the thesis and its company.
- `policy`: `auto` (a filing that bears on a claim runs the thesis at once, up to the
  daily cap) or `ask` (the run waits in the inbox for the owner). `policy_label` is
  its words.
- `watching_since`: when it was first put on watch.
- `last_check_at`, `next_check_at`: when the watcher last read the company's filing
  index and when it next will; both `null` before its first cycle, and then
  `next_check_note` says so in words (otherwise `""`).
- `last_error`: why the last read of the index failed; `""` when it succeeded.
- `last_job_error`: the error of the newest job of this thesis that gave up; `""`.
- `jobs`: how many of this thesis's jobs are `queued`, `running`, `done`, `failed`.
- `unread`: its inbox items not yet read. `waiting_runs`: its items holding a run
  waiting for the owner.

## An inbox page (`inbox.json`, `inbox-page-2.json`)

`items` (unread first, then newest first), `total` and `unread` (of the whole inbox,
or of one thesis with `?thesis_id=`), `limit`, `offset`, and `next_offset` (the
offset of the next page; `null` on the last).

## An inbox item

One per watched thesis and new filing.

- `id` (`ib-...`), `job_id` (`wj-...`, the job that triaged it), `thesis_id`,
  `thesis_name`, `ticker`.
- `kind`, one of six; `meta.kind_labels` has their words:
  - `not_relevant`: the filing bears on no claim; no run. `collapsed` is true for this
    kind only: draw it folded.
  - `waiting`: it bears, and a run waits for the owner (`run.waiting_reason` says why:
    the policy is `ask`, or the daily cap was reached).
  - `running`: a run it caused is under way.
  - `moved`: the run ended and something moved (see `moved`).
  - `nothing_moved`: the run ended and nothing moved.
  - `failed`: the run, or the job, failed; `error` says why. A failed run is tried
    again (as a new run) after a wait, up to `meta.limits.max_attempts` attempts; in
    between, the item stays `failed` with that run's reason, and turns `running`
    again when the next attempt starts. After the last, `error` begins "Gave up
    after".
- `created_at`, `updated_at`; `read_at` (`null` while unread).
- `collapsed`: draw the item folded.
- `headline`: the item in one line, ready to show.
- `error`: why it failed; `""` unless `kind` is `failed`.

### `filing`: the filing that arrived

- `accession`, `form` (`10-K`, `10-Q`, `8-K` or `8-K/A`), `filed_date`,
  `report_date` (the period's end for a 10-K or 10-Q, the event's date for an 8-K),
  `url` (the document on sec.gov).
- `items`: for an 8-K, each item's `number`, SEC's `title` and its `category`
  (leadership, accounting, deal, restructuring, incident, financing, control,
  listing, results, governance, disclosure, exhibits, other); `[]` for a 10-K or 10-Q.
- `label`: the filing in words ("8-K of 10 Mar 2026, Items 5.02 and 9.01").

### `triage`: does it bear on the thesis, and why

Decided by rules, without a model (`app/core/triage.py`).

- `bears`: it bears on at least one claim.
- `rules`: the rules that decided (`meta.rule_labels` has their words):
  `periodic_report` (a 10-K or 10-Q bears on every claim), `results_announced`
  (Item 2.02 bears on every claim; the figures come with the quarterly report),
  `event_category` (an 8-K item's category is one of a claim's), `no_items` (an 8-K
  listing no items bears on every claim, to be safe), `routine` (only exhibits, a
  vote and the like), `no_match` (a substantive item no claim is about), `extension`
  (reserved for version 14's compiled claims; unused).
- `summary`: the decision in one sentence.
- `notes`: anything else worth saying about the filing; usually `[]`.
- `claims`: one entry per claim of the thesis:
  - `claim_id` (`c1`, `c2`, ... in the thesis's order), `claim` (its text).
  - `categories`: the 8-K categories the claim is about, from its words.
  - `bears`, and `reasons`: why it bears, one sentence each.
  - `paragraphs`: for a 10-K or 10-Q, at most three changed paragraphs sharing words
    with the claim, each with `kind` (added or changed), `item` (the report's Item),
    `text`, `link` (to the paragraph in the filing) and `matched_terms` (the shared
    words).

### `run`: the run the filing caused (`null` when none is needed)

- `state`: `waiting`, `running` or `finished`.
- `waiting_reason`: why it waited for the owner; `""` if it never waited.
- `run_id`: the run, once started (`GET /api/runs/{run_id}` has it); `null` while waiting.
- `status`: the finished run's status (`complete`, `partial`, `failed`); `null` before.
- `started_by`: `watch` (an automatic run) or `owner` (started from the inbox).

### `moved`: what the run changed (`null` until a run ends)

Compared with the thesis's previous finished run.

- `earlier_run_id` (`null` when this is the thesis's first run), `later_run_id`.
- `moved`: anything below changed. `line`: it in one sentence.
- `verdicts`: each verdict that changed: `claim`, `before`, `after`.
- `new_cautions`: cautions a claim has now and did not have: `claim`, `text`.
- `new_notes`: 8-K notes on a claim that had none: `claim`, `text`.
- `new_events`: 8-Ks new on the run's timeline: `accession`, `form`, `filed_date`,
  `items` (numbers), `url`, `label`.
- `sources_added`: the filings the later run read that the earlier did not.
- `claims`: every claim, compared: `claim`, `before`, `after`, `moved`, `change`
  (`moved`, `unchanged`, ...), `reviewed_before` and `reviewed_after` (the second
  reading's verdict when there was one, else `null`), `excerpts_added`,
  `excerpts_dropped`.
- `comparison_note`: the comparison in one sentence, as the compare page says it.

## Starting a waiting run (`waiting-run-started.json`)

`id` (the run), `status` (`running`), `item_id` (the inbox item). The item turns
`running`, and `moved` or `nothing_moved` (or `failed`) when the run ends
(`inbox-item-after-run.json`). Asking twice is 409.

## Marking read (`mark-read.json`)

Sent `{"ids": [...], "read": true}` (`false` marks unread again; at most 100 ids).
Answers `marked` (the ids changed), `unknown` (ids no item has; not an error) and
`unread` (what is left unread in the whole inbox).

## Taking a thesis off watch (`unwatch.json`)

`thesis_id`, `watching` (false). Its inbox and jobs stay.

## The watcher's health (`health.json`, `health-not-running.json`)

- `alive`: a watcher finished a cycle at most `stale_after_seconds` ago (two
  intervals and a minute). `note` says it in words.
- `worker`: the watcher's name; `started_at`: when it started; `last_cycle_at`: when
  its last cycle finished; all `null` before any cycle.
- `interval_seconds`: its polling interval.
- `last_cycle`: what that cycle did: `started_at`, `finished_at`, `companies` (indexes
  read), `index_errors`, `jobs_queued`, `jobs_done`, `jobs_retried`, `jobs_failed`,
  `leases_expired` (jobs whose worker stopped mid-job, put back in the queue), and
  `errors` (their messages). `{}` before any cycle.
- `jobs`: all jobs by state (`queued`, `running`, `done`, `failed`);
  `queue_depth`: queued plus running.
- `waiting_runs`: inbox items holding a run waiting; `watches`: theses watched.

## The labels and numbers (`meta.json`)

- `kind_labels`, `policy_labels`, `job_state_labels`, `rule_labels`: words for each
  value of `kind`, `policy`, a job's state and a triage rule.
- `collapsed_kinds`: the kinds drawn folded. `default_policy`: `ask`.
- `forms`: the forms watched.
- `limits`: `min_interval_seconds` (300; a shorter setting is raised to it),
  `default_interval_seconds` (900), `default_auto_runs_per_day` (5),
  `max_attempts` (4), `backoff_seconds` (the waits before each retry),
  `lease_seconds` (how long a job may run before it is taken back),
  `paragraphs_per_claim` (3), `default_page_size` (20), `max_page_size` (100).

## A refusal (`error-422.json`)

`error` (one sentence) and `details`: each problem's `field` and `message`. As in
the app's other routes, a field of the body is named bare (`policy`, `ids`), one of
the query or the path with its place (`query.limit`, `path.thesis_id`).
