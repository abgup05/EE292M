# The page's design

Evidence Desk's page is a research note read in a workspace: on a wide screen it fills the
window as a frame of panes (the claims in a rail, the selection under tabs, an inspector for
whatever is picked) and the page itself does not scroll; on a phone and on paper the same
markup is one column in reading order. It has one frame and one set of components, drawn in two
themes:

- **Paper** is a typeset note inside the frame: warm paper, ink, a serif for prose and claims,
  hairline rules, and small capitals for labels.
- **Terminal** is the same frame as a market terminal: near-black, a monospace for every label,
  number and control, an amber accent, a code before every title, and tighter rows.

Every rule in `src/web/styles.css` reads tokens only. The themes differ in their token values and
in a few rules scoped to `:root[data-theme="terminal"]`. The specimen page,
`src/web/specimen.html`, shows every component once on made-up data, except its version 14 parts,
which are excerpts of `docs/examples/v14`. It is linked from nowhere: open it at `/specimen.html`,
or see `docs/screenshots/specimen*.png` (`make screenshots`). Its note is the run view laid out
flat, every panel and docket at once as on paper, and its "frame" part draws the centre pane's
head, the tabs and the inspector with the page's own code. Its note was empty from version 13
until version 14: the page's code hid a view the specimen did not have.

## The boundary still holds

The page draws and computes nothing a scientist would call a result. Every verdict, count,
outcome, change, flip and percentile on it is a record field or wording from `/api/meta`.
Three things are drawing, not computing:

- the time line places record dates on an axis;
- a sparkline places a series' values in a box;
- a negative number is set in `--neg` from the sign of the record's own value or display string.

And one is navigation, not computing: the rail's selection and the tabs decide which of the
record's items are on screen (one claim's docket, one claim's lane, one tab's panel), and the
inspector which item is read at the side; with nothing picked it reads the first item the
record lists for that tab. No item is ranked, counted or filtered by a value.

Text from filings and from models is inserted as text, never as HTML.

## Themes and how one is chosen

The theme is `data-theme="paper|terminal"` on `<html>`. A small inline script sets it before the
first paint, and `app.js` owns it after that. It is chosen in this order:

1. `?theme=paper` or `?theme=terminal` in the address. This applies to one page load and is
   never stored; screenshots use it.
2. The reader's choice, from the toggle in the bar or the `t` key. It is stored under
   `localStorage["evidence-desk-theme"]` when the browser allows storage. Every read and write is
   wrapped in `try`, so the page works without storage.
3. The system: `prefers-color-scheme: dark` gives Terminal. With no stored choice, the page
   follows the system when it changes.

Without JavaScript, a dark system still gets the Terminal colours through
`@media (prefers-color-scheme: dark) :root:not([data-theme])`.

## Colour tokens: one meaning each

Colour is never the only signal: every mark also carries its glyph and its words.

| Token | Paper | Terminal | Meaning, and only this |
|---|---|---|---|
| `--bg` / `--surface` / `--surface-2` | #f2eee3 / #fbf9f3 / #ece6d8 | #07090c / #0d1116 / #151b22 | the page, the note's sheet, a raised row |
| `--ink` / `--ink-2` | #1d1b17 / #57524a | #e8e3d4 / #9ba4ae | text, secondary text |
| `--line` / `--line-strong` | #d9d1bf / #958c78 | #222b35 / #46525f | hairlines, rules |
| `--accent` | #1f4e8c ink blue | #ffad33 amber | selection and focus: the rail's selected row, the tab in use, the focus ring. Never a heading, a value or a rule. |
| `--link` | the accent | the ink, underlined | something you can click. In Terminal a link is ink, so amber stays selection. |
| `--support` | #1d6b3f | #62d28f | ✓ supported, a supporting finding, a test that holds |
| `--challenge` | #9a1f5a | #ff7ab8 | ✕ challenged, a challenging finding, a test that fails (± mixed shows both) |
| `--neutral` | #575c64 | #a4acb6 | ? not judged (dashed), ∅ not addressed, • context, tags about the page |
| `--limit` | #8a5800 | #f0dc5a | ▲ a limit of the record, including evidence an 8-K postdates |
| `--model` | #5a3fb8 | #b9a3ff | the glyph ✎ of "written by a model", and ◎ ◐ of a second model's reading; the words beside it are dim, with no box |
| `--reject` | #b3261e | #ff6b6b | ! the server refused your input |
| `--rule` | #586112 | #b5cc6a | the glyph ƒ of "computed by a fixed rule"; the words beside it are dim, with no box |
| `--change` | #0b6670 | #5ad7e4 | # ~ + − what changed between two filings (square tags) |
| `--neg` | #9b3412 | #ff8a65 | a negative number, which always keeps its minus sign |
| `--mark-bg` | #f5df7a | #4d3f00 | a quote found word for word, inside its context |
| `--ink`, inverted | | | ▣ ☒ your own decision. A dark filled tag is only ever the reader's. |

The Terminal limit is sulphur yellow so that it is never confused with the amber accent.

**Contrast (WCAG AA).** Every token used as text was measured against `--bg`, `--surface` and
`--surface-2`, and against its own tint background. The lowest pair is Paper `--limit` on
`--surface-2`, at 4.85:1; the lowest in Terminal is `--reject` on its tint, at 6.03:1. All pairs
are at or above 4.5:1. These ratios were computed from the hex values; they were not measured
on screen. The pairs the second pass leans on:

| Pair | Ratio |
|---|---|
| Terminal dim text `--ink-2` #9ba4ae on `--bg`, `--surface`, `--surface-2`, the black bar | 7.89, 7.50, 6.86, 8.32 |
| Terminal stamp text (`--surface`) on `--support`, on `--challenge` | 10.04, 7.87 |
| Terminal selected tab: black on amber | 11.28 |
| Paper stamp text (`--surface`) on `--support`, on `--challenge` | 6.18, 7.34 |
| Paper dim text `--ink-2` on `--bg`, on `--surface` | 6.68, 7.36 |
| Paper link on `--surface` | 7.89 |

