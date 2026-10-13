# Evidence Desk — capstone plan

Evidence Desk is a proposed research workbench for turning an open-ended project question into a decision brief whose findings can be checked against source passages. It is meant for a researcher or project lead making a real choice: whether to proceed, revise a plan, or investigate further. The deliverable is a detailed answer with traceable citations, conflicting evidence, and visible gaps.

These files contain the plan and the [coding-agent prompt](PROMPT.md); the proposed application has **not** been built. The prompt is the implementation brief for a fork of `starting_point`.

## Why it is worth doing

Deep research often fails at the last step: a polished summary is difficult to audit, and a citation may point to a page that does not support the stated claim. Evidence Desk makes the source passage a first-class part of the result. The researcher can inspect how a conclusion was reached, see where sources disagree, and decide whether the evidence is strong enough to act on. The tool is useful across topics because it takes the user's question, decision, and scope as inputs rather than embedding one domain's assumptions.

## First working result

The first version accepts one question, one decision, optional scope notes, and public HTML links. A configured search provider can add sources. The application plans 3–6 subquestions, retrieves up to the selected budget of 6–15 distinct sources, and returns a brief with 3–8 findings when evidence permits. Each factual finding must link to an exact excerpt from a stored source. When fewer than six sources are available or a key question remains unresolved, the brief says **partial** and explains why.

A real demonstration starts with the public [NIST AI Risk Management Framework](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10) and [GAO technology assessment](https://www.gao.gov/products/gao-24-106946). These seed links test retrieval, metadata capture, and citation tracing. They are not prewritten answers.

## Milestones

| Milestone | Reviewable result | Exit check |
| --- | --- | --- |
| 1. Provenance proof | One real HTML page becomes a stored source, exact excerpt, verified finding, and clickable citation | Altering the excerpt invalidates the finding |
| 2. Research run | Question form, 3–6 subquestions, multiple sources, synthesis, and partial-run state | A two-source seed run is marked partial and explains coverage |
| 3. Discovery and export | Optional web search, deduplication, source budget, and Markdown brief | A run shows source counts, failures, and traceable exported citations |
| 4. Hardening | Input and URL safeguards, failure recovery, and focused tests | Invalid URLs and source instructions cannot redirect the run |

The first milestone tackles the main uncertainty: whether generated conclusions can be tied to passages the application actually retrieved. Later work can add PDFs, private collections with permission controls, saved projects, comparison across runs, and scheduled updates.

## Main risks

| Risk | How the first version handles it |
| --- | --- |
| A citation looks plausible but does not support the claim | Store exact source excerpts; verify they exist in the extracted text; show the excerpt beside the finding |
| Search and retrieval leave blind spots | Show failed pages and unanswered subquestions; mark insufficient coverage partial |
| Several pages repeat one underlying source | Canonicalize URLs and flag source dependence; do not count duplicates as corroboration |
| Retrieved pages contain adversarial instructions | Treat page text as data and keep it separate from tool instructions |
| Slow, costly, or blocked retrieval | Bound candidate results, source count, time, and response size; retain usable evidence from partial runs |

## Frontend and backend boundary

The backend owns search access, page retrieval, extraction, source records, synthesis, and citation verification. It returns a structured brief only after checking that cited excerpts exist in the stored pages. The frontend collects inputs and renders run progress, findings, excerpts, and export actions.

The boundary is deliberately after verification. If verification moved one function earlier into the frontend, a direct API or Markdown export could publish unchecked findings, and different clients could disagree about whether a citation was valid. Server-side verification gives every output path the same rule.

## Scope and success

The first version covers public HTML pages and one research run at a time. PDF parsing, authenticated sources, collaboration, monitoring, and automated decisions are later work. Success means a reviewer can start a run, inspect how each factual finding maps to a real passage, and see a clear partial result when the available evidence is thin. The app should never fill missing evidence with a confident-sounding claim.
