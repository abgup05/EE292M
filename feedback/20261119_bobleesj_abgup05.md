# Peer review, tests: does the interface state one thing, and is it tested?

Course: Stanford University, EE292M, AI-Augmented R&D: Foundations and Practice, Fall 2026.
Form: ee292m_round4. Capstone review: yes. Written 2026-11-20 06:20 UTC by feedback_helper 147bfa0.

## Reviewer information

- SUNet ID: bobleesj
- First name: Sangjoon
- Last name: Lee

## Reviewee information

- SUNet ID: abgup05
- First name: Abhiraj
- Last name: Gupta
- Repository: https://github.com/abgup05/EE292M
- Reviewed commit: 640a938 on main

## Environment

- date: Thu Nov 19 22:20:41 PST 2026
- whoami: macbook
- uname -a: Darwin phil 25.4.0 Darwin Kernel Version 25.4.0: Thu Mar 19 19:33:50 PDT 2026; root:xnu-12377.101.15~1/RELEASE_ARM64_T6050 arm64
- repo path: ../EE292M_abgup05

## Checklist

Score: 5 of 5

### 1. The author finished the sentence 'If they take away one thing, it should be ...', and the first screen is built around that one thing, with the rest cut or kept as backup.

Verified: yes

The one thing, in the author's words, and what was cut:

I reviewed 640a938 and the live /v14/ page. I read the one thing as the first-screen headline: every verdict opens to the exact filing passages or reported figures it rests on. I found the same sentence on line 3 of Capstone/README.md. I saw How it works, the legend and the no-run lookups kept as backup. I think the 13 recorded samples beside the headline are still too many, see item 5.

### 2. We have gone through the interface mark by mark: each color, line and number means one thing, one group of related items has its own color used everywhere, and unsettled parts are labeled as drafts.

Verified: yes

The group and its colors, what is marked as a draft, and any word borrowed from the audience:

I went through the recorded NVIDIA run (/v14/?sample) against the colour table in docs/design.md. I took the verdicts as the group: green check supported, magenta cross challenged, both for mixed, grey dashed not judged. I saw the same colours on the claim list, the verdict table and the header pills. I found the drafts marked: the summary says model-written, not checked for meaning, and the run is tagged Sample record. Audience words I noticed: thesis, overweight position, 10-K, 10-Q, 8-K. I did not check contrast or the phone layout.

### 3. We have discussed what is tested and what should be, and for each of unit, integration, end-to-end and smoke I saw one test, or we agreed where the missing one belongs; we named one wrong program the tests would still pass, and one tripwire any error would move.

Verified: yes

One test of each kind, or where the missing one belongs; the wrong program, and the tripwire:

I found one test at each level in docs/testing.md and opened each file. Unit: test_gate.py::test_identity_holds_for_every_evidence_record. Integration: test_thesis_run.py::test_every_excerpt_is_an_exact_slice_of_the_stored_filing on a recorded 10-Q. End to end, offline: test_golden.py::test_the_example_run_matches_the_golden_record. Smoke: tests/smoke.py, which never starts a run. The wrong program I would name: quote any real sentence and call it support, which Abhiraj also names in W9L1.md. Tripwire: tests/golden/golden.json via make golden-check. I read the tests; I did not run them.

### 4. We have discussed which tests save the author time, and what in this project no test can see, and I understood both.

Verified: yes

The tests that pay for themselves, and the scope no test covers:

I agree with his pick of the tests that pay for themselves: the integration test on the recorded 10-Q (real parser, under a second) and the request-rejection tests, which are the contract with the page. He reports 2,361 offline tests in about 112 s; I did not rerun that. I understand that no test can see whether a quote actually supports its claim, whether Open in filing lands on the quote on sec.gov, whether a newcomer understands the page, or how the live model and EDGAR behave.

### 5. We have discussed at least one suggestion I made on how this code could be improved.

Verified: yes

State the suggestion and what was decided:

Email discussion, November 19: I suggested opening the first screen on one recorded verdict already expanded to its quote and folding the other 12 samples behind one link, because I saw no verdict on the first screen. I also suggested having the smoke test start one keyless run on a recorded filing. Decided:

## Attestation

Completed: 5 of 5 checklist items.

All of my answers are true and accurate to the best of my understanding and ability, and I will upload this feedback to the reviewee's repository and verify that it was uploaded.

Signed: Sangjoon Lee
