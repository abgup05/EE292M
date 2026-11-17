# EE292M Work Log

## Week 5A: Evidence Desk Stage One (19 October 2026)

**Building the first slice**

- Built the first working version of Evidence Desk in `Capstone/evidence_desk` from the prompt, on the Week 2 app's stack: FastAPI backend, static frontend, Docker Compose on `127.0.0.1:8766`, everything through the Makefile. The `starting_point` fork named in the prompt does not exist, so that was stated and the repository's own conventions were used.
- Implemented the full run: subquestions, bounded retrieval with URL safety, extraction with section locators and metadata, synthesis (Claude when a key is set, otherwise a deterministic extractive mode), citation verification, a structured brief, Markdown export, and a frontend that renders findings with their exact excerpts.
- Wrote every module test-first; `make verify` runs lint, 110 offline tests and a live smoke test, and passes from a fresh clone.
- Ran the real seed case. The NIST page was retrieved with its publisher and publication date from metadata; the GAO page returned HTTP 403 and was recorded as a failed source. The run is marked partial, with 4 findings whose excerpts are verified exact substrings.
- The verification gate caught a real bug on the first demo: the extractor dropped the NIST abstract, Claude drafted findings whose excerpts were not in the stored text, and all 3 were withheld. Fixed the extractor with a failing test first; the next run verified 4 of 4.

**Status**

Stage one. Public HTML only, seed URLs or a search key required, single-source findings flagged. Next: discovery without a Brave key, and more than one source per finding.

**Takeaway**

The "boring" check — is this excerpt really in the stored page text? — did more for quality than any prompt change. It turned a silent extraction bug into a visible, explained result.
