# EE292M Work Log

## Week 5B: Clarity by Design (lecture of 21 October 2026)

**How the work was done**

- I had fallen behind after the first implementation. I gave a Claude Code session one brief: turn the capstone into a real financial research tool, work through each session's homework in order, and keep a record. It ran unattended. This log is drafted by that session from what it did; the decisions are mine to check.
- One session planned and verified. Claude Opus sessions wrote the code. Claude Sonnet, in a fresh context, reviewed each version blind. None of the reviewers saw the planning conversation.

**The structure review (Week 5A homework)**

- Reviewed `capstone-v1` with a model that did not write it, against the session's four items. Ten findings, kept unedited in `Capstone/evidence_desk/docs/reviews/review-1-structure.md`; decisions in `Homework/Week 5/W5L1.md`.
- The finding that mattered most was the messaging: the reviewer could say what the tool did but not who it was for or how anyone would know it worked.

**The new version (Week 5B homework), tag `capstone-v2`**

- Narrowed the project to testing the claims of an investment thesis against SEC filings. Rewrote `Capstone/README.md` and `Capstone/PROMPT.md` first.
- Wrote the contracts before any module: the record types, the document shapes, the interfaces, one file for every limit and one for the verdict and status rules. Four sessions then built against them in parallel: the EDGAR client and filing parser; chunking, BM25 and the engines; the quote gate, the store and the export; the page. A fifth integrated them and wrote the pipeline tests.
- Removed the open-web question mode and the Brave search backend. It was never tested against the live API.
- `make verify` green with 385 offline tests. Live demo on NVIDIA: 3 of 3 filings, 636 passages, 15 of 15 quotes verified, 3.2 s.

**What went wrong**

- Both API keys were refused for lack of credit, so the model engine never ran live. The run fell back, said so, and came out partial, which is the designed behaviour, but it means the demo shows no judged verdict.
- The integration found seven bugs in the pipeline, which the planning session had written without tests. Among them: a failed filing index made the denominator shrink, so extra pages alone could look like a full reading; a duplicate source counted as unreadable; claims skipped by the time limit were labelled "no evidence found".
- The parser was tested on one company. A probe of seven others found two layouts it does not handle (Costco, JPMorgan). Recorded as a known limitation in the README; fixed in the next version.

**Status**

Version 2. Reads real filings and verifies quotes. No judged verdicts without model credit, no reported numbers, no measurement of retrieval.

**Takeaway**

Writing the contracts first is what let four sessions build at once without stepping on each other. But the bugs were all at the seams the contracts did not describe: what a count means when something upstream fails.
