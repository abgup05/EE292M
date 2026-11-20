# Peer review, systems: where does the time go, and where does everything run?

Course: Stanford University, EE292M, AI-Augmented R&D: Foundations and Practice, Fall 2026.
Form: ee292m_round5. Capstone review: yes. Written 2026-11-20 00:46 UTC by feedback_helper 147bfa0.

## Reviewer information

- SUNet ID: tylerkc
- First name: Tyler
- Last name: Colenbrander

## Reviewee information

- SUNet ID: abgup05
- First name: Abhiraj
- Last name: Gupta
- Repository: https://github.com/abgup05/EE292M
- Reviewed commit: 640a938 on main

## Environment

- date: Thu Nov 19 16:46:07 PST 2026
- whoami: tyler
- uname -a: MINGW64_NT-10.0-26200 Tyler-ThinkPad 3.6.9-b4195d69.x86_64 2026-06-06 17:49 UTC x86_64 Msys
- repo path: ../EE292M

## Checklist

Score: 5 of 5

### 1. We have looked at a profile of the capstone's slowest part, and at one change measured before and after that changed no answer.

Verified: yes

Where the time goes, the change, and the ratio:

From speed.md: a live run without a model key takes about 1.16 s with an empty filing cache and about 0.33 s with a warm one. 57–59% of that is waiting on EDGAR (5 requests cold, 2 warm). Parsing is about a quarter of a cold run.

### 2. The README has a drawing of the capstone as a system, and from it I can say where each part runs and how code and data reach it.

Verified: yes

The machines or containers, and how code and data arrive:

Yes

### 3. We have named the original copy of the data, and what in the project cannot be rebuilt by a script, and where that is backed up.

Verified: yes

The original, what cannot be rebuilt, and where its copy is:

SEC EDGAR holds the original filings and facts. The filing cache, the facts database and results/ are disposable. make backup can also create backups.

### 4. We have discussed each boundary in the system (between front end and backend, data and database, or services) and whether it is real.

Verified: yes

The boundaries, and which one is not real yet:

The backend computes every verdict, excerpt and count after verification, and the page only places what it gets.

### 5. We have discussed at least one suggestion I made on how this capstone could be improved.

Verified: yes

State the suggestion and what was decided:

There is a lot of stuff happening on the page, so it's difficult to digest all at once. There is an example, but that is still a lot of new info, so if there is any way you can reveal parts one at a time or change the UI flow, that could help with usability (e.g. trying to utilize progressive disclosure). What are the most important parts that need to be highlighted? Those should be the most clear and easy to interpret.

## Attestation

Completed: 5 of 5 checklist items.

All of my answers are true and accurate to the best of my understanding and ability, and I will upload this feedback to the reviewee's repository and verify that it was uploaded.

Signed: Tyler Colenbrander
