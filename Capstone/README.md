# Evidence Desk — capstone plan

**In one sentence.** For an equity analyst who has to decide whether a thesis still holds after a new filing, Evidence Desk tests each claim in the thesis against the company's own SEC filings and reported numbers, and we will know it works because every verdict opens to exact filing passages or to reported figures with their arithmetic, and a golden set of questions with known passages measures how often the right one is retrieved and cited.

**In three sentences.** You give Evidence Desk a ticker, the decision you are facing and the claims your thesis rests on. It reads the company's latest annual and quarterly reports from SEC EDGAR, and for each claim returns a verdict (supported, challenged, mixed or not addressed) with the exact passages behind it, each verified on the server against the stored filing text before anything reaches the page or the export. When the evidence is thin the brief says **partial** and gives the reasons; it never fills a gap with a confident sentence.

The working application is in [`evidence_desk/`](evidence_desk/README.md). [`PROMPT.md`](PROMPT.md) is the prompt that milestone 2 was built from. Later milestones were not given a rewritten prompt: each was briefed from the row of the table below, the findings of the review before it, and a contract of record types written first. Those briefs were given to agent sessions and are not kept in this repository, which is a gap.

## What changed since the first plan

The first version (tag `capstone-v1`) was a general research-brief tool: any question, any public web page. The structure review of that version ([review 1](evidence_desk/docs/reviews/review-1-structure.md)) found that the plan named "a researcher or project lead" but no concrete reader, and gave no evidence by which anyone would know it worked. Both were true.

The project is now narrowed to the research I actually want it for, equity research, and to the place where a thesis is checked: the company's own filings. This merges the second idea in [`idea pitches.md`](idea%20pitches.md), the investment thesis change tracker, with the part of the first version that worked, the citation gate. Narrowing it also makes it testable. A filing has a stable identifier, a fixed text and reported numbers with published values, so there is an answer key. The open web had none.

## Why it is worth doing

An analyst's thesis is a short list of claims. Each quarter a 10-Q of a hundred pages arrives, and the question is narrow: which of my claims does this support, which does it challenge, and which does it not speak to. The work today is search and copy, and the notes that result do not record where a sentence came from. A language model will answer the question fluently, but a fluent answer with a citation that does not say what the sentence claims is worse than no answer, because it reads the same as a correct one.

Evidence Desk makes the passage the unit of the result. A verdict is computed by the backend from the findings that survived the quote check; a model can propose a stance but cannot assert a verdict. The analyst can open the filing at the passage, accept or reject each finding, and export a brief that records those decisions.

## Milestones

Each milestone is one prompt and ends in a tagged version that can be opened on its own (`git checkout <tag>`, then `make up` in `Capstone/evidence_desk`).

| # | Tag | Reviewable result | Exit check | Status |
| --- | --- | --- | --- | --- |
| 1 | `capstone-v1` | A generic research brief: one real page becomes a stored source, an exact excerpt and a verified finding | Altering the excerpt withholds the finding | Done |
| 2 | `capstone-v2` | Filings and claims: a thesis run over a real 10-K and 10-Qs, verdicts first, each excerpt in context with a link into the filing | A recorded 10-Q splits into its Items; a quote with one word changed is withheld | Done |
| 3 | `capstone-v3` | Reported numbers with an answer key: a metrics panel computed from XBRL facts; a numeric check on findings; tests at four levels and a tripwire; one measured speed change | Published values for three companies reproduce; a statement whose number is in neither its quote nor a reported fact is withheld | Done |
| 4 | `capstone-v4` | Reviewer decisions and saved theses: accept or reject each finding; re-run a saved thesis and see which verdicts moved; backup with a tested restore | A restore from backup returns every decision; a re-run names the claims whose verdict changed | Done |
| 5 | `capstone-v5` | Measured retrieval: a golden set with the passage that must come back; retrieval and generation scored apart; a second model checks that each excerpt supports its statement | Recall on the golden set is reported per retrieval variant; an unanswerable claim is refused | Done, with a caveat: recall is reported for five variants, unanswerable claims are refused in 6 of 6 cases, and a second model checks meaning. The golden set has not yet been read by a person |
| 6 | `capstone-v6` | What changed between two filings: added, removed and reworded risk factors and moved numbers | A planted paragraph change is reported as added and removed | Done, with caveats: the exit check is a test; the comparison ran on eight companies' annual reports, but its one threshold was set on NVIDIA and nobody has read the other seven results. A paragraph whose numbers alone moved is counted and not listed, so "moved numbers" is met only as a count |

