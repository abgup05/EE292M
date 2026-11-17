# Standards for this repository

These rules apply to every task. How the project is built is described in
ARCHITECTURE.md: read it before creating or moving files, adding a dependency,
or changing anything in `docker/`, and keep it true when you change the design.

## Boundaries (these override everything else)

- NOTHING is installed on the host. No packages, tools, libraries, language
  runtimes or global configuration, by any means. If you believe a host
  install is truly unavoidable, stop, explain why no container-based
  alternative works, and wait for my explicit approval of that specific
  install. Expect the answer to be no.
- Every change on the host happens inside this repository. Nothing is written
  outside this directory tree. An agent's own memory or global instruction
  file is the only possible exception, and only when I have agreed.
- Powerful commands (docker, gh, curl, wget, and their like) run only inside
  Makefile targets. Never run them as one-off commands, and never tuck them
  inside a longer command or script. Anything run more than once (testing,
  validation, a data step) belongs in the Makefile; if a task needs a new
  command, add a target and say so.
- Secrets live in `.env`, which is gitignored; commit a `.env.example`.

## Git

- A new repository starts with one commit on `main`, made by me: at least a
  README. Branch from it.
- Work on your feature branch. Commit to it often, in small steps, each with a
  clear message. You may push it.
- `main` changes only through a pull request that I review and merge. Never
  commit to, merge into, or push to `main`.
- Merging into any branch other than your feature branch needs my explicit
  approval, every time. Approval for one merge is not approval for the next.
- Never force-push, rewrite published history, or change git configuration.

## Before you start

For any task that creates or changes more than one file, reply first with your
plan and the files you will touch, in under 40 lines, followed by your
assumptions and your questions. Wait for approval.

## Invariants (true after every change)

- Results are computed by the backend and delivered through the API. The
  frontend draws and handles interaction; it computes nothing a scientist
  would call a result (a fit, a unit conversion, a filter, a statistic).
- Everything the app needs is installed when the image is built, never while
  it runs.
- The app is published on `127.0.0.1` only.

## Running anything

Through the Makefile, and nothing else. `make help` lists the targets;
`make verify` is the gate.

## Quality

Follow current best practice for code quality, structure and security, and say
in the plan where you depart from it and why. Code a stranger can read, with
type hints and docstrings on anything public. Every input validated at the API
boundary, errors handled and never swallowed. No secrets in code, logs or
error messages, no `eval`, no shell built from user input. Add a dependency
only when it earns its place, and say why.

## Done means

- `make verify` is green from a fresh clone.
- Each pipeline has a test that fails when the result is wrong; show it
  failing once before you make it pass.
- The README is enough for a stranger, and ARCHITECTURE.md still describes the
  project.
- Say what you did not verify.

## This repository: what an agent could not find

*Drafted on 17 November 2026 from the corrections made during the catch-up sprint. Mine to curate: a line stays only if an agent could not have found it in the code.*

### Tooling

- Docker Desktop's credential helper is not on an agent's `PATH`. Prefix every make call: `PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH" make <target>`.
- `make verify-fresh` is the gate for a tag. It clones the committed branch, so untracked work in the tree can neither pass nor fail it. Every capstone target runs from the repository root or from `Capstone/evidence_desk`.
- `make up`, `smoke`, `uitest`, `screenshots` and `demo` all start the app on port 8766. When several agents work at once, exactly one of them may run these.
- An agent worktree created by the harness branches from `main`, which has no capstone app. Make one from the ref you mean: `git worktree add .claude/worktrees/<name> <tag-or-branch>`.

### Which data is the original

- `Capstone/evidence_desk/data/record/record.sqlite` holds runs, decisions and saved theses. Nothing can rebuild it. Never delete it; run `make backup` before a schema change and `make restore-check` after.
- `data/cache/` and `results/` are disposable.
- `demo/cassettes/` are recordings of model answers. Never edit a response by hand; record it again and say who answered.
- `tests/fixtures/edgar/` and `tests/golden/` are a baseline. Re-record or re-baseline only on purpose, and read which stage moved before committing it.
- `eval/golden.json` is an answer key. Never change an expected value to make a result pass; find out which of the two is wrong.

### Mistakes made more than once

- A count that survives a failure upstream. When a step can fail, check what every count and denominator after it then means.
- Testing on one company. A parser change is not done until `make probe` on the eight companies agrees, and a change to the reported figures until `make figures` on the same eight does, run before and after (`make probe` says nothing about figures: three of the eight were wrong for seven versions under it). A change that moves a company's figures invalidates the recorded answers of its golden cases; record them again (`Capstone/evidence_desk/eval/README.md`).
- Reporting a measurement the numbers do not support. Every number in a README or a docs file needs the command that produced it and its denominator; a speed claim needs a before and after measured alternately.
- Text shown to a model comes back as the model saw it. Whatever is escaped on the way in must be unescaped on the way out.
- XBRL `fy` and `fp` describe the filing, not the fact. Place a period by its dates.

### Never

- Never report a model-backed result without saying where the answers came from: the API or a cassette.

### Skills and agents in this repository

- A review of a version for a course session: use `/blind-review`, never an ad hoc reviewer prompt. The reviewer is another Claude model, not an independent party.
- Asked to attack the project's own claims: use the `referee` agent.
