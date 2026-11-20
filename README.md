# EE292M

Coursework for EE292M, AI-Augmented R&D.

## Capstone: Evidence Desk

[Evidence Desk](Capstone/README.md) tests the claims of an investment thesis against a company's own SEC filings. You give it a ticker, a decision and the claims your thesis rests on; it returns a verdict for each claim with the exact filing passages behind it, verified on the server before they reach the page. The plan is in [`Capstone/README.md`](Capstone/README.md), the current build prompt in [`Capstone/PROMPT.md`](Capstone/PROMPT.md) and the application in [`Capstone/evidence_desk/`](Capstone/evidence_desk/README.md).

Run `make up`, then open the loopback URL it prints. Docker selects an available port from 8766 through 8769. To request a specific port, run `make up EVIDENCE_DESK_PORT=8876`. `make verify` builds the container, lints, runs the offline tests and checks the live API. `make down` stops the app.

Each milestone is a tag (`capstone-v1`, `capstone-v2`, ...). To open one, `git checkout <tag>` and run `make up`; the table of versions is in the capstone plan.

## Which version to open for each week

For peer review, one version of the capstone per week of the course. Each link opens that version itself, running live in the browser; the tag is the code behind it.

| Week | Version | Open it | Code | What it shows that the one before did not |
| --- | --- | --- | --- | --- |
| Week 4 | 6 | <https://ee292m-visualization.vercel.app/v6/> | [`capstone-v6`](https://github.com/abgup05/EE292M/tree/capstone-v6) | What changed between two filings: added, removed and reworded risk factors and moved numbers |
| Week 5 | 8 | <https://ee292m-visualization.vercel.app/v8/> | [`capstone-v8`](https://github.com/abgup05/EE292M/tree/capstone-v8) | Those changes ranked under each claim of the thesis |
| Week 6 | 10 | <https://ee292m-visualization.vercel.app/v10/> | [`capstone-v10`](https://github.com/abgup05/EE292M/tree/capstone-v10) | Segment, geography and customer tables from the filing's own tags, and findings that cite them |
| Week 7 | 12 | <https://ee292m-visualization.vercel.app/v12/> | [`capstone-v12`](https://github.com/abgup05/EE292M/tree/capstone-v12) | The 8-Ks filed since the annual report, and how old a run's evidence is |
| Week 8 | 13.1 | <https://ee292m-visualization.vercel.app/v13/> | [`capstone-v13.1`](https://github.com/abgup05/EE292M/tree/capstone-v13.1) | The page as a workspace that fills the window, and a standing watch on a saved thesis |
| Week 9 | 14.3 | <https://ee292m-visualization.vercel.app/v14/> | [`capstone-v14.3`](https://github.com/abgup05/EE292M/tree/capstone-v14.3) | Claims computed as tests and an analysis on every run: base rates, peer ranks, what the price implies, and an argument audited sentence by sentence |

These are the versions shared for each week's review, not a record of when each was built: that, with the session each version was built for and every other version, is in [`docs/versions.md`](docs/versions.md) and in the table of sessions below. On the website a new run works for NVIDIA and the other tickers its recorded company list holds (AAPL, MSFT, BRK-B, KO); the samples each page offers open for any visitor. To run a version on your own machine with any ticker: `git checkout <tag>`, `make up`, then <http://127.0.0.1:8766>.

## Week 2: Industry Flow Explorer

The [Week 2 Industry Flow Explorer](Homework/Week%202/visualization/README.md) visualizes official BEA purchases between product categories and U.S. industries across 1997–2025. Run `make APP=week2 up`, then open <http://127.0.0.1:8765>.

## Sessions, hand-ins and versions

`Homework/` holds the hand-in for each session and `Work Logs/` the work log. The [three capstone pitches](Capstone/idea%20pitches.md) are in `Capstone/`. One row per course session; the slide decks themselves are not in this repository. The same history one row per capstone version, with each version's review and its recorded snapshot on the website, is [`docs/versions.md`](docs/versions.md).

