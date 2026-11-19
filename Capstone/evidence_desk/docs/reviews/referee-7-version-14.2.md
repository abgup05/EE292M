# Referee 7: a hostile reading of version 14.2's analysis

- **Why:** the sixth referee's brief predated version 12, so it read the older checks and opened none of what versions 12 to 14.2 added. The brief was extended to name those claims (commit `5ef601d`) and the referee run again.
- **Reviewed:** commit `5ef601d` on `capstone/evidence-desk`: the code of tag `capstone-v14.2` with the documents answering the sixth referee and the extended brief; no code differs from the tag. From a git worktree of that commit with `Work Logs/`, `Homework/`, `Capstone/evidence_desk/docs/reviews/` and the six triage files under `docs/` deleted before the referee started. Deleting `Homework/` also removed the public site's code, which lives under it, so the referee could not read the site's guard and says so.
- **Referee:** the `referee` agent defined in `.claude/agents/referee.md`, started with `make -s referee` from the root of that worktree: a fresh headless Claude Code session that uses the agent by name. Model: Claude Sonnet 5.5, which did not write the code of version 14.2 but is one of the app's two model readers of claims. Tools limited by the agent definition to Read, Grep and Glob; it ran no commands. Cost of the session: $2.65. It is another Claude model, not an independent party.
- **Run on:** 19 November 2026 (UTC). The session that started it was told to return the referee's findings exactly as written; the text below is what it returned, unedited.
- **Checks made afterwards:** no file in the checkout is newer than the marker written before the referee started.

The triage of every finding is in [`../referee-7-triage.md`](../referee-7-triage.md).

---

I opened the code and docs listed below. I had no shell, so I ran nothing: every finding comes from reading, and each "how to show it" is a test or input I did not execute. I did not read the site guard, `src/live/guard.py`: it sits under `Homework/Week 2/`, which my brief excluded, so the guard and banner claims are unchecked.

## Findings, worst first

**1. The argument audit's "verified" is weaker than the page says, and the exceptions are not stated on the page or the record.**
- File and lines: `src/app/core/analysis_audit.py` 179-266, `src/web/app.js` 7737, `src/app/core/analysis_audit.py` docstring lines 12-14.
- The page says: "Verified by code: … every number it writes is carried by something it cites." In `audit_sentence`, the number sources are the `excerpts` of every cited item that is a real id, and three kinds of item put non-evidence text into that pool.
  - **A cited claim id.** `Citable("claim", False, (claim.text,))` puts the user's own claim text in the pool. A sentence citing `["c1", <any finding>]` may write the claim's threshold as if it were a fact. "Gross margin was 70%" passes when c1 reads "above 70%". The README tells the reader that restating a threshold is flagged; citing the claim silences the flag.
  - **A corollary.** `texts = [corollary.sentence, corollary.result_label]`. The sentence is model-written (step `propose`), so a model can invent a threshold in a corollary and then cite it in the argument to carry the number.
  - **A condition's own threshold.** The model sets it, and any number in the sentence that equals it passes.
- The docstring says the threshold exception is "stated on the record". I found no such wording in `analysis_policy.py` or `app.js`, so the inspector shows "Verified by code" without the carve-out.
- The bare-year exemption (`raw.strip() not in carried`) also excuses any unmatched number whose raw text equals a cited year string. "2020 customers" passes if any cited item is dated 2020.
- To show it:
  - Build `KNOWN` as in `tests/test_relevance_audit.py`, with `c1 = Citable("claim", False, ("Gross margin is above 70%.",))`.
  - Run `audit_sentence(ArgSentence(text="Gross margin was 70%.", cites=["an:x","c1"]), ...)` and `.verified` comes out True.
  - Repeat with a corollary whose `sentence` contains "80%".
- The tests cover only a claim cited alone and a bare year. The README's "105 of 109 verified" figures count these passes.

**2. The price the market view uses is not shown to be a closing price, and "confirmed" is never enforced.**
- File and lines: `src/app/sources/thirteenf.py` 260-321, `src/app/core/thirteenf.py`, `docs/market-view.md` lines 57-59.
- The README says "the quarter-end close that Form 13F filings imply, confirmed by a second manager's filing".
- The code takes the first manager that name-matches and uses its price even when the other manager's price differs. `Price.confirmed` is set but read nowhere in `src/app`.
- A differing or unconfirmed price therefore still feeds P/E, FCF yield and the reverse DCF. The only warning is a sentence in `price.note`.
- 13F value is whatever valuation the manager (or its custodian) used. The code assumes it is the day's close.
- The doc admits the only check against an exchange close was "as I remember them", and the README does not carry that caveat.
- Matching is by issuer name only. A matched single CUSIP can be a preferred or other non-common security of the same name.
- To show it: feed `QuarterEndPrices` two tables whose prices differ by 10%. `price()` returns the first with `confirmed=False`, and `market_view` still computes everything from it.

