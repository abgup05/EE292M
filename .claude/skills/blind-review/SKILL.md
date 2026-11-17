---
name: blind-review
description: Runs a blind review of a tagged version of the Evidence Desk capstone by a model that did not write it, against one course session's checklist, and saves the reviewer's text unedited under docs/reviews. Use when the user asks for a blind, independent or foreign-model review of the capstone, of a version or of a tag, or asks to get a session's review done. Not for finding bugs in a diff or a pull request (use /code-review), and not for a hostile referee (use the referee agent).
argument-hint: "[tag] [structure | message-tests | speed-system | check-in-safety]"
---

# Blind review

A review is only worth having if the reviewer could have disagreed. These steps keep the
reviewer from agreeing by construction. Do them in order.

1. **Fix the version.** `$ARGUMENTS` may name a tag; with none, use the newest
   `capstone-v*` tag. If the tag does not exist, stop and say so. If the working tree has
   commits or edits after the tag, say that the review covers the tag, not them.
2. **Make a clean checkout** of that tag with
   `git worktree add .claude/worktrees/review-<tag> <tag>`. The reviewer reads that path
   and nothing else, so work can continue in the main checkout while it reads.
3. **Pick the checklist.** `reference/checklists.md` holds the four session checklists,
   quoted from the course slides. If the request does not say which, ask once.
4. **Start one reviewer as a subagent** on a model that did not write the code. The code
   here is written by Claude Opus sessions, so use `sonnet`. Its brief contains only:
   - the checkout path and the checklist, word for word;
   - read-only: Read, Grep and Glob; no edits, no git, no make, no docker;
   - forbidden paths: `Work Logs/`, `Homework/`, `Slides/`, `external/`,
     `Capstone/evidence_desk/docs/reviews/`, and anything outside the checkout;
   - the output: numbered findings, worst first, each with a file and line it opened and
     one suggested change; no praise; a word limit; and a closing list of what it could
     not judge from the repository alone.
   Never put your own opinion of the code, the plan, or what you expect it to find into
   the brief. Never show it an earlier review.
5. **Save its text unedited** as
   `Capstone/evidence_desk/docs/reviews/review-<n>-<topic>.md`, under a header that states
   the session, the version reviewed, the reviewer model, that it was blind and read-only,
   the date it ran and the checklist. Add a row to `docs/reviews/README.md`.
6. **Hand the findings to the user for triage.** Each one is built in or answered in one
   line of `Capstone/README.md` with the reason. Decisions go in the session's hand-in
   under `Homework/`, not in the review file.
7. **Remove the checkout** with `git worktree remove .claude/worktrees/review-<tag>`.

## Checks before you report

- `git -C .claude/worktrees/review-<tag> status --short` printed nothing after the review.
  If the reviewer changed a file, discard the review and say so.
- Every finding cites a file that exists at that tag.
- The saved file contains the reviewer's words only below the header.

## When to stop

- The tag does not exist, or the checklist is not one of the four and the user has not
  supplied another.
- The reviewer returned fewer than three findings with a file and line: run it once more
  with the same brief, then report what you have.

## What this does not do

It does not replace a colleague who knows the field. A model reviewer checks the work
against its own README; it cannot say whether the tool is useful to a real analyst.
