# Review 2: the message, the interface and the tests

- **Session:** Week 6A, "Challenge Builds Trust" (review of the current state of the code)
- **Reviewed:** tag `capstone-v2`, from a clean checkout of that tag
- **Reviewer:** Claude Sonnet 5.5, in a fresh context with read-only tools. It did not write the code and was not shown the work logs, the homework files, the earlier review or any conversation. It could view the three screenshots in `docs/screenshots/`. There was no colleague review for this session.
- **Run on:** 17 November 2026
- **Checklist given to the reviewer:** the session's four items: the message, the interface, the tests (one test at each of four levels, wrong programs the suite would pass, a tripwire), time and limits.

The reviewer's text follows unedited. My decision on each finding is in `Homework/Week 6/W6L1.md`.

---

**First screen, as I read it:** this tool tests each claim in my thesis against the company's own SEC filings, and every verdict opens to the exact passage.

**Result screen, as I read it:** the sample (an NVIDIA run) shows five "? Passages found, not judged" verdicts, a partial-run warning and a wall of error text, so the takeaway is that something went wrong and nothing was concluded.

## Findings, worst first

**F1 [message]** The lede and step 3 say a verdict is "computed from quotes checked word for word". The check proves only that a quote exists in the filing. In claude mode the support or challenge stance comes from the model (`src/app/core/policy.py`, `claim_verdict`). The page never says "Supported" can rest on a model's reading of a real sentence. Evidence: `index.html:19,95`, `policy.py:56-76`. Change: say "quotes are verified; the model's reading of them is not".

**F2 [message]** The only result screen shown to a new user is the sample, and it shows no verdict at all. All five claims read "?" and the status banner is amber. The raw Anthropic billing error ("credit balance is too low") is printed seven times. Evidence: `sample-run.png`; `sample-run.json`. Change: ship a sample with a mix of judged verdicts, or hide the engine failure text behind one line.

**F3 [interface]** The header says "Engine: claude (a language model drafts findings…)" on a run where claude failed on every step and the extractive fallback ran. The banner says "5 of 5 claims with verified evidence" while every claim is unjudged. Evidence: `app.js:292-295,693`; `sample-run.png`. Change: show the engine that actually did the work, and word the count as "with verified excerpts".

**F4 [interface]** The caution amber carries at least six meanings: partial or failed run, field-validation error, over-limit counter, sample tag, model-written summary, and unread source. The ▲ glyph is reused for status, errors, coverage limits, the withheld heading and field errors. Evidence: `styles.css:3-10,200,221,289,373,435,550`; `app.js:40`. Change: give "draft or model-written" and "sample" their own colour and glyph, separate from "something limits the record".

**F5 [interface]** Dashed borders mean different things in different places: unjudged verdict, sample tag, engine commentary, context finding, withheld box, running banner and model tag. "Unjudged" (dashed) and "not addressed" (dotted) differ only by border style. Accent blue marks both "clickable" and the current stage, which is not clickable. Evidence: `styles.css:146,300,396-397,436,479,497,544`; `styles.css:336`. Change: reserve dashed for drafts and unjudged, and use a different treatment for the stage marker.

**F6 [interface]** The model-written label is incomplete. The summary tag depends on a regex over the origin string (`/model|claude|llm/i`, `app.js:801`), so any other origin name goes unflagged. Finding statements and findings' "Engine's reason" carry no model marker (only the confidence line mentions "Engine's"). The ✎ glyph appears only on the summary. Evidence: `app.js:801-805,861,866`. Change: have the API return a `model_written` boolean and badge every model-written field.

**F7 [interface]** Several numbers have no denominator. "3 findings · 8 passages considered" does not say 8 of how many; the banner says "636 passages indexed". "15 findings verified, 0 withheld" does not say how many were proposed. Evidence: `app.js:779,694`. Change: show "8 of 636 passages" and "15 of 15 proposed".

**F8 [tests]** The frontend (1010 lines of `app.js`) has no test of any kind. `tests/smoke.py` only checks that `/app.js` is served with the right content type. Verdict glyphs, colours and the count wording can break unnoticed. Evidence: `smoke.py:62-67`; `app.js:28-40`. Change: add a headless-browser test that renders `sample-run.json` and asserts the pill text and class for each verdict.

**F9 [tests]** `tests/test_engine_claude.py` (462 lines) tests the Claude engine only against a mocked SDK. It never checks what the prompt makes a real model do. Evidence: `test_engine_claude.py:112-140`. Change: record a few real responses once and assert them with a cheap check.

**F10 [time and limits]** Timing and exact-string tests are brittle. `test_gate.py:170` ("fast on a large text") depends on machine speed. `test_demo.py` asserts exact Markdown strings. `test_api.py` and `test_cli.py` run against `FakeFilings`, so they test the fake as much as the code. Evidence: `test_gate.py:170`; `test_demo.py:34-48`. Change: replace the timing assertion with an algorithmic-complexity check and loosen the string asserts.

**F11 [tests]** Every pipeline test uses the same recorded NVIDIA filings. No other company, no 10-K/A, and no filing with a different layout is covered. Evidence: `fakes.py:46-52`. Change: record one more small filer from a different sector.

**F12 [tests]** Each test file checks one value in isolation. Nothing records the whole run's output, so changes upstream are caught only if some specific assertion happens to cover them (see Tripwire).

## Wrong programs the tests would pass

- `src/app/core/limits.py`, `PASSAGES_PER_CLAIM` 8 → 2. The tests use the constant, and the smoke test asserts only `MAX_CLAIMS` and the time limit. Retrieval gets worse and nothing fails.
- `src/app/engines/claude.py`, the assess system prompt: add "prefer findings that support the claim". Every test mocks the SDK, so verdicts skew toward Supported with all tests green.
- `src/app/core/gate.py`, the Evidence construction: set the locator from the wrong passage or a fixed string. `test_thesis_run.py:108` asserts only `assert item.locator`, so a wrong "Located under: Item 1A" still passes.
- `src/web/app.js`, `VERDICT_GLYPH`: swap ✓ and ✕, or point `.v-supported` at the challenge colour. No test touches the JS or CSS.
- `src/app/sources/edgar.py`, filing selection: take the older 10-K when two are close. This depends on `test_edgar` using only the recorded NVIDIA submissions, so I am less sure of it.

## Tripwire

None exists. The only recorded hashes are the fixtures' input `sha256` in `tests/fixtures/edgar/manifest.json`, and `demo/demo-2026-11-17-v2.json` is not asserted by any test. I would add a golden test. Run the extractive engine on the recorded filings with a fixed clock and fixed ids. Serialise the run without timestamps or run ids. Compare it with a checked-in `golden.json`: `passages_indexed`, per-claim offered passage ids, each excerpt's start offset, verdicts, coverage counts, plus one SHA-256 of the whole thing. Any upstream change moves the hash, and the diff shows which stage moved.

## Only a person can check

- Whether a highlighted quote actually supports or challenges the claim. The gate proves the text exists, not what it means.
- Whether the "Open in filing" link scrolls to and highlights the quote on live sec.gov.
- Whether a newcomer understands the page, and whether colour, contrast, dark mode and the phone layout hold up.
- Live-service behaviour: real Claude output quality, EDGAR rate limits and outages, billing and key failures.
