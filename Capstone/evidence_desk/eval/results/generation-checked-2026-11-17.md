# Generation evaluation

Model answers: replayed from cassette golden: 79 responses recorded via Claude Code subagent standing in for the Anthropic API (no API credit on 2026-11-17); minimal wrapper, no reminders of the engine's rules, Claude Code subagent standing in for the Anthropic API (no API credit on 2026-11-17); minimal wrapper, no reminders of the rules and Claude Code subagent standing in for the Anthropic API, which refused every call for lack of credit on 2026-11-17 with claude-haiku-5-5 and claude-sonnet-5-5, 2026-11-17 to 2026-11-17.

A recording answered by a stand-in (any `via` other than the model a run calls) is an upper bound for quote validity: a stand-in that copies from the prompt in front of it quotes more exactly than a model may, so the quote and citation scores may be lower live.

Generated 2026-11-17T18:10:27.890242+00:00. Each case is run as a one-claim thesis with the decision "Whether the thesis still holds after the latest filings"; the gate and the verdict rule are the pipeline's own.
Golden set SHA-256 `4ef5c8d35bf11a1e…`; queries from `eval/queries.json` (SHA-256 `7609070a134303ab…`).
The meaning check ran: a second model read every case's verified findings through the same cassette (step `check`), as a run would.

Reported figures offered with every claim:

- NVDA: 37 figures from the XBRL facts (fixture, SHA-256 5b264d77a76a...)
- COST: 36 figures from the XBRL facts (cache, SHA-256 b675ced201b2...)
- AAPL: 37 figures from the XBRL facts (cache, SHA-256 f085735b4d08...)
- MSFT: 37 figures from the XBRL facts (cache, SHA-256 8c1903c041f5...)
- KO: 38 figures from the XBRL facts (cache, SHA-256 87a4173fcd3d...)

## Answerable cases (24)

| Score | Value | Cases |
|---|---|---|
| Verdict agreement | 83.3% | 20 / 24 |
| where a must-retrieve passage was offered | 77.8% | 14 / 18 |
| where none was offered | 100.0% | 6 / 6 |
| Cites a must-retrieve passage (verified excerpt holds half of it) | 62.5% | 15 / 24 |
| where a must-retrieve passage was offered | 83.3% | 15 / 18 |
| where none was offered | 0.0% | 0 / 6 |

Expected stance (rows) against the verdict obtained (columns):

| Expected | supported | challenged | mixed | unjudged | not_addressed | Cases |
|---|---|---|---|---|---|---|
| supports | 10 | 0 | 2 | 0 | 0 | 12 |
| challenges | 0 | 8 | 2 | 0 | 0 | 10 |
| mixed | 0 | 0 | 2 | 0 | 0 | 2 |

## Unanswerable cases (6)

| Score | Value | Cases |
|---|---|---|
| Refusal (no verified finding, verdict not_addressed) | 100.0% | 6 / 6 |

## All cases (30)

| Count | Value | Of |
|---|---|---|
| Quotes verified (located in the stored text) | 84 | 84 / 84 offered |
| Quotes rejected | 0 | 0 / 84 offered |
| Excerpts kept as evidence (verified findings only) | 83 |  |
| Numbers unmatched | 2 | 2 / 68 checked |
| Findings verified | 78 | 78 / 79 proposed |
| Findings withheld | 1 | 1 / 79 proposed |
| withheld: a number in the statement is not in its quotes or cited figures | 1 | 1 / 1 withheld |
| Reported figures cited by verified findings | 14 |  |
| Model answers that could not be parsed | 0 | 0 / 30 cases |
| Cases with no passage offered (model not asked) | 0 | 0 / 30 cases |

## The meaning check

A second model read each verified finding's excerpts and cited figures, without the engine's rationale or confidence. A finding it judged not supported drops out of the verdict; one it judged partly supported is kept. Agreement is over the answerable cases.

| Score | Value | Of |
|---|---|---|
| Findings checked | 78 | 78 / 78 verified |
| supported (passed) | 67 | 67 / 78 checked |
| partly supported (kept) | 10 | 10 / 78 checked |
| not supported (failed, withheld) | 1 | 1 / 78 checked |
| Findings left unchecked (the check could not run) | 0 | 0 / 78 verified |
| Verdict agreement before the check | 83.3% | 20 / 24 |
| Verdict agreement after the check | 83.3% | 20 / 24 |
| Disagreeing cases that now agree | 0 | 0 / 4 disagreeing before |
| Disagreeing cases that still disagree | 4 | 4 / 4 disagreeing before |
| Agreeing cases the check broke | 0 | 0 / 20 agreeing before |

## How to read it

Verdict agreement and citation are over the answerable cases; refusal over the unanswerable ones; the counts over every case. A must-retrieve passage was offered when a passage holding half of one of the case's excerpts was among the passages the model saw; where none was, a wrong verdict is a retrieval failure first. Only verified findings count: a withheld finding never makes a verdict or a citation. Citing a must-retrieve excerpt is a strict test: a correct answer may cite other evidence.

