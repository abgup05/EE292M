# Referee 6: a hostile reading of version 14.2

- **Why:** version 14.2 added the analysis (relevance, analytics, corollaries, persistence odds, the argued analysis and its audit), the outside view and the market view, the reference pack and the workspace page, and no referee had read any of it.
- **Reviewed:** tag `capstone-v14.2` (commit `2b56f7a`), from a git worktree of that commit with `Work Logs/`, `Homework/`, `Capstone/evidence_desk/docs/reviews/` and the five triage files under `docs/` deleted before the referee started. The agent's brief in that checkout predates version 12: it names no claim of versions 12 to 14.2, so the referee chose what to read. It read the gate, the number check, the period check, the verdict rule, the filing comparison, the speed and gate evidence and the first live sample; it opened none of the analysis code (`core/analytics.py`, `core/analysis_audit.py`, `engines/analyser.py`), the outside or market view, or the page.
- **Referee:** the `referee` agent defined in `.claude/agents/referee.md`, started with `make -s referee` from the root of that worktree: a fresh headless Claude Code session that uses the agent by name. Model: Claude Sonnet 5.5, which did not write the code of version 14.2 (Claude Opus 5.5 and Claude Fable 5.2 agents did) but is one of the app's two model readers of claims. Tools limited by the agent definition to Read, Grep and Glob; it ran no commands. Cost of the session: $3.45. It is another Claude model, not an independent party.
- **Run on:** 19 November 2026 (UTC). The session that started it was told to return the referee's findings exactly as written; the text below is what it returned, unedited, including the absolute paths of the checkout it read.
- **What it could not see:** the gate at version 14.2 had been run green on a fresh clone before the tag (lint, 2,568 offline tests, the smoke test, 573 page assertions and 2 skipped), but the committed `docs/evidence/verify-fresh.txt` was still version 14.1's. That is its finding 6.
- **Checks made afterwards:** no file in the checkout is newer than the marker written before the referee started, and every path the report cites is inside that checkout.

The triage of every finding is in [`../referee-6-triage.md`](../referee-6-triage.md).

---

I could not run anything: this session had no shell, so no test, `make` target or Python was executed. Every finding below comes from reading the code and the committed outputs. Where I say "pass" or "fail" for a constructed input, I traced the code by hand, and each one needs a test to confirm.

## Findings, worst first

**1. The quote gate lets a quote stop at the edge of a unit, and the number check then rescales the bare number.**
- `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v14.2/Capstone/evidence_desk/src/app/core/gate.py:76-99` (`_splits`) only refuses a cut between two letters or digits, or beside a decimal point or comma between digits.
- A cut between `7` and the space in "$46.7 billion" is therefore accepted. So is a cut before `%`, and a quote that starts after a leading `-`.
- `numcheck.py:601` marks a bare USD or plain number as `rescalable`, so it matches at 1e3, 1e6 and 1e9 (lines 584-593).
- Input: the engine quotes "Data Center revenue was $46.7" from "…was $46.7 billion" and writes "revenue was $46.7 million".
- By my trace the excerpt is whole and 29 characters long, so it is kept. `$46.7 million` matches 46.7 × 1e6, so the finding is verified with the wrong scale.
- A quote that starts after the minus in "-5% from the prior year" is read as a positive 5%, which defeats the direction rule for "revenue grew 5%".
- The module docstring says a span never ends inside a number, and the README says "46.7" cannot be quoted out of "46.78 billion". That is true only for a cut inside the digits.
- The README's blind-spot list says a bare number matches an amount at table scales. It does not say the gate itself can produce the bare number by cutting the scale word.
- Show it with a gate test of that quote and statement, and a second with a quote beginning at `5%` from `-5%`.

**2. A "partly supported" finding counts at full strength, and most of the shipped live run is "partly".**
- `core/policy.py:393-404` (`counted_stance`) returns the engine's stance for any verified finding that has evidence. `checks.support` is never read.
- In `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v14.2/Capstone/evidence_desk/src/web/sample-run-live.json`, `coverage.findings_partly` is 10 and `findings_verified` is 13. Only 3 of the 13 are "passed".
- Finding f2 (line 11488 onward) is counted as `challenges`. Its checker note says nothing in the excerpt mentions the Board Chair appointment its statement asserts.
- The README leads with "Rejected 1 of 78" and "changed no verdict". It does not say that "partly" is the usual outcome in the live runs, or that "partly" does not reduce a verdict.
- The README's "complete does not mean much evidence" admission is not enough here, because the status never reflects this.
- Show it by building a claim whose findings are all "partly" and checking that `claim_verdict` returns `supported`.

