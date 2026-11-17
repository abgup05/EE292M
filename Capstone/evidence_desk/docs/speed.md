# Speed

Version 4. **The offline profile below is not where a real run's time goes.** It replays three
recorded NVIDIA filings with the deterministic engine and waits on nothing. A real run waits on
SEC EDGAR for the filing list, each filing and the XBRL facts, and, with a key, on one model call
per claim of several seconds each. The model has never been timed (the API account has no
credit), so the largest part of a model-backed run is unmeasured. What was measured follows,
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

- Model latency and the real gain from concurrency (no API credit).
- EDGAR latency beyond the two runs above, and its variance.
- Speed on other hardware: every number here comes from one laptop, in Docker.
- The filing cache under two processes writing at once (WAL allows it; no test runs two).
