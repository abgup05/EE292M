# Review 4: the check-in, the agent notes, the skill and the safety nets

- **Session:** Week 8A, "Know What You Know, and What You Don't" (review of the capstone)
- **Reviewed:** commit `413efe9`: tag `capstone-v4` plus the safety-nets note and the settings file, from a clean checkout
- **Reviewer:** Claude Sonnet 5.5, in a fresh context with read-only tools. It did not write the code and was not shown the work logs, the homework files, the earlier reviews or any conversation. There was no colleague review for this session.
- **Run on:** 17 November 2026
- **Checklist given to the reviewer:** the session's five items: the check-in against the plan; CLAUDE.md, what changed and why; the skill; safety nets; one suggestion.

The reviewer's text follows unedited. My decision on each finding is in `Homework/Week 8/W8L1.md`.

---

Findings are worst first. I opened every file cited, except `docs/reviews/`, `Work Logs/`, `Homework/`, `Slides/` and `external/`, which I left alone. I did not run anything.

**F1 [safety nets]** `docs/safety-nets.md:29` says `.claude/settings.json` "is enforcement", but the file is only a five-line deny list (`settings.json:3-10`). It does not stop `git push --force-with-lease`, `git push origin +branch`, or a bare `git push` while on `main`. Prefix rules such as `Bash(git push origin main:*)` also miss reordered arguments. It does not stop `cat .env`, grep or `make shell` reading the key. Nothing enforces the AGENTS rules on docker, curl and gh. Suggested change: say "partial" in the document, and add deny rules for `Bash(cat*.env*)`, `Bash(gh *)`, `Bash(curl *)` and `Bash(docker *)`.

**F2 [the skill]** The blind-review skill claims blindness, but nothing enforces it. `referee.md:4` and the skill's brief grant Read, Grep and Glob over the whole machine. The forbidden paths are only prose, and `settings.json` does not deny `Work Logs/` or `Homework/`. The skill's post-check (`SKILL.md:42`) runs `git status`, which sees writes, not reads. Suggested change: add `Read` denies for those paths and have the reviewer list every file it opened, then grep that list for forbidden paths.

**F3 [the skill]** `docs/skill-test.md:29-32` shows 5/5 with the skill and 5/5 without it, so the test has a ceiling and cannot separate the conditions. Both controls were contaminated (`:34`), the turn counts (6.2 against 8.0) have n=5 and no spread, and the raw outputs are not committed (`:3`). The firing test (`:11-16`) has three positives and one near miss, with no without-skill baseline. The conclusion "kept, because it fires without a search" is weakly supported. Suggested change: add near misses such as "review my PR" and "summarise review 2", and commit the raw outputs.

**F4 [the check-in]** The check-in's `live-walk` line quotes "live walk: PASS", but `tests/live_walk.py:87-93` only prints a NOTE when the engine falls back, and the walk still passes. `README.md:24` says the recording stops matching after NVIDIA's next filing. So PASS does not mean a judged run, and the line is time-bound. Suggested change: make `expect(judged)` fail the walk, and put the expiry in the check-in.

**F5 [the check-in]** The `backup && restore-check` line cites `record-20261117T123824Z.sqlite` with "5 runs, 2 decisions, 1 theses". `backups/` is gitignored (`.gitignore:9`) and empty in the checkout. The record is probably walk data, and `restore_check` compares the backup with the live store (`backup.py:210`). The command is real, but the output cannot be confirmed from the repository. A restore into a running app is not tested. Suggested change: label it "same disk, same machine" and drop the specific counts.

**F6 [the check-in]** The check-in's "what failed" leaves out five things the repository shows. The first is the API key pasted into a conversation, which needs rotating (`safety-nets.md:24`). The second is the unknown listener on `*:8088` (`:38`). The third is the golden set, drafted by a model and unread, whose `expected` stances are only the model's reading (`eval/README.md:3-8`). The fourth is the stale `-B` instruction (`eval/README.md:28`), although `eval` is in `.PHONY` (`Makefile:1`). The fifth is that `make eval` needs `eval/cache`, which is gitignored and has to be fetched from EDGAR first (`eval/README.md:20`), so the "fresh clone" retrieval line is not offline. Suggested change: add these to section 2.

