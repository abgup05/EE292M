# EE292M Work Log

## Week 6B: Speed Through Insight (lecture of 28 October 2026)

*Work done on 17 November 2026, in the catch-up sprint. This log is drafted by the Claude Code session that did the work; the decisions are mine to check.*

**The new version, tag `capstone-v3`: what changed, finding by finding**

- **F1, the page overclaims.** Reworded the first screen and added a note under the verdicts: quotes and numbers are checked, the engine's reading is not. Built the number check (`core/numcheck.py`): every number in a finding must match one of its quotes or a reported figure it cites, or the finding is withheld with the reason.
- **F2, the sample shows nothing.** Recorded a model-backed run and made it the sample: two claims supported, three mixed. A repeated engine failure is now one line.
- **F3, the wrong engine named.** The record says which engine assessed each claim, how many steps fell back and where the answers came from.
- **F4 and F5, overloaded marks.** One meaning per mark, with a legend on the page.
- **F6, the model-written label.** Exact comparison; a badge on every model-written field.
- **F7, denominators.** The backend counts proposed findings; the page shows "8 of 636 passages considered".
- **F8, no test of the page.** `make uitest`: headless Chromium renders two records, 25 assertions on the DOM, now part of `make verify`.
- **F9, the engine only tested against a mock.** A cassette of seven recorded answers and a replay test that fails if a prompt changes.
- **F10, brittle tests.** A scaling check replaces the timing assertion; the demo test asserts facts. The fake EDGAR stays, with the reason in the README.
- **F11, one company.** Costco's 10-K is a second fixture.
- **F12, no tripwire.** `make golden-check`, stage by stage.
- **The five wrong programs and the sixth.** Each fails a named test, and each test was seen failing with the wrong program planted. The table is in `Homework/Week 6/W6L2.md`.

**New in this version beyond the review**

- Reported figures from XBRL facts (revenue, growth, margins, cash flow, per quarter and fiscal year), each with its arithmetic, tested against fourteen published values for three companies.
- `make probe`: how well a company's filings split into their Items, on eight companies.
- A record-and-replay layer for model answers, because the API refused every call for lack of credit.

**The hands-on: profile, then measure one change**

- Profiled the offline run. Parsing is 66% of 0.44 s and almost all of that is the HTML library. Retrieval, the part one would tune first, is 6%.
- Cut the inline-XBRL header before parsing: 0.445 s to 0.411 s, median of five. The tripwire hash did not move.
- Made claim assessments concurrent, three at a time. Measured only with a stand-in engine that waits 200 ms: 1.13 s to 0.50 s.
- Did not run `/speed-review`: the course's skill file is not in this repository.

**What went wrong**

- The first recorded run withheld three true findings. The model had copied "&amp;amp;" from the prompt's escaped text and the gate could not find it. An engine bug, fixed test first.
- "Exactly equal" and "the latest filing wins" both failed on real data (a rounding difference of USD 1 million at NVIDIA; restated annual revenue at Microsoft). Both rules in the brief had to change, and the tests name the exceptions.
- The parser had three layout faults that one company's filings could not show.

**Status**

Version 3. `make verify` green from a fresh clone: 708 offline tests, smoke, 25 page assertions. A complete, judged, recorded run. Still no check of meaning, no measurement of retrieval, and no live call to the API since version 1.

**Takeaway**

The speedup was 8%, from deleting work, and the profile showed that retrieval, the obvious thing to tune, was 6% of the time. The larger lesson of the week was the answer key: the figures were right on the first run, and two rules the brief had stated about them were wrong.