**3. The period check passes a fiscal label whenever the quote prints that year as a calendar date. The docs say the opposite.**
- `core/periods.py:474` returns `IN_QUOTE` before the fiscal/calendar distinction at 476-483. `years_in` (372-388) counts any four-digit number.
- `docs/period-check.md:23` says "A calendar year is not enough for a fiscal label… NVIDIA's quarter ended 26 July 2026 is in its fiscal 2027."
- Input: the statement says "fiscal 2026" about the quarter ended 2026-07-26, and the quote contains "Jul 26, 2026". The check returns passed.
- That is the dominant label error for an off-calendar filer. The limits section lists wrong-column and date-versus-year, but not this.
- The shipped sample shows a related misattribution. For "quarter ended 2026-07-26", finding f3's `periods_detail` says the year is "the calendar year of a filing quoted (period ended 2026-01-25)".

**4. The claim-changes page can say something false about EDGAR.**
- `services/claim_changes.py:149-154` takes the run's filing and the earlier one from a list fetched with `filings_of_form(…, FORM_HISTORY=12)`.
- `sources/edgar.py:344-369` only reads older index pages while fewer than 2 filings of the form were found. The `limit` argument only trims.
- So when the recent index holds 2 or more 10-Ks, and the run read the older of them, no earlier 10-K is in the list. The page prints "EDGAR lists no 10-K filed before …", which is false because EDGAR does list it. The same path hits an as-of run on an older 10-K.
- The comment "three years of 10-Qs, or twelve of 10-Ks" describes a fetch that does not happen.
- Show it with a fake index of two 10-Ks and a run that read the older.
- Separately, the README admits the earlier filing of each pair is not one the run read. That admission is accurate, but the claim "a change in the filings the run read" is still false for removed and reworded-before paragraphs.

**5. The README's speed sentences are contradicted by committed outputs and describe an old version.**
- README line 230 says "57 to 59%" of a live run is waiting for EDGAR, and "about 45 ms of every run is covered by no stage".
- `docs/speed/live-timing-v12.txt` gives 73.3% and 71.1% cold, and unaccounted time of 140.3 ms cold and 144.2 ms cold with tagged figures. Reading and parsing the 8-Ks is the unattributed part.
- `live-timing-v12-before.txt` is the same 0.11.1 code, measured the next morning. It shows 60.0%, 66.4%, 55.5% and 68.0%, and 1360 ms cold against 1160 ms the night before. So "57 to 59%" is one session's range, not a property.
- The 11.1 file's header line says "version 0.11.0", while the doc says 11.1.
- The "2.11 s instead of 1.36 s" comparison is two sessions run one after the other. `AGENTS.md` says a speed claim needs alternation.
- Nothing in the README was timed at 0.14.2, which adds events, a fact store, computed tests, analysis and two network-bound views.
- The 123 s and 126 s live-run figures do match the sample timestamps (00:11:05 to 00:13:08 and 00:08:47 to 00:10:53).
- The header-cut table matches `bench-v11.1.txt`. I found no fault there: 20 of 20, medians 25.4 and 24.0 ms.

**6. The gate and restore evidence belong to 0.14.1, not 0.14.2.**
- `docs/evidence/verify-fresh.txt` line 2 says commit 358b0b0, version 0.14.1.
- README line 237 presents "2,361 offline tests" as what `make verify` does now. Version 0.14.2 added the analysis and the market view.
- `backup-restore.txt` is also 0.14.1.
- Nothing in the repository shows a green gate for the shipped version.

**7. "No lookahead" is stated without the outside view's exception.**
- README line 221 (`evidence_desk/README.md`) and the Capstone README's milestone 14 row say no output references a fact filed after the as-of date.
- `docs/outside-view.md:64-66` and `docs/reference-pack.md:60-62` say frames hold the latest, possibly restated, value, and that the pack is built from today's SEC data.
- A past-date run that includes the outside view therefore uses later facts. The README's as-of limitation (line 310) mentions only documents edited in place.

