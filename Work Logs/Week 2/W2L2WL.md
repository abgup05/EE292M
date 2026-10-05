# EE292M Work Log

## Week 2B: Visualization and Capstone Research (30 September 2026)

Work completed for the October 5 deadline.

**Visualization app**

- Built the Industry Flow Explorer to investigate what U.S. industries buy and which industries buy a particular product category. The idea connects to my research work at RD2 / Radius, where understanding input costs and customer markets can help guide company research.
- Started with the NYSE classification workbook and an illustrative supply-chain map, but the fixed links were not especially useful. Reworked the app around official BEA Supply–Use data covering 1997–2025, with 71 buying industries and 73 product categories.
- Added purchase rankings, comparisons between years, changes in spending share, interactive historical charts, and CSV export. Kept industry-level relationships separate from claims about individual companies, and made the data limitations visible.
- Checked the calculations against small examples and the source workbook, tested the app in the browser, and prepared the Vercel deployment files. Added the homework description in `Homework/Week 2/W2L2.md`, with a placeholder for the website link. Deployment is still pending.

**Capstone ideas research**

- Explored three directions: a company relationship graph with source evidence, an investment thesis change tracker, and a tool for researching shared exposures and historical shocks.
- Considered the data each would need, how to keep the scope manageable, and how to evaluate whether the output is accurate and useful. Public filings and company announcements could support company-specific relationships; BEA data provides broader industry context.
- Drafted the three pitches in `Capstone/idea pitches.md`. The relationship graph is the current recommendation because it could turn the visualization into a practical research tool with citations and a review process for proposed links.

**Takeaway**

A visualization is more useful when it answers a concrete question with traceable data. The biggest improvement was moving from a plausible-looking map to relationships whose size and history can actually be inspected.
