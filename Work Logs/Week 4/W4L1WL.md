# EE292M Work Log

## Week 4A: Capstone Plan (12 October 2026)

**Capstone plan**

- Chose Evidence Desk from the three pitches in `Capstone/idea pitches.md`: a research tool that turns one question and decision into a brief whose findings trace to exact source passages.
- Wrote the plan in `Capstone/README.md` (why it is worth doing, first working result, milestones, risks, frontend/backend boundary) and the coding-agent prompt in `Capstone/PROMPT.md` (scope, data contract with a real seed case, research method, acceptance checks).
- Put the backend boundary after citation verification so the API, the export and the page all show the same checked findings.

**Takeaway**

Writing the acceptance checks first made the riskiest piece obvious: tying a generated finding to a passage the tool actually retrieved. That became milestone one.
