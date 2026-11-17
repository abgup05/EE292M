# Findings that cite a filing's own tagged figures (milestone 10)

Version 9 read revenue by segment, product and geography and customers' shares from each filing's inline XBRL and showed them in a view of their own ([`breakdowns.md`](breakdowns.md)). A finding could not cite them, so the three claims of the example that are about a segment, a customer and a region were judged without the figure each is about. Version 10 lets a run ask for them.

`POST /api/runs` takes `tagged_figures` (true or false, false by default); the page has a checkbox for it with the other options; `make run ARGS='example --tagged-figures'` and `make replay ARGS='--cassette demo/cassettes/nvda-example-tagged --tagged-figures'` do the same from the command line. Code: `core/tagged_figures.py` (pure), `services/tagged_figures.py`. No model is involved in reading or choosing the figures.

## What a run does with the option on

1. **Which filings.** The newest annual report and the newest quarterly report among the filings the run read. Their primary documents are fetched again, because the cache keeps a filing's parsed text and the tags are only in the HTML.
2. **Which figures.** For every row of every breakdown: its value in the breakdown's newest period, and its change from the same period a year earlier where the record has one. Each is a figure with an id of its own, `tagged:<breakdown>:<member>:<period>:<end>` or `...:change:<period>:<end>`, the same on every run of the same filing. A breakdown tagged only for the year to date is left out, and a note says so. A breakdown's total is not offered: the company-wide figure is already among the others.
3. **How many.** At most 40 (`MAX_TAGGED_FIGURES_OFFERED`). When the filings hold more, members are taken largest first across every breakdown at once, the newer filing first among members of the same place, and a value always goes with its change. NVIDIA's two filings give 52; 40 are offered, and a note on the run says so.
4. **Where they go.** After the company-facts figures in the engine's prompt, and into the run's record with them. So the citation gate, the number check, the page and the Markdown brief treat a citation of a tagged figure exactly as they treat any other: the id must have been offered, and every number in the statement must be in a quote or in a figure the finding cites.
5. **When it fails.** A filing whose tags cannot be read gives a reason naming the filing, the run goes on with the rest, and its status is partial. It never raises.

## Why it is off by default

A recorded model answer belongs to the exact prompt it answered. The figures change the assessment prompt of every claim, so a run with the option and a run without it are two different questions, and every recording made before version 10 would stop matching if the option were on. With it off, a run asks byte for byte what it asked before: the tripwire's recorded run and the first recording replay unchanged, which `make verify` checks.

A second reason is cost in attention. Forty more figures are forty more things the model can cite beside a claim, relevant or not.

## Two recordings made to see what it changes

On 17 November 2026 the example thesis was recorded twice, the same day, by the same stand-in models, each given one request under a neutral name and told only to answer it: once without the option ([`nvda-example-plain`](../demo/cassettes/nvda-example-plain/README.md)) and once with it ([`nvda-example-tagged`](../demo/cassettes/nvda-example-tagged/README.md)). Both use the plan already recorded for the identical prompt, so both search with the same queries and each claim is shown the same passages. `make replay` on each gives:

| | Without | With the tagged figures |
| --- | --- | --- |
| Figures offered | 37 | 37 and 40 tagged |
| Citations of figures in verified findings | 8 | 20 |
| Findings that cite a tagged figure | none | 6: 5 verified, 1 withheld |
| Findings verified, withheld | 18, 0 | 18, 1 |
| Numbers in statements checked; not found | 22; 0 | 35; 1 |
| Verified findings with no excerpt, figures only | 1, counted as context | 3: two counted as support, one as context |
| Verdicts, claims 1 to 5 | supported, supported, supported, mixed, mixed | supported, supported, supported, mixed, supported |
| Status | complete | partial |

**What the figures were used for.** Under "data center revenue is still growing": tagged Data Center revenue of $193.74B for the fiscal year, up 68.2%. Under "a small number of customers": the two customers at 22% and 14% of revenue beside the quoted sentence, and three at 25%, 18% and 13% of accounts receivable, which no passage shown to the engine states. Under "export controls on sales to China": revenue tagged under the geography member labelled "China Including Hong Kong", $19.68B for the fiscal year, down 21.4%. In the recording without the option, the only figure cited under the China claim was the whole company's revenue growth.

**What the recording found wrong in this project's own check.** The first replay withheld two findings. One said "at fiscal year-end 2026, Customer One was 25%...", and the number check read 2026 as a quantity that nothing cited contained. The three percentages had each matched a cited figure. That was a false alarm in the check, fixed with a test, and it is why two requests of the recording were asked a second time (its README says which).

**What is still withheld**, correctly by the rule and against a true statement: a finding ends "in the second quarter of fiscal year 2026 two customers represented 23% and 16%". The sentence is in a passage the engine was shown, but the finding did not quote it, and the tagged figure it cited says 16%. One number in 35 broke the rule that a statement's numbers are in what the finding itself cites; the stand-in had not been reminded of that rule.

## Limits

- **Nothing here shows that the option changes a verdict.** The verdict on claim 5 differs between the two recordings and no finding under claim 5 cites a tagged figure. Between the control and the first recording of the very same prompts, the verdict on claim 3 differs. With one answer per prompt, asking again moves a verdict as much as the option does.
- **A cited figure is not checked for relevance.** A finding that cites figures and quotes nothing passes the number check and is then read by the second model; nothing else stands between it and the verdict. With the option on, three verified findings are of that kind and two count as support. The first referee's example (a company-wide figure set against a claim about China) is this case; the tagged figures make it more common and, here, more relevant.
- **The labels are made from tag names.** "TW" and "US" for country members, "China Including Hong Kong" as the tag spells it. The figure's note says so on the page and in the brief. A member attached to the wrong label would not be noticed outside NVIDIA's annual report, where the tests compare tagged values with the filing's text.
- **A customer's number is a position in the filing's list**, "Customer One", not a named customer, and not shown to be the same customer from one period to the next.
- **One company.** The option has been run on NVIDIA, on recorded and on live filings (`make live-walk`). The breakdowns behind it were run on sixteen filings of eight companies; the figures built from them were not.
- **The answers are a stand-in's**, Claude Sonnet 5.5 and Claude Haiku 5.5 as Claude Code subagents, because the Anthropic API refused every call from this project for lack of credit. The API path with the option on has never run.
- **Forty is a guess.** It keeps the three largest members of every NVIDIA breakdown in both filings. Whether a model reads 77 figures as well as 37 was not measured.
