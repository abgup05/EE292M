# EE292M

Coursework for EE292M, AI-Augmented R&D.

## Capstone: Evidence Desk

[Evidence Desk](Capstone/README.md) tests the claims of an investment thesis against a company's own SEC filings. You give it a ticker, a decision and the claims your thesis rests on; it returns a verdict for each claim with the exact filing passages behind it, verified on the server before they reach the page. The plan is in [`Capstone/README.md`](Capstone/README.md), the current build prompt in [`Capstone/PROMPT.md`](Capstone/PROMPT.md) and the application in [`Capstone/evidence_desk/`](Capstone/evidence_desk/README.md).

Run `make up`, then open <http://127.0.0.1:8766>. `make verify` builds the container, lints, runs the offline tests and checks the live API. `make down` stops the app.

Each milestone is a tag (`capstone-v1`, `capstone-v2`, ...). To open one, `git checkout <tag>` and run `make up`; the table of versions is in the capstone plan.

## Week 2: Industry Flow Explorer

The [Week 2 Industry Flow Explorer](Homework/Week%202/visualization/README.md) visualizes official BEA purchases between product categories and U.S. industries across 1997–2025. Run `make APP=week2 up`, then open <http://127.0.0.1:8765>.

## Hand-ins

`Homework/` holds the hand-in for each session and `Work Logs/` the work log. The [three capstone pitches](Capstone/idea%20pitches.md) are in `Capstone/`.

Docker and Make are required; all dependencies stay inside containers. `AGENTS.md` holds the rules for this repository.