**3. A replayed run's "who wrote it" describes the whole cassette, not the answers that run used.**
- File and lines: `src/app/engines/cassette.py` 159-161 and 262-294, `src/app/services/analysis.py` 683 and 832.
- `analysis.corollaries_by` and `argument_detail` are `analyser.detail`, which is `Cassette(directory).describe()`.
- That string lists the vias, models and dates of every response in the directory.
- The README says `demo/cassettes/nvda-example` mixes 12 stand-in answers with 14 recorded through the API. A replay of it therefore carries one blended "via … with …" line. It cannot say that the argument was written by the API model while the findings came from the stand-in.
- The README's own rule is "never report a model-backed result without saying where the answers came from". The attribution is per directory, not per request.
- I did not trace where the finding-level `assessed_by` is set, so check it.

**4. "Complete" and thin evidence.**
- File and lines: `src/app/core/policy.py` 28-31, 393-443, 463-539.
- The complete note says "each claim has verified evidence".
- A claim whose only support is a computed test (one grammar reader, or two models) gets verdict "supported" from `claim_verdict`. It has no finding and no quote, and it raises no reason in `run_status`.
- A finding the meaning check marked "partly supported" counts in full, so a single short quote can produce "Supported" in a run marked complete. The README admits this, and says 10 of 13 findings in the first live sample were "partly". Disclosing it does not make "no model-asserted verdict without verified evidence" hold in spirit, because the verdict does not distinguish them.
- Per-claim finding and filing counts exist, but nothing gates or flags a verdict resting on one quote.
- To show it, use the claim-test fixture:
  - Compile "Gross margin is above 70%" with no findings.
  - `claim_verdict([], computed_holds)` returns `supported`.
  - `run_status` returns `complete` if nothing else is withheld.

**5. Reverse DCF.**
- File and lines: `src/app/services/market_view.py` 153-177, `src/app/core/reverse_dcf.py` 100-129.
- The margin is `income.value / revenue.value`. Each comes from `trailing()`, which falls back from four quarters to the fiscal year separately.
- Revenue can be a four-quarter sum while operating income is a fiscal-year figure, giving a mixed-basis margin that the "trailing operating margin" assumption line never mentions.
- `implied_growth` returns the first sign change scanning from -50% upward. When growth and value are not monotonic, a second root is silently ignored. The note appears only when return on new capital is below the discount rate.
- The target is enterprise value, and non-current securities and leases are excluded (documented). A reader told "reproduces the market value" does not get a market value back.

**6. Base-rate class definition.**
- File and lines: `src/app/core/base_rates.py` 21-24, 369-380.
- The module claims the class is decided in the base year, "keeping the outcome out of the class".
- The base year is `year - test.reach`, so for a level test (reach 0, such as "revenue above $X") the base year is the outcome year.
- The class floor is a revenue floor. For a revenue-level claim the class is chosen on the outcome variable.
- To show it, run `base_rate` with a revenue-level test: `held` equals `computable` by construction for any floor above the threshold.
- The industry class uses today's SIC code (disclosed). Persistence counts only survivors that are computable in t+1 (disclosed).

**7. Persistence arithmetic with non-positive values.**
- File and lines: `src/app/core/persistence.py` 62-72, 105-109.
- For a flow or instant measure the step is `value * (1 + change)`.
- A negative start (a loss) moves the wrong way: growth makes it more negative. A year-earlier base of zero or less returns False for the path.
- Changes are drawn only where `older > 0`.
- The result "% of paths where the test holds" is then not what the stated method gives for loss-making companies. No guard or note covers it.

**8. Markdown export treats only `\n` as a line break.**
- File and lines: `src/app/services/export.py` 114-129, versus line 161.
- Excerpts go through `splitlines()` in the blockquote. `_text()` for statements, rationales and notes uses `partition("\n")` and a `^` pattern with `re.MULTILINE`, which matches only after `\n`.
- CommonMark ends a line at a bare `\r`, so `"ok\r# Heading"` in a model statement would start a heading in a viewer.
- I did not run this. Test it with a finding statement of `"a\r# injected\r- item"`.
- GitHub-style `$…$` math is not escaped either; the README does not claim it.

**9. The restore check's BEHIND excuse and its limits.**
- File and lines: `src/app/backup.py` 330-386, 420-466.
- A live row that differs from the backup is excused when its `decided_at`, `updated_at` or `read_at` is after the backup's filename timestamp. That timestamp comes from the filename, not the file.
- A backup row corrupted for a table with a changed column cannot be told from a legitimate later edit, if the live row was touched afterwards.
- Runs and theses have no changed column. A run that was still `running` at backup time and finished later gives FAIL, not BEHIND. The README says "only behind gives BEHIND".
- `unreadable()` is checked on the backup only, not on the live record. A record the live app already cannot parse is copied and compared as identical, so it PASSes.
- No integrity check beyond the checksum written at backup time.