No text in Terminal is smaller than 11px.

## Type

There are no web fonts and nothing is fetched. These are system stacks:

| Stack | Fonts, in order |
|---|---|
| serif | Iowan Old Style, Charter, Bitstream Charter, Sitka Text, Cambria, Source Serif 4, Noto Serif, Georgia, FreeSerif |
| sans | -apple-system, Segoe UI, Helvetica Neue, Noto Sans, FreeSans, system-ui |
| mono | SF Mono, ui-monospace, JetBrains Mono, IBM Plex Mono, Cascadia Mono, Menlo, Consolas, DejaVu Sans Mono, Liberation Mono, FreeMono |

The Free\* faces come last. They are what the headless Chromium used for the screenshots
actually has, so the screenshots show a fallback, not a Mac.

Each kind of text is set through a role token:

| Role | Paper | Terminal |
|---|---|---|
| `--font-quote`: what was filed (a quote, an 8-K's opening sentences) and the summary | serif | sans |
| `--font-prose`: claims, findings, headings | sans | sans |
| `--font-ui`: body, hints | sans | sans |
| `--font-control`: buttons, field labels, the bar | sans | mono |
| `--font-label`: block titles, column heads | sans, small capitals | mono capitals, no tracking |
| `--font-data`: counts, tables, dates | sans | mono |
| `--font-code`: tickers, ids, accessions, expressions | mono | mono |

Paper is one sans, with the serif kept for what the company filed and for the summary. In
Terminal a line is one face: a count inside a sentence takes the sentence's face ("8 of 636
passages"), and a line of data is mono throughout. Numbers are `tabular-nums` everywhere, and a
value is set in three columns (up to the decimal point, the decimals, the unit) so a column of
"$96.22B", "+105.9%" and "75.0%" lines up on the point.

Paper's scale steps by about 1.2: 0.72, 0.8125, 0.9375, 1.0625, 1.3125, 1.75 and 2.375 rem,
with prose at 1.0625rem and a line height of 1.6. Terminal is a size smaller and tighter
throughout: 13px body and prose at a line height of 1.35, 12px data, 11px labels, 22px table
rows, and a rail whose claim rows are two lines.

## Layout: a workspace, not a document

On a screen at least 641px wide the page fills the window and does not scroll; its panes scroll
inside themselves. One command bar (one row at 1280px and wider), then the view.

**The second pass** (after a review that found "one document layout recoloured twice"):

- *The verdict is the loudest mark.* A verdict stamp is solid: 11px capitals on the verdict's
  own colour (mixed is half and half; not judged is a dashed outline, not addressed a plain
  one). The same fills make the **verdict strip**: one cell per claim in the record's order,
  with its glyph, drawn the same in the bar, over the rail, at the head of the whole thesis's
  Overview (there with each claim's id) and over the thesis over time. A cell selects its claim.
  On paper stamps keep their outline, since a printer does not print fills.
- *Provenance is dim.* "Model-written, not checked …", "ƒ By rule", a second model's reading
  and the reader marks are words in `--ink-2` after their glyph, with no box and no fill.
- *One stripe, two meanings.* A rule at the left edge is a finding's stance or the rail's
  selected row, nothing else (the Events register keeps its ink rule on a substantive 8-K).
  Commentary, the computed test, a quote, a reason, a caution and the status line are set off
  by space or a hairline.
- *The Overview shows the result first:* the run's date and as-of line, the verdict strip and
  the record's count of claims with evidence; then a **verdict table** (one row per claim by
  its id: verdict, test, margin, readers, findings; a narrow table drops columns from the
  right) beside the newest figures, a row each; then the summary, which a model wrote, under
  both at body size in two columns. Narrower than 36rem the three stack.
- *Margin is a graphic:* a test's value as a bar from zero with what it is compared with as a
  tick, from the test's own `left.value` and `right.value`, with both display strings beside
  it. It replaces the "Compared:" sentence on screen (the sentence stays for a screen reader
  and on paper).
- *Evidence is quote first:* on the Evidence tab a finding leads with what was filed, in the
  serif between quotation marks, and the model's statement is its caption.
- *The inspector is always there.* It reads only what is behind the thing picked (a test's
  operands and arithmetic, not its expression and outcome again; each fact as a Concept /
  Period / Value / Filing grid). With nothing to pick on a tab it reads the run's own facts:
  status, the status line's counts, the sources, the coverage limits.
- *One low bar.* 32px, words not boxes, no key hints inside buttons; the guide, the theme and
  the keys are in one **Menu**. The status line is at the head of the rail (the bar is the only
  strip across the window); it gives the counts and does not repeat the status. Terminal's
  footer is one hint and the run's id. One boxed shape remains on the page, the verdict stamp:
  a stance, a test's outcome, a change mark, a kind and a page tag are coloured words.
- *Codes are real.* In Terminal each title is preceded by a dim code (".sum"). Typed in the
  ticker field after a full stop, then Enter, a code goes to that panel (see Keys). A code
  that would not do that is not shown.
- *Every view is in the frame.* A filing comparison, tagged breakdowns, the restatement
  ledger, the inbox, a saved thesis and figures-only are laid out in the same three panes on a
  window at least 1100px wide: sections or items in the rail, tables and lists in the centre,
  the head, the legend and a watch's settings at the side.

**A run** is the status line across the top and three panes under it:

```
┌ bar ─ § Evidence Desk │ [NVDA] / │ Thesis e │ ▲ Partial  Run r │ As of 17 Nov 2026 (8-K) │ … sample · Inbox i · Guide · Paper t · Keys ? ┐
│ ▲ Partial · 3 of 3 sources · 17 of 20 findings verified · 3 withheld · ▲ limits                              all counts ▾ │
├ RAIL ──────────────────┬ CENTRE ───────────────────────────────────────────┬ INSPECTOR ─────────────────┤
│ NVIDIA CORP  NVDA  CIK │ c2  ✓ SUPPORTED  3 findings · 8 of 636 · ⊨ Holds   │ Computed test of claim c2  │
│ Decision: Whether …    │ Gross margin has stayed above 70% …                │ ⊨ HOLDS  Counted as support│
│ VERDICTS BY CLAIM      │ 1 Overview │ 2 Evidence │ 3 Over time │ 4 Events │  │ each(4): gross_margin[Q]>70│
│ The whole thesis       │ 5 Figures │ 6 Limits                               │ gross_margin[Q2 FY2027] 75%│
│ c1 ± MIXED    ▲Caution │ ─────────────────────────────────────────────────  │  GrossProfit · … · 10-Q ↗  │
│ c2 ✓ SUPPORTED  ⊨ HOLDS│ verdict rule · assessed by · commentary            │  Revenues · … · 10-Q ↗     │
│ c3 ✕ CHALLENGED ⊭ FAILS│ the computed test (expression, outcome, readers,   │ …                          │
│ c4 ✕ CHALLENGED ⊭ FAILS│ each part) · the findings in short                 │ Every reading              │
│ c5 ✕ CHALLENGED        │                                                    │                            │
└ (Terminal) footer: / ticker  e thesis  i inbox  j k claims  1-9 tabs  r run  t theme  ? keys      run-id · status ┘
```

- **The rail** (`#rail`) lists the claims once: the company and the decision, an entry for the
  whole thesis, then one row per claim (`#scorecard`): id, verdict stamp, the claim, the computed
  outcome with what it counted and how many readers agreed, the record's counts, and a caution
  flag. Selecting a row (a click, or `j` and `k`) drives the other two panes. A run opens on the
  whole thesis.
- **The centre pane** (`#centre`) shows the selection under tabs. Its head says what is selected
  (a claim's id, stamps, counts and flags are the record's). The tabs are a registry, `TABS` in
  `app.js`: a new tab is one entry there and one `.tabpanel[data-tab]` in `index.html`.

  | Tab | The whole thesis | One claim |
  |---|---|---|
  | Overview | the result (date, as-of line, verdict strip), the verdict table beside the newest figures, the summary (and the line code wrote after it), what moved, unknowns and next steps | the verdict rule, who assessed, the caution or 8-K note, the engine's commentary, the computed test, then the findings in short |
  | Evidence | the sources, the withheld findings (folded), which filings were compared | the findings in full (checks, cited figures, your decision, each quote) and the changed paragraphs |
  | Over time | the time line and every compiled claim's lane | the time line and that claim's lane |
  | Events | the as-of line in full, then the 8-K register | the same |
  | Figures | the reported figures, the tagged figures, the charts | the same |
  | Limits | coverage limits and errors | the same |

- **The inspector** (`#inspector`) reads whatever is picked in the centre pane: a finding's
  quotes in the text around them with where each sits and the link to the filing; a computed
  test's operands (each with the facts it was read from), its arithmetic and every reading; an
  8-K whole (items, roles, opening sentences, link); a figure's formula and the reported values
  behind it. Pick by selecting the item or its button ("Read the quote in its context"). With
  nothing picked it reads the first item of the tab on show, and the item being read carries an
  tinted ground. What the inspector reads is not drawn twice: in the centre pane a quote is its
  own words, a test is its summary, an 8-K its items. On a tab with nothing to pick (Limits,
  the whole thesis's Evidence) it reads the run's facts; the centre pane never reflows.
- **The status line** (`#status-banner`) is one line; its full counts open over the panes and
  close again.
- **The Run drawer** (`#run-drawer`, from the right; the status chip or `r`) holds everything
  about who did the work: the engine, who checked meaning, who read the claims into tests and
  the counting rule, the run's id and times, the as-of line, the saved thesis, the sample's
  provenance. Under it: the guide (`#howto`, also opened by **Guide**), the marks (`#legend`) and
  the terms. The thesis form is the other drawer, from the left (`e`).

`?claim=c2&tab=evidence` opens a run on that claim and tab (read once; the screenshots use it).
`#claim-c4-changes` and `#claim-c4-test` still select the claim and show the block.

**The first screen** is the same frame with two panes: the thesis form on the left, and on the
right the guide as the lead (what this is, the takeaway, the configured engine), how it works,
and the recorded samples in a column of their own.

**Any other view** (a filing comparison, tagged breakdowns, the restatement ledger, the inbox, a
saved thesis, figures only) is in the same three panes on a window at least 1100px wide
(`VIEW_FRAMES` in `app.js`): a rail listing its sections or items, which scroll the centre
pane to them; the centre pane with its tables and lists; and at the side what explains it (its
head, its legend, a watch's settings). Narrower, it is one column set to a measure.

**Narrower windows.** Below 1100px the rail is a strip across the top (the entry for the whole
thesis, then the claims as chips of id and stamp that wrap; a chip's title is its claim) and the inspector is a sheet
from the bottom that opens when something is picked and closes with Close or Esc; the bar takes
a second row. Below 641px the page is one column that scrolls: a one-row bar (the mark, the
ticker, the menu; the other controls open with the menu), the status line, the rail, then the
selection with its tabs stuck to the top of the window and fading at the edge they scroll past; there is no inspector, and what it
would read (a quote's context, a test's operands, an 8-K's opening sentences) is drawn in place.
Widths inside a pane respond to the pane's own width (container queries), not to the window's.

One spacing scale (`--s-1` to `--s-6`: 4, 8, 12, 16, 24, 32px) sets every gap and padding of the
frame, and one chrome every titled part: `.pane-label` for a pane, `.block-title` for a block
inside one.

### What left the reading path, and where it lives now

| Was in view on every run | Now |
|---|---|
| The provenance block under the company's name (engine, checker, readers, the counting rule, run id, times) | The Run drawer, one step from the status chip. The bar keeps the status and an as-of chip. |
| The engines in the bar's second row | The Run drawer. The bar has one row. |
| The as-of line in the bar | A chip with the date and form of the newest filing read (`as_of.newest_filed`, `newest_form`); the record's whole line is the chip's title, its text for a screen reader, the first line of the Events tab, and in the Run drawer. |
| The claims three times (verdict board, thesis over time, dockets) | Once, in the rail. A lane of the thesis over time is named by its claim's id; a docket has no heading of its own on screen. |
| "How to read this", the legend and the glossary | The Run drawer, opened on the guide from **Menu**. The guide is still the lead of the first screen. |
| A claim's counts and "Counted as …" on its rail row | The centre pane's head and the claim's computed test when it is selected (and for a screen reader on the row). A row is its id, stamp and test mark over two lines of claim. |
| The engine's tinted, boxed tags | Dim words after a glyph. |
| "Assessed by" and "Read by …; computed by code:" on every row of the board | Said in full for the selected claim (its Overview and its computed test) and to a screen reader on every row; a row keeps the outcome, what it counted and the count of readers. On paper every row prints them. |
| A reason's "Model-written" badge under a statement that has one | The statement's badge and the violet rule on both; the reason's own badge is drawn on a phone and on paper. |

The honesty labels that stay in view: the status and the limit mark (the bar and the status
line), "Model-written, not checked …" on the summary and on every finding, the caution flag on
a claim's row and the caution itself in its Overview, the computed test's own line saying who
read the claim, and the sample tag.

## Components, and when to use each

**Command bar.** One row: the brand, the ticker (the `/` key), **Thesis** (`e`), then for a run
the status chip (glyph and word, never filled; it opens the Run drawer) and the as-of chip (it
opens the Events tab) and the verdict strip. At the right: the sample tag and **Leave the
sample**, the watch's health, **Inbox**, and **Menu** (the guide, the theme, the keys). The run's chips are hidden on every view that is not a run. The watch's
detail is what is cut short when the row is full.

**Status line** (`#status-banner`). The status, `sources_read` of `sources_requested`,
`findings_verified` of `findings_proposed`, `findings_withheld`, and the limit mark when the run
has coverage limits. It is the summary of a `<details>` whose body is the full strip (the
status note, every count, the limit lines), which opens over the panes. Every count is a
`[data-coverage]` node holding the record's number. A partial or failed run gets a limit rule
at its left edge; a running run's line is dashed and the stages follow it.

**Tape** (`#tape`). The newest period's key figures, first on the whole thesis's Overview. Each
cell is a metric from `run.metrics` (the quarter's when the record has one, else the year's):
its label, its `display` string (split at the decimal point, not reformatted) and its sparkline
from `run.series`. Selecting a cell reads that figure in the inspector. The row holds as many
cells as the record has of these figures and wraps to the pane: nothing is built around a count.

**Codes.** Every pane and block title carries a short code in `data-code` (VRD, SUM, MOV, FND,
WHD, FIG, KEY, EVT, UNK, NXT, SRC, LIM, ERR, TL, TOT, INS, RUN, GDE). Terminal writes each dim
before its title as what you type to go there (".fig"); Paper does not show it.

**Terminal, the instrument.** Mono for every label, number and control; amber for selection
and focus only (the tab in use, the rail's selected row, the focus ring), values in ink and
links in underlined ink; the tabs as numbered keys; the figures as a 22px-row list beside the
verdict table; a footer with one hint and the run on screen. Paper is the same frame as a typeset note: the centre pane is the sheet, the rail
and the inspector sit on the desk beside it, claims and prose are in the serif.

**Time line** (`#timeline`). One SVG date axis, drawn at its pane's width and redrawn when that
changes. Use it on any run whose record has dated filings.

- *Above the axis:* a bar for each 10-K and 10-Q the run read (`data-tl="filing"`), with a yellow
  dot on top when a verified quote comes from it (`data-quoted`).
- *Below the axis:* each 8-K in `run.timeline` (`data-tl="8k"`). A filled diamond is substantive;
  a small hollow circle is routine. A substantive 8-K is labelled with its categories, and a
  yellow dot on the axis above one means a quote comes from it.
- *The run* is a rule with its date (`data-tl="run"`).
- *The gap* (`data-tl="gap"`) is a hatched band from `as_of.newest_filed` to the run, labelled
  with `as_of.days_since_newest`. It is drawn only when the record has an `as_of`.
- *Every mark* is a link to its filing, with an SVG `<title>`, an `aria-label` and a tooltip on
  hover or focus.

**Rail row** (`#scorecard a.score-row`). A claim's id, its verdict stamp and its caution flag
on one line; the claim; the computed outcome with what it counted and the count of readers; the
record's finding and passage counts. With a review the row holds two stamps under their own
labels, the engine's and the one after your review, with the tally. The row selected carries an
accent rule and the sheet's ground; verdict colours stay in the stamps.

**Verdict stamp** (`.pill.verdict`). Square corners, 11px capitals, a solid fill in the verdict's
colour (an outline on paper). Use it only for a claim's verdict; `verdictStrip` draws the same
fills as one cell per claim. A **stance pill** (`.pill.stance`) is round and is used only for a finding's
stance.

**Claim docket** (`details.claim`). One per claim, in two parts: why the verdict
(`[data-part="overview"]`) and the findings (`[data-part="evidence"]`). On screen only the
selected claim's docket is drawn, without its heading; every other docket is `inert` and off, so
neither the keyboard nor a screen reader reaches it. On paper every docket prints open under
its own heading (the verdict stamp, the id, the claim, the counts).

Each finding (`article.finding`) has its statement, stance, the "predates the 8-K of …" mark,
checks, cited figures and review slot, then its quotes and the button that reads them in the
inspector. A cited figure's link reads that figure in the inspector.

**Quote** (`figure.evidence`). In the inspector, on a phone and on paper: the excerpt in the
serif with the words found highlighted inside their context, then where it sits and a link to
the filing. In the centre pane: its own words, cut to three lines, and the source.

**Withheld findings** (`#withheld`). On the whole thesis's Evidence tab, folded behind one line:
the record's `findings_withheld`, then the kinds of reason present, with
`findings_failed_meaning` counted when the meaning check withheld any. Inside the fold they are
grouped by kind, as before.

**Reported figures.** Dense rows: label, sparkline, value (set on its decimal point). The
sparkline is the `run.series` entry with the figure's key and period; the figure's own period is
circled. A negative value is in `--neg`. Selecting a row reads its arithmetic and inputs in the
inspector; on a phone and on paper the row opens in place.

**8-K register** (`#events`). The date in the left column, then the form and accession, kind and
status, and the items with their categories. A substantive 8-K carries an ink rule. The roles a
5.02 names, the opening sentences and the link to each item are read in the inspector (in place
on a phone and on paper).

**Tables** (sources, the comparison between runs, breakdowns, the restatement ledger). A heavy
rule under the heading, hairlines between rows, numbers right-aligned, dates never broken. A
table wider than its pane scrolls inside its own frame. In the inspector a table of values
stacks, one value to a block, each cell named.

**Marks.** The decision mark, the meaning mark, the model badge, the rule mark, the change mark,
the limit line and the page tag are as before. Each keeps its colour, shape and border style, so
no two are confused. The legend in the Run drawer lists them all. One change: the line on a
computed test saying who read the claim is the fixed rule's olive and its ƒ without the tag's
dotted box, because it is a sentence.

**Print.** `@media print` lays the note out as a document, whatever was selected: the company
and the decision, the verdicts (each row with "Assessed by" and who read its test), how the run
was made, the status line with every count, then every tab's panel in order and every claim's
docket open under its own heading, with each quote in its context, each test's operands and
each 8-K's opening sentences in place. No bar, tabs, inspector, drawers, buttons or legend.
`app.js` opens every closed disclosure before printing, moves the Run drawer's block after the
rail and switches to Paper (the Terminal theme's own rules are not for a printer), and undoes
all three after.

**Motion.** Three things move: the current stage's marker pulses, and the two drawers slide.
`prefers-reduced-motion` turns them off.

## The standing watch (version 13)

The page draws the routes of `docs/watch.md` with the words of `GET /api/watch/meta`; every payload and field is in `docs/examples/v13/README.md`. It orders nothing: the inbox is drawn unread first, then newest first, as the API sends it. It counts one thing only: the folded items on the page it draws, because the API sends no count of them.

**Health** (`#watch-health`, in the bar; its detail is cut short when the bar is full, and whole in its title). One line from `GET /api/watch/health`:

- a filled dot (support colour) and "Watch alive", or a hollow dot (limit colour) and "Watch not running";
- the last cycle's time of day; the whole time and the watcher's `note` are in the title;
- the queue depth and the runs waiting.

At phone width only the dot and the words show. It is read again every minute while the page is visible.

**Not running.** When `alive` is false, a limit line says so near every watch control, in the inbox view and on a saved thesis. It reads "The watcher is not running. No new filing will be noticed, and no watched thesis run, until it runs.", followed by the health's `note`.

**Inbox button** (`#inbox-button`, the `i` key, `#inbox`). It shows the unread count from the last inbox payload, or from a mark-read answer. The count sits on an accent fill, with a quiet outline at zero.

**Watch card** (`.watch-card`). The same card appears on a saved thesis (`#thesis-watch`) and in the inbox's list of watches. When the thesis is on watch, it shows:

- since when, and the policy label;
- the last check, the next check (or `next_check_note`) and the last error;
- the last failed job, when there is one;
- unread items and runs waiting, with a link to that thesis's inbox;
- the policy as two radios, a change of which is a `PUT`;
- "Take it off watch", a `DELETE`.

When the thesis is not on watch, the radios start on `default_policy`, and "Put it on watch" sends the `PUT`. Every refusal is said under the card in the server's words:

- a 422 names its fields;
- a 404 says the thesis is gone;
- a 503 adds "Nothing was saved";
- a 409 on a `DELETE` shows the watch as ended.

A refused policy puts the radio back on the server's policy.

**Inbox item** (`article.inbox-item`). Each item shows, in order:

1. The kind tag in the record's words, with a glyph: ◇ waiting (dashed), ◌ running (dotted), ◆ moved (change colour), · nothing moved, ▲ failed (limit colour), ○ not relevant.
2. Unread or read, then the thesis and the time.
3. The headline.
4. The filing: form and accession linked to sec.gov, filed and report dates, and each 8-K item with its title and category.
5. The triage: a rule mark "By rule, no model", the summary and the rules. Then each claim says whether it bears, gives its reasons and, for a 10-K or 10-Q, its changed paragraphs with their change mark, shared words and link.
6. The run:
   - a waiting run shows its reason and **Run now (uses the model)**. A 202 reads the item again and names the run. A 409 says the run was not started, in the server's words, and reads the item again.
   - otherwise the run's id and status, and who started it, with **Open the run in the note**. The run opens with the item's comparison under its head.
7. What moved: the record's line, each verdict that moved as two stamps, new cautions (limit lines), new 8-K notes and new 8-Ks.
8. "Compare with the previous run, claim by claim": the run comparison table, drawn from the item's `moved` (no counts: the payload has none).
9. Mark read or unread.

Unread items carry an accent rule at their left edge.

**Folded items** (`.inbox-folded`). Items with `collapsed: true` sit on one closed line under the list: "Seen, not relevant: N filings on this page".

**Paging.** "Older items" asks for the page's `next_offset`. "Newer items" goes back to an offset the page came from. "Mark this page read" sends the page's unread ids.

**Empty and failure states.** Each says so plainly:

- no watches;
- an empty inbox;
- an inbox route this server lacks (a 404);
- a server that cannot be reached, with "Try again".

**Recorded inbox** (`?sample=inbox`, `?sample=inbox-page-2`). It is drawn from the five example payloads that `make sample-inbox` copies unedited, and says where they come from. In sample mode nothing is sent, and the controls are disabled or say so.

## Computed claims, dates and restatements (version 14)

Drawn from the backend's own fields: `docs/examples/v14/README.md` is the contract and the
recorded samples are those payloads copied unedited (`make sample-v14`). The page computes no
outcome, margin, flip, count or change. It places dates on an axis and maps the outcome tokens
to glyphs and words. Every field is read defensively: a missing one is left out and an added one
is ignored, so additive changes to these payloads do not break the page. The functions are in
`app.js`, in the section "version 14".

1. **The computed test on a claim** (`computedTest`, from `Claim.computed`). It sits in the
   claim's Overview before the findings, with an olive left rule and a line in the fixed rule's
   olive saying who read the claim into the test and that the arithmetic is code. On a wide
   screen the test's summary is in the centre pane (the expression, the outcome, what it counted,
   the readers, the bound test, the two sides, the margin, and every part of a test of several
   parts) and its operands, arithmetic and readings are read in the inspector
   (`computedDetail`); on a phone and on paper all of it is in place. The line reads: "Read into a test by the grammar
   and computed by code from the XBRL facts: no model read the claim" with the grammar alone, or
   "Read into a test by the grammar, Model 1 and Model 2; the arithmetic is done by code from the
   XBRL facts" when a model reader took part (the readers of the test shown, from `read_by`). It
   never says "no model" when a model read the claim. It shows, in order:
   - the canonical expression in monospace;
   - the outcome with its own glyphs: ⊨ holds, ⊭ fails, ⊘ cannot be computed (dashed). These
     are never a verdict's glyphs, although holds and fails borrow the support and challenge
     colours;
   - what the verdict rule counted (`counted_as`: "Counted as support", "Counted as a
     challenge", "Not counted");
   - the reason it could not be computed;
   - the bound test, and the date the facts were read up to (`as_of`);
   - the two sides compared;
   - a table of the operands: term, label, value, formula, and every fact read with its
     concept, period, value, filing (form and date, linked to EDGAR's index page of the
     accession) and its derived or restated flag;
   - the arithmetic, line by line, then the margin and the backend's note.

   **A test of several parts** (`combines` "each" or "and", with `parts`) draws every part, each
   on its own rule in its outcome's colour: its bound expression, outcome and margin, its two
   sides, its arithmetic and, for a part that could not be computed, why. A line above says how
   the parts combine (each of N periods, or both tests: holds when every part holds, fails when
   any fails), and the record's last line of arithmetic ("each of 4 tests: 4 hold, 0 fail, 0
   cannot be told: holds") follows as "Together". The whole test shows no sides of its own (the
   record's `left` and `right` are the first part's) and its margin reads "each part has its
   own". The operand table lists every part's values once, as the record does.

   A threshold is written once on the sides line ("> 70%", not "70% = 70%"). At phone width the
   operand table stacks, one value to a block.

   A claim that did not compile shows its `compile_note` quietly instead, behind a dashed rule.
   With several readers it also shows each reader's mark and, in the open, each reader's reason.
2. **Which part of a verdict is computed.** In the rail each claim's row keeps the engine's
   "Assessed by" line (the reading of the filings: a model's or the extractive engine's) and,
   after it (both for a screen reader and on paper; a sighted reader has them in the selected
   claim's Overview), "Computed by code, no model:" (the grammar alone) or "Read by the grammar,
   Model 1 and Model 2; computed by code:" (a model reader took part), with the outcome, what it
   counted and how many readers
   agreed ("3 of 3 readers", "2 of 3 readers, one dissenting": the length of `read_by` against
   the claim's readings, when `agreement` says they agreed), or "No computed test: the verdict
   rests on the findings". The centre pane's head (and on paper the docket's heading) adds
   "⊨ Computed: Holds". The note under the
   verdicts (in the guide) adds the computed tests when the run has one: the arithmetic is
   code, and either the grammar alone read the claims (no model) or the reading may be a model's,
   with the run's `claim_readers`.

   After a model's summary, `brief.verdicts_after_summary` (version 14.1: a line the code writes,
   naming each claim whose verdict the computed tests set or changed after the summary was
   written) follows directly under the summary's box, outside the model's violet mark, in the
   fixed rule's olive with the mark "Written by code after the summary, not by the model".
   Extra decimals in an arithmetic line, a margin or a history point's sides ("74.96% >= 75.00%:
   fails") are drawn as the record writes them; the page rounds nothing.
3. **Who read the claim.** The Run drawer says who read the claims into tests (`claim_readers`, with
   `claim_reader_detail`) and the counting rule in words (`claim_reading_rule`), which "How to
   read this" repeats for the run on show. Under each test's outcome, one row:
   - one mark per reading in `Claim.readings`: ● read this test (the reader is in `read_by`),
     ≠ read another test (in `dissent`, or any other test when nobody agreed), ○ read no test.
     Each mark takes the focus; on hover or focus it says who the reader is (the model and where
     its answers came from, from `claim_reader_detail`) and what it read, or why it read nothing.
     The same words are in the mark for a screen reader;
   - the record's `agreement_label` ("at least two readers agree", "counted, with one dissenting
     reading", "not counted: no two readers agree", "one reader: the grammar");
   - each dissenting reading, "≠ Dissent: Model 2 read …".

   Every reading in full, with the normal form the rule compared where it differs from the
   reader's writing, is behind "Every reading" at the end of the test. When `agreement` is
   `not_agreed`, the test, the board and the docket say "Readings differ: not counted" in the
   limit colour, and the backend's note says what each reader read. The page compares no
   readings: the marks come from `read_by` and `dissent`, the conclusion from `agreement`.
4. **The thesis over time** (`drawThesisOverTime`, from each compiled claim's `history`). It is
   a block of its own on the Over time tab, directly under the time line (code `TOT`). The whole
   thesis shows every compiled claim's lane; a selected claim shows its own. Each lane has:
   - the claim's id (its words too on paper), its test now, and a step line over the filing dates: holds on top, cannot be
     computed in the middle, fails at the bottom, one dot per point;
   - a ring on each point the record marks `flipped`, labelled with its form and date when the
     note is wide enough;
   - under the line, the `history_note`, then the flips in words ("Flipped to Holds with the
     10-K filed 25 Feb 2026", linked, with the bound test and both sides);
   - every point as a table behind a fold.

   A test of several parts has one line for the whole test. The record gives, at each point,
   the whole test's outcome and the two sides of its first part only, so the lane says so, the
   table's columns are "First part's left" and "First part's right", and each flip's sides read
   "first part 78.4% against 70%".

   A claim with no history (a share of revenue, a part of the company) shows only its `history_note`. A claim that did
   not compile is named in one line. The lanes share one date axis and are drawn again when the
   note changes width.
5. **As of a date.** The drawer has a date field, "As of a past date" (`as_of`), sent with the
   run and used by the restatement lookup; the server checks the date and a refusal shows under
   the field. A run with `as_of.requested` is unmistakable:
   - a banner runs across the top of the frame, above the status line: a double rule on a
     hatched ground, the date, and `requested_note` (on paper and a phone it opens the note);
   - the rail's head (the company and the decision) gains a double left rule;
   - the command bar's as-of chip starts "Run as of 1 Mar 2026", and the status footer says so;
   - the time line ends at the requested date ("As of 1 Mar 2026"), not at the day the run ran.

   The banner and the rule print.
6. **The restatement ledger** (`restatementLedger`, `GET /api/companies/{ticker}/restatements`).
   It is a lookup beside the others in the drawer ("Restated values"), as of the drawer's date
   when one is set. Its view gives:
   - the company, the date, and "28 of 922 periods ... changed value in a later filing" in the
     record's two counts;
   - the metrics compared, the tolerance, the notes;
   - a table with one row per restated period: the first value struck through with its filing,
     each later value with its filing and the change in units and percent, "back to an earlier
     value" (`returns_to_earlier`), "tagged with another concept later" (`concept_changed`), and
     how many filings reported it.
7. **Coverage.** The status line's full counts (opened from the line) gain "N of M claims compiled to a computed test:
   ⊨ holds, ⊭ fails, ⊘ cannot be computed", with each count the record's.
8. **The watch's version 14 fields.** The inbox's folded line uses the backend's `folded` count,
   of the whole inbox (or of the thesis), and says when this page draws none of them. An item
   shows `claims_line` and each computed test whose outcome changed (`moved.computed`: the
   canonical test, before and after). The saved theses list takes each thesis's `watch` from
   `GET /api/theses`.

The recorded samples are `?sample=run-live`, offered first on the first screen: a live NVIDIA
run of 18 Nov 2026 answered by the Anthropic API (claude-opus-5-5 reading, claude-haiku-5-5
checking) with three claim readers (the grammar, claude-haiku-5-5, claude-sonnet-5-5), copied
unedited from `results/run-7fa4a528d428.json`: three tests all three readers read alike, one of
them held in each of the last four quarters, and two claims no reader could read.
`?sample=readers` (`docs/examples/v14/run-readers.json`) shows what the live run does not: the
grammar refusing while both models agree ("2 of 3 readers"), two writings of one test, and a
test that cannot be computed; its readers' answers are replayed from a cassette recorded through
the API. `?sample=computed` (the example run: two tests that hold, one that fails, one that
cannot be computed, one claim that does not compile), `?sample=as-of` (the same claims as of
1 Mar 2026) and `?sample=restatements` (NVIDIA's ledger from the recorded facts) were made
offline with the extractive engine: no model, no cassette. No recorded run has a dissent, a
disagreement or a test of two parts joined by "and": `uitests/v14.html` makes each from the
example run, and the specimen shows a dissent made up from the live run's c4, labelled.

**Not built: the peer strip.** The backend has no peers route, so the strip is only on the
specimen, on made-up data, under the heading "Not built". It is not on the page.

## Keys

| Key | Does |
|---|---|
| `/` | Put the cursor in the ticker (Esc leaves it) |
| `e` | Open or close your thesis (the form drawer) beside a result; Esc closes it |
| `i` | Open the inbox of the standing watch |
| `j` / `k` | Select the next or previous entry of the rail (the whole thesis, then each claim); the focus goes to its row, and it stops at the ends |
| `1` to `9` | Show that tab of the selection (the arrow keys move between tabs when one has the focus) |
| `Enter` | On the claim selected in the rail: move the focus to its tabs |
| `r` | Open or close the Run drawer; Esc closes it |
| `t` | Switch between Paper and Terminal, and remember the choice |
| `?` | Show the keys (Esc or Close shuts the list) |
| `.` then a code, in the ticker field, then Enter | Go to the panel with that code: `.sum` `.vrd` `.key` `.mov` `.unk` `.nxt` (Overview), `.fnd` (the selected claim's findings), `.src` `.whd` (the whole thesis's Evidence), `.tl` `.tot` (Over time), `.evt`, `.fig`, `.lim` `.err`, `.run` and `.gde` (the Run drawer), `.ins` (the inspector). A code that names nothing on the screen says so under the field. A ticker never starts with a full stop, so a code is never read as one. |
| `Esc` | Close a drawer, the list of keys, or the inspector when it is a sheet |

The keys do nothing while you type in a field or hold Ctrl, Cmd or Alt. Every control has a
visible focus ring in `--accent`.

## Tests

`uitests/test_frame_dom.py` reads what `uitests/frame.html` recorded. That page frames the page
at 1440x900, 1280x800, 900x800 and 360x740 (a frame's size is its viewport), selects claims,
switches tabs and picks items, and records the browser's own measures after each step. The
tests hold the page to:

- no page scroll at 1440x900, 1280x800 and 900x800, each pane inside the window and scrolling
  inside itself, and the bar one row with every control inside the window;
- no sideways scroll at 360, one column, the tabs stuck to the top while the page scrolls;
- the claims listed once: every claim's row in the rail, and a claim's own words drawn a second
  time only in the centre pane's head while it is selected;
- the selection driving the panes: the docket, the head, the lanes and the inspector, with the
  inspector's text checked against the record (a finding's evidence ids, excerpts and links; a
  test's operands; an 8-K's opening sentences; a figure's label, value and concepts);
- a docket that is not on show being inert and out of the tab order, at every step;
- the Run drawer's contents, the first screen, and the strip and sheet below 1100px;
- the second pass: the verdict strip's cells in the bar, over the rail and in the Overview against the record's verdicts, and a cell selecting its claim; a stamp filled and 11 to 12px, a model tag without a box; a rail row no taller than its id line and two lines of claim; the menu's three items and no key hint in the bar; the bar no taller than 36px; a code typed in the ticker field going to its panel and an unknown one saying so; the inspector staying on every tab and reading the run's facts (the counts, every source, every limit) when nothing is picked; the inbox laid out in the three panes with one rail entry per item; an operand with a long note staying inside the inspector.

`uitests/test_print_dom.py` reads what `uitests/print.html` recorded: the live run with a claim
and the Events tab selected in Terminal, then the page's own `beforeprint` and the stylesheet's
print rules turned on (an emulation on a screen: page breaks and a printer are not checked).
Every docket is drawn open under its heading, every panel in reading order, no frame, each
quote's context, each test's operands and each 8-K's opening sentences in place, the theme
Paper, and how the run was made after the verdicts and back in the drawer afterwards.

`uitests/test_keys_dom.py` reads what `uitests/keys.html` recorded. That page frames the
live-run sample, presses each key, clicks the theme button and notes the focus, the rail's
selection, the docket on show, the tab, the theme, the stored value, the dialog and the drawers
after each step: `j` and `k` through the claims and back to the whole thesis, a digit for a
tab, `e` and `r` for the two drawers with Esc closing each, Enter on the selected claim.

`uitests/test_run_events_dom.py` checks the time line against each run's filings and 8-Ks:
every mark, its kind, whether it is quoted, its link, the run and the gap. It also checks the
live-run sample, the command bar, the caution and the predated mark. For every run sample it also checks:

- the tape: each cell is the record's metric, in order, with its own display string;
- the order of the markup (a phone's and paper's reading order): the company and decision, the verdicts, the status line, the tape and summary, the dockets, the time line, the figures; and that a run opens on the whole thesis's Overview;
- the status line's counts, and that the full strip starts folded;
- the withheld fold and its counts;
- that the standing prose sits in the guide, in the Run drawer, which starts closed and inert;
- that the Run drawer names the engines whole and the bar names none;
- the way out of a sample and the drawer button in the bar.

`uitests/test_v14_dom.py` checks the version 14 samples against their JSON:

- the copies are byte for byte the examples;
- each compiled claim's expression, outcome, counted state, bound test, reason, margin and
  arithmetic, its operands and every fact with its filing and link;
- the compile note of a claim that did not compile;
- the board's computed part, and the readings;
- the computed counts in the status line;
- the thesis over time under the time line, with each history's points, outcomes and flips;
- the as-of banner, the bar, the body class and where the time line ends;
- the ledger's rows, values, changes and flags, and its denominator.

`uitests/v14.html` drives the page for what the examples do not show, and the same file checks
what it recorded:

- three readers with the record's real fields, made the way the backend makes them: no two
  agreeing, a dissent, a claim the grammar did not compile with one model reading a test, all
  three agreeing, two agreeing and one refusing;
- a test of two parts joined by "and", put together as the backend does: every part drawn,
  the tally, no whole-test sides, one history line labelled as the first part's sides;
- the ledger lookup's 422, 200 and 503;
- a run sent with `as_of`, refused and then drawn;
- an inbox item with `moved.computed`;
- the theses list with each thesis's `watch`.

`uitests/test_live_readers_dom.py` checks the live three-reader sample and the two-model example
against their JSON:

- the live sample is byte for byte the run's record (when `results/` holds it), is offered
  first, and says where it came from and who answered;
- the reading rule in the Run drawer and in the guide;
- each reader's mark on each claim, from `read_by` and `dissent`, with its words on hover and
  focus and for a screen reader;
- each test's agreement, dissent and counted state, and on the board "N of M readers";
- each reader's reason on a claim no reader could read, in the open;
- the grammar refusing while both models agree, and the normal form shown where a writing differs;
- every part of the "each" test (expression, outcome, margin, sides, arithmetic), the tally,
  the operands, and its one history line with the first part's sides labelled.

The run samples' time line, tape, reading order and status line are checked by
`uitests/test_run_events_dom.py` for both as well.

`uitests/test_inbox_dom.py` checks the recorded inbox against its JSON:

- the copies are byte for byte the examples;
- the order of the items, and their kinds and headlines;
- the folded line's count;
- the unread number;
- that only the waiting item has the Run now button;
- the filings, the reasons per claim and what moved;
- the watch card's fields and the health.

It also reads what `uitests/watch.html` recorded. That page answers the page's watch requests with the example payloads and the README's refusal shapes: 202 and 409 on Run now, 422, 503 and 200 on a policy, 409 on taking a watch off, an empty inbox beside a watcher that never ran, an unreachable server, paging by offsets, and marking read. It records what the page showed and sent.

The specimen page has no browser test of its own; it is checked by eye in the screenshots. The API serves it at `/specimen.html` (`tests/test_api.py` checks that).