The draft write-up is due on 30 November and the final in finals week.

## Main risks

| Risk | How it is handled |
| --- | --- |
| A quote is real but does not support the statement made about it | The quote check alone cannot see this. A numeric check (milestone 3), a second-model support check (5) and the reviewer's own decision (4) are three separate layers; none is trusted alone |
| Filings differ in structure from one company to the next, and Item detection fails | Detection is tested on recorded real filings at full size. If it fails, the document is kept whole, the quote check still applies, and the coverage limits say that Items were not found |
| Retrieval misses the passage that matters, and the claim reads as "not addressed" | The verdict is worded as "no verified evidence in the passages retrieved", the run is marked partial, and the golden set (5) measures how often the right passage is in the top results |
| A filing contains text written to steer a model | Filing text is passed as data inside marked elements and is only ever quoted; a test plants an instruction and checks the output is unchanged |
| EDGAR access is refused or limited | Requests carry a descriptive User-Agent, stay under EDGAR's rate limit and are cached; a failed filing is recorded as a failed source and the run continues |

## Frontend and backend boundary

The backend owns EDGAR access, credentials, extraction, retrieval, the engines, quote verification, the verdict rule, the status rule and every count shown. The frontend collects the thesis, shows progress and draws the record.

The boundary sits after verification and after the verdict rule. If the verdict were computed one function later, in the browser, the Markdown export and any API client could show a verdict that the checked evidence does not support, and two views could disagree about the same run.

## Scope and success

In scope: US filers of 10-K and 10-Q reports, one company per run, the latest annual report and the quarterly reports after it, and up to five extra public pages the user supplies. Out of scope: prices, forecasts, PDFs, 8-K exhibits, foreign filers, earnings-call transcripts and any automated buy or sell decision.

Success means an analyst can enter a thesis, read the verdicts, open any finding at its passage in the filing, and see a partial result with its reasons when the evidence is thin. It is measured, from milestone 5, by the golden set: how often the passage that must come back is retrieved, how often a cited quote is exact, and how often an unanswerable claim is refused.

Evidence Desk reads what the company itself reported. It does not check the company against outsiders, and it says so on every brief.

## Review findings answered here

Findings that were built in are listed in the hand-in for the session that reviewed them (`Homework/`). A finding that was not built in as written gets one line here, with the reason.

- **Review 1, F5** (add an extractor registry keyed by content type, with the fetcher carrying bytes): answered with one adapter per source kind behind a shared `Document` shape, not a content-type registry. The next format this project needs is a filing, which is HTML with a different structure, not a PDF, and PDFs remain out of scope.
- **Review 1, F10** (give each subquestion a `kind` field for the extractive engine to branch on): not built. The deterministic engine no longer guesses a stance at all; a claim it handles gets the verdict "passages found, not judged".
- **Review 2, F10** (the API and command-line tests run against a fake EDGAR, so they test the fake as much as the code): kept as they are. The fake serves recorded real filings through the real parser, and the path over the live network is `make demo`, which stays outside `make verify` because the gate has to pass from a fresh clone without a network.
- **Review 4, F1** (also deny direct `docker`, `curl` and `gh` calls in the settings file): not added. The same file governs my own sessions, and I use those commands. The note now says the deny list is partial and what a real boundary would be.
- **Review 4, F2** (deny reading `Work Logs/` and `Homework/` in the settings file): not added, for the same reason. The review checkout is instead an export of the tag that does not contain those folders, and the reviewer lists every file it opened.
- **Review 4, F9** (delete the course's standing rules from `AGENTS.md`): kept. They are the course's file and they hold; only my own section was cut back.
- **Review 4, F11** (make the re-baseline of the tripwire a skill): not built. The test of the first skill showed that a second copy of a documented procedure changes nothing. If a baseline is ever committed without its diff being read, the procedure in `docs/testing.md` becomes a skill and that section becomes a pointer to it.
- **Review 4, F12** (use a reviewer from another vendor once): not possible in this session, which has only Claude models. The skill and the notes now say the reviewer is another model of the same family, not an independent party.
