# Referee 2: a hostile reading of version 6

- **Why:** the last milestone, the filing comparison, was tagged without any review. This was run before the session of 18 November for that reason; it is not a hands-on of a lecture.
- **Reviewed:** commit `a79cf92`: tag `capstone-v6` plus three later commits that change no code (a work log, the draft outline with a note in the evaluation README, and one added line in the referee's own brief naming the comparison's claim). From a git worktree of that commit with `Work Logs/`, `Homework/`, `Capstone/evidence_desk/docs/reviews/` and `Capstone/evidence_desk/docs/referee-triage.md` deleted before the referee started, so the author's notes, the earlier reviews and the triage of the first referee were not there to read. Two of its remarks (a deleted link to the triage, "uncommitted deletions") are about that preparation, not about the repository.
- **Referee:** the `referee` agent defined in `.claude/agents/referee.md`, started by name in a fresh headless Claude Code session with the same sentence as the first time ("Use the referee agent on this repository"). Model: Claude Sonnet 5.5, which did not write the code. Its tools were limited by the agent definition to Read, Grep and Glob. It is another Claude model, not an independent party.
- **Run on:** 17 November 2026. The session that started it was told to return the referee's findings exactly as written, with nothing added and nothing removed; the text below is what that session returned.
- **Checks made afterwards:** no file in the checkout was changed after the referee started. Every file in its closing list is inside the checkout. That list is incomplete: its findings cite lines in `core/text.py`, `core/limits.py`, `core/links.py`, `services/thesis_run.py`, `tests/test_filing_diff.py` and `tests/test_filing_changes.py`, which the list does not name.

The triage of every finding, accept with a fix or reject with a reason, is in [`../referee-2-triage.md`](../referee-2-triage.md).

---

I found no hard failure of any claim by reading the code. I could not execute anything: this session had Read, Grep and Glob only, so no tests, no `make` target and no EDGAR fetch were run. Every finding below comes from opening the files, and the "how to show it" lines are things you can run.

Version 6's central claim (every listed paragraph is an exact span, sits in its class, and is counted truly) holds for the span identity. It fails on the labelling of the counts and on what the classes can see.

## Findings, worst first

**1. The comparison's "paragraphs" columns mix denominators.**
- `core/filing_diff.py:358-359` and `:386-387`. Passes 1 and 2 (unchanged, numbers-only) consume every line, including short lines and table rows. Only `added`, `removed` and `reworded` are restricted to lines of 60+ characters that are not table rows. Rows and short lines left over go to `minor_*`.
- The README table (lines 163-167) and `changes.py:177` ("Paragraphs by Item") head all five columns "Paragraphs", which is false for the first two.
- The README's JPMorgan figure is wrong in its denominator. "6,460 of 7,253 paragraphs sit under Item 15" equals 2886+2726+586+262 over 3133+2815+848+457, from `docs/evidence/changes-eight-companies.md`. Both leave out `minor_added` (733 and 845). The later report has 8,098 lines and Item 15 holds 7,193 (88.8%). This is the "count that survives a failure upstream" mistake the project's own AGENTS.md warns about.
- NVIDIA's 417 numbers-only lines include 416 outside Item 1A. They are mostly financial-statement rows and figure-only lines, not prose "paragraphs".
- To show it: assert, for one Item, that `unchanged + numbers_only + reworded + added + minor_added` equals the later filing's line count. That holds. Then show that `unchanged` and `numbers_only` count table rows while `added` does not.
- The README never says which lines each column counts. The admission in `docs/filing-changes.md` (a short-lines column) is not enough, because the README table omits that column.

**2. Sub-headings are invisible to the comparison, so some real changes read as "unchanged".**
- `sources/filing.py:428-433` turns a short bold line (under 140 characters, no trailing period) into a section heading and does not add it to the section text. `filing_diff.py:303-319` compares only `section.text` lines and groups by the Item part of the heading.
- A risk-factor headline that is bold and has no full stop is therefore never counted, listed or compared. Reword or delete such a headline over an identical body and the Item shows no change.
- A body paragraph moved under a different headline is "unchanged" (matched across the whole Item, ignoring locator).
- Whether a headline is a heading or a line depends on typography and neighbouring lines, so the same kind of content is compared in one company and skipped in another.
- To show it: a pair of tiny HTML 10-Ks that differ only in one bold headline. I expect `diff_documents` to return all zeros except `unchanged`. The existing tests use synthetic `Document`s built without this parser path.

