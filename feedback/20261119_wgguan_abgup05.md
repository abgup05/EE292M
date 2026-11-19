# Peer review, tests: does the interface state one thing, and is it tested?

Course: Stanford University, EE292M, AI-Augmented R&D: Foundations and Practice, Fall 2026.
Form: ee292m_round4. Capstone review: yes. Written 2026-11-19 19:31 UTC by feedback_helper 147bfa0.

## Reviewer information

- SUNet ID: wgguan
- First name: Helena
- Last name: Guan

## Reviewee information

- SUNet ID: abgup05
- First name: Abhiraj
- Last name: Gupta
- Repository: https://github.com/abgup05/EE292M
- Reviewed commit: fde4eed on HEAD

## Environment

- date: Thu Nov 19 11:31:05 PST 2026
- whoami: wgguan
- uname -a: Darwin DN51sc4j.SUNet 27.2.0 Darwin Kernel Version 27.2.0: Wed Oct 14 23:46:57 PDT 2026; root:xnu-13432.41.4~25/RELEASE_ARM64_T8103 arm64
- repo path: ../abgup05_EE292M

## Checklist

Score: 5 of 5

### 1. The author finished the sentence 'If they take away one thing, it should be ...', and the first screen is built around that one thing, with the rest cut or kept as backup.

Verified: yes

The one thing, in the author's words, and what was cut:

I reviewed from the repository without a live session, so this is the author's sentence as the README and the page state it. If they take away one thing, it should be that every verdict opens to the exact filing passages or reported figures it rests on, quotes are checked word for word, and whether a quote supports a claim is a model's reading checked by a second model and then by you. At capstone-v10 that sentence is the headline of the first screen (docs/screenshots/first-screen.png), with the sample links right under it. What was cut since version 7 is the long tool description and the engine paragraph, now one small line. The rest is kept as backup behind "How a run works" and the illustrative record. One gap is that a first visitor sees an empty form and steps rather than a result, so the takeaway is told before it is shown.

### 2. We have gone through the interface mark by mark: each color, line and number means one thing, one group of related items has its own color used everywhere, and unsettled parts are labeled as drafts.

Verified: yes

The group and its colors, what is marked as a draft, and any word borrowed from the audience:

I went through styles.css (every color is a named token defined once, lines 33 to 60, with a dark mode set) and the legend on the recorded run. Every mark is a glyph plus a word, so no meaning rests on color alone. Each group has one color used everywhere. Verdicts are green for supported and magenta for challenged, anything a model wrote or judged (Model-written, Agrees, In part) is violet, filing changes (Added, Removed, Reworded, Numbers only) are teal, the ƒ Fixed rule tag is olive, and your own decisions are dark filled tags. Unsettled parts are labeled. A dashed border means not final, the summary says "Model-written, not checked for meaning", ƒ marks the keyword match nobody has checked, and a grey SAMPLE RECORD tag marks the recording. Words borrowed from the audience are thesis, claim, 10-K, 10-Q, segment and diluted EPS. One small issue is that Mixed is half green and half magenta but its ± glyph is magenta (styles.css line 522), so it reads as leaning toward challenged. The legend has about 25 marks, which is careful but a lot to learn.

### 3. We have discussed what is tested and what should be, and for each of unit, integration, end-to-end and smoke I saw one test, or we agreed where the missing one belongs; we named one wrong program the tests would still pass, and one tripwire any error would move.

Verified: yes

One test of each kind, or where the missing one belongs; the wrong program, and the tripwire:

> make verify (build, lint, offline tests, smoke against the container, browser test) was green on my laptop at capstone-v10 on the first try in 1 min 30 s, with 1,361 tests passed, smoke ok and 142 browser checks passed.
> Unit is tests/test_gate.py::test_identity_holds_for_every_evidence_record (the stored slice of the filing is exactly the quote). Integration is tests/test_thesis_run.py::test_every_excerpt_is_an_exact_slice_of_the_stored_filing (ingest to chunk to retrieval to gate to store on a recorded 10-Q). End to end is tests/test_golden.py, the whole example thesis run offline, plus uitests/ rendering seven sample pages in headless Chromium and checking the DOM against the JSON. Smoke is tests/smoke.py (the container starts, answers health, serves the page and refuses bad input naming the field).
> What is missing is a test that clicks the real buttons. It belongs in uitests/, clicking Load example and Test the thesis under make up-recorded and reading the verdict row. make live-walk does this over HTTP but sits outside the gate.
> A wrong program the tests would still pass is an engine that quotes a real sentence on the right topic that does not carry the claim and labels it supports. It passes the word for word gate, the number check, the golden tripwire (which runs the extractive engine that judges no stance) and the DOM tests. The meaning check is scripted in the tests, and the mismatch eval only swaps in quotes from another company or claim, the easy kind. docs/testing.md says this hard kind is unmeasured.
> The tripwire is tests/golden/golden.json, the whole offline example run grouped by stage with a sha256 over the record. make golden-check names the first stage that moved, so a planted PASSAGES_PER_CLAIM change from 8 to 2 shows up first as limits.

### 4. We have discussed which tests save the author time, and what in this project no test can see, and I understood both.

Verified: yes

The tests that pay for themselves, and the scope no test covers:

> The tests that pay for themselves are the golden tripwire, because a failure names the first stage that moved and so where to look (parser, a constant, ranking, the gate, the metrics), and the planted defect tables in docs/testing.md, since every test there was seen failing on a named wrong program first. The gate is fast enough to run on every change. On my laptop the 1,361 offline tests took 41 s and all of make verify took 1 min 30 s including the build (one run).
> What no test can see is whether a quote actually supports the claim (the gate proves the text exists, not what it means), whether Open in filing lands on the passage on live sec.gov, whether a newcomer understands the page, color contrast and the phone layout, and live services. Every model-backed result since 22 Oct comes from recorded answers because the API keys had no credit, which the README says plainly.

### 5. We have discussed at least one suggestion I made on how this code could be improved.

Verified: yes

State the suggestion and what was decided:

My suggestion is a small hand-labeled set for the hard mismatch. Have a person pick 20 or so on-topic quotes from the golden set that do not carry their claim, and score the meaning check on them. That is the one number that says how far a supports verdict can be trusted, and it is the case the current eval cannot measure. Two smaller ones are a browser test inside make verify that clicks Load example and Test the thesis and reads the verdict row, and giving the Mixed glyph ink color so it looks neutral. Since we reviewed without a live session, nothing has been decided yet. I will leave these on the pull request for the author to answer.

## Attestation

Completed: 5 of 5 checklist items.

All of my answers are true and accurate to the best of my understanding and ability, and I will upload this feedback to the reviewee's repository and verify that it was uploaded.

Signed: Helena Guan