**10. Period check.**
- File and lines: `src/app/core/periods.py` 459-476.
- "Evidence" for a year includes any year printed anywhere in any quote (`years_in`, deliberately generous), so a wrong-column year passes (the README admits 4 of 25 and 5 of 18). The admission is sufficient on that point.
- The calendar comes from the newest annual report in the facts. A company that changes its fiscal label convention mid-history would get false alarms or false passes. I found no test of that.

**11. Number check gaps not listed in the README.**
- File and lines: `src/app/core/numcheck.py` 374-420.
- "$1.2tn" and "$3tn" are skipped entirely. After the digits the `tn` letters are alphanumeric, so `_read` returns None, and a wrong "$1.2tn" figure is never checked.
- "$46.7 bn" with a space reads as 46.7 dollars (no scale) and can match a bare "46.7" table cell. The same text fails against "$46.7 billion".
- Documented gaps (bare integers 12 and under, 4-digit numbers after "by", "for", "of", "in", scale by 1e3/1e6/1e9) are real and the admission is adequate.

**12. Docs that contradict each other or the code.**
- `docs/analysis.md` "Not verified" says the argument "has not" been answered by a model and was exercised only with a fake transport. The README says two live runs wrote 105 and 92 sentences. The doc is stale.
- The README says "A model call has never been timed", and also quotes two live model runs at 123 and 126 seconds.
- The README speed row: I cross-checked its figures against `docs/speed.md` (1,160 ms and 326 ms, 57 to 59% waiting on EDGAR, 25.4 to 27.0 ms and 24.0 to 26.1 ms, 20 of 20 pairs) and they match the tables. They are version 11.1 numbers and the README says so, but "Speed" in the results table for a 14.2 release carries no current timing without a key.

## The public site guard (`docs/site-live.md`)

I could not read `src/live/guard.py`, so I cannot confirm that the caps, refused writes and addresses cannot be gone round, or that nothing there returns a secret. From the doc alone:
- Caps are per serverless instance and in memory. A visitor reaching several instances, or waiting for a recycle, exceeds every cap, and the doc says so. The only hard limit it names is a spend limit in the Anthropic console. That is the real control, and it is not something the code enforces. The admission is honest but insufficient as a guard: with the key set, "20 model runs a day" is a per-instance figure.
- "Other visitors of the same instance see the same runs and saved theses." Any visitor can read another visitor's decision and claims and set a watch on their thesis. Whether the banner says this I cannot tell. The doc's banner list says only "runs are not kept".
- "Under the emulation all 14 versions run live" and the Vercel results are claims about runs I could not see.

## README statements I could not confirm from the repository

- The test counts: 2,568 offline tests, 573 assertions with 2 skipped, 337 DOM tests. `grep` finds 1,599 `def test_` in `tests/test_*.py`, so the total depends on parametrisation, which I did not count.
- The lookahead harness results (138, 140 and 136 dates).
- The live-run figures: the 105/101 and 92/85 sentence counts, 123 s and 126 s, the NVIDIA 8-K counts, the restatement counts, the 13F price ($134.29 for 31 December 2024).
- The golden-set and compiler measurements (150 of 150, 60 of 60, set A, B and C).
- "Restore check: 43 runs, 20 decisions, 10 theses". That is a snapshot of a gitignored record.
- The banner's wording and the Vercel behaviour (cold start, the forwarding header, a run with a key).

## Admissions that are sufficient and ones that are not

- **Sufficient:** the flattened-table number gap, the period check's blind spot for comparison columns, the 13F price being up to four and a half months old, and "complete is not a measure of evidence".
- **Insufficient:** "partly supported counts in full". It changes a verdict, not just a display.
- **Insufficient:** the per-instance caps, for the reason above.
- **Missing:** the audit's number sources (finding 1) are not on the page or the record.
- **Missing:** the cassette-wide attribution (finding 3).

## Files opened

- `Capstone/evidence_desk/src/app/core/` (gate, numcheck, analysis_audit, analysis_models, policy, frames, base_rates, peers, reverse_dcf, valuation, thirteenf, persistence, periods, events, filing_diff)
- `Capstone/evidence_desk/src/app/services/` (analysis, computed, market_view, export; plus greps of thesis_run, ingest)
- `Capstone/evidence_desk/src/app/sources/` (edgar, prices, thirteenf)
- `Capstone/evidence_desk/src/app/engines/cassette.py`
- `Capstone/evidence_desk/src/app/backup.py`
- `Capstone/evidence_desk/src/app/store.py`, `Capstone/evidence_desk/src/web/app.js`
- `Capstone/evidence_desk/tests/test_relevance_audit.py`
- `Capstone/evidence_desk/docs/` (analysis, market-view, speed)
- `docs/site-live.md`