**F7 [the check-in]** The "what works" figures `805 passed` and `33 passed` cannot be checked. I count 529 `def test_` in `tests/` and 22 in `uitests/test_dom.py`, which parametrisation could explain. The `make probe` figures (13 of 14, 95.8% to 99.4%) have no committed record, because `results/` is gitignored. The recall figures are confirmed (`eval/results/retrieval-claim-2026-11-17.md:10-12`). Suggested change: commit the probe summary.

**F8 [the check-in]** The check-in is dated "at tag `capstone-v4`" but cites a retrieval eval that the plan puts in milestone 5 (`Capstone/README.md:31`). The plan's milestone-5 exit checks are not met: recall is reported for one variant, not "per retrieval variant", and there is no second-model check and no refusal of unanswerable claims. Section 3 says nothing is cut for milestone 5, and only 6 is "at risk". The plan still promises both. Suggested change: mark milestone 5 as partial in `Capstone/README.md`.

**F9 [the agent notes]** `Capstone/README.md:7` calls PROMPT.md the prompt "for the current milestone", but it is the milestone-2 prompt (`PROMPT.md:1`). Several AGENTS.md lines either carry no project knowledge or are inherited from a different project. The "scientist would call a result (a fit, a unit conversion…)" invariant (`AGENTS.md:44-46`) and most of lines 1-72 are course boilerplate. "Never put a personal name in the User-Agent" (`:103`) is visible in `.env.example` and `edgar.py`. Suggested change: delete the lines an agent can already see in the code.

**F10 [the agent notes]** `AGENTS.md:68` and `:71` direct an agent to `make verify-fresh`, but the root `Makefile:1` has no such target, nor `replay`, `backup`, `probe` or `eval`. The root `Makefile:9` forwards only a fixed list. From the root these commands fail. Suggested change: state "run from `Capstone/evidence_desk`", or forward the missing targets.

**F11 [the skill]** Procedures that repeat but are not skills: the re-baseline of the golden tripwire (`testing.md` "When a new baseline is legitimate", `AGENTS.md:90`); the "parser or figures change means probe on eight companies plus three fixtures" checklist (`AGENTS.md:96`); and re-recording a cassette. `AGENTS.md:96-99` also holds lessons that read as procedure. Suggested change: make a `rebaseline` skill first.

**F12 [the skill]** The skill's independence claim fails against the project's own admission. `safety-nets.md:67` says the builder, the stand-in and the reviewers are all Claude models, and "foreign-model review" is used as a trigger phrase (`skill-test.md:15`). Suggested change: rename the skill's claim to "another instance", or use a different vendor once.

## The most likely wrong answer that looks right

A claim is paraphrased, BM25 does not return the decisive passage (it is in the eight shown for only 7 of 24 cases, `eval/results/...md:11`), and the engine judges it on weaker verified quotes. Every mechanical gate passes, because the quote is real and the verdict follows from the findings. The page then shows "Supported" or "Mixed" on a partial reading, and only a reader who opens the filing can catch it.

## One suggestion

Make a human read the 30 golden cases and fix the `expected` stances, then add a second retrieval variant such as claim+queries and re-measure. The cost is about two hours of reading, plus a re-run of `make eval` once the filings are cached. This turns the main measurement from a model's guess into an answer key and also tests the cut "reranking first".

## What I could not judge from the repository alone

- Whether the 805 and 33 test counts, the `make probe` coverage percentages, or the backup counts were real output, since those artifacts are gitignored.
- Whether a quote that passes the gate means what the finding says, or whether the golden stances are right. Only someone who knows the filings can say.
- Whether `.claude/settings.json` was in force during the unattended session, and what the process listening on `*:8088` is.
