# EE292M Work Log

## Week 9B (session of 18 November 2026)

*Written on 17 November 2026, the day before the session, in the catch-up sprint. This log is drafted by the Claude Code session that did the work; the decisions are mine to check. Nothing here is about the lecture: it had not happened when this was written, and its slides are not in the repository.*

**The new version, tag `capstone-v6`: what changed between two filings**

- The last milestone of the plan. For one ticker it compares the latest annual report with the one before it (or the latest quarterly report with the previous one), Item by Item. Each paragraph of the later filing is unchanged, changed only in its numbers, reworded, or added; each paragraph of the earlier one with no counterpart is removed.
- Every listed paragraph is an exact span of the stored text with a link into its own filing. A reworded pair shows its changed words: added words underlined, removed words struck through.
- Three ways in: `make changes ARGS="NVDA --form 10-K"`, the route `GET /api/companies/{ticker}/changes`, and a third action on the page beside the thesis and the reported figures. `?sample=changes` shows a recorded comparison without the network.
- No model is involved in this feature.

**Measured, on filings fetched live on 17 November**

| Annual reports | Unchanged | Numbers only | Reworded | Added | Removed |
| --- | ---: | ---: | ---: | ---: | ---: |
| NVIDIA, fiscal 2026 against fiscal 2025 | 606 | 417 | 218 | 133 | 132 |
| of which Item 1A, Risk Factors | 139 | 1 | 51 | 34 | 22 |

- The same command on seven more companies (Apple, Microsoft, Coca-Cola, JPMorgan, Tesla, Costco, Amazon) ran on six at once and on JPMorgan after a fix (below), and matched every Item of one report to its Item in the other. The rows are in `Capstone/evidence_desk/docs/evidence/changes-eight-companies.md`.
- The gate from a fresh clone: 1,094 offline tests, the smoke test, 69 assertions on the rendered page. The live walk now also compares NVIDIA's two annual reports through the running app.

**How it was tested**

- The plan's exit check is a test: one planted paragraph comes back as exactly one added and one removed.
- Breaking the one threshold on purpose (0.5 to 0.0) failed 14 tests. Restored, they pass.
- The recorded sample has tests that damage a copy in eight ways (a wrong total, a missing paragraph, a link into the wrong filing, a lost changed word) and expect each to be reported.

**What went wrong**

- **Tested on one company, again.** `AGENTS.md` lists this as a mistake made more than once. The threshold was set and the feature finished on NVIDIA alone. Running the other seven took under a minute and found that JPMorgan could not be compared at all: it files so often that EDGAR's recent index held only one annual report. Fixed with ten tests written first: the index's older pages are now read, newest first, at most twelve.
- **JPMorgan's Item labels mean little.** 6,460 of the 7,253 paragraphs of its later report sit under "Item 15", because the bank's annual report follows its last Item heading. The paragraphs compared are the right ones; the Item named beside them is not where a reader would look. "Item coverage" of 99.4% cannot see this.
- **The threshold was set by a model's reading.** At 0.6 many "added" paragraphs had a twin among the "removed". It went to 0.5 after the pairs near it were read on two NVIDIA comparisons, by the session and not by a person. On the other seven companies nobody has read anything.
- **The page tests were written after the view.** They passed at once, which shows nothing. The view was then broken in eight places and all nine failed. The check was made; the order was wrong.
- **A layout fault no test could see.** At phone width the column headings broke inside a word. It was found by looking at the screenshot. Fixed; still no test for layout.
- **"Moved numbers" is met only as a count.** The plan promised them. A paragraph whose numbers alone changed is counted and not listed, and table rows are counted apart and never compared cell by cell.
- The candidate index that was meant to make the comparison fast saves about 5%. Reported as measured.

**Status**

Version 6. All six milestones of the plan have a tag. What that does not mean:

- No person has read the thirty golden cases, the code, or one filing comparison.
- The model path has not run through the API since October: both keys were refused for lack of credit, and every model answer here is a recording made by a stand-in.
- No colleague has reviewed this, and my reviews of colleagues are still owed.
- The link that opens a filing at a passage has never been clicked in a real browser.

**To the draft, due 30 November**

A proposed order, mine to change. The outline is `Capstone/evidence_desk/docs/draft-outline.md`.

1. Read the thirty golden cases and correct them; re-run `make eval`. Every evaluation number depends on this.
2. Rotate the API key that was pasted into a conversation; get credit; record the cassettes again through the API.
3. Use the tool on a thesis of my own and write down where it was wrong.
4. Read five reworded pairs and five added paragraphs for a company other than NVIDIA, and say whether the classes hold.
5. Ask a colleague to review it, and review theirs.
6. Write the draft from the outline, with the results table as it then stands.

**Takeaway**

Everything that passed on NVIDIA passed. The failure was one command away on a different company, and the instruction to run that command was already written down. A rule in a file did not get it run until the documents had already been written around one company.
