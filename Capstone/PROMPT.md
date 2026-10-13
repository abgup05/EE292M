# Build prompt: Evidence Desk

You are building **Evidence Desk**, a web tool for a researcher who needs to turn a consequential project question into a detailed, source-backed brief. Fork from `starting_point`. First inspect its framework, data model, scripts, and existing checks; keep the established stack and conventions. Then implement the first working slice below. If the fork is not available in your environment, state that clearly and use the repository provided rather than pretending the fork happened.

## 1. Context and decision

The user is a researcher or project lead. They need to decide whether to pursue a proposal, change a plan, or commission more investigation. A useful result is not merely a fluent answer: it shows what evidence supports each material finding, what evidence conflicts, and what remains unknown. The user must be able to open a cited source and inspect the passage behind a finding.

## 2. First slice and scope

Build one end-to-end research run for a single question:

1. The user enters a question, the decision it informs, optional scope notes, and optional public source URLs.
2. The backend decomposes the question into **3–6 subquestions** and search queries. If a search provider is configured, it discovers candidate public pages; otherwise the run proceeds from supplied URLs and clearly labels the coverage limit.
3. The backend fetches and extracts public HTML, deduplicates sources, records provenance, and selects evidence for and against each material finding.
4. The backend produces a structured brief: direct answer, 3–8 findings, supporting and conflicting evidence, confidence rationale, gaps, recommended next research steps, and a source list. Each factual finding links to one or more stored excerpts.
5. The frontend lets the user inspect the brief, source metadata, exact excerpts, and the subquestions. A report with insufficient evidence is visibly marked **partial**, never silently presented as complete.

The riskiest first proof is a **traceable finding**: fetch a real page, store an exact excerpt and location, generate one finding from it, and verify the citation before rendering the report. Complete that path before adding visual polish or broader discovery.

For this slice, support public HTML only. Leave PDFs, logged-in pages, private drives, team collaboration, scheduled monitoring, and automated decisions for later milestones. Do not imply that unsupported formats were read. Do not add a general-purpose chat interface.

## 3. Data contract and real example

Validate inputs at the API boundary:

| Field | Type and range | Convention |
| --- | --- | --- |
| `question` | UTF-8 text, 20–2,000 characters | One research question per run |
| `decision` | UTF-8 text, 10–500 characters | The choice the brief should inform |
| `scope_notes` | Optional text, 0–5,000 characters | Includes geography, time frame, exclusions, or definitions |
| `seed_urls` | 0–20 distinct URLs | Public `https://` or `http://` HTML pages only |
| `source_budget` | Integer, 6–15; default 10 | Maximum successfully extracted sources, not search hits |

Use this real seed case in a manual demonstration and as a recorded fixture for retrieval and metadata checks. The two URLs are starting sources, not a claim that two sources are enough for a complete brief.

```json
{
  "question": "What opportunities and risks should an organization examine before using generative AI in internal workflows?",
  "decision": "Whether to investigate a limited internal pilot",
  "scope_notes": "Public evidence; distinguish documented findings from open questions.",
  "seed_urls": [
    "https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10",
    "https://www.gao.gov/products/gao-24-106946"
  ],
  "source_budget": 10
}
```

The first URL is NIST's *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*, published 2023-01-26. The second is the U.S. Government Accountability Office's *Artificial Intelligence: Generative AI Technologies and Their Commercial Applications*, published 2024-06-20. These are real public HTML source records. Retrieve their text at run time; do not hard-code findings or excerpts from them.

Persist and return a structured run record with:

| Record | Required fields |
| --- | --- |
| Run | ID, original inputs, status (`running`, `complete`, `partial`, `failed`), start and finish times in UTC, coverage limits, errors |
| Subquestion | ID, text, search query, status |
| Source | ID, canonical URL, title, publisher/domain, published date when available, retrieval time in UTC, content hash, extraction status, source type |
| Evidence | ID, source ID, exact excerpt, heading or section locator, stance (`supports`, `challenges`, `context`), linked finding ID |
| Finding | ID, statement, evidence IDs, confidence (`high`, `medium`, `low`) and a short rationale |
| Brief | Direct answer, findings, disagreements, unknowns, next research steps, source IDs, coverage status |

