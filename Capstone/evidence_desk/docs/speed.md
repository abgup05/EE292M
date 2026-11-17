# Speed

Version 3: the parser skips the inline-XBRL header; claims are assessed three at a time.

## Where the time goes

`make profile` runs the offline example (`tests/golden_run.build_golden`: parse, chunk, index,
retrieve, assess with the extractive engine, gate, figures, save) under cProfile; it writes the
top 25 functions by cumulative time and an unprofiled time per stage to
`results/profile-<UTC>.txt`. The first output is [`speed/profile-before.txt`](speed/profile-before.txt):

| Stage (unprofiled, best of three) | Time | Share |
| --- | ---: | ---: |
| Parse 3 filings (4.65 MB of HTML, 46,674 start tags) | 286.5 ms | 66% |
| Other: assess, gate, verdicts, 24 SQLite saves | 106.5 ms | 24% |
| Index (BM25 over 636 passages) | 21.4 ms | 5% |
| Figures (XBRL facts to 156 metrics) | 16.4 ms | 4% |
| Chunk; retrieve 5 claims | 2.9 ms; 2.2 ms | 1% |
| Whole run | 435.9 ms | |

Under the profiler, 0.89 of 1.29 s is BeautifulSoup feeding `html.parser` (0.53 s in
`parse_starttag`); our walk over the tree is 0.14 s. Retrieval is 6% of the run.

## The one algorithmic change: do not parse what is thrown away

The largest share is tokenising tags, which is library code: lxml would be a new dependency, a
streaming extractor a rewrite of the parser. In our own code, a whole subtree is built only to
be discarded: the `ix:header` block (XBRL contexts and units, never text), 14-17% of each
filing's tags. `sources/filing.parse_filing` now cuts it out in one linear pass before parsing,
and reads it only when the body does not tag `dei:DocumentType` (covered in `test_filing.py`).

Measured with `make bench` (median of 5 runs of `build_golden`, in the app container):

| | Before | After |
| --- | ---: | ---: |
| Start tags parsed | 46,674 | 39,936 |
| Parse 3 filings (best of three) | 286.5 ms | 267.7 ms |
| Whole run, median of 5 | 0.445 s | 0.411 s (0.409 and 0.411 on two more benches) |

A modest gain (8%); beyond the parse, part of it is run-to-run variation in SQLite commits.
Profile afterwards: [`speed/profile-after.txt`](speed/profile-after.txt). **No answer changed:**
`make golden-check` passed with the same sha256, `fd8760cb…6a13e5f`, before and after.

## Assessing claims concurrently

With a model each assessment is a network call of several seconds, and claims ran one after
another. `execute_run` now runs up to `limits.MAX_CONCURRENT_ASSESSMENTS = 3` on a thread pool.
Claims start in claim order (retrieval stays on the main thread) and pass the gate in claim
order, so ids (`f1`, `e1`, ...) and counts are a sequential run's. Progress still names "claim n
of 5"; the time limit is checked before each round of starts, and a claim not started in time is
reported as not assessed; a failed call falls back for that claim only.

**The real model could not be called in this version (the API account has no credit), so the
gain is measured with a stand-in that waits 200 ms per call** (`ScriptedAnalyst` plus a sleep).
`test_thesis_run.py::test_concurrent_assessment_gives_the_sequential_record_in_less_time` runs
five claims at concurrency 1 and 3 and asserts identical records apart from ids and timestamps,
at most three calls at once, and a time ratio below 0.6. Three runs: 1.13 s sequential, 0.50 s
concurrent, ratio 0.44 (ideal 0.4: two rounds of 200 ms against five).

**No answer changed:** with the new constant left out of the limits snapshot, the concurrent run
reproduced the old record exactly (`fd8760cb…6a13e5f`). The constant moved only `limits`; the
new baseline is `ea760582…f66c59778`. The offline run waits on nothing: its bench is 0.414 s.

## What was not measured

- Model latency: no call reached the API, so the real gain, and whether three parallel calls
  meet a rate limit, are unknown.
- EDGAR latency beyond one live run: three filings, 3.2 s end to end
  ([`../demo/demo-2026-11-17-v2.md`](../demo/demo-2026-11-17-v2.md)). Only NVIDIA was profiled.
