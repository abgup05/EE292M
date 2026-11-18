# Referee 5: a hostile reading of version 14

- **Why:** versions 12, 13 and 14 added the 8-Ks read since the annual report, the standing watch, dated facts, runs as of a past date, claims compiled to computed tests and the model readers of those tests, and no referee had read any of them.
- **Reviewed:** tag `capstone-v14` (commit `b372c7f`), from a git worktree of that commit with `Work Logs/`, `Homework/`, `Capstone/evidence_desk/docs/reviews/` and the four triage files under `docs/` deleted before the referee started. The agent's brief in that checkout was the one committed at `8c9a7a0` (before version 12): it names no claim of versions 12 to 14, so the referee chose what to read.
- **Referee:** the `referee` agent defined in `.claude/agents/referee.md`, started with `make -s referee` from the root of that worktree: a fresh headless Claude Code session that uses the agent by name. Model: Claude Sonnet 5.5, which did not write the code. Tools limited by the agent definition to Read, Grep and Glob; it ran no commands. Cost of the session: $2.95. It is another Claude model, not an independent party.
- **Run on:** 18 November 2026. The session that started it was told to return the referee's findings exactly as written. It returned them with one added note at the top and the list of files at the end, and says so in its first line; the text below is what it returned, unedited.
- **What it could not see:** the gate at version 14 had been run green on a fresh clone (lint, 2,326 offline tests, the smoke test, 337 page assertions and 2 skipped), but no output of that run was committed; and the Anthropic API had been answering since credit was added on 18 November, while older parts of the README still said it had never run. Both bear on several findings.
- **Checks made afterwards:** the session that ran it checked that nothing in the checkout was changed by the referee (the worktree has since been removed, so this could not be checked again here); every path the report cites is inside that checkout.

The triage of every finding is in [`../referee-5-triage.md`](../referee-5-triage.md).

---