| Session | Date (2026) | Slides | What the session's work was | Hand-in | Work log | Version to open |
| --- | --- | --- | --- | --- | --- | --- |
| 1B |  | w01-b | Something Claude got wrong | [W1L2](Homework/Week%201/W1L2.md) | [W1L2WL](Work%20Logs/Week%201/W1L2WL.md) |  |
| 2A |  | w02-a | A data set, explored | [W2L1](Homework/Week%202/W2L1.md) | [W2L1WL](Work%20Logs/Week%202/W2L1WL.md) |  |
| 2B | 30 Sep | w02-b | Industry Flow Explorer | [W2L2](Homework/Week%202/W2L2.md) | [W2L2WL](Work%20Logs/Week%202/W2L2WL.md) | `make APP=week2 up` |
| 3A | 5 Oct | w03-a | Visualization problem set | none in the repository | [W3L1WL](Work%20Logs/Week%203/W3L1WL.md) |  |
| 3C | 7 Oct | w03-b | Check-in | none in the repository | [W3L3WL](Work%20Logs/Week%203/W3L3WL.md) |  |
| 4A | 12 Oct | w04-a | Capstone plan | none in the repository | [W4L1WL](Work%20Logs/Week%204/W4L1WL.md) |  |
| 4B | 14 Oct | w04-b | Plan reviews and stage one | [W4L2](Homework/Week%204/W4L2.md) | [W4L2WL](Work%20Logs/Week%204/W4L2WL.md) |  |
| 5A | 19 Oct | w05-a | Review of the code's structure | [W5L1](Homework/Week%205/W5L1.md) | [W5L1WL](Work%20Logs/Week%205/W5L1WL.md) | reviewed: [`capstone-v1`](https://github.com/abgup05/EE292M/tree/capstone-v1) |
| 5B | 21 Oct | w05-b | The version that answers the structure review: filings and claims | [W5L2](Homework/Week%205/W5L2.md) | [W5L2WL](Work%20Logs/Week%205/W5L2WL.md) | [`capstone-v2`](https://github.com/abgup05/EE292M/tree/capstone-v2) |
| 6A | 26 Oct | w06-a | Review of the message, the interface and the tests | [W6L1](Homework/Week%206/W6L1.md) | [W6L1WL](Work%20Logs/Week%206/W6L1WL.md) | reviewed: [`capstone-v2`](https://github.com/abgup05/EE292M/tree/capstone-v2) |
| 6B | 28 Oct | w06-b | The version that answers it: reported numbers with an answer key, tests at four levels | [W6L2](Homework/Week%206/W6L2.md) | [W6L2WL](Work%20Logs/Week%206/W6L2WL.md) | [`capstone-v3`](https://github.com/abgup05/EE292M/tree/capstone-v3) |
| 7A | 2 Nov | w07-a | Review of the speed, the system and what cannot be rebuilt | [W7L1](Homework/Week%207/W7L1.md) | [W7L1WL](Work%20Logs/Week%207/W7L1WL.md) | reviewed: [`capstone-v3`](https://github.com/abgup05/EE292M/tree/capstone-v3) |
| 7B | 4 Nov | w07-b | The version that answers it: reviewer decisions, saved theses, backup; a skill; the check-in | [W7L2](Homework/Week%207/W7L2.md) | [W7L2WL](Work%20Logs/Week%207/W7L2WL.md) | [`capstone-v4`](https://github.com/abgup05/EE292M/tree/capstone-v4) |
| 8A | 9 Nov | w08-a | Review of the check-in, the agent notes, the skill and the safety nets | [W8L1](Homework/Week%208/W8L1.md) | [W8L1WL](Work%20Logs/Week%208/W8L1WL.md) | reviewed: [`capstone-v4`](https://github.com/abgup05/EE292M/tree/capstone-v4) |
| 8B | 11 Nov | w08-b | A hostile referee, and measured retrieval with a second-model check | [W8L2](Homework/Week%208/W8L2.md) | [W8L2WL](Work%20Logs/Week%208/W8L2WL.md) | [`capstone-v5`](https://github.com/abgup05/EE292M/tree/capstone-v5) |
| 9A | 16 Nov | not in the repository | A second referee and a fifth blind review: what changed between two filings, and its counts corrected | [W9L1](Homework/Week%209/W9L1.md) | [W9L1WL](Work%20Logs/Week%209/W9L1WL.md) | [`capstone-v6`](https://github.com/abgup05/EE292M/tree/capstone-v6), [`capstone-v7`](https://github.com/abgup05/EE292M/tree/capstone-v7) |
| 9B | 18 Nov | not in the repository | Changes under each claim, tagged segment and customer figures, findings that cite them, a check of the year a finding names; the 8-Ks since the annual report, a standing watch and the page redesigned, dated facts and claims computed as tests; a workspace page and an analysis on every run with an outside and a market view (versions 13.1 and 14.2), every version live on the site; a third, a fourth, a fifth, a sixth and a seventh referee, the last two answered in version 14.3 and a sixth review | [W9L2](Homework/Week%209/W9L2.md) | [W9L2WL](Work%20Logs/Week%209/W9L2WL.md) | [`capstone-v8`](https://github.com/abgup05/EE292M/tree/capstone-v8), [`capstone-v9`](https://github.com/abgup05/EE292M/tree/capstone-v9), [`capstone-v10`](https://github.com/abgup05/EE292M/tree/capstone-v10), [`capstone-v11`](https://github.com/abgup05/EE292M/tree/capstone-v11), [`capstone-v11.1`](https://github.com/abgup05/EE292M/tree/capstone-v11.1), [`capstone-v12`](https://github.com/abgup05/EE292M/tree/capstone-v12), [`capstone-v13`](https://github.com/abgup05/EE292M/tree/capstone-v13), [`capstone-v14`](https://github.com/abgup05/EE292M/tree/capstone-v14), [`capstone-v14.1`](https://github.com/abgup05/EE292M/tree/capstone-v14.1) |

To see the versions side by side: `make versions-up` starts versions 1 to 11, and `make versions-up VERSIONS="12 13 14"` the later ones, each from its own checkout of its tag and on its own port, version N at `http://127.0.0.1:87NN` (version 3 at <http://127.0.0.1:8703>); `make up` starts the newest, version 14.3, at the URL printed by Make. `make versions-status` asks each which version it is, and `make versions-down` stops them. Each keeps its data under its own checkout in `.claude/worktrees/`, so none reads or writes the newest version's record. To open one version alone instead: `git checkout capstone-v5` (any tag), then `make up`; `git checkout -` goes back. From version 3 on, `http://127.0.0.1:8766/?sample` shows a recorded run without the network or a key. What each version added, with its exit check and its caveats, is the milestone table in the [capstone plan](Capstone/README.md).

The website, <https://ee292m-visualization.vercel.app>, is the Week 2 app. It also runs each capstone version live at `/vN/` (`/v13/` is version 13.1 and `/v14/` is version 14.3) and serves the table of versions at `/versions`. How that is done, what guards the key there and what differs from running a version locally are in [`docs/site-live.md`](docs/site-live.md): each version's source is copied into the site with `make site-version N=… REF=…`, tested under a local emulation of the function, and deployed when the change is merged to `main`; `make site-check URL=https://ee292m-visualization.vercel.app` asks the deployed site which versions are live.

Docker and Make are required; all dependencies stay inside containers. `AGENTS.md` holds the rules for this repository.