**8. The change list pools queries, and a model writes those queries.**
- `core/claim_changes.py:152-164` unions the content terms of the claim and all its planner queries, then requires 2 shared terms from that union.
- A paragraph sharing one word with the claim and one with a different query qualifies.
- README item 9 says "two words with the claim or with the queries". The page also says no model chose the list, but with a key the planner queries are model output.

**9. The number check and the period check disagree with their own docs after a preposition.**
- `numcheck.py:226-234` treats a four-digit number after "of", "for", "by" or "in" as a year, so it is not checked.
- "headcount of 2000 employees" is then unchecked, contradicting the docstring at lines 36-44 ("'2000 employees' … are checked").
- The period check then reads "2000" as a year and can report it as not found, which is a false alarm.

**10. Thin evidence is still not reported.**
- This was refused four times (`policy.py:487-489`). A run with one quote per claim, mostly "partly" supported (item 2), is "complete".
- The brief shows "Filings quoted" per claim, but the status headline and the verdict word do not move.
- The README's admission is accurate and not sufficient as the page's signal.

**11. Minor.**
- README says `demo/cassettes/nvda-example` holds 12 answers. It has 26 files: 12 from stand-ins and 14 from the API (the analysis).
- Milestone 14's exit check says 52 golden computed claims, and its result says 69.

## Claims I tried and could not break
- The span identity in `gate.py`: the excerpt is sliced from the stored text by construction.
- The restore check in `backup.py`: every table and every column is compared, and a deleted row fails.
- The filing-comparison counts: the arithmetic in `filing_diff._compare_group` makes every line land in exactly one count. `sample-changes.json` matches the README's 251/60/218/133/132.
- Tagged figures: they are gated on offered ids, and a run that did not ask never loads them (`thesis_run.py:340-355`).
- The no-lookahead check: I did not look for a flaw in the fact-book path.

## README statements I could not confirm from the repository
- The 28 published values and the figures for the eight companies.
- 13 of 14 filings split into Items.
- The golden-set, period-check and meaning-check measurements.
- The 2,361 tests at 0.14.2.
- Anything in the gitignored `results/`: run-8a12ef614117, run-72359824897a, run-7fa4a528d428 and run-39d0b17b5396.
  - I confirmed NVIDIA's 105 and 101 sentences and both durations from the samples. I did not open the Costco sentence counts.
- That each cassette answer came from the channel it names. The `via` field is self-declared.
- The watch replay, the screenshots and the browser claims.

I did not read `tests/` beyond counting them, the eval sets, or `docs/` beyond the files cited.

Files opened (all under `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v14.2/Capstone/`):
- `evidence_desk/src/app/core/gate.py`
- `evidence_desk/src/app/core/numcheck.py`
- `evidence_desk/src/app/core/policy.py`
- `evidence_desk/src/app/core/periods.py`
- `evidence_desk/src/app/core/meaning.py`
- `evidence_desk/src/app/core/filing_diff.py`
- `evidence_desk/src/app/core/claim_changes.py`
- `evidence_desk/src/app/core/tagged_figures.py`
- `evidence_desk/src/app/core/metrics.py`
- `evidence_desk/src/app/core/facts.py`
- `evidence_desk/src/app/core/limits.py`
- `evidence_desk/src/app/services/claim_changes.py`
- `evidence_desk/src/app/services/filing_changes.py`
- `evidence_desk/src/app/services/tagged_figures.py`
- `evidence_desk/src/app/services/thesis_run.py`
- `evidence_desk/src/app/services/export.py`
- `evidence_desk/src/app/sources/edgar.py`
- `evidence_desk/src/app/sources/ixbrl.py`
- `evidence_desk/src/app/sources/filing.py`
- `evidence_desk/src/app/backup.py`
- `evidence_desk/src/app/store.py`
- `evidence_desk/docs/speed.md`
- `evidence_desk/docs/speed/live-timing-v11.1.txt`
- `evidence_desk/docs/speed/live-timing-v12.txt`
- `evidence_desk/docs/speed/live-timing-v12-before.txt`
- `evidence_desk/docs/speed/bench-v11.1.txt`
- `evidence_desk/docs/period-check.md`
- `evidence_desk/docs/evidence/verify-fresh.txt`
- `evidence_desk/docs/evidence/backup-restore.txt`
- `evidence_desk/src/web/sample-run-live.json`
- `evidence_desk/src/web/sample-changes.json`
- `evidence_desk/demo/cassettes/nvda-example/responses/*.json` (the `via` and `model` fields only)