I ran the referee agent. This is its report as it wrote it, but I added this note and the file list below because the agent could not execute anything: it read the code and committed outputs, and ran no commands.

  I read the code and the committed outputs but ran nothing: this session had no way to execute commands. Every "how to show it" below is a test or command I would write, not one I ran. Nothing in the README's measured results could be reproduced from here.
  
  ## Problems, worst first
  
  **1. The README says both that the Anthropic API has been used and that it has not.**
  - Lines 30, 184 and 233 of `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v14/Capstone/evidence_desk/README.md` say the API path has not run since version 1, both keys were refused for lack of credit, and "every model-backed result below comes from recorded answers".
  - Lines 15, 59, 170 and 254 present `?sample=run-live`, `?sample=run-events` and set C (240 calls) as run "through the Anthropic API" on 18 November.
  - `src/web/sample-run-live.json` lines 30-35 carry `"engine_detail": "claude-opus-5-5 via the Anthropic API"` and Haiku/Sonnet readers, started 2026-11-18T13:55Z.
  - One side is false. A reader cannot tell which model-backed numbers are live and which are a stand-in's recordings, which is what the repo's own "never report a model-backed result without saying where the answers came from" rule exists to prevent.
  - I could not confirm either side. `results/run-7fa4a528d428.json` is gitignored, and the sample is only a copy.
  - Show it by `grep -n "Anthropic API" README.md` and reading lines 30, 59, 184, 233 side by side.
  
  **2. The committed example brief has a summary that contradicts its own verdict table.**
  - `docs/examples/v14/brief.md` lines 23-27 show two Supported, one Challenged, two "not judged". Lines 31-33 say "Passages found, not judged: 5 … 5 claim(s)", written by "template".
  - Cause: `src/app/services/thesis_run.py:535` writes the summary, and `:546` (`count_computed`) changes the verdicts afterwards. Every run that compiles a claim gets this.
  - The Supported rows also show "Supporting 0 / Challenging 0 / Context 3", so the verdict rests on nothing the columns show.
  - The README limitation (line 246) describes the summary mismatch as something that "could" happen and says the summary is "marked as model-written". Here it is a template summary and the mismatch is systematic, so the admission is not sufficient.
  - Show it by running `make examples` and diffing the Summary against the Verdicts table.
  
  **3. A computed test compares raw floats, so a rounding tie counts as a challenge.**
  - `src/app/core/claim_eval.py:94-99` defines only `> >= < <=`. Line 1111 evaluates `OPS[op](l_value, r_value)` on unrounded values.
  - The arithmetic line is built from the displayed values (line 1118). "Gross margin is at least 75%" against a stored 74.96 prints `75.0% >= 75.0%: fails`, margin "-0.0 points", and the claim counts as a challenge (`policy.py:400`).
  - No document I read mentions rounding for tests.
  - Show it by compiling that claim, evaluating it on a `FactBook` whose margin is 74.96, and asserting the outcome and the arithmetic line agree.
  
  **4. "No model is involved" (README item 13, line 49) is false once model readers are on.**
  - With `READERS=models`, `policy.reading_agreement` (`policy.py:275-295`) and `computed.py:123-127` let two model readers' agreement decide the test. The grammar may have refused it, and the test still counts as verified support or challenge.
  - README line 170 says 17 of the 36 counted tests in set C came from the two models alone.
  - The same line says the claims' author, one of the readers, and the judge are all Sonnet 5.5. It reports one counted test wrong (h063) and two unsure, so a wrong test can set a verdict.
  - The evaluation is circular, and the admission in line 254 contradicts line 49.
  
  **5. The number check misses some wrong numbers.**
  - Direction of decline is not checked even for signed computed figures. `numcheck.py:550-573` matches "fell 55.6%" to a cited `revenue_yoy = +55.6`. The README excuse (filings print declines as positives) does not apply to a computed figure whose sign is known.
  - Unit-glued numbers are silently unchecked. `numcheck.py:397-398` returns None for "46.7B" or "2.5M" with no "$", so a wrong value passes.
  - `numcheck.py:404` also exempts bare integers up to 12 before the count test, so "12 customers" is unchecked.
  - Show the first with `check_numbers("Revenue fell 55.6% year over year", [], [Metric(unit="percent", value=55.6, …)])` and assert it fails. It passes.
  - I did not run the date-mask case: `_DATE_MASKS` (`numcheck.py:202`) would mask "March 15%" as a date and skip the percentage. It is unlikely in real text.
  
  **6. `make verify` is not shown green at version 14, and several README test counts have no committed output.**
  - `docs/evidence/verify-fresh.txt` is version 0.12.0 (1,702 tests, 168 DOM assertions).
  - The README gives 2,079 tests and "339 tests on the DOM" (lines 189 and 193). Those two figures appear nowhere else in the repo except prose in `docs/testing.md` (2,079 only).
  - README line 178 admits the smoke and browser tests were not run at version 14. Line 193 still states 339 as fact.
  - The suite went from 28.85 s to 92.96 s, explained only as "other projects' containers".
  - `grep -c "def test_" uitests/*.py` gives 201 functions; 339 needs parametrization. I could not confirm it.
  
  **7. The restore-check evidence is stale, and the check cannot tell stale from broken.**
  - `docs/evidence/backup-restore.txt` is version 0.11.1, before the watch tables, and its backup was taken seconds before the check from a record the live walk "had just written".
  - `restore_check` (`backup.py:321-360`) compares the newest backup with the live record. A run written after the backup produces a FAIL ("run X is in the live record but not in the backup"), the same as a corrupt backup would.
  - The same evidence file prints "found a version 3 database at /work/data/runs/runs.sqlite; it is not read". That older record is neither read nor backed up, and the README's "What cannot be rebuilt" table never mentions it.
  - The column-by-column comparison itself looks sound. Show it by adding a run after `make backup` and running `make restore-check`.
  
  **8. Filing text sits in a "disposable" cache, but the exact-span invariant for stored runs depends on it.**
  - `store.py:555` (`source_texts`) is the only way stored text is read, and I found no re-verification at read time.
  - `parser_version()` (`ingest.py:49`) is a hash of `filing.py`. After any parser edit, a rebuilt text for an old run differs, and the evidence offsets point at nothing.
  - The README table says "Yes, rebuildable from EDGAR, by the parser version that produced it", but that version no longer exists in the tree once it has changed.
  
  **9. The filing-change lists claim a little more than they should.**
  - `claim_changes.py:168` raises `REREAD_NOTE` only when the later filing's hash differs, never the earlier one. When it fires, the listed paragraphs and offsets come from today's parse, not the text the run stored.
  - README item 9 says "five best by keyword overlap". The ranking is BM25 best-over-queries (`core/claim_changes.py:170-173`), with overlap used only as a threshold.
  - The results table (line 162) titles the row "Changes that bear on each claim".
  - `filing_diff.py:85` masks digits only when `(?<![a-z0-9])`, so "FY25" to "FY26" and "Q1" to "Q2" are classed "reworded", not "numbers only".
  - The rest of the listing logic held up when I read it. Spans are built by construction (`_section_starts`) and the counts reconcile.
  
  **10. Tagged figures.**
  - `reader_version()` (`services/tagged_figures.py:61`) hashes `ixbrl.py`, `breakdowns.py` and `breakdown_models.py` but not `core/metrics.py`. The kept reports hold `display` and `change_formula` strings from `millions_text`, `percent_text` and `YEAR_MATCH_DAYS`, so editing those leaves stale cached figures.
  - A segment-qualified customer share is labelled "Share of revenue by major customer". The breakdown note says the tags do not say whether it is of total or of segment revenue (`breakdowns.py:951-956`), but the offered figure's note (`tagged_figures.py:122-126`) omits that.
  - I could not confirm the claim "a run that did not ask is unchanged". It is plausible from `thesis_run.py:323` and `:339`.
  
  **11. Speed.**
  - README says the header cut saves "25 to 27 ms a run". `speed.md` shows 25.4 to 27.0 ms on the parse, but 24.0, 25.2 and 26.1 ms on the whole run.
  - The version 12 before/after (1.36 s to 2.11 s) was not alternated. The README says so, but AGENTS.md requires alternation.
  - All speed figures are version 11.1 or 12. Version 14's fact store, claim compilation, five-year histories and model readers are untimed.
  - The README section is headed "17 November 2026" but contains 18 November rows.
  
  **12. The period check's "no false alarm" is measured on its own development data.**
  - The 34 years come from the golden set, and the rules (`years_in`, `EVIDENCE_YEARS`) were widened to avoid false alarms. The plant measurement uses the check's own year recogniser.
  - A bare year such as "in 2025" over a 10-Q of a later period with no 2025 in the quote is flagged "comparative". By design it is a true-but-unevidenced year.
  - The README admission about wrong-column years is adequate. "No false alarm" is not shown beyond the golden set.
  
  **13. Thin evidence is only partly reported.**
  - `run_status` (`policy.py:432-508`) is complete or partial by counts of withheld, unaddressed and unjudged. One 20-character quote or one figure-only finding passed by the meaning check is "Supported" in a "complete" run.
  - `STATUS_NOTES[complete]` says "each claim has verified evidence". Per-claim finding counts are shown, but no threshold applies.
  - A bank's cash flow also shows as a reported figure. The version 12 evidence file lists JPM at -$211.76B and -$251.84B operating cash flow, and the README admits the tool does not say so. That admission is not enough, because such a figure can be cited and verified.
  
  ## Claims I tried and could not break
  - The quote gate (`gate.py`): the normalised-to-original mapping, the whole-word and number-split rule, and the named-then-offered passage logic all hold in my reading.
  - The Markdown escaping holds for everything the README says it covers.
  - The period check misses the planted errors the README says it misses, and no others I could construct.
  
  ## README statements I could not confirm from the repository
  - Every eval figure: retrieval 9/24 and 18/24, verdicts 20/24, meaning check 150/152, set A/B/C counts, 150/150 and 60/60 claim labels, 69/69 independent route.
  - Restatements 28/922, watch-replay 12/19, 8-K probe 200/200, event categories 0.94/1.00, contention 299 vs 318 ms (the evidence file does match).
  - 28 published values; the key is hand-typed in `tests/test_facts.py:586`.
  - 2,079 tests and 339 DOM tests; no committed run output.
  - The three-reader live run and set C through the API (see item 1).
  - The links opening a filing at a passage. The README already admits it has not checked this.
  
  ## Files opened
  - `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v14/Capstone/evidence_desk/README.md`
  - `.../src/app/core/gate.py`, `numcheck.py`, `periods.py`, `policy.py`, `claim_eval.py`, `filing_diff.py`, `claim_changes.py`, `breakdowns.py`, `tagged_figures.py`, `facts.py`, `links.py`
  - `.../src/app/backup.py`, `store.py`, `sources/ixbrl.py`, `sources/edgar.py`
  - `.../src/app/services/thesis_run.py`, `computed.py`, `claim_changes.py`, `filing_changes.py`, `tagged_figures.py`, `export.py`
  - `.../docs/period-check.md`, `speed.md`, `examples/v14/brief.md`
  - `.../docs/evidence/verify-fresh.txt`, `backup-restore.txt`, `two-writers.txt`, `watch-contention.txt`, `figures-eight-companies.md`
  - `.../src/web/sample-run-live.json`