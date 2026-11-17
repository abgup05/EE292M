# Review 6: speed, the system and what cannot be rebuilt, on version 10

- **Session:** before Week 9B. The slides for Week 9 are not in the repository; this review was run because the system had grown since it was last read against this checklist, in review 3 on version 3: recorded model answers, an evaluation, two more records that are not part of a run, and a run option that fetches two filings a second time.
- **Reviewed:** tag `capstone-v10` (commit `fde4eed`), from an export of the tag made by `git archive` without `Work Logs/` and `Homework/`, and with `Capstone/evidence_desk/docs/reviews/` and the three triage files deleted from it before the reviewer started. Work after the tag is not covered.
- **Reviewer:** Claude Sonnet 5.5, which did not write the code, as a subagent in a fresh context. Blind: its brief held the checkout path, the checklist word for word, the rules and the output format, and nothing else. Read-only by instruction; the harness did not limit its tools, so the export was checked afterwards. It says it used Read only.
- **Run on:** 17 November 2026, with the `/blind-review` skill.
- **Checklist:** `speed-system` (Week 7A, "Design Your System for Your Problem"), quoted in `.claude/skills/blind-review/reference/checklists.md`.
- **Checks made afterwards:** no file in the export is newer than the marker written before the reviewer started. Every file in its closing list is inside the export and none is under `docs/reviews/`. Every file it cites exists at the tag.

The reviewer's text follows unedited. Decisions on the findings are in `Homework/Week 9/W9L2.md`.

---

**Findings, worst first**

1. **The profile does not show where a real run's time goes, and the document says so itself.** `docs/speed.md` lines 3-8 admit the profile is an offline replay with the extractive engine that "waits on nothing", and that model latency "has never been timed". The only live evidence is two single runs, 1.006 s and 0.378 s (lines 18-29). EDGAR time is derived by subtraction ("roughly 0.36 s", line 32) and the cache saving is computed the same way. The README's Speed row (README.md:137) then rates the change against "the one live run without a key that was timed". The keyless run is not the run the app exists for, and its profile is 77.9% parsing of recorded files. Change: time the live path stage by stage inside the run, with a stopwatch like `tests/speed_run.py` `Stopwatch` and not by subtraction, and repeat it at least 5 times. Alternatively retitle item 1 as "profile of the offline path only" and drop the "3% of a live run" ratio, which divides a median of 20 offline pairs by one live sample.

2. **The measured numbers are from version 4 and the code is version 10.** `docs/speed.md:3` says "Version 4". The README's results table (README.md:118) is dated 17 November and carries the 28.8 ms figure as current. Since version 4 the parser, the `PARSER_VERSION` hash input in `sources/filing.py`, the figures code and the tagged-figures stage have all changed. Nothing in the repository shows `make bench` or `make profile` run on the tagged commit. The Makefile help for them is also out of date: `Makefile:22` says "cProfile ... top 25" and "median wall time of the offline run, in seconds", but `bench` now interleaves header-cut pairs. Change: rerun `make bench` and `make profile` at this tag and record the commit hash beside the output files, or label the section "measured at v4".

3. **"One change, measured" is really two changes, and the measurement of the second is weaker.** `docs/speed.md` lines 60-76 changed the commit sync (`store.py:107-118`, `durable=False` for progress saves). Lines 82-99 changed the header cut. The README names only one. Changing the commit sync for the record store is also a durability trade-off: `store.py:168-171` accepts losing the latest progress save on a power cut. The sync change was timed best-of-three, not interleaved. The document itself says its first, non-interleaved header-cut claim did not reconcile (speed.md:82-84). The interleaved bench has a range of -8.6 to 93 ms and the document admits the machine was shared (line 97), so "saves 28.8 ms" is a median of a noisy distribution. Change: state which change is "the one", give the other as a separate side note, and rerun the bench on an idle machine.

4. **The "changed no answer" proof for the header cut rests on equal hashes, and one is weaker than it sounds.** The sha256 `9a9298a4…` (speed.md:74, 99) is the offline NVIDIA golden record. The eight-company check (lines 103-111) compares `make probe` rows and section outlines, not a full `Document` (text and hash) on seven of the eight; only Costco and the NVIDIA filings are compared that way, in `tests/test_ingest.py`. Change: compare the parsed-text hash for all 14 filings with and without the cut, not only the outline of headings.

