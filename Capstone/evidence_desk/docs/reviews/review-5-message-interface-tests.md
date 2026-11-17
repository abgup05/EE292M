# Review 5: the message, the interface and the tests, on version 7

- **Session:** before Week 9B. The slides for Week 9 are not in the repository; this review was run because the page had gained two whole views (the comparison of two filings, and its corrected counts) since it was last read against this checklist, in review 2.
- **Reviewed:** tag `capstone-v7` (commit `c91d0bc`), from an export of the tag made by `git archive` without `Work Logs/` and `Homework/`, and with `Capstone/evidence_desk/docs/reviews/` and both triage files deleted from it before the reviewer started. Work after the tag is not covered.
- **Reviewer:** Claude Sonnet 5.5, which did not write the code, as a subagent in a fresh context. Blind: its brief held the checkout path, the checklist word for word, the rules and the output format, and nothing else. Read-only by instruction (Read, Grep and Glob); the harness did not limit its tools, so the export was checked afterwards.
- **Run on:** 17 November 2026, with the `/blind-review` skill.
- **Checklist:** `message-tests` (Week 6A, "Challenge Builds Trust"), quoted in `.claude/skills/blind-review/reference/checklists.md`.
- **Checks made afterwards:** no file in the export is newer than the marker written before the reviewer started. Every file in its closing list is inside the export and none is under `docs/reviews/`. Every file it cites exists at the tag.

The reviewer's text follows unedited. Decisions on the findings are in `Homework/Week 9/W9L1.md`.

---

1. **Item 1 (message).** `src/web/index.html` lines 19-20 and 120-133. The first screen opens with a description of the tool ("Test each claim in your thesis...") and a three-line caveat. An empty form takes the left column. On the right there is a four-step procedure, "How a run works", instead of a result. The one takeaway in `Capstone/README.md` line 3 is that each verdict opens to exact filing passages or figures. Nothing on the first screen states it. The screenshot `docs/screenshots/sample-run.png` shows the sample's masthead carrying a dense paragraph about engines, cassettes and credit. The sample link is small text at the bottom of the empty state. Change: put one sentence at the top, such as "Every verdict opens to the filing passage or reported figure behind it; quotes are checked word for word, meaning is not." Move the sample link next to it and cut the engine paragraph to a single line.

2. **Item 2 (interface).** `index.html` lines 207 and 211-212 and `styles.css` lines 149 and 565-578. "Rejected" names two different marks. One is red `!`, meaning your input was refused. The other is a dark `☒`, meaning you rejected a finding. The word `Reject` is also the button label. Change: call the input case "Invalid input" or "Refused", and keep "Rejected" for decisions only.

3. **Item 2.** `index.html` line 200 and `styles.css` lines 25 and 495. The legend says "A dashed border always means not judged or provisional". Dashed borders appear on `? Not judged` and on `☐ Undecided`. Per `styles.css` line 382, they also appear on a running banner. These are three different states under one rule, and the "always" is wider than what the page marks. Change: state the shared meaning once ("not final") and list the three cases in the legend, or use a separate mark for each.

4. **Item 2 (drafts).** `index.html` lines 146-161 against `Capstone/README.md` lines 31 and 154 and `evidence_desk/README.md` line 214. The README says the comparison's reword threshold was read only by a model, and that the golden set has had no human reader. In `index.html` the comparison view carries only the "Limit" legend entry, and I did not find a draft tag. The sample-record tag is the only draft marker I saw. Change: add a visible "Unchecked by a person" tag to the changes view and to any golden-set figure, using one mark defined once in the legend. I did not open `app.js` past line 120, so this is unconfirmed on the rendered page.

5. **Item 2.** `app.js` line 81 and `styles.css` line 565. The complete-status glyph `■` and the accepted-decision glyph `▣` are both dark squares. The CSS header says a dark tag is "always yours". Change: give the complete status a glyph and colour that are not the inverted ink tag.

6. **Item 3 (wrong program that passes).** `evidence_desk/README.md` lines 206 and 209, `tests/test_golden.py` lines 1-8 and `tests/golden_run.py` lines 3-4. Consider a program that quotes any real sentence from the filing and labels it "supports". It passes the gate, because the quote is present. It passes the number check, because no figure is cited. It passes the tripwire, because the tripwire runs the extractive engine, which "judges no stance". It passes the DOM test, which only checks marks against the record. The README confirms the gate checks presence, not relevance. Only the recorded second-model check could catch this, and a recording replays fixed answers. Change: add a golden-set test with a planted irrelevant but real quote and assert it is not counted toward a verdict.

