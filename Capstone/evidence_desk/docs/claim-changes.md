# What changed that bears on each claim (milestone 8)

A thesis run reads a company's latest annual report and the quarterly reports after it, and gives a verdict per claim. The comparison of two filings (milestone 6) says what a company added, removed and reworded. This joins them: **for each claim of a run, the paragraphs that changed in the filings the run read, ranked by how many of the claim's words they share.** It answers the question the tool exists for: what is new since the last filing that I should read before I trust this claim again?

`GET /api/runs/{run_id}/changes` returns the record (`RunChanges`, `core/claim_change_models.py`); the page shows it under each claim. Code: `core/claim_changes.py` (pure), `services/claim_changes.py`. No model is called to make the list, and nothing in it is a verdict. Its inputs are the claim and the search queries the run wrote for that claim, which a model wrote when the engine is Claude.

## What it is, and what it is not

It is keyword retrieval. A paragraph is listed under a claim because it shares words with the claim or with the search queries the run wrote for that claim. That says nothing about whether the paragraph supports or challenges the claim, and the page says so beside every list. The findings above it are a model's reading that passed two mechanical checks; this list is a reading list.

## Method

1. **Which filings.** For each form among the filings the run actually read (10-K, 10-Q), the newest one it read is compared with the filing of the same form filed immediately before it. The run itself did not read that earlier filing: it is fetched for the comparison, and every "removed" paragraph comes from it. For a run that read one quarterly report, the filing before it is the previous quarterly report, which after a first quarter is the third quarter of the year before; the two period ends are shown. The pair is fixed by the run's own filing, found by its accession number, not by "the two latest now": a run made last quarter gives the same list after the company files again.
2. **Which paragraphs.** Every changed paragraph of those comparisons, with no list cut: added (text of the later filing), removed (text of the earlier one), reworded and numbers-only (the later paragraph of the pair).
3. **The score.** BM25 over those paragraphs as the corpus. A paragraph's score for a claim is its best score over the claim's text and its stored queries, the same rule the run's own retrieval uses.
4. **The rule.** A paragraph is listed only if it holds at least two distinct content terms taken from the claim's text and its queries together (stemmed, stop words dropped, digit-only tokens not counted, so a shared year is never enough). So a paragraph can pass on one word of the claim and one of a query, or on two words of the queries alone. The third referee pointed out that every sentence here used to say "two words of the claim". The five best are listed, best first. The record keeps how many paragraphs were searched and how many passed the rule.
5. **Repeats.** A filing often prints the same paragraph under two Items. A claim's list holds it once and names the other Items.
6. **When it cannot be done.** No earlier filing of a form, a filing that has left EDGAR's index, EDGAR out of reach, or a run still going: each is a sentence in the record's `notes`, never an error, and the other comparison is still made.

The two constants (`MIN_SHARED_TERMS` 2, `MAX_CHANGES_PER_CLAIM` 5) sit at the top of `core/claim_changes.py`.

## On the recorded example, 17 November 2026

`make sample-run-changes` computes the record for the page's sample run (five claims about NVIDIA, three filings) against live EDGAR and writes `src/web/sample-run-changes.json`. The annual report for fiscal 2026 is compared with the one for fiscal 2025, and the quarterly report for the second quarter of fiscal 2027 with the one for the first.

The two comparisons hold 802 changed paragraphs. For each claim:

| Claim | Listed | Distinct changes sharing two words with the claim or its queries | Paragraphs sharing two such words (repeats counted) | Changed paragraphs searched |
| --- | ---: | ---: | ---: | ---: |
| c1 | 5 | 276 | 291 | 802 |
| c2 | 5 | 138 | 146 | 802 |
| c3 | 5 | 160 | 177 | 802 |
| c4 | 5 | 126 | 129 | 802 |
| c5 | 5 | 173 | 180 | 802 |

So the rule alone lets through between 126 and 276 changes per claim; what the reader sees is the ranking's first five.

What it lists first under each claim, as found in the filings:

| Claim | First changed paragraph listed | Kind |
| --- | --- | --- |
| Data center revenue is still growing year over year | "Data Center revenue was $75.2 billion, up 92% from a year ago and up 21% sequentially" (the earlier 10-Q), then "Data Center revenue was $89.0 billion, up 117% from a year ago and up 18% sequentially, driven by the ramp of our Blackwell Ultra infrastructure." (the later one) | removed, then added |
| A small number of customers account for a large share of revenue | the risk factor "We have experienced periods where we receive a significant amount of our revenue from a limited number of customers", then "For fiscal year 2026, sales to one direct customer represented 22% of total revenue and sales to another direct customer represented 14% of total revenue" (10-K; printed under Item 7 and again under Item 15, listed once) | reworded, then added |
| Export controls on sales to China are restricting revenue | "In April 2025, the USG informed us that a license is required for exports of our H20 product into the China market. As a result of these requirements, we incurred a $4.5 billion charge" (10-K) | added |
| Gross margin is expanding | "Gross margin decreased in fiscal year 2026 as our business model transitioned from offering Hopper HGX systems to Blackwell full-scale datacenter solutions." (10-K) | added |
| The company depends on a limited number of suppliers | a paragraph about vendor risk assessment under Item 1C, then "We continue to increase our supply and capacity purchases with existing and new suppliers" | reworded, removed |

The fourth row is the feature doing its job: the newest annual report added a sentence that contradicts the claim as written, and it is the first thing listed under that claim. The fifth row is the feature's limit: the first hit shares "supplier", "third", "party" and "depend" with the claim and is about cybersecurity questionnaires.

## Limits

- **Keyword overlap is not relevance.** The rule is permissive on purpose: on the example between 126 and 276 distinct changes share two words with each claim or its queries, and only the five best are shown. A paragraph that bears on a claim in other words is not found.
- **Nobody has judged these lists.** No person has read them and no model has scored them. The page marks the block as a keyword match that no one has checked.
- **The comparison's own limits carry over**: what counts as a paragraph, the threshold for "reworded", table rows that are counted and never shown (`filing-changes.md`).
- **Old runs.** The filing before the run's is looked for among the twelve latest filings of that form which EDGAR lists, and EDGAR's older index pages are read only when its recent index holds fewer than two of the form. A run whose filing is older than that gets a note in place of a comparison.
- **In the Markdown brief it is a reading list, set apart.** `export.md?changes=true` adds it after the claims under a paragraph that says it is not findings; the page's download links ask for it.
