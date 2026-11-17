# Referee 4: a hostile reading of version 11

- **Why:** versions 10 and 11 added findings that cite tagged figures, the period check, a stricter restore check and new speed measurements, and none of those claims had been attacked.
- **Reviewed:** tag `capstone-v11` (commit `ff14e72`), from a git worktree of that commit with `Work Logs/`, `Homework/`, `Capstone/evidence_desk/docs/reviews/` and the triage files under `docs/` deleted before the referee started. The agent's brief in that checkout was the one committed after the tag (`8c9a7a0`), which adds four lines naming the claims of versions 10 and 11.
- **Referee:** the `referee` agent defined in `.claude/agents/referee.md`, started with `make -s referee` from the root of that worktree: a fresh headless Claude Code session that uses the agent by name. Model: Claude Sonnet 5.5, which did not write the code. Tools limited by the agent definition to Read, Grep and Glob. It is another Claude model, not an independent party.
- **Run on:** 17 November 2026. The session that started it was told to return the referee's findings exactly as written; the text below is what that session returned.
- **Checks made afterwards:** no file in the checkout was changed after the referee started, and every path it cites is inside the checkout.

**Not yet answered.** None of the eight findings below has been checked against the code or decided. Until each is, read what the README says about the changed paragraphs under a claim, the period check, the restore check and the speed figures with these findings beside it.

---

I could not run anything here: I had read and search tools only, so no test, command or input below was executed. Where I say "would", it is by reading the code. The first four findings are the ones I am most sure of, and the first two need no execution to see.

## Findings, worst first

**1. The changed-paragraph lists compare only the newest 10-K and newest 10-Q, but the page, brief and README say "each filing the run read".**
- `src/app/services/claim_changes.py:84-103` (`filings_read`) keeps one source per form, the newest.
- The page says "Each filing this run read is compared with the filing of its form filed before it" (`src/web/app.js:2626`) and heads the block "Changed since the filing before each one this run read" (`app.js:2737`, `export.py:371`). The README's item 9 says the same.
- A default run reads one 10-K and two 10-Qs. The older 10-Q is never compared, and nothing says it was left out.
- To show it, give `run_changes` a run with two 10-Q sources and check that `compared` has two entries, not three.
- The page does list the pairs it compared, so a careful reader can notice. The sentence is still false, and a keyword-match disclaimer does not cover it.

**2. The period check raises a false alarm for any year before 1990, and its measurement cannot see its own blind spots.**
- `core/periods.py:68` sets `EVIDENCE_YEARS = range(1990, 2101)`. `numcheck.YEARS` (`numcheck.py:89`) is 1900 to 2100, and `years_in` (`periods.py:339`) drops anything earlier.
- "The Company has operated since 1886", over a quote that prints "since 1886", would be reported as unverified. Coca-Cola's incorporation date (1919) is a realistic case. The test is `check_periods("…since 1886", [("…since 1886…", None)], [], None)`.
- The "no false alarm on 34 years" figure covers a golden set that happens to contain no pre-1990 year.
- A year used as an adjective ("2025 revenue was…") is not a year to `is_year` (`numcheck.py:312-323`, which needs a preceding period word or a joined year). The period check never sees it. The number check reads it as a count of 2025 and matches it only against a bare "2025" in the quote, which can wrongly withhold a true finding.
- The planted-error measurement uses the same recogniser (`shift_years`), so it cannot plant years the recogniser misses.
- It also moves every year in a statement together (`generation_eval.py:454`). A realistic slip is one wrong year beside a correct one, which is easier to miss than 21 of 25 suggests.
- The docs admit the wrong-column miss. They do not admit the pre-1990 false alarm, the adjective-year gap, or the optimism of the planting.

**3. The restore-check evidence is from the old check, and the new check does not compare everything.**
- `docs/evidence/backup-restore.txt` is stamped "version 0.10.0". Its PASS line has no "taken … before this check" (compare `backup.py:307-310`) and no "readable" clause.
- The README and `docs/results.md:124` describe the version 11 check ("compared record by record … all readable") and cite that output. No committed output comes from the check described.
- `results.md:124` says "the real record". The evidence file says it is "the record the live walk had just written".
- `backup.py:225-234` compares only the `record` text column (`store.py:279-293`). The `runs.thesis_id`, `runs.started_at`, `decisions.decided_at` and `theses.created_at` columns are never compared. `runs_of_thesis` (`store.py:203-209`) reads `thesis_id`, so a backup whose column differs passes while "what moved" breaks. No test in `tests/test_backup.py` changes a column other than `record`.
- The check compares the backup against the live record. Any write since the backup, including a running run's progress save, produces FAIL. It shows that backup and live are identical, not that the backup is right.
- "Fails on any difference" is not true as worded.

