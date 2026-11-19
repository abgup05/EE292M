# Peer review, safety nets: where does the capstone stand, what does the agent know, and what catches a wrong result?

Course: Stanford University, EE292M, AI-Augmented R&D: Foundations and Practice, Fall 2026.
Form: ee292m_round6. Capstone review: yes. Written 2026-11-19 11:57 UTC by feedback_helper 147bfa0.

## Reviewer information

- SUNet ID: lanmei
- First name: Lan
- Last name: Mei

## Reviewee information

- SUNet ID: abgup05
- First name: Abhiraj
- Last name: Gupta
- Repository: https://github.com/abgup05/EE292M
- Reviewed commit: 640a938 on main

## Environment

- date: Thu Nov 19 03:57:21 PST 2026
- whoami: lanme
- uname -a: MINGW64_NT-10.0-26200 lanmei 3.6.5-22c95533.x86_64 2025-10-10 12:02 UTC x86_64 Msys
- repo path: ../EE292M-abgup05

## Checklist

Score: 5 of 5

### 1. We have gone through the capstone check-in, docs/check-in.md, together, against the capstone plan: what works, what failed, what is cut, and one part to throw away and one to keep.

Verified: yes

What works, what failed, what is cut, and what the plan still claims:

Works (docs/check-in.md, pinned at version 4):
- make verify-fresh passes (805 tests);
- an offline judged run verifies 18 of 18 findings;
- 14 reported figures match the annual reports;
- 13 of 14 filings split into their Items;
- a backup restores every decision.
Failed:
- retrieval on paraphrased claims (7 of 24, which they call the largest open problem);
- no API credit, so a stand-in recorded the model’s answers;
- a speed claim that didn’t add up;
- a parser tested on one company;
- a pasted API key that hasn’t been rotated.
Cut: the open-web mode, PDFs and transcripts, embeddings, hosting. 
Throw away: the stand-in recordings. 
Keep: the quote and number checks and the tripwire.

### 2. We have gone through what changed in the capstone's CLAUDE.md this week together (git log -p CLAUDE.md), and why: each line added is something the agent could not have found by reading the code, and each line cut has a reason.

Verified: yes

A line added and why it is needed, and a line cut and why:

CLAUDE.md is "AGENTS.md" since 5 Oct, and the agent notes live in AGENTS.md's new section "what an agent could not find" (17 Nov).
A line added an agent could not find by reading the code: "make probe says nothing about figures: three of the eight were wrong for seven versions under it." The code shows what each target checks, but not that one target's green hid a fault for seven versions. Also "record.sqlite ... Nothing can rebuild it", and the macOS PATH prefix for Docker's credential helper.
A line cut: "Never put a personal name or e-mail in the default SEC User-Agent", because review 4 (F9) showed it is already visible in .env.example and edgar.py. The course boilerplate review 4 also flagged (AGENTS.md:44-46, "a scientist would call a result") is still there.

### 3. We have discussed which skill the author used this week and why; or, if none was used, why not, and which repeated procedure should become a skill.

Verified: yes

The skill and why it ran; or why none, and which skill to write:

/blind-review (.claude/skills/blind-review), plus the referee agent (.claude/agents/referee.md: Sonnet, Read, Grep and Glob only). It ran this week for the Week 9 review of version 7, from an export of the tag with the author's notes removed. It runs because every course review here is done by a model that did not write the code, and the skill keeps that reviewer from agreeing by construction. It was tested in fresh sessions (docs/skill-test.md): it fired on 3 of 3 requests and stayed quiet on 3 near misses.
A next skill: triage. The same procedure ran seven times (referee-1 to referee-7, each with its triage file): check each finding against the code, a failing test first, then a decision.

### 4. We have named the safety nets of this capstone: the layers that would catch a wrong result (tests, a check against a known answer, a person's review, ...), one failure that would slip past all of them, and where the copies of the code and data are, one of them offline.

Verified: yes

The layers, the failure that slips past them, and where the copies are:

Layers (docs/safety-nets.md): request validation, the quote check, the number check, the period check, the meaning check by a second model, the fixed verdict rule, the answer key for figures, the tripwire, the replay test, page tests, the tagged total, blind reviews, and the reader's accept or reject.
One failure that slips past all of them: a wrong stance on the right topic. A real quote, misread, passes every mechanical check, and the meaning check is another Claude model; it rejected 150 of 152 planted off-topic quotes, but only 1 of 78 real findings, and on-topic misreadings were never tried.
Copies: code on the laptop and a private GitHub repository; record.sqlite on the laptop, with backups on the same disk. There is no Time Machine and no offline copy.

### 5. We have discussed at least one suggestion I made on how this capstone could be improved.

Verified: yes

State the suggestion and what was decided:

One suggestion is to read ten golden cases as the answer key nobody has written yet. Every layer above the reader, and every reviewer, is a Claude model, and "the golden set has not yet been read by a person." So take ten of the 30 cases in eval/golden.json, hide the expected stance, and write your own stance for each from the passage. Then compare with the model-written one. One hour gives the project its first answer key from outside the models, and a measured rate for the failure that slips past every net. The author decided to integrate this.

## Attestation

Completed: 5 of 5 checklist items.

All of my answers are true and accurate to the best of my understanding and ability, and I will upload this feedback to the reviewee's repository and verify that it was uploaded.

Signed: Lan Mei
