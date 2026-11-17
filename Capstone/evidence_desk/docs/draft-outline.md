# Outline for the draft write-up (due 30 November 2026)

*Prepared on 17 November 2026 by the Claude Code session that ran the catch-up, from what the repository can show today. An outline, not the draft: the draft is mine to write. Every number here has a command behind it in the README; the ones marked "to redo" depend on work only I can do.*

## The one sentence

For an equity analyst who has to decide whether a thesis still holds after a new filing, Evidence Desk tests each claim against the company's own SEC filings and reported figures, and shows for every verdict the exact passages and figures it rests on.

## 1. The problem, for whom, and how you would know

- A thesis is a short list of claims. Each quarter the question is which of them a new filing supports, challenges or does not address.
- A fluent answer with a citation that does not say what it claims is worse than no answer.
- How you would know it works: every quote is in the filing; every number is in the evidence; the figures match published values; a golden set says how often the right passage is found and the verdict agrees.

## 2. What it does (one figure: the result screen)

Ticker, decision, claims in; verdicts first; each finding opens to its passage; reported figures with their arithmetic; accept or reject; save a thesis and see what moved; what changed between two filings. Under each claim, what changed in the filings since the one before. Segments, geographies and customers from the filing's own tags.

## 3. How it is built (one figure: the system drawing)

- A pure core with adapters around it; one pipeline; two entry points.
- The boundary: everything a reader would call a result is computed by the backend.
- The layers that catch a wrong result, and the hole in each (the table in `docs/safety-nets.md`).

## 4. Results, each with its evidence

| Claim in the draft | Evidence today | State |
| --- | --- | --- |
| Every quote shown is an exact span of a passage the engine was shown | The gate's tests; 84 of 84 on the golden set; 18 of 18 on the recorded run, and again 18 of 18 when it was recorded with no reminder of the rule | Holds, for the parser's rendering of the filing |
| Every number in a finding or its reason is in its evidence | The number check's tests; it withheld 1 of 79 findings on the golden set, and 1 of 19 in the recording with tagged figures | Holds, with stated blind spots: a year is never checked, and a third referee found two false passes that are now tests |
| The reported figures are right | 28 published values for three companies match; a probe on eight companies | Holds for those 28. On 17 November the probe found the figures wrong for three of the eight (a year in weeks, twelve months taken for a fiscal year, a bank's revenue); fixed, each with a test |
| Retrieval finds the passage that matters | 18 of 24 in the top eight with the planner's queries; 9 of 24 without | **To redo** once I have read the golden cases |
| The verdict agrees with a careful reading | 20 of 24; no reversal; 6 of 6 unanswerable claims refused | **To redo**, same reason; and re-recording alone moved it by three cases |
| A second model catches misreadings of real findings | It withheld 1 of 78 findings and changed no verdict | Not shown. Same model family as the engine |
| It tells you what changed between filings | The planted-paragraph test; every line of two real filings counted exactly once; run on eight companies' annual reports; pairs near the threshold read by a model for three | No person has read a comparison; in template-built sections about 3 in 10 borderline pairs are wrong; table rows are counted, never shown |
| It shows what is new that bears on each claim | The planted-paragraph test; on the recorded example the first paragraph under "Gross margin is expanding" is an added sentence saying it decreased | A keyword match. Nobody has judged the lists; between 126 and 276 changes share two words with each claim or its search queries and five are shown |
| A second model rejects evidence that does not fit | 150 of 152 planted mismatches rejected, none accepted; 1 of 76 true pairs rejected | The easy kind of mismatch, answered by a stand-in. The hard kind is not measured |
| It reads segment, geography and customer figures from the filing's tags | Checked against NVIDIA's own text; members add up to the tagged total on sixteen filings of eight companies | Labels come from tag names; no table compared with the printed one by a person |
| A finding can cite those figures | Two recordings of the example made the same day, without and with the option: five verified findings cite a tagged figure, citations of figures go from 8 to 20 | That it changes a verdict is not shown: asking the same prompts again moved one too. One company, stand-in models |

## 5. What failed, and what it taught

The schedule. An idea with no reader. A model that could not be called. A parser tested on one company. Two rules about figures that real data broke. A speed claim that did not hold. A referee who found three faults in tested code. A skill that changed nothing because the documentation already did its job. A filing comparison finished on one company, which could not compare a bank at all until the other seven were run. A headline table whose columns counted different things, found by a second referee and by none of 1,094 tests.

## 6. Limits, stated plainly

The model path has not run through the API since October. The golden set is a model's reading. The second model is not independent. Tables are flattened. The link into a filing is unverified in a browser. The record has one disk. No colleague has reviewed this, and I have not reviewed theirs.

## 7. What I have to do before 30 November

1. Read the thirty golden cases (`eval/golden-reading.md` lays them out, the four disputed ones first); correct them; re-run `make eval`.
2. Get API credit or a key that works; record the cassettes again through the API; re-measure the quote rate without a stand-in.
3. Use the tool on a thesis of my own and write down where it was wrong.
4. Read five reworded pairs and five added paragraphs of a filing comparison for a company other than NVIDIA.
5. Ask a colleague to review it, and review theirs.
6. Read the three files the claims rest on: `core/gate.py`, `core/numcheck.py`, `core/policy.py`.
