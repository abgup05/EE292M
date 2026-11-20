# Peer review, tests: does the interface state one thing, and is it tested?

Course: Stanford University, EE292M, AI-Augmented R&D: Foundations and Practice, Fall 2026.
Form: ee292m_round4. Capstone review: yes. Written 2026-11-20 06:02 UTC by feedback_helper 147bfa0.

## Reviewer information

- SUNet ID: afarmer8
- First name: Alek
- Last name: Farmer

## Reviewee information

- SUNet ID: abgup05
- First name: Abhiraj
- Last name: Gupta
- Repository: https://github.com/abgup05/EE292M
- Reviewed commit: 640a938 on main

## Environment

- date: Thu Nov 19 22:02:24 PST 2026
- whoami: alekfarmer
- uname -a: Darwin Aleks-MacBook-Pro.local 27.2.0 Darwin Kernel Version 27.2.0: Thu Oct 15 00:00:57 PDT 2026; root:xnu-13432.41.4~25/RELEASE_ARM64_T6020 arm64
- repo path: ../EE292M

## Checklist

Score: 5 of 5

### 1. The author finished the sentence 'If they take away one thing, it should be ...', and the first screen is built around that one thing, with the rest cut or kept as backup.

Verified: yes

The one thing, in the author's words, and what was cut:

- What the page says (src/web/index.html:493): "Every verdict opens to the exact filing passages or reported figures it rests on: quotes are checked word for word, and whether a quote supports a claim is a model's reading, checked by a second model and then by you."
- What was cut or moved to backup: docs/design.md §"What left the reading path" lists it. Provenance (engine, run id, times), the legend and glossary, and the engine list in the bar all moved into the Run drawer. The claims used to appear three times and now appear once, in the rail.

### 2. We have gone through the interface mark by mark: each color, line and number means one thing, one group of related items has its own color used everywhere, and unsettled parts are labeled as drafts.

Verified: yes

The group and its colors, what is marked as a draft, and any word borrowed from the audience:

- One group with its own colour (docs/design.md:56-96): the verdicts. Supported is green ✓, challenged is magenta ✕, and mixed (±) shows both. Each has a token used everywhere, and the same colours mark a computed test that holds or fails. Each mark also has a glyph and words, so colour is never the only signal.
- Marked as unsettled / draft: the word "draft" never appears on the page. The closest thing is "Model-written, not checked…" with ✎ in violet on the summary and on every finding. There is also ▲ in yellow for a limit of the record, ? for "not judged", and the sample tag. Do you count "model-written" as his draft label? Are any parts of the page itself still unsettled, and is that marked?
- Words borrowed from the audience: thesis, claim, "overweight", docket, base rates, peer ranks, and the whole Terminal theme (it imitates a market terminal). Ask which of these did you choose on purpose for analysts.
- Worth raising: in version 2, amber had six meanings and the dashed border seven (W6L1 §3). Check with him that version 14 really fixed this. Amber is now only selection and focus, and the limit colour is a separate yellow.- What was cut or moved to backup: docs/design.md §"What left the reading path" lists it. Provenance (engine, run id, times), the legend and glossary, and the engine list in the bar all moved into the Run drawer. The claims used to appear three times and now appear once, in the rail.

### 3. We have discussed what is tested and what should be, and for each of unit, integration, end-to-end and smoke I saw one test, or we agreed where the missing one belongs; we named one wrong program the tests would still pass, and one tripwire any error would move.

Verified: yes

One test of each kind, or where the missing one belongs; the wrong program, and the tripwire:

- Tripwire: tests/golden_run.py → tests/golden/golden.json, checked by make golden-check. It records each pipeline stage plus one SHA-256 of the whole record, and on a failure it names the first stage that changed.
- A meaning-check model that says "supported" to everything. Every test uses a scripted checker, and you doc admits no test measures how often the check is wrong (testing.md, "Whether the check would catch anything").
- should the live end-to-end check have a home outside the gate, for example a scheduled target?

### 4. We have discussed which tests save the author time, and what in this project no test can see, and I understood both.

Verified: yes

The tests that pay for themselves, and the scope no test covers:

- Time savers (his words from W6L1 §5): the integration test on a recorded 10-Q, which runs the real parser at full size in under a second, and the request-rejection tests, which are the contract with the page. Also the tripwire, because it names the stage that moved.
- Cost worth raising: the suite has grown from 21 s (version 8) to 112 s and 149 s for the whole gate (version 14.1, testing.md, "How long the gate takes").
- No test sees (testing.md, "What no test here can see"): whether a quote actually supports its claim, whether "Open in filing" lands on the quote on sec.gov, whether a newcomer understands the page (including colour, contrast and the phone layout), and live model and EDGAR behaviour. Only one other company's full filing (Costco) is a test fixture.

### 5. We have discussed at least one suggestion I made on how this code could be improved.

Verified: yes

State the suggestion and what was decided:

- Shorten the takeaway to one idea and move the "model's reading" caveat next to each verdict.
- Test the checker against a person: a small set of findings a person has labelled, with the meaning check's agreement rate reported. That would close the blind spot he names himself.
- Split the gate into a fast tier (unit tests plus the tripwire) and a full tier, now that it takes about 2.5 min.

## Attestation

Completed: 5 of 5 checklist items.

All of my answers are true and accurate to the best of my understanding and ability, and I will upload this feedback to the reviewee's repository and verify that it was uploaded.

Signed: Alek Farmer
