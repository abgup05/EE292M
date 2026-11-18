# Speed

*Two parts. The first was measured at version 11, on 17 November 2026, in answer to the sixth review ([`reviews/review-6-speed-system.md`](reviews/review-6-speed-system.md)): it found that the numbers below it were six versions old, that the time a live run spends on EDGAR had been inferred and never measured, and that "one change" was two. The second part is the version 4 note, kept as it was measured then.*

## Version 12: what reading the 8-Ks costs a live run

`make time-live RUNS=5`, live, no key, the example thesis, five runs per condition, on 18 November 2026: once at version 0.11.1 (07:49 UTC, [`speed/live-timing-v12-before.txt`](speed/live-timing-v12-before.txt)) and once at 0.12.0 (08:24 UTC, [`speed/live-timing-v12.txt`](speed/live-timing-v12.txt)). The two were run one after the other, not alternated: the old version would have had to run from a second worktree.

| Condition | 0.11.1: median (range), EDGAR requests | 0.12.0: median (range), EDGAR requests |
| --- | --- | --- |
| Cold filing cache | 1360 ms (1007 to 1667), 5 | 2108 ms (2019 to 2496), 13 |
| Warm filing cache | 421 ms (380 to 504), 2 | 384 ms (303 to 463), 2 |
| Cold, tagged figures | 1236 ms (1004 to 1440), 5 | 2084 ms (2015 to 2489), 13 |
| Warm, tagged figures | 460 ms (333 to 1289), 2 | 313 ms (305 to 655), 2 |

The request counts are the result: a cold run fetches the eight 8-Ks it reads (NVIDIA had twelve listed that day, eight chosen), and listing them costs nothing because the submissions index fetched for the periodic reports is reused. A warm run reads them from the filing cache. The warm medians moved inside their own spread, and without alternation that difference means nothing. Reading and splitting the 8-Ks is not a stage of its own in the timing; their requests are in "EDGAR requests".

## Version 11.1: the two measurements the fourth referee faulted, taken again

The fourth referee read two faults out of the committed outputs ([`referee-4-triage.md`](referee-4-triage.md), findings 4 and 5). Both were real, and each changed a number. The sections for version 11 below are kept as they were written. **Where they disagree with this one, this one is right.**

**The live run** (`make time-live RUNS=5`, [`speed/live-timing-v11.1.txt`](speed/live-timing-v11.1.txt)). The script built an EDGAR client for every run, so every timed run fetched the company list. The running app does not: its client lives as long as the app, keeps that list for a day, and resolves the ticker before a run starts. One client now serves all the runs, with the list loaded before the first. Decoding EDGAR's JSON answers and reading a filing back from the cache are stages of their own, and the time no stage covers is taken run by run.

| Five runs each | Whole run: median (range) | EDGAR requests | Parsing | Decoding EDGAR's answers | Reading the filings back from the cache | Covered by no stage: median (range) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Empty filing cache | 1,160 ms (1,046 to 1,551) | 661 ms, 5 requests | 367 ms | 19 ms | none | 45 ms (42 to 48) |
| Warm filing cache | 326 ms (312 to 527) | 188 ms, 2 requests | none | 31 ms | 1.0 ms | 44 ms (44 to 47) |
| Empty cache, tagged figures asked for | 1,243 ms (1,066 to 1,272) | 721 ms, 5 requests | 358 ms | 19 ms | none | 44 ms (42 to 47) |
| Warm cache, tagged figures asked for | 351 ms (321 to 983) | 208 ms, 2 requests | none | 30 ms | 1.5 ms | 47 ms (45 to 50) |

- A run makes **5 requests with an empty cache and 2 with a warm one**, not 6 and 3. Waiting for EDGAR is **57 to 59%** of a run without a key, not "about two thirds".
- The note below says that what no stage covers on a warm run "is mostly rebuilding the three documents from the cached text". Nothing had timed that, and it was wrong: reading the three filings back takes 1 ms.
- Decoding the two JSON answers of a run (the filing list and the company facts) takes 19 to 31 ms.
- **About 45 ms of every run is still covered by no stage**: 42 to 50 ms in all twenty runs, cold or warm. It is a fixed cost this stopwatch does not name. What it is has not been found, and this note does not guess a second time.
- EDGAR's latency still moves more than anything measured here: the first row's range is 500 ms wide. The rows can be compared with each other because the four conditions are taken in turn.