**3. The numbers-only class hides material number changes, and the README meets "moved numbers" only as a count.**
- `filing_diff.py:83-86`. Every number, date and amount is masked, so "customers over 10% of revenue" against "customers over 50%" is numbers-only: counted, never listed, with no figure shown anywhere.
- "Item 1A" against "Item 7A" also collapses (`#a` against `#a`).
- Any line made only of numbers matches any other such line. The README admits the count-only limit (README line 32). The admission is adequate for the plan row but not for the headline table, which presents 417 as a result.

**4. "Every listed paragraph is an exact span" holds in the record but not in the two renderings a reader sees.**
- `changes.py:66-68`. `escape` collapses whitespace and backslash-escapes, so the exported Markdown text is not byte-exact. The reworded entries (`changes.py:118-139`, `web/app.js:1112-1120`) are rebuilt from `segments` (`split()` then `join`), with removed and added words interleaved.
- Exactness is tested on synthetic documents (`tests/test_filing_diff.py:337`). On a real parsed filing it is tested for one added paragraph (`tests/test_filing_changes.py:102`). The "recorded annual report compared with itself" test lists nothing, so it checks no span.
- Removed and reworded spans have no real-filing test, and the committed sample record has no filing text to check against.

**5. The reworded threshold has no measured error rate and is tuned on one company.**
- `filing_diff.py:67`, `docs/filing-changes.md:24-31`. The method read the pairs each candidate value added, on NVIDIA only, and a model did the reading. Seven other companies ran with no classification read. There is no precision or recall anywhere.
- The stop-word list (`core/text.py:14-24`) includes "not", "no", "may", "could", "will", "down", "up" and "more". A paragraph that flips "could" to "will" or drops "not" scores similarity 1.0 and is shown as "reworded". Likewise 0.5 Jaccard on content words does not exclude two different templated risk factors.
- The README admits this (line 169, line 207). The admission is sufficient for the threshold but not for the table: the "reworded" column reads as a measurement.

**6. A verdict needs a verified quote, but "verified" means only "present and 20 to 600 characters long".**
- `core/gate.py:322-351`, `limits.py:32`. Nothing ties the quote to the statement beyond the number check. A `supports` finding whose statement has no number and whose quote is any 20-character span of an offered passage is verified.
- `policy.py:156-167`: confidence is ignored.
- Only the second model, a later and optional step, tests relevance. If it errors, the run is still COMPLETE with the findings unchecked (`thesis_run.py:332-334`, `policy.py:140-147`, which says "status is unaffected").
- A figure-only finding counts toward a verdict once a second model of the same family agrees. That is a verdict asserted by models on stated figures with no quote.
- To show it: feed `gate_claim` a draft with statement "Demand is collapsing", stance `supports`, and an arbitrary 25-character quote. It will be verified and `claim_verdict` returns `supported`. The README admits this (lines 5, 134, 198). The admission is not enough because the status stays COMPLETE.

**7. The number check lets a wrong direction through.**
- `numcheck.py:382-405`. An unsigned statement number matches a positive source whatever the statement's verb says. "Revenue fell 56%" against "up 56%" passes.
- The opposite case is checked, but `NEGATIVE_WORDS` (`:76-115`) includes "paid", "purchases", "expense", "down" and "lower". "Operating expenses grew 3%" matches a source "(3)%".
- Other gaps: bare integers 0-12 and numbers written as words are exempt (`:301`), a bare table number rescales by 1e3, 1e6 or 1e9 (`:408-419`), and the masks drop a number after a capitalised "Note", "Phase" or "Level".
- The README's wording "every number in a finding is in its quotes or its cited figures" is literally true but promises more than it checks. The caveat on line 202 does not name the direction hole.