**4. The `make bench` data contradicts "the saving on the whole run agrees with the saving on the parse, as it must" (`docs/speed.md:48`).**
- `docs/speed/bench-v11.txt`: in pairs 5, 10, 15 and 20 the cut parse is slower, by 10 to 16 ms (for example 305.7 against 289.2), yet the whole run is faster by 27 to 35 ms.
- In pair 5 the part outside parsing is 125.6 ms with the cut and 177.2 ms without.
- The cut-variant parse time is bimodal and follows a period of five: about 265 ms in pairs 1, 3, 6, 8, 11, 13, 16 and 18, and about 305 ms in the rest. That points to a cyclic artifact, such as garbage collection or allocation, and not random noise.
- The order within each pair is fixed (cut first), so it may be confounded.
- "Saves about 34 ms" is a median between two modes, and the order effect is as large as the claimed saving. The sentence is arithmetically true and does not show the cut's effect. The same pattern is in `bench-v11-repeat.txt`, which I did not open.

**5. The live-timing numbers include a request the app does not make per run.**
- `tests/live_timing.py:94` builds a new `EdgarClient` for every run.
- The ticker list is cached per client (`sources/edgar.py:317-326`) and fetched inside `execute_run` (`thesis_run.py:243`). That is why the cold run makes 6 requests and the warm run 3.
- The long-lived app fetches that list once, and the API resolves the ticker before the run starts. So "about two thirds spent waiting for EDGAR" and the 6 and 3 request counts are inflated for the app.
- `speed.md:20` says the unstaged time on a warm run is "mostly rebuilding the three documents from the cached text". Nothing timed that, so it is an inference stated as fact.

**6. "A verdict cannot be asserted without verified evidence" and "every number is in its quotes" are weaker than worded.**
- A figure-only finding counts toward a verdict when a second model passes it (`policy.py:164-175`). The "verified" figure is only an offered id with matching digits. The README admits this.
- The exact-match path accepts a quote that begins or ends inside a word or number (`gate.py:154-156`; only the normalised path checks alignment). A quote ending in "…$46.7" over a filing's "$46.78 billion" verifies, and the displayed excerpt carries 46.7.
- A plain number in a quote with no scale word matches a dollar amount at 1e3, 1e6 or 1e9 (`numcheck.py:533-538`). "$12.5 billion" can be satisfied by an unrelated "12.5". The README's blind-spot list does not mention this.

**7. The Markdown export escapes only "<".**
- `export.py:69` and `:89-90`: `[x](url)`, `![](url)`, `*` and backticks in an excerpt survive.
- Excerpts from user-added pages are untrusted, so a brief opened in a Markdown viewer can render a link or fetch an image. The excerpt is exact in the record, not in the rendering.

**8. Smaller points.**
- `breakdowns._pick` keeps the first-encountered value when a fact is tagged twice with different rounding. A rounded MD&A figure can be shown over the exact one, with a conflict note.
- "Thin evidence is shown per claim" is true on the page for findings (`app.js:2864`), but the export's verdict table shows stance counts, not filings. The README admits "complete" is not a measure of evidence. The remedy is not in the verdict row.

## README statements I could not confirm

I read the code but ran nothing, so I could not confirm any of these:

- 1,499 tests passing. I counted 970 test functions, and `verify-fresh.txt` is from commit `a9edf2f`, not HEAD.
- The eval counts: retrieval 9 and 18 of 24, verdicts 20 of 24, 6 of 6 unanswerable refused, 84 of 84 quotes, 150 of 152 planted mismatches.
- The 28 published values, the eight-company figures, and 14 of 16 breakdowns adding up.
- NVIDIA's filing-comparison counts (251, 60, 218, 133, 132) and the 802 changed paragraphs.
- The period-check tables, the 34 years and 21/24/25/23 flagged. The same eval run produced them; only the committed `docs/period-check.md` was read.
- That the links open filings at the passage. The README admits this one.
- That the two-writers result holds beyond one run on one laptop. The README says as much.

All paths are under `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v11/Capstone/evidence_desk/`.