## Per case

| Case | Ticker | Expected | Obtained | Must-retrieve passage | Cited it | Findings verified / withheld | After the meaning check |
|---|---|---|---|---|---|---|---|
| nvda-data-center-drives-growth | NVDA | supports | supported | not offered (rank 20) | no | 4 / 0 | supported (4 supported, 0 partly, 0 failed) |
| nvda-few-buyers-dominate | NVDA | supports | supported | offered #7 of 8 | no | 4 / 0 | supported (4 supported, 0 partly, 0 failed) |
| nvda-china-reopened | NVDA | challenges | challenged | not offered (rank 15) | no | 3 / 0 | challenged (2 supported, 1 partly, 0 failed) |
| nvda-margin-widened | NVDA | supports | mixed | offered #2 of 8 | yes | 3 / 0 | mixed (3 supported, 0 partly, 0 failed) |
| nvda-cash-returned | NVDA | supports | supported | offered #6 of 8 | no | 4 / 0 | supported (4 supported, 0 partly, 0 failed) |
| nvda-no-borrowing | NVDA | challenges | challenged | offered #3 of 8 | yes | 4 / 0 | challenged (2 supported, 2 partly, 0 failed) |
| nvda-commitments-small | NVDA | challenges | challenged | not offered (rank 20) | no | 3 / 0 | challenged (2 supported, 1 partly, 0 failed) |
| nvda-custom-silicon-threat | NVDA | supports | supported | not offered (rank 23) | no | 2 / 0 | supported (1 supported, 1 partly, 0 failed) |
| nvda-crypto-lawsuit-over | NVDA | challenges | challenged | offered #2 of 8 | yes | 4 / 0 | challenged (4 supported, 0 partly, 0 failed) |
| nvda-workforce-unionising | NVDA | none | not_addressed | n/a | n/a | 0 / 0 | nothing to check |
| cost-members-renew | COST | supports | mixed | offered #5 of 8 | yes | 4 / 0 | mixed (4 supported, 0 partly, 0 failed) |
| cost-markup-widened | COST | mixed | mixed | offered #1 of 8 | yes | 3 / 0 | mixed (3 supported, 0 partly, 0 failed) |
| cost-tariffs-unrecovered | COST | challenges | mixed | offered #1 of 8 | yes | 4 / 0 | mixed (3 supported, 1 partly, 0 failed) |
| cost-north-america-dependence | COST | supports | supported | not offered (not in top 50) | no | 2 / 0 | supported (2 supported, 0 partly, 0 failed) |
| cost-franchising | COST | none | not_addressed | n/a | n/a | 0 / 0 | nothing to check |
| aapl-china-shrinking | AAPL | challenges | challenged | offered #1 of 8 | yes | 2 / 0 | challenged (2 supported, 0 partly, 0 failed) |
| aapl-margin-runway | AAPL | mixed | mixed | offered #1 of 8 | yes | 3 / 0 | mixed (3 supported, 0 partly, 0 failed) |
| aapl-asian-assembly | AAPL | supports | supported | offered #1 of 8 | yes | 4 / 0 | supported (3 supported, 1 partly, 0 failed) |
| aapl-eu-app-store | AAPL | supports | supported | offered #1 of 8 | yes | 4 / 0 | supported (3 supported, 1 partly, 0 failed) |
| aapl-electric-car | AAPL | none | not_addressed | n/a | n/a | 0 / 0 | nothing to check |
| msft-azure-growth | MSFT | supports | supported | offered #7 of 8 | yes | 2 / 1 | supported (2 supported, 0 partly, 0 failed) |
| msft-cloud-margin | MSFT | challenges | mixed | offered #7 of 8 | yes | 4 / 0 | mixed (3 supported, 1 partly, 0 failed) |
| msft-ai-harm | MSFT | supports | supported | offered #1 of 8 | no | 4 / 0 | supported (4 supported, 0 partly, 0 failed) |
| msft-never-breached | MSFT | challenges | challenged | offered #2 of 8 | yes | 2 / 0 | challenged (1 supported, 0 partly, 1 failed) |
| msft-stock-split | MSFT | none | not_addressed | n/a | n/a | 0 / 0 | nothing to check |
| ko-north-america-volume | KO | challenges | challenged | offered #6 of 8 | yes | 3 / 0 | challenged (2 supported, 1 partly, 0 failed) |
| ko-pricing-lifts-margin | KO | supports | supported | offered #1 of 8 | yes | 3 / 0 | supported (3 supported, 0 partly, 0 failed) |
| ko-irs-dispute-settled | KO | challenges | challenged | not offered (not in top 50) | no | 3 / 0 | challenged (3 supported, 0 partly, 0 failed) |
| ko-cannabis-stake | KO | none | not_addressed | n/a | n/a | 0 / 0 | nothing to check |
| ko-bitcoin-treasury | KO | none | not_addressed | n/a | n/a | 0 / 0 | nothing to check |