**8. A run with thin evidence can say COMPLETE.**
- `policy.py:222-282`. Complete requires only: sources read, no withheld finding, no unaddressed or unjudged claim, no engine fallback, no time limit. It does not look at how many passages or sources supported a verdict, or at a 20-character lone quote.
- Retrieval puts the key passage in the top 8 in 18 of 24 golden cases, and the verdict agrees with the expected stance in 20 of 24 (README lines 148-149, 199). A claim judged on weaker evidence still gets a verdict, and no signal reaches the status.
- The "partial when thin" promise covers only an empty result. Line 199 admits retrieval can hide the passage, but it offers no run-level signal.

**9. The model path is not exercised.**
- README line 26 says that with `ANTHROPIC_API_KEY` Claude plans, drafts and summarises. Line 197 admits the API path has not run since version 1.
- Every model-backed number (the recorded run, the golden-set generation scores) comes from Claude Code subagents through a cassette. The stub clients do not exercise the SDK call.
- "Run it" states the capability as fact. Line 197 is the real status and should sit next to line 26.

**10. A speed sentence contradicts the project's own file.**
- README line 175 says the header cut is "well under 1% of a live one". `docs/speed.md:97-98` says "about 3% of the keyless path". The README's own measurement (1.01 s live) gives 28.8 ms / 1010 ms = 2.9%. The claim is wrong as written.
- The paired-run IQR spans roughly −8.6 to 93 ms, and the repeat bench gave 37.9 ms. The README states the median with no spread.

## Smaller points
- `filing_diff.py:386-387`. A line of 59 characters in one filing and 61 in the other becomes "minor removed" plus "added", so an added paragraph can have a real earlier counterpart. The same applies when one side is a table row. The same split exists in `links.py:58-76`, which uses a different table-row rule from the diff, so a listed paragraph can get a plain URL while the page labels it "at this paragraph".
- "Items in both 23 of 23" (`docs/filing-changes.md:59-66`, README line 169) counts the Cover page as an Item. The probe shows 22 Items for NVIDIA.
- `docs/evidence/changes-eight-companies.md` records only the Item 1A and Total rows. It does not show per-Item presence, so "every Item matched" and "no coverage note on any run" cannot be checked from the repository.
- The `Paragraph.link` for the filing comparison has no link-kind field, so the page cannot say when a link has no fragment.
- `docs/evidence/verify-fresh.txt` records the gate at commit `cad269a`. HEAD is `a79cf92` and the working tree has uncommitted deletions.

## README statements I could not confirm from the repository
- The live NVIDIA table (606 / 417 / 218 / 133 / 132, plus the 10-Q row) and the seven other companies' rows. They need EDGAR as of 17 November. The totals rows are in the evidence file, but not the underlying filings.
- The OpenAI risk factor and the rescinded export rule, which are claims about outside facts.
- The model identities ("Sonnet 5.5", "Haiku 5.5"), which are self-reported by subagents in the cassette README. The 28 answer-key values are hand-entered, so I cannot tell how independent they are of the fixture data.
- The link to `docs/referee-triage.md` is deleted in this working tree.
- Not run: the 1,094 tests, `make probe` and `make live-walk`. Only the 14-filing probe output and the committed gate output were read, not reproduced.
- Not read: the Items-found percentages (`docs/speed/probe-v4.md`) match README line 159, but not Item boundaries (the README says so itself).

## Files opened
- `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v6/Capstone/evidence_desk/src/app/core/filing_diff.py`
- `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v6/Capstone/evidence_desk/src/app/core/gate.py`
- `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v6/Capstone/evidence_desk/src/app/core/numcheck.py`
- `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v6/Capstone/evidence_desk/src/app/core/policy.py`
- `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v6/Capstone/evidence_desk/src/app/sources/filing.py`
- `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v6/Capstone/evidence_desk/src/app/changes.py`
- `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v6/Capstone/evidence_desk/src/web/app.js`
- `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v6/Capstone/evidence_desk/README.md`
- `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v6/Capstone/evidence_desk/docs/filing-changes.md`
- `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v6/Capstone/evidence_desk/docs/evidence/changes-eight-companies.md`
- `/Users/abgup/Documents/Code/EE292M/.claude/worktrees/referee-v6/Capstone/evidence_desk/docs/speed.md`
