# The reference pack

The outside view (base rates, peer standing) and the market view (valuation, implied growth)
read data that is not about the one company a run tests: SEC's XBRL frames, one body per
concept and year with every filer in it, and three managers' Form 13F tables. Fetched during a
run they are hundreds of megabytes and several minutes. On a host that keeps nothing on disk
between starts, every run began with an empty cache, both views ran out of their time budgets,
and the analysis had no base rate, no peer and no valuation: the live Costco run of 18 November
2026 is the example.

The pack is that data, fetched once and shipped with the app as package data in
`src/app/reference/`, so that every checkout and every copy of the app has it with no request.

## What is in it

- `frames.json.gz`. For each concept the outside view reads (`core/frames.FRAME_GROUPS`) and each
  calendar year from 2009 to the newest year SEC's frames held when it was built: the value of
  every filer that **ever reported annual revenue of at least $100 million**, with the period
  it is for. That floor is the floor of the outside view's industry class, so a class read from
  the pack has the members it has read live; a smaller filer is in no class. For each filer:
  its name and its SEC industry code (SIC) as its submissions index gave them that day.
- `prices.json.gz`. For each of the three managers (`sources/thirteenf.MANAGERS`): its newest
  8 Form 13F-HR filings, each with its accession number, the quarter it reports, the date it
  was filed, and every share position (issuer, class, CUSIP, value, shares). A quarter-end
  price is derived from them exactly as from the filed table, and cross-checked between
  managers as before.
- `manifest.json`: when it was built, the command, the counts, each file's size and SHA-256,
  and each 13F filing in it.

It holds no accession number for a frame value (SEC's frames carry one; the pack drops it for
size), so an input of a base rate names its frame and not a filing. Nothing in the pack is
computed: it is SEC's values, fewer of them.

## How it is read

`sources/reference.py`. `PackFrames` and `PackThirteenF` stand in front of the live sources:

- a frame the pack read is answered from it, at once; a frame it does not have (a year newer
  than the pack) is asked of EDGAR, inside the provider's time budget, and kept in the cache;
- an industry's members are the pack's filers with that code;
- a company the pack does not list (it never reported $100 million of revenue) is read live
  throughout, because its own rows are not in the pack;
- a manager's 13F filings are the pack's when the run's date is on or before the day the pack
  was built. For a later date EDGAR is asked for the manager's index, so that a 13F filed since
  is found; a table the pack holds is never fetched.

**A date is still exact.** Frames are admitted by year as before (`core/frames.admitted_years`).
A 13F counts only when it was filed on or before the run's date, so a run as of a past date
gets the price of the quarter whose filing was public by then, not the newest in the pack.

Every analytic that read the pack says so in its note, with the pack's date. The offline
examples (`make examples-analysis`, `make market-examples`) do not read it: they keep their own
small recorded fixtures, so that rebuilding the pack does not change them or the recorded model
answers that were given their figures.

## What a stale pack means for a reader

The pack is a photograph of EDGAR on the day it was built.

- **Restatements.** SEC's frames hold each filer's latest value for a period. A value restated
  after the pack was built is in the pack as it stood. (Read live, the outside view has the
  same limit in the other direction: frames carry no filing date, so a past date sees today's
  values. `docs/outside-view.md` says so.)
- **A new fiscal year.** About four months after a calendar year ends the outside view admits
  that year. A pack built before then does not hold it, so those frames are fetched live, within
  the 20-second budget; when they do not arrive, the provider is recorded as failed for that run
  and the base rates are missing, as before the pack existed. Rebuild the pack each spring.
- **A new quarter's price.** Each manager files a 13F about six weeks after a quarter ends. For
  a date after the pack's, the newer filing is looked for live; if EDGAR does not answer, the
  price is the pack's newest and the note says a newer filing was not looked for. Either way the
  note gives the price's date. A price is at most one quarter-end old when the pack is fresh and
  older by as long as the pack is stale.
- **Industry codes** are those of the build day. A filer that changed code since is still under
  its old one.
- **A filer new to the list**, one that first reported $100 million of revenue after the pack
  was built, is in no class until the pack is rebuilt, and as the run's own company it is read
  live.

## Refreshing it

    make reference-pack

Live, through the app's EDGAR client and its rate limit. The first build asks for about 255
frames, one submissions index for each of several thousand filers (the slow part, most of an
hour) and 24 13F tables; everything fetched is kept under `data/cache`, so a build that is
interrupted, or run again later, asks only for what it does not have. Delete
`data/cache/frames` first to pick up restated values, and `data/cache/reference/profiles.json`
to pick up changed industry codes. Then read `src/app/reference/manifest.json`, run
`make test T=tests/test_reference_pack.py`, and commit the three files together. A good time is
after each quarter's 13F filings (mid-February, mid-May, mid-August, mid-November) and at least
once after the spring's 10-Ks.

## Not verified

- The pack's numbers were not compared, class by class, with the same views read live from
  EDGAR; `tests/test_reference_pack.py` checks that a frame read from a pack parses to the rows
  SEC gave, on made-up frames, and that the shipped pack gives both views to a cold run.
- How long a run's providers take when a frame is missing from the pack and fetched live.