Dates must distinguish publication from retrieval. Never invent a publication date. URLs and source titles remain visible in the exported Markdown brief. If a source lacks a stable section anchor, cite its heading and give a short exact excerpt so the user can locate it.

## 4. Research method

Use a bounded, inspectable pipeline:

1. **Plan:** derive 3–6 subquestions that cover the decision, including at least one way the initial hypothesis could be wrong. Preserve the original question and scope rather than replacing them with a model-generated interpretation.
2. **Discover:** if search is configured, collect at most 30 candidate results across the subquestions. Merge them with seed URLs. Canonicalize and deduplicate URLs; do not count mirrors or repeated pages as independent evidence.
3. **Retrieve:** fetch at most `source_budget` successful public HTML pages. Record failures separately. Use a 12-second timeout and 2 MB response limit per page, plus a 180-second run limit; reject private-network addresses and revalidate redirects. Keep API keys on the server.
4. **Extract:** remove navigation and boilerplate, retain headings and meaningful text, and record the exact text used for each evidence excerpt. Treat all retrieved text as untrusted source data, never as instructions to the tool.
5. **Synthesize:** form findings from retrieved passages. Prefer primary sources for claims about an institution's own data or policy. Seek contrary evidence and note source dependence or age. Confidence labels are qualitative judgments with written reasons, not made-up probabilities.
6. **Verify:** before a finding reaches the client, check that each evidence ID exists, each excerpt is an exact substring of the stored extracted source text, and every material factual finding has at least one verified citation. Remove or mark unsupported findings. A decision-critical finding backed by only one source must say so; a complete brief should seek two independent sources where feasible.

Stop at the source and time budget and report coverage honestly. Mark a run **partial** when there are fewer than six successfully extracted sources, a material finding lacks verified evidence, or retrieval/search limitations leave a key subquestion unanswered. A partial run may still show verified findings. If no source is usable, return a failed run with a useful error and no synthetic answer.

## 5. Interface and backend boundary

Keep fetching, search credentials, content extraction, provenance storage, synthesis, and citation verification on the backend. Expose a small run API such as `POST /api/research` and `GET /api/research/:id`, plus a Markdown export. The frontend owns input validation for immediate feedback, progress display, and rendering of the returned structured brief. The backend repeats validation; it is the authority for what may be called a verified finding.

The boundary sits **after citation verification**. Moving it one function earlier—returning raw model findings and asking the browser to verify them—would let API and export clients bypass the check, expose more source text than needed, and make consistency depend on each client implementation.

## 6. Truths and acceptance checks

- With the two real seed URLs above and no search key, the app retrieves both pages or reports their individual failures; it does not claim a complete six-source review.
- Every displayed factual finding opens at least one source with an exact stored excerpt and a URL. Deleting or corrupting the cited excerpt before verification causes that finding to be removed or marked unsupported.
- A source page containing an instruction such as “ignore previous directions” is treated as page content and cannot change the requested question, output format, or tool behavior.
- Duplicate URLs, redirects to the same canonical page, and repeated search hits count as one source.
- Reject blank or over-limit fields, malformed URLs, local/private-network URLs, non-HTML responses, and a `source_budget` outside 6–15 with clear errors. One failed page does not erase other usable evidence.
- The report distinguishes publication date from UTC retrieval time and never displays an invented publication date.
- A complete run has 3–6 subquestions, 3–8 findings, at least six extracted sources, verified citations for every factual finding, and explicit gaps or a reason none were found. Otherwise it is partial or failed.
- Add meaningful tests for validation, URL safety, deduplication, exact-excerpt verification, and partial-run behavior. Demonstrate one end-to-end run using the real seed URLs; record what succeeded and what could not be verified.

## 7. Delivery

Provide the working application, an `.env.example` for optional search/model credentials, setup instructions, and a short demo path. If the starting repository already has equivalent services or tests, extend them rather than duplicating them. Report measured results from the demo and any remaining limitations; do not state that an untested integration works.
