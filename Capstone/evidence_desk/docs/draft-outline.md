# Outline for the draft write-up (due 30 November 2026)

*Prepared on 17 November 2026 by the Claude Code session that ran the catch-up, from what the repository can show today. An outline, not the draft: the draft is mine to write. Every number here has a command behind it in the README; the ones marked "to redo" depend on work only I can do.*

## The one sentence

For an equity analyst who has to decide whether a thesis still holds after a new filing, Evidence Desk tests each claim against the company's own SEC filings and reported figures, and shows for every verdict the exact passages and figures it rests on.

## 1. The problem, for whom, and how you would know

- A thesis is a short list of claims. Each quarter the question is which of them a new filing supports, challenges or does not address.
- A fluent answer with a citation that does not say what it claims is worse than no answer.
- How you would know it works: every quote is in the filing; every number is in the evidence; the figures match published values; a golden set says how often the right passage is found and the verdict agrees.

## 2. What it does (one figure: the result screen)

Ticker, decision, claims in; verdicts first; each finding opens to its passage; reported figures with their arithmetic; accept or reject; save a thesis and see what moved; what changed between two filings.

## 3. How it is built (one figure: the system drawing)

- A pure core with adapters around it; one pipeline; two entry points.
- The boundary: everything a reader would call a result is computed by the backend.
- The layers that catch a wrong result, and the hole in each (the table in `docs/safety-nets.md`).

## 4. Results, each with its evidence

| Claim in the draft | Evidence today | State |
| --- | --- | --- |
| Every quote shown is an exact span of a passage the engine was shown | The gate's tests; 84 of 84 on the golden set; 18 of 18 on the recorded run | Holds, for the parser's rendering of the filing |
| Every number in a finding or its reason is in its evidence | The number check's tests; it withheld 2 of 79 findings on the golden set | Holds, with stated blind spots |
| The reported figures are right | 28 published values for three companies match | Holds for those; other figures are self-consistent only |
| Retrieval finds the passage that matters | 18 of 24 in the top eight with the planner's queries; 9 of 24 without | **To redo** once I have read the golden cases |
| The verdict agrees with a careful reading | 20 of 24; no reversal; 6 of 6 unanswerable claims refused | **To redo**, same reason; and re-recording alone moved it by three cases |
| A second model catches misreadings | It withheld 1 of 77 findings and changed no verdict | Not shown. Same model family as the engine |
| It tells you what changed between filings | Run on NVIDIA's annual and quarterly reports | One company; no check of the classification by a person |

## 5. What failed, and what it taught

The schedule. An idea with no reader. A model that could not be called. A parser tested on one company. Two rules about figures that real data broke. A speed claim that did not hold. A referee who found three faults in tested code. A skill that changed nothing because the documentation already did its job.

## 6. Limits, stated plainly

The model path has not run through the API since October. The golden set is a model's reading. The second model is not independent. Tables are flattened. The link into a filing is unverified in a browser. The record has one disk. No colleague has reviewed this, and I have not reviewed theirs.

## 7. What I have to do before 30 November

1. Read the thirty golden cases; correct them; re-run `make eval`.
2. Get API credit or a key that works; record the cassettes again through the API; re-measure the quote rate without a stand-in.
3. Use the tool on a thesis of my own and write down where it was wrong.
4. Ask a colleague to review it, and review theirs.
5. Read the three files the claims rest on: `core/gate.py`, `core/numcheck.py`, `core/policy.py`.