7. **Item 3 (tripwire).** `tests/test_golden.py` lines 48-64 and `docs/testing.md` lines 34-41. A single sha256 over the whole record moves on any change, so every error moves it. It cannot distinguish a wrong result from an intended one. The re-baseline instruction is "read the diff" with no further control. The filing-comparison pipeline is not among its stages. `docs/testing.md` says the stages are those listed from `sources` to `figures`. Change: make the baseline commit fail in CI unless the PR description names the moved stage. Add a comparison-pipeline stage to the record.

8. **Item 3 (smoke).** `tests/smoke.py` lines 4-5 and 54. The smoke test never starts a run, by design, so it cannot show the pipeline works in the container. Line 54 hardcodes `version == "0.7.0"`, so every release breaks it for a reason unrelated to health. Change: compare the version against a single constant, and add one keyless run on a recorded filing.

9. **Item 3 (end-to-end and integration).** `docs/testing.md` lines 12-15 and `tests/test_golden.py`. The end-to-end test uses the extractive engine and fakes, as the table says: "proves only that nothing moved". The integration test uses a recorded 10-Q through a fake EDGAR. The path that fetches filings live is covered only by `make live-walk`, which is outside `make verify` (`Capstone/README.md` line 67). Change: label this tier "regression" rather than end-to-end in `testing.md`.

10. **Item 3 (unit test strength).** `tests/test_gate.py` lines 68-72 and 218-225. The unit test asserts that the stored slice equals the excerpt, using three hand-picked quotes. That holds by construction if the gate slices the stored text. It would not fail if the gate located the wrong occurrence of a repeated phrase. Change: add a case with a quote that occurs twice, under different Items, and assert the locator matches the passage offered.

11. **Item 4 (time and limits).** `tests/test_gate.py` lines 199-212 and `uitests/test_dom.py` lines 3-10 and 66-71. The linear-scaling test compares two wall-clock timings against a bound of 20x. That is still a timing test and can flake on a loaded machine. The DOM tests read `results/dom-*.html`, which `make uitest` writes. A stale file could be read if the test is run alone. Change: skip or retry the timing test on noisy runners, and have the DOM tests check the dump is newer than the page source.

12. **Item 4.** `docs/testing.md` lines 141-149. No test can see the following, and the README confirms each:
    - whether a quote bears on its claim;
    - whether "Open in filing" highlights the passage on sec.gov;
    - whether the page is understood, including colour, contrast and dark mode;
    - live API and EDGAR behaviour.

    The time saved by `make test` (offline, no network) is stated, but no measured runtime is given for `make verify` or `make test`. Change: record both runtimes in `testing.md` with the command that produced them.

**What I could not judge from the repository alone**
- Whether a human reader grasps the takeaway from the first screen. Nobody has tested that.
- Contrast, dark mode and phone layout. The README says they were not checked.
- Whether the colours are distinguishable for colour-blind users. I read hex values only.
- Whether the draft marking in `app.js` beyond line 120 covers the changes view.
- Whether the test counts in the README (1,128 tests, 75 assertions) are current. I did not run anything.
- Whether the golden set, the filing comparison's classification, or the recorded model answers are correct.
- Whether the text-fragment links work on sec.gov.
- `make verify` from a fresh clone.

**Files opened**
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v7/Capstone/README.md
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v7/Capstone/evidence_desk/README.md
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v7/Capstone/evidence_desk/docs/testing.md
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v7/Capstone/evidence_desk/src/web/index.html
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v7/Capstone/evidence_desk/src/web/styles.css
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v7/Capstone/evidence_desk/src/web/app.js
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v7/Capstone/evidence_desk/tests/smoke.py
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v7/Capstone/evidence_desk/tests/test_gate.py
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v7/Capstone/evidence_desk/tests/test_golden.py
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v7/Capstone/evidence_desk/tests/golden_run.py
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v7/Capstone/evidence_desk/uitests/test_dom.py
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v7/Capstone/evidence_desk/docs/screenshots/sample-run.png
