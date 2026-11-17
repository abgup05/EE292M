# Referee 3: a hostile reading of version 9

- **Why:** versions 8 and 9 added two features (the changed paragraphs listed under each claim, and the tagged breakdowns) and neither had been read by anyone but its builders.
- **Reviewed:** tag `capstone-v9` (commit `8d57e42`), from a git worktree of that commit with `Work Logs/`, `Homework/`, `Capstone/evidence_desk/docs/reviews/` and both triage files deleted before the referee started.
- **Referee:** the `referee` agent defined in `.claude/agents/referee.md` (its brief had gained two lines naming the new features' claims), started with `make -s referee` from the root of that worktree: a fresh headless Claude Code session that uses the agent by name. Model: Claude Sonnet 5.5, which did not write the code. Tools limited by the agent definition to Read, Grep and Glob. It is another Claude model, not an independent party.
- **Run on:** 17 November 2026. The session that started it was told to return the referee's findings exactly as written; the text below is what that session returned.
- **Checks made afterwards:** no file in the checkout was changed after the referee started. This time the referee did not close with a list of the files it opened; every path it cites is inside the checkout.

The triage of every finding is in [`../referee-3-triage.md`](../referee-3-triage.md).

---

I could not execute anything: this session had only read and search tools, so no test, make target or input was run. Every finding below comes from reading the code and the committed outputs. Each "how to show it" is a test or input I expect to fail the claim, but none has been run.

## Findings, worst first

**1. "When the evidence is thin the brief says partial" is false as the project words it.**
- `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v9/Capstone/README.md:5` promises this without qualification.
- `core/policy.py:248-295` (`run_status`) is the rule that decides status. It has no threshold on quotes, filings or retrieval quality. `policy.py:26-28` tells the reader of a COMPLETE run "Every claim has verified evidence".
- A claim judged `supported` on one 20-character quote from one filing gives `complete`. So does a claim where retrieval missed the key passage. The README's own figure is 6 of 24 golden cases judged on weaker evidence.
- A shortfall in filings is also not partial. `services/ingest.py:128-132` only adds a coverage-limit line when EDGAR lists fewer filings than asked. `sources_requested` then shrinks to match (`ingest.py:157`), so `filings=5` with 3 listed still reads COMPLETE.
- The admission in the evidence_desk README ("Complete is not a measure of evidence") is not sufficient. The Capstone README headline, the status banner and the status note all still say otherwise.
- To show it: run `filings=1` with a stub engine returning one 20-character quote per claim. Assert `status == complete`.

**2. "Every number in a finding is in its quotes or cited figures" has three holes, none in the README's blind-spot list.** All are in `core/numcheck.py`.
- **Years and fiscal labels are never checked.**
  - Masks are at `numcheck.py:145-146`. The year exemption is `_is_year` (254) and `_read` (314-315).
  - Statement "Revenue was $130,497 million in fiscal 2023" against a quote that says fiscal 2025 passes.
  - Period misattribution is the commonest error in finance, and the README's list of blind spots omits it.
- **A bare integer in a quote matches a dollar amount in the statement.**
  - `_COMPATIBLE` (388-393) lets `plain` match `usd`. `rescalable` (432) and `TABLE_SCALES` (73, 415) then multiply by 1e3, 1e6 and 1e9.
  - Statement "$46 million of revenue" against a quote containing "46 customers" passes. "$130 million" against "130 countries" does too.
- **Any decline word anywhere in the sentence lets an unsigned percentage match a negative source.**
  - See `numcheck.py:497` and `_matches` 421-423.
  - "Revenue grew 3% while gross margin fell" passes against "(3)%".
  - `test_numcheck.py:275-279` only tests the decline word in a *different* sentence. This case has no test.
- The same check also guards rationales, commentary and summaries, so those inherit all three holes.

**3. "A model cannot assert a verdict" holds for the verdict table only.**
- **Figure-only findings.**
  - `policy.py:157-168` (`counted_stance`): a finding with no quote counts as its stance whenever `checks.support == "passed"`.
  - That value is set by a second model. The gate (`gate.py:411`, `_cited_figures`) only checks that the figure id was offered.
  - So two models can produce `supported` or `challenged` with no excerpt, on any offered figure. The README's China case is an instance.
- **The stance on a real quote is never verified.** Only the second model and the user check it.
- **The brief's summary can state a verdict.**
  - `thesis_run.py:458-467` checks only its numbers. Its prose can say "claim 2 is supported" while the table says Challenged.
  - The summary is labelled "model", but the prose is unchecked against the verdicts.
- To show it: a stub engine returning a summary that contradicts a claim's verdict. The run records it as `summary_origin="model"`.

**4. Changes under a claim: wrong wording about what matched, and about which filings.**
- **"Shares at least two words with the claim" is false whenever the run has planner queries.**
  - `core/claim_changes.py:150-164` builds `wanted` as the union of terms from the claim and all its queries, then applies the two-term rule to that union.
  - A paragraph can pass with one claim word plus one query word, or with none from the claim.
  - The false wording appears at `src/web/app.js:2757`, `services/export.py:416`, `matched_terms`, the README item 9 and Known limitations. `docs/claim-changes.md:16` says "of the claim".
  - The "126 to 276 distinct changes share two words with each claim" figure is really words shared with claim plus queries.
  - To show it: a test with `Claim(text=..., queries=[...])` and a paragraph sharing one word with each.
- **The page says "in the filings this run read", but the earlier filing was never read.**
  - `services/claim_changes.py:112-122` and `141-146` fetch the filing before the run's newest of each form. Every "removed" paragraph comes from a filing the run did not read.
  - A run that read 10-K plus one 10-Q (`filings=2`) compares that 10-Q with the previous year's Q3 10-Q, a different quarter, with no warning. Only the export note at `export.py:357` is accurate.
- **The "never raises" promise is wider than the code.**
  - `api.py:371-382` and `claim_changes.py:160-174` say it never raises. `_compare_form` (125-157) catches only `SourceError`.
  - A `ValueError` from `filing_diff._section_starts` (295) or `_check_complete` becomes an HTTP 500 for the whole claim-changes route.

**5. The filing comparison's classes and counts are looser than stated.** `core/filing_diff.py`.
- "Unchanged" is case-folded and quote-straightened (138-139). A case-only edit is "unchanged".
- "Numbers only" masks digits (83-86), so formatting-only edits count as moved figures: "$1,000" to "$1000", "5.0" to "5". "Item 1A" becomes "item #A".
- `is_table_row` (119-126) treats an unpunctuated prose bullet ending in a digit, or with 80% capitalised words, as a table row. It is counted but never listed, and a real change disappears from the list.
- "Every line of each filing is in exactly one count" is overstated. Sub-heading lines and Part lines are in no count. The test (`test_filing_diff.py:270-280`) checks only section lines.
- The listed-paragraph tests (`test_filing_diff.py:349`, `:530`) do show that listed paragraphs are exact spans of the parser's text.
- Similarity ignores stop words, including "not", "no", "up" and "down" (`core/text.py:14-25`, `filing_diff.py:133-135`). A negation flip scores 1.0. It is still listed as reworded with the words marked, so this is not silent.
- The README admission about the threshold covers pairing, not these.

**6. Tagged breakdowns: the check is circular and several labels mislead.**
- `docs/breakdowns.md:33` concedes that the printed amount and the tagged amount are "the same characters in the same document". The answer key therefore cannot catch a wrong figure, only wrong attachment. It covers NVIDIA's 10-K only.
- "Adds up" is a search, not a sum. `core/breakdowns.py:511-577` (`_shape`, `_subset_summing_to`) tries nested-member removal, two-split detection and subset combinations over up to 16 members. The tolerance is the sum of half-units. "All 16 filings add up" is weaker evidence than it reads.
- `breakdowns.py:791` takes the first untyped no-dimension fact (`totals.setdefault`) with no conflict note. Members get `_pick` conflict notes; totals do not.
- Apple's "Revenue by business segment" lists 5 members that are, in practice, geographic segments (evidence file line 16). The title comes from the axis name.
- The README table is not tool output. The tool prints "US" and "China Including Hong Kong" (evidence lines 102 and 104); the README shows "United States" and "China including Hong Kong". It also splices product and geography rows under one "Revenue, USD millions" heading.
- The customer table puts "Customer One" in a single row across three years (evidence lines 117-118). The README says that position is not shown to be the same customer.
- The milestone row says "shown beside a run". The route `api.py:541-560` and `services/breakdowns.py:69` start no run and read the latest filing. An older saved run therefore sits beside a different filing's figures.
- `breakdowns.py:770` is an `assert kind is not None`. It can fail if the unit filter in `_only_unit` removes every usable period kind. I constructed no input for this; it would be a 500 instead of a note.

**7. "Every excerpt is an exact span of the stored filing" holds by construction. The qualifiers around "stored" are weaker than they sound.**
- The gate's identity guarantee (`gate.py:143-169`, `_within` at 256) looks sound by reading.
- The stored text is not the filing. `sources/filing.py:153` strips zero-width characters and collapses non-breaking spaces. `180-194` joins "$" and "%" to their neighbours. The README admits table flattening, not the rest.
- `services/export.py:66-67` and `87-88` replace "<" with "\<" in the raw Markdown excerpt. The export is not byte-exact.
- "Deleting the cache loses nothing" (ARCHITECTURE.md:79, README table) is false for the identity property.
  - Filing text exists only in the cache, keyed by content hash.
  - Once it is deleted, old evidence offsets cannot be re-checked unless the same parser and bs4 version reproduce the text.
  - "Rebuildable by the parser version that produced it" depends on an old parser that is no longer in the tree.

**8. Reported figures use period bands that exclude 52/53-week retailers.**
- `core/facts.py:134-139` uses quarter 80-100 days, half 170-195 and nine months 260-290.
- `core/breakdowns.py:122-131` widened its own bands because Costco's 16-week quarter and its 168-day and 252-day year-to-date periods fall outside the facts bands.
- By reading, Costco's Q4 cannot be derived and its newest quarter is wrong or absent in the metrics panel.
- The answer key covers only Apple, Microsoft and NVIDIA annuals. This is the project's own "testing on one company" mistake.
- To show it: build a `FactBook` from Costco facts and ask for `quarters("revenue")`.

**9. Some measured-result framing is unsafe.**
- The replay table (18 of 18 quotes, 25 numbers and 0 unmatched) comes from a recording whose stand-in was told to re-check each quote as an exact substring and not compute numbers (`demo/cassettes/nvda-example/README.md:20-30`). That file calls it "an upper bound". The main README table omits this.
- The README's later caution says recordings had "no reminder of the rules". That is true of the eval cassettes but not of this one.
- "Passage among the eight shown, 15 of 18" uses a rule the README never states: half of an excerpt counts (`eval/results/generation-checked-2026-11-17.md:78`).
- "About 3% of a live run" divides an offline paired median (28.8 ms) by one unpaired live run (1.01 s).

## README statements I could confirm

- **Probe coverage:** 95.8% to 98.6% for the seven companies, JPMorgan 10-Q at 1.6% (`docs/speed/probe-v4.md`).
- **Speed:** the 28.8 ms median with IQR 21.5 to 56.9 and range -8.6 to 93.0, matching `docs/speed/bench-v4.txt`. The 7% to 9% share follows from 374.6 ms and 404.5 ms in `docs/speed.md:90`.
- **Breakdowns table:** eleven of sixteen filings with two unread facts, and 593 to 7,961 facts, match `docs/evidence/breakdowns-eight-companies.md`.
- **Replay run:** the counts match `demo/recorded-run-v5.json`: 636 passages, 18 verified, 0 withheld, 25 numbers checked with 0 unmatched, 156 metrics, 1 finding without a quote.
- **Eval:** 20 of 24 verdict agreement and 3 of 70 numbers unmatched match `eval/results/generation-checked-2026-11-17.md`. The unanswerable and mismatch counts were not re-checked.
- **Filing-comparison table:** 251/60/218/133/132 matches `docs/filing-changes.md:52`, and the 802 changed paragraphs sum correctly (543 + 259).
- **Gate output:** `docs/evidence/verify-fresh.txt` records 1265 passed and 124 UI tests. I counted 849 test functions, which is plausible given parametrisation.

## README statements I could not confirm from the repository

- Every live-EDGAR number: the NVIDIA table values, the 802 and 126-276 counts, the live-walk output, and "both keys were refused for credit".
- That Sonnet 5.5 and Haiku 5.5 answered the cassette. Only the cassette's own README says so.
- "Ignoring scale failed 25 of 67 tests."
- The 1.01 s and 0.38 s live-run timings, which are one pair of runs.
- That the golden set was model-drafted and unread by a person. The README says so, and I could not check it.
- The link text fragment working in a browser. The README admits it is untested, and that admission is sufficient.