5. **The record is not safe from a single failure, and the data sits in the source tree.** README.md:110 and :180 admit "No copy off the laptop". `backups/` is on the same disk, gitignored. The record lives in `data/record/record.sqlite` under the bind mount `..:/work` (`docker/compose.yaml:18`, `EVIDENCE_DESK_DATA_DIR: /work/data`). Hence `git clean -fdx`, deleting the checkout or a disk failure removes the original and every backup together. Nothing in `make clean` or `verify-fresh` touches it, but nothing prevents it either. Change: see the suggestion below.

6. **`restore-check` compares only what parses, so it can pass on a record it cannot read.** `store.py:131-143` and the docstring say records that no longer validate are skipped with a warning. `backup.py:220-223` compares `restored.run_ids()` (all rows, including invalid ones) but `all_decisions()` and `list_theses()` go through the skipping parser. A backup and a live record that both hold unreadable decisions or theses would report PASS. `ARCHITECTURE.md:190-192` tells the student to "compare counts too" after a schema change, but `restore_check` does not do it. Change: make `restore_check` also compare raw row counts per table (a `SELECT count(*)` on both files) and fail on a mismatch with the parsed counts.

7. **The backup is a manual step with no trigger and no staleness check.** `Makefile:176-180` is the only mechanism. The architecture says run it "before a schema change", but nothing blocks a schema change without one, and `restore_check` (backup.py:210-232) passes against a backup of any age as long as it matches the live record at that moment. A decision made after the last backup is an unreported gap only if the live record is compared, which it is; but the output never says how old the newest backup is. Change: print the backup's age in the PASS line, and have `make up` warn when the newest backup is older than the newest decision.

8. **Two processes write the same WAL SQLite file across a macOS bind mount, and this is unmeasured.** `store.py:87-88` says WAL lets a `make run` container write the same file as the app. `docs/speed.md:129` says "no test runs two". The README's drawing (README.md:82-84) shows both `APP` and `ONEOFF` using `RECORD`. WAL needs shared memory and locks that can behave differently through Docker Desktop's file sharing on macOS. This is the file the project says cannot be rebuilt. Change: add a test or a `make` target that runs a one-off `backup` and a decision write against the running app and checks `restore-check`, or document that one-off commands must not run while the app is up.

9. **The drawing and the text disagree in two small places.** README.md:101 says the code that runs is "the working tree", but the diagram's arrow `CODE -->|bind mount| APP` hides that the image holds only dependencies, so editing a file changes a running app without a rebuild. The diagram also shows `SHOTS -->|"docs/screenshots"| CODE`, a write into the repository, which is fine but is the only container with a writable `..:/work` and a third-party image (`zenika/alpine-chrome:124`, compose.yaml:41). Change: say in the "How code reaches it" paragraph that `jscheck` mounts read-only and `app`, `lock` and `shots` read-write.

**One suggestion: add a boundary, between the record and the laptop.** Add a `make backup` step that also copies the `decisions-<UTC>.jsonl` file (small, human-readable, no filing text) to a second place the repository already has: commit it on a separate branch, pushed to the private GitHub repository by the student, not by an agent, since `main` rules forbid agents from touching main. Add the age line from finding 7 to `restore-check`. This turns "No copy off the laptop" into a stated, tested copy. It removes no existing boundary.

**What I could not judge from the repository alone**

- Whether the `results/`, `speed/*.txt` and `docs/evidence/` files were produced by the commands listed. I did not open them.
- Whether any real decisions exist in `data/record/record.sqlite`, how large the record is, and whether `backups/` holds a recent backup. Both are gitignored and absent from a checkout.
- Model latency and the real gain from concurrency, which the document itself says are unmeasured.
- Whether concurrent WAL writers across the Docker Desktop mount behave on this laptop.
- Whether `make verify` and `make backup` run, since I ran nothing.
- Whether the sha256 in `speed.md` still matches the current golden record (`tests/golden/` not opened).
- Whether `.gitignore` really ignores `data/`, `backups/` and `results/`.
- I used Read only, because Grep and Glob were not available in this session. Files not named below, including the rest of `store.py` after line 200 and `docs/results.md`, were not opened.

**Files opened**

- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v10/Capstone/evidence_desk/README.md
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v10/Capstone/evidence_desk/ARCHITECTURE.md
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v10/Capstone/evidence_desk/docs/speed.md
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v10/Capstone/evidence_desk/tests/speed_run.py
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v10/Capstone/evidence_desk/src/app/backup.py
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v10/Capstone/evidence_desk/Makefile
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v10/Capstone/evidence_desk/docker/compose.yaml
- /Users/abgup/Documents/Code/EE292M/.claude/worktrees/review-capstone-v10/Capstone/evidence_desk/src/app/store.py (lines 1-200)

A path I tried, `Capstone/evidence_desk/docker-compose.yml`, does not exist.