**The header cut** (`make bench RUNS=20`, three outputs: [`speed/bench-v11.1.txt`](speed/bench-v11.1.txt), [`speed/bench-v11.1-repeat.txt`](speed/bench-v11.1-repeat.txt), and with `COLLECTOR=1` [`speed/bench-v11.1-collector-on.txt`](speed/bench-v11.1-collector-on.txt)). In the version 11 output the times of one variant fall into two groups 40 ms apart on a cycle of five pairs, and in every fifth pair the parse is slower with the cut while the whole run is faster. The cut always ran first in a pair, and nothing kept a garbage collection made due by one run from landing inside the next. Now the order within a pair alternates, and the collector is run before each timed run. It is then either switched off for the timed part, which times the run's own work, or left on as it is in the app, where a run also pays for the collections its own allocations cause.

| 20 pairs | With the cut | Without | Saved per pair: median (interquartile range; range) | Cut faster | Saved with the cut run first; second |
| --- | ---: | ---: | --- | ---: | --- |
| Collector off. Parse 3 filings | 255.4 ms | 280.5 ms | 25.4 ms (24.6 to 26.7; 21.3 to 29.7) | 20 of 20 | 25.2 ms; 26.1 ms |
| Collector off. Whole run | 386.8 ms | 412.8 ms | 24.0 ms (22.8 to 29.0; 20.8 to 34.6) | 20 of 20 | 23.7 ms; 24.9 ms |
| Collector off, the repeat: parse; whole run | 256.6; 387.5 ms | 281.9; 413.1 ms | 25.7 ms; 25.2 ms | 20; 20 of 20 | 24.8, 25.8 ms; 24.9, 25.5 ms |
| Collector on. Parse 3 filings | 258.1 ms | 285.1 ms | 27.0 ms (25.9 to 27.8; 23.2 to 32.0) | 20 of 20 | 27.3 ms; 26.7 ms |
| Collector on. Whole run | 389.5 ms | 415.8 ms | 26.1 ms (23.3 to 28.9; 19.4 to 30.1) | 20 of 20 | 28.7 ms; 23.4 ms |

The two groups are gone. On the parse, the pairs now lie within 9 ms of each other where they had been spread over 85 ms, the cut is faster in every pair where it had been in 16 of 20, and which variant runs first makes no difference with the collector off. With it on, the whole-run saving is 5 ms larger when the cut runs first; ten pairs each way do not show whether that is real.

**The cut saves 25 to 27 ms of an offline run of about 415 ms, 6% of it, and not the 34 ms reported at version 11.** The version 11 runs were also about 45 ms longer in both variants (432 and 462 ms). The only things that differ here are the collection before each timed run and the alternating order, so the extra time and the extra saving both came from those; which of the two, the outputs do not say. Against a live run with an empty cache, 25 ms is about 2% (of 1,160 ms). The sentence below, that the saving on the whole run "agrees with the saving on the parse, as it must", is withdrawn: in the version 11 pairs it did not, pair by pair. In these it does, to within 2 ms.

## Version 11: where a live run's time goes, measured inside the run

`make time-live` runs the example thesis on filings fetched from SEC EDGAR, with the deterministic engine and no key, five times under each of four conditions, the conditions taken in turn. Every stage is timed by wrapping the functions that make it up, as the offline profile does; "EDGAR requests" is every HTTP request the client made, with the waiting its rate limit imposes. Output: [`speed/live-timing-v11.txt`](speed/live-timing-v11.txt).

| Median of five runs | Whole run (range) | EDGAR requests | Parsing three filings | Everything else timed | Not covered by a stage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Empty filing cache | 1,472 ms (1,303 to 1,523) | 940 ms, 6 requests | 366 ms | 78 ms | 88 ms |
| Warm filing cache | 545 ms (492 to 598) | 380 ms, 3 requests | none | 65 ms | 100 ms |
| Empty cache, tagged figures asked for | 1,269 ms (1,188 to 1,522) | 739 ms, 6 requests | 364 ms | 105 ms | 62 ms |
| Warm cache, tagged figures asked for | 526 ms (489 to 1,027) | 359 ms, 3 requests | none | 71 ms | 96 ms |

What that says, and how far:

- **A live run without a key is mostly waiting for EDGAR**: about two thirds of it, cold or warm. Parsing is a quarter of a cold run and none of a warm one. Indexing, building the figures, retrieval, the extractive assessment, the gate and saving are together 65 to 105 ms: about 5% of a cold run and 12% of a warm one.
- **EDGAR's latency moves more than anything here.** The same six requests took a median of 603 ms, 760 ms, 1,006 ms and 940 ms in four sessions on one afternoon. So the whole-run medians of different sessions are not comparable to within a few hundred milliseconds, and the third row above being faster than the first is that noise and nothing else. Within one session the conditions are taken in turn, which is what makes their comparison fair.
- **What is not covered by a stage** on a warm run is mostly rebuilding the three documents from the cached text, which is not a stage of this stopwatch.
- **The model is still untimed.** With a key, five assessments of several seconds each would outweigh all of this. The API refused every call from this project for lack of credit until 18 November, and the live runs since were not timed ([`README.md`](../README.md#where-the-model-answers-came-from)), so the largest part of the run the tool exists for has never been measured.

## Version 11: one change on the live path, measured, that changed no answer

The first run of that timing, at version 10 ([`speed/live-timing-v10.txt`](speed/live-timing-v10.txt)), showed something no profile had been asked: a run that asked for tagged figures made two more requests to EDGAR than one that did not, on every run. The filing cache keeps a filing's parsed text; the tags are in the HTML; so the newest annual and quarterly report were fetched a second time.

| Requests to EDGAR per run | Without the option | With it, version 10 | With it, version 11 |
| --- | ---: | ---: | ---: |
| Empty filing cache | 6 | 8 | 6 |
| Warm filing cache | 3 | 5 | 3 |

Two changes: what is read from a filing's tags is kept in the disposable cache, by accession and by a hash of the code that reads them; and on a first run the tags are read from the HTML the run has just fetched for its text. In the version 10 session the option cost a warm run 306 ms (a median of 788 ms against 482 ms) and a cold run 442 ms (1,545 against 1,103). At version 11 it costs no request, and reading the tags from HTML already in hand takes 32 ms on a cold run and nothing on a warm one.

**It changed no answer**: a test compares the figures offered with and without the cache; the recording with tagged figures replays, so the engine's prompts are byte for byte what they were; and a failure is never kept (`tests/test_tagged_cache.py`).

## Version 11: the offline numbers, at this version

`make profile` ([`speed/profile-v11.txt`](speed/profile-v11.txt)): the offline example run takes 455 ms, where it took 345 ms at version 4. Parsing three filings is 308 ms of it (67.5%). The part no stage covers has grown from 13 ms to 76 ms (16.7%), which is where the tripwire's run now also compares two filings; that comparison is not a stage of this stopwatch and was not timed apart, so this is the likely reason and not a measured one. The stages that were timed at version 4 have barely moved.

`make bench`, the header cut, 20 alternating pairs on a machine doing nothing else, twice ([`speed/bench-v11.txt`](speed/bench-v11.txt), [`speed/bench-v11-repeat.txt`](speed/bench-v11-repeat.txt)):

| | With the cut | Without | Saved per pair: median (interquartile range; range) | Cut faster |
| --- | ---: | ---: | --- | ---: |
| Parse 3 filings | 301.5 ms | 327.3 ms | 30.5 ms (19.0 to 62.8; −16.5 to 68.4) | 16 of 20 |
| Whole run | 432.3 ms | 462.0 ms | 34.3 ms (27.9 to 58.7; 16.6 to 65.3) | 20 of 20 |
| The repeat: parse; whole run | 304.8; 439.6 ms | 332.4; 468.7 ms | 31.0 ms; 35.4 ms | 16; 20 of 20 |

So the cut saves about 34 ms of an offline run, 7% of it, and the saving on the whole run agrees with the saving on the parse, as it must. A first bench the same afternoon, taken while another session was running tests, gave 31.7 ms on the parse and 51.7 ms on the whole run: the two did not agree, which is how it was known to be disturbed. Against a live run with an empty cache, 34 ms is about 2% (of 1,472 ms).

## Version 11: which change is "the one", and whether it changed an answer

**The one change measured that changed no answer is the header cut.** The README's speed row and the bench are about it. The other change described below, not syncing a run's progress saves to disk, is a second change and of another kind: it trades durability for time. A power cut can lose the latest progress save of a run that would then never finish; the final save, every decision and every saved thesis are synced. It was timed best of three, not in alternating pairs, and it is kept.

**"Changed no answer" now rests on whole documents.** For the header cut the evidence was the offline tripwire, a test on four recorded filings, and, for the seven companies other than NVIDIA and Costco, only that section headings and lengths agreed. `make header-cut-check` parses each company's latest annual and quarterly report both ways and compares the documents whole: text, hash and every section. Run live on the eight probe companies: 14 of 14 the same ([`evidence/header-cut-fourteen-filings.md`](evidence/header-cut-fourteen-filings.md)).

## Version 4, as measured then

**The offline profile below is not where a real run's time goes.** It replays three
recorded NVIDIA filings with the deterministic engine and waits on nothing. A real run waits on
SEC EDGAR for the filing list, each filing and the XBRL facts, and, with a key, on one model call
per claim of several seconds each. The model has never been timed (the API account had no
credit when this was measured), so the largest part of a model-backed run is unmeasured. What was measured follows,
live path first. Review 3's findings F1 to F5 are answered in order.

## A live run, and what the filing cache saves (F1)

The NVIDIA example against live EDGAR, extractive engine, run twice with
`make run ARGS='example --engine extractive'`, the cache empty before the first run
(17 November 2026, 12:33 UTC; output in [`speed/live-v4.txt`](speed/live-v4.txt)):

| | First run (cache empty) | Second run (cache warm) |
| --- | ---: | ---: |
| Run time, `started_at` to `finished_at` in the record | 1.006 s | 0.378 s |
| `make run` wall time, container start included | 1.89 s | 1.22 s |
| Filings fetched from EDGAR | 3 | 0 (3 of 3 from the cache) |
| EDGAR requests | 6 | 3 |
| Verified excerpts; content hashes of the three filings | 15; same | 15; same |

The requests are counted from the run record and the code path, not by a counter in the client:
the company list (once per process, before the run starts), the filing index, one request per
filing fetched and the company facts. The second record's filings carry the first run's
`retrieved_at`, which shows they were not fetched again, and it says "3 of 3 filings were read
from the local cache; for those, EDGAR was asked only for the filing list." One pair of runs on
one network: EDGAR's latency varies, and these are single samples.

The cache saved 0.63 s: fetching and parsing three filings. The parse is about 0.27 s of that
(offline profile below), so the three downloads were roughly 0.36 s; the warm run still waits on
EDGAR for the filing index and the company facts. With a key, five assessments of several
seconds each (three at a time) would outweigh all of this; that is the unmeasured bulk.

## The offline run, every stage timed (F3)

`make profile` now times each stage inside the run itself (best of three, claims assessed one at
a time so no two stages overlap) and reports what no stage covers as "unaccounted"; there is no
"Other" left. [`speed/profile-v4.txt`](speed/profile-v4.txt):

| Stage | Time | Share | Calls |
| --- | ---: | ---: | ---: |
| Parse 3 filings | 268.9 ms | 77.9% | 3 |
| Index (BM25 over 636 passages) | 22.0 ms | 6.4% | 1 |
| Figures (XBRL facts to metrics) | 17.7 ms | 5.1% | 2 |
| `save_run` (of which serialising the record: 5.3 ms) | 14.4 ms | 4.2% | 24 |
| Chunk; retrieve 5 claims | 2.9 ms; 2.4 ms | 1.5% | 3; 5 |
| Assess (extractive); `gate_claim` | 2.0 ms; 1.2 ms | 0.9% | 5; 5 |
| Filing cache (in memory here) | 1.3 ms | 0.4% | 10 |
| Plan; summary | 0.0 ms | 0.0% | 1; 1 |
| Unaccounted (store set-up, ingest and policy logic, building the golden record) | 12.7 ms | 3.7% | |
| Whole run | 345.4 ms | | |

Version 3's "Other" (74 to 106 ms in its two profiles) was mostly saving. A run saves its
record 24 times: 7 stage changes, 2 per source, 2 per claim and the finish. With version 3's way
of saving, those 24 saves took 33 to 36 ms, and version 3 also copied each filing's text into the
record once per run, which no longer happens.

**The cause was not the one suspected.** The review pointed at one connection and one WAL pragma
per save. Measured, that costs almost nothing; the cost is the commit's sync to disk:

| How each save commits | 24 saves | Each |
| --- | ---: | ---: |
| Version 3: a new connection and WAL pragma per call, every commit synced | 33.3 ms | 1.39 ms |
| One connection per store, every commit synced | 33.8 ms | 1.41 ms |
| Now: one connection, progress saves not synced | 14.4 ms | 0.60 ms |

The fix is in `store.Store.save_run`: a save made while the run is still `running` commits with
`synchronous=NORMAL` (WAL mode: the file is never corrupted, but a power cut can lose that
latest progress save, of a run that would then never finish anyway). The final save, every
decision and every saved thesis commit with `synchronous=FULL`, and a synced commit carries every
commit before it. The record's sha256 is the same under all three ways of committing
(`9a9298a4…c4c81231`), and `make golden-check` passes. Version 4's tripwire moved only in
`limits` (the two new constants `MAX_NOTE_CHARS` and `MAX_THESIS_NAME_CHARS`); the store split and
the cache moved nothing.

The saving is about 19 ms of an offline run and nothing a reader of a live run would notice.

## The header cut, measured again (F2)

Version 3 claimed 8% from two separate benches. That did not reconcile: the whole run fell more
than the parse did. `make bench` now interleaves: each pair is one run with the cut and one
without, alternately in one process, after a discarded warm-up, and both variants must give the
same record. 20 pairs ([`speed/bench-v4.txt`](speed/bench-v4.txt)):

| | With the cut | Without | Saved per pair: median (interquartile range; range) | Cut faster |
| --- | ---: | ---: | --- | ---: |
| Parse 3 filings | 300.2 ms | 329.9 ms | 26.0 ms (16.6 to 61.2; −16.0 to 96.7) | 16 of 20 |
| Whole run | 374.6 ms | 404.5 ms | 28.8 ms (21.5 to 56.9; −8.6 to 93.0) | 18 of 20 |

A second bench of 12 pairs ([`speed/bench-v4-repeat.txt`](speed/bench-v4-repeat.txt)) saved
34.9 ms on the parse and 37.9 ms on the whole run (interquartile range 27.6 to 62.2 ms; cut
faster in 12 of 12). Measured this way the whole-run saving equals the parse saving, as it
must, and the interquartile range of the paired difference excludes zero: the cut saves roughly
25 to 40 ms, about 7 to 9% of the offline run. The spread is wide (single pairs went the other
way), because the machine was shared with other work while it ran. On a live run it is about
3% of the keyless path and nothing beside a model call. Both variants gave the same record
(`9a9298a4…`) in every pair.

## The header cut on eight companies (F4)

`results/probe-20261117T114758Z.md` was taken before the cut, on NVIDIA, Apple, Microsoft,
Coca-Cola, JPMorgan, Tesla, Costco and Amazon. The same probe after the cut
(`make probe OUTLINE=1 TICKERS="NVDA AAPL MSFT KO JPM TSLA COST AMZN"`) read the same 14 filings.
Every row is identical apart from parse time (HTML size, text size, sections, Items found, Item
coverage, verdict), and so are all 1,832 lines of the section outlines, heading and length
([`speed/probe-v4.md`](speed/probe-v4.md)). `tests/test_ingest.py::
test_cutting_the_inline_xbrl_header_changes_no_document` parses Costco's 10-K and NVIDIA's three
filings with and without the cut and requires the identical `Document` (text, hash and every
section).

## Assessing claims concurrently: mechanism tested, gain unmeasured (F5)

`execute_run` assesses up to `limits.MAX_CONCURRENT_ASSESSMENTS = 3` claims at once. Claims
start in claim order and pass the gate in claim order, so ids and counts are a sequential run's.
`test_thesis_run.py::test_concurrent_assessment_gives_the_sequential_record_in_less_time` proves
the mechanism with a stand-in engine that waits 200 ms per call: identical records, at most
three calls at once, 0.50 s against 1.13 s. That ratio is the stand-in's sleeps overlapping, and
the check uses the deterministic engine, so it proves ordering and ids, not model behaviour.
**The gain with the real model is unmeasured**, as are rate limits on three parallel calls and
the thread safety of the real transport beyond its lock.

## What was not measured

- Model latency and the real gain from concurrency (no API credit when this was measured; not timed since).
- EDGAR latency beyond the two runs above, and its variance.
- Speed on other hardware: every number here comes from one laptop, in Docker.
- The filing cache under two processes writing at once (WAL allows it; no test runs two).
