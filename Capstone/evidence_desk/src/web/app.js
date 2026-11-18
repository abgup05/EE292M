// Evidence Desk frontend (the research-note design: docs/design.md).
//
// Collects a thesis, starts a run, polls it, and draws the record the API
// returns; records the reader's decision on each verified finding; saves a
// thesis and shows what moved between its runs. It computes nothing a reader
// would call a result: verdicts (the engine's and the one after review),
// counts, coverage, comparisons, reported figures and their display strings,
// excerpt context and all status, verdict and decision wording come from the
// API (`GET /api/runs/{id}`, `/api/runs/{id}/review`, `/api/theses/...`,
// `GET /api/companies/{ticker}/metrics` and `GET /api/meta`). A decision is
// shown as the server's Review returns it, never as a local guess. Optional
// routes that answer 404 hide their feature without an error. Chart geometry
// maps given values to pixels; every number a reader sees is a record field.
// Client-side validation is immediate feedback only, using the limits from
// `/api/meta`; the server decides. Every string from the API is inserted as
// text, never as markup, and only http(s) links from the API become hrefs.
//
// One meaning per mark (see the legend in index.html):
//   ▲ amber   something limits this record
//   ✎ violet  written by a model and not checked for meaning (solid rule, filled badge)
//   ◎ ◐ violet a second model read the evidence and agrees (◎) or agrees only in
//             part (◐): still a model's reading, so the same violet, but a double
//             rule and no fill, never the engine's badge. A finding the second model
//             rejects is withheld, which is a limit (▲).
//   ! red     the server refused your input ("Refused"; "Rejected" is only ever your decision)
//   ƒ olive   computed by a fixed rule, not checked by a person (dotted border)
//   status    ◇ complete, ⋯ running, ▲ partial or failed: never a filled tag
//   dashed    not final: a claim not judged, a decision still to make, a run in progress
//   verdicts  ✓ supported, ✕ challenged, ± mixed, ? unjudged, ∅ not addressed
//   stances   reuse ✓ and ✕; context is •
//   decisions ▣ accepted, ☒ rejected (dark filled tag: only ever the reader's own);
//             ☐ undecided is dashed, because the verdict after review is provisional
//   changes   between two filings (`/api/companies/{ticker}/changes`), cyan, square tags:
//             # numbers only, ~ reworded, + added, − removed; inside a reworded
//             paragraph, added words are underlined and removed ones struck through
//
// Drawing, not computing: the time line places record dates on an axis, a sparkline places
// a series' values in a box, and a negative number is set in its colour from the sign of the
// record's own value. Every date, label, count, outcome and percentile a reader sees is a
// record field or wording from /api/meta. The theme ("paper" or "terminal") is the reader's
// setting, kept in localStorage when the browser allows it, else it follows the system.

"use strict";

const POLL_MS = 1500;

/** Pipeline stages in order, with the words shown on the progress line. */
const STAGES = [
  ["queued", "Queued"],
  ["company", "Company"],
  ["filings", "Filings"],
  ["events", "Current reports (8-K)"],
  ["numbers", "Reported figures"],
  ["planning", "Planning"],
  ["retrieving", "Retrieving passages"],
  ["assessing", "Assessing"],
  ["verifying", "Verifying quotes"],
  ["done", "Done"],
];

const VERDICT_GLYPH = {
  supported: "✓",
  challenged: "✕",
  mixed: "±",
  unjudged: "?",
  not_addressed: "∅",
};
/** Stances reuse the supported and challenged marks exactly; context is a grey dot. */
const STANCE_MARK = {
  supports: ["✓", "Supports"],
  challenges: ["✕", "Challenges"],
  context: ["•", "Context"],
};
/**
 * The reader's decision on a finding: its own glyphs, never a verdict or stance mark.
 * ▣ rather than ☑, which headless Chromium draws as a colour emoji.
 */
const DECISION_MARK = { accepted: "▣", rejected: "☒", undecided: "☐" };
/** Used only when /api/meta has no decision_labels. */
const DECISION_FALLBACK = { accepted: "Accepted", rejected: "Rejected", undecided: "Undecided" };
/** The second model's reading of a finding's evidence (`checks.support`), in words; ◎ and ◐ are its marks. */
const MEANING_MARK = { passed: "◎", partly: "◐" };
const MEANING_WORDS = {
  passed: "Meaning: a second model agrees",
  partly: "Meaning: a second model agrees only in part",
  failed: "Meaning: a second model disagrees",
  unchecked: "Meaning: not checked",
};
const MODEL_BADGE = "Model-written, not checked for meaning";
/** On a finding a second model has read: its meaning was checked, but only by a model. */
const MODEL_BADGE_READ = "Model-written, not checked by a person";
/** A run's status. Complete is an open diamond: a filled dark square would read as the reader's decision. */
const STATUS_GLYPH = { running: "⋯", complete: "◇", partial: "▲", failed: "▲" };
const LIMITING_STATUS = new Set(["partial", "failed"]);

/** The engine name the deterministic engine reports; anything else non-empty is a model. */
const EXTRACTIVE = "extractive";
const MODEL_ORIGIN = "model";
const SAMPLE_NAME = /^[a-z0-9-]{1,40}$/;

const FORM_GLOSS = {
  "10-K": "annual report",
  "10-Q": "quarterly report",
  "10-K/A": "amended annual report",
  "10-Q/A": "amended quarterly report",
};
const ENGINE_GLOSS = {
  claude: "a language model reads the passages and proposes findings; the backend checks every quote and number",
  extractive: "no model: it quotes the best-matching sentences and judges no stance",
};
const ITEM_GLOSS = "Where the passage sits in the filing. An Item is a numbered section, such as Item 1A, Risk Factors.";
/**
 * What an evidence link opens, by the record's `link_kind`, for a filing and for a page.
 * A record without `link_kind` keeps the plain words ("Open in filing", "Open the page").
 */
const LINK_WORDS = {
  passage: ["Open in filing, at this passage", "Open the page, at this passage"],
  "first-line": ["Open in filing, at the first line of this passage", "Open the page, at the first line of this passage"],
  document: ["Open the filing (this link does not locate the passage)", "Open the page (this link does not locate the passage)"],
};
const ACCESSION_GLOSS = "Accession number (the SEC's identifier for this filing)";
const FIELD_NAMES = {
  ticker: "Ticker",
  decision: "Decision",
  claims: "Claims",
  scope_notes: "Scope notes",
  filings: "Number of filings",
  extra_urls: "Extra public pages",
  thesis_name: "Thesis name",
  changes_form: "Filings to compare",
  breakdowns_form: "Filing to read",
  tagged_figures: "Tagged figures",
};

/**
 * What changed between two filings: its own family of marks, never a verdict, stance,
 * limit, model, decision or meaning mark. Unchanged paragraphs carry no mark.
 */
const CHANGE_MARK = {
  numbers_only: ["#", "Numbers only"],
  reworded: ["~", "Reworded"],
  added: ["+", "Added"],
  removed: ["−", "Removed"],
};
/** The five per-Item counts, in the order the rows show them. */
const CHANGE_COUNTS = ["unchanged", "numbers_only", "reworded", "added", "removed"];

/** Charts drawn from `series`, in order; each picks the quarterly series, else the annual one. */
const CHARTS = [
  { kind: "bars", keys: ["revenue"], title: "Revenue by period, in US dollars", axis: "USD" },
  { kind: "lines", keys: ["revenue_yoy"], title: "Revenue growth, year over year, in percent", axis: "Percent" },
  {
    kind: "lines",
    keys: ["gross_margin", "operating_margin", "net_margin"],
    title: "Gross, operating and net margin, in percent of revenue",
    axis: "Percent of revenue",
  },
];
/** Line identity never rests on colour: each series has its own dash pattern and marker. */
const LINE_STYLES = [
  { dash: "", marker: "circle" },
  { dash: "7 4", marker: "square" },
  { dash: "2 3", marker: "triangle" },
];

const state = {
  meta: null,
  sample: false,
  runId: null,
  viewSeq: 0, // bumped on every run or lookup selection; stale responses are dropped
  recentSeq: 0,
  timer: null,
  controller: null,
  bannerKey: "",
  chartSeq: 0,
  run: null, // the run on screen
  review: null, // the Review the server last returned for that run
  comparison: null, // the RunComparison whose later run is on screen
  thesisId: null, // the saved thesis on screen
  theses: new Map(), // saved theses by id, from GET /api/theses
  thesesSeq: 0,
  sampleName: "", // which sample file is on screen, in sample mode
  // The RunChanges of the finished run on screen: {runId, status: "loading" | "ready" | "failed", record, error}.
  claimChanges: null,
  claimChangesOpen: new Set(), // claim ids whose "Changed in the filings" block the reader opened
  sampleNote: "", // where a sample record came from, said in the run's head
  timelineRun: null, // the run whose time line is drawn, redrawn when the note changes width
  // The standing watch (version 13): /api/watch/meta, the watches by thesis, the health, the inbox.
  watchMeta: null,
  watches: new Map(),
  watchesLoaded: false,
  health: null,
  inboxUnread: null,
  inboxPage: null,
  inboxThesis: null, // the thesis the inbox is filtered to, or null for every thesis
  inboxOffsets: [], // the offsets of the pages before this one, to go back by the API's own offsets
  inboxSeq: 0,
  itemComparison: null, // an inbox item's `moved`, shown under the run it made
};

/** Samples that have a recorded RunChanges beside them; any other sample shows no such block and asks for none. */
const SAMPLE_RUN_CHANGES = { run: "sample-run-changes.json" };

/**
 * Samples stored as a bare run, copied unedited from a run's own record (results/<run>.json):
 * they carry no note and no wording, so the note is here and the wording comes from /api/meta.
 */
const BARE_SAMPLE_NOTES = {
  "run-events":
    "A live run of 18 November 2026 on NVIDIA (run run-39d0b17b5396), answered by the Anthropic API: claude-opus-5-5 read the passages and claude-haiku-5-5 checked their meaning. It is copied unedited from results/run-39d0b17b5396.json. Its first claim is about the chief executive leaving, and the 8-K of 12 Nov 2026 postdates the evidence of one of its findings.",
};

const THEMES = ["paper", "terminal"];
const THEME_KEY = "evidence-desk-theme";
const THEME_NAMES = { paper: "Paper", terminal: "Terminal" };

const $ = (id) => document.getElementById(id);

const els = {
  sampleTag: $("sample-tag"),
  engineLine: $("engine-line"),
  metaError: $("meta-error"),
  form: $("thesis-form"),
  ticker: $("ticker"),
  decision: $("decision"),
  claims: $("claims"),
  scope: $("scope_notes"),
  filings: $("filings"),
  urls: $("extra_urls"),
  tagged: $("tagged_figures"),
  advanced: $("advanced"),
  decisionCount: $("decision-count"),
  claimsCount: $("claims-count"),
  scopeHint: $("scope-hint"),
  filingsHint: $("filings-hint"),
  urlsHint: $("urls-hint"),
  formErrors: $("form-errors"),
  submit: $("submit"),
  figuresOnly: $("figures-only"),
  filingChanges: $("filing-changes"),
  changesForm: $("changes_form"),
  breakdowns: $("breakdowns"),
  breakdownsForm: $("breakdowns_form"),
  example: $("load-example"),
  saveThesis: $("save-thesis"),
  savePanel: $("save-panel"),
  thesisName: $("thesis_name"),
  saveConfirm: $("save-confirm"),
  saveCancel: $("save-cancel"),
  formNote: $("form-note"),
  thesesBlock: $("theses-block"),
  theses: $("theses"),
  recent: $("recent"),
  resultPanel: $("result-panel"),
  empty: $("empty-state"),
  loading: $("loading"),
  loadError: $("load-error"),
  figuresView: $("figures-view"),
  figuresHead: $("figures-head"),
  figuresStandalone: $("figures-standalone"),
  changesView: $("changes-view"),
  changesHead: $("changes-head"),
  changesBody: $("changes-body"),
  breakdownsView: $("breakdowns-view"),
  breakdownsHead: $("breakdowns-head"),
  breakdownsBody: $("breakdowns-body"),
  thesisView: $("thesis-view"),
  thesisHead: $("thesis-head"),
  runAgain: $("run-again"),
  runAgainMessage: $("run-again-message"),
  thesisRuns: $("thesis-runs"),
  thesisChangesSection: $("thesis-changes-section"),
  thesisChanges: $("thesis-changes"),
  runView: $("run-view"),
  banner: $("status-banner"),
  stagesWrap: $("stages-wrap"),
  stages: $("stages"),
  runHead: $("run-head"),
  reviewLine: $("review-line"),
  scorecard: $("scorecard"),
  distinction: $("distinction"),
  changesSection: $("changes-section"),
  changes: $("changes"),
  summarySection: $("summary-section"),
  summaryBox: $("summary-box"),
  summaryOrigin: $("summary-origin"),
  summary: $("summary"),
  figuresSection: $("figures-section"),
  figures: $("figures"),
  eventsSection: $("events-section"),
  eventsTitle: $("events-title"),
  events: $("events"),
  claimList: $("claim-list"),
  runFilingChanges: $("run-filing-changes"),
  withheldSection: $("withheld-section"),
  withheld: $("withheld"),
  unknownsSection: $("unknowns-section"),
  unknowns: $("unknowns"),
  nextSection: $("next-section"),
  nextSteps: $("next-steps"),
  sourcesBody: document.querySelector("#sources tbody"),
  limits: $("limits"),
  errors: $("errors"),
  errorsMore: $("errors-more"),
  provenance: $("provenance"),
  cmdRun: $("cmd-run"),
  cmdStatus: $("cmd-status"),
  cmdEngine: $("cmd-engine"),
  cmdAsof: $("cmd-asof"),
  themeToggle: $("theme-toggle"),
  keysButton: $("keys-button"),
  keysDialog: $("keys-dialog"),
  timelineSection: $("timeline-section"),
  timeline: $("timeline"),
  tapeSection: $("tape-section"),
  tape: $("tape"),
  boardHead: $("board-head"),
  howto: $("howto"),
  howtoButton: $("howto-button"),
  thesisButton: $("thesis-button"),
  formPanel: $("form-panel"),
  drawerClose: $("drawer-close"),
  drawerScrim: $("drawer-scrim"),
  leaveSample: $("leave-sample"),
  statusbarRun: $("statusbar-run"),
  keysHowto: $("keys-howto"),
  inboxView: $("inbox-view"),
  inboxHead: $("inbox-head"),
  inboxButton: $("inbox-button"),
  inboxCount: $("inbox-count"),
  inboxItems: $("inbox-items"),
  inboxCollapsed: $("inbox-collapsed"),
  inboxPaging: $("inbox-paging"),
  inboxMessage: $("inbox-message"),
  watches: $("watches"),
  watchesSection: $("watches-section"),
  watchDown: $("watch-down"),
  watchHealth: $("watch-health"),
  thesisWatch: $("thesis-watch"),
  thesisWatchSection: $("thesis-watch-section"),
};

// ---------------------------------------------------------------- helpers

/**
 * Build an element. `props` keys: `class`, `text`, `on<event>`, or any
 * attribute. Children may be nodes or strings; strings become text nodes.
 * Never pass an API value as `href`: use `externalLink` for those.
 */
function h(tag, props = null, ...children) {
  const node = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = String(value);
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : String(value));
    }
  }
  appendAll(node, children);
  return node;
}

const SVG_NS = "http://www.w3.org/2000/svg";

/** Build an SVG element; same conventions as `h`. */
function s(tag, attrs = null, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.setAttribute("class", value);
      else if (key === "text") node.textContent = String(value);
      else node.setAttribute(key, String(value));
    }
  }
  appendAll(node, children);
  return node;
}

function appendAll(node, children) {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false || child === "") continue;
    node.append(child instanceof Node ? child : String(child));
  }
}

/** The URL if it is an absolute http(s) address, otherwise null. */
function safeUrl(value) {
  if (typeof value !== "string") return null;
  return value.startsWith("https://") || value.startsWith("http://") ? value : null;
}

/** A new-tab link to an API-supplied URL, or plain text when the URL is unsafe. */
function externalLink(url, text, className = "ext") {
  const href = safeUrl(url);
  if (!href) return h("span", { class: "muted", text: "No link available" });
  return h(
    "a",
    { href, target: "_blank", rel: "noopener noreferrer", class: className },
    text,
    h("span", { class: "visually-hidden", text: " (opens in a new tab)" }),
    h("span", { "aria-hidden": "true", text: " ↗" }),
  );
}

/** A count from the record, grouped for reading; a missing count shows as a dash. */
function num(value) {
  return Number.isFinite(value) ? value.toLocaleString("en-US") : "—";
}

/** The unit word after a count from the record: "1 claim", "3 claims". */
function unit(count, one, many) {
  return count === 1 ? one : many;
}

/** "1 filing" / "3 filings": a count from the API with its unit. */
function plural(count, one, many) {
  return `${num(Number.isFinite(count) ? count : 0)} ${unit(count, one, many)}`;
}

/** A count from `run.coverage`, tagged with its field so the browser test can compare it. */
function cov(coverage, field) {
  return h("span", { class: "count-value", "data-coverage": field, text: num(coverage?.[field]) });
}

/** An ISO timestamp shown as "YYYY-MM-DD HH:MM UTC". */
function utc(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

function capitalize(word) {
  const text = String(word ?? "");
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

/** Only known enum values become CSS class suffixes. */
function token(value, allowed) {
  return Object.hasOwn(allowed, value) ? value : "unknown";
}

function formGloss(form) {
  if (!form) return "";
  return FORM_GLOSS[String(form).toUpperCase()] ?? "";
}

function str(value) {
  return typeof value === "string" ? value : "";
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

// ---------------------------------------------------------------- marks

/** ▲ amber: something limits this record. */
function limitGlyph() {
  return h("span", { class: "glyph g-limit", "aria-hidden": "true", text: "▲" });
}

/** A line that says what limits the record, with its mark. */
function limitLine(tag, ...content) {
  return h(tag, { class: "mark-limit" }, limitGlyph(), " ", ...content);
}

/** ✎ violet: written by a model and not checked for meaning (by a person, when a second model read it). */
function modelBadge(words = MODEL_BADGE) {
  return h(
    "span",
    { class: "badge-model" },
    h("span", { class: "glyph g-model", "aria-hidden": "true", text: "✎" }),
    ` ${words}`,
  );
}

/** ◎ / ◐ violet, double rule: a second model agrees, or agrees only in part. */
function meaningMark(support) {
  return h(
    "span",
    { class: `meaning-mark m-${support}` },
    h("span", { class: "glyph g-meaning", "aria-hidden": "true", text: MEANING_MARK[support] }),
    h("span", { class: "meaning-words", text: MEANING_WORDS[support] }),
  );
}

/** The second model's own sentence, under its double violet rule. `attr` tags it for the browser test. */
function checkerReason(reason, attr) {
  return h("p", { class: "checker-reason" }, h("span", { class: "label", text: "Second model's reason: " }), h("span", { [attr]: "", text: reason }));
}

/** Whether a second model read a finding's evidence: its support check has an outcome. */
function meaningRead(finding) {
  return ["passed", "partly", "failed"].includes(str(finding?.checks?.support));
}

/** Whether the run's record names a second model that checked meaning. */
function runMeaningChecked(run) {
  const checker = str(run?.checker);
  return checker !== "" && checker !== "none";
}

/**
 * ƒ olive, dotted: computed by a fixed rule and not checked by a person. `label` is the
 * mark's words; the legend defines it once.
 */
function ruleMark(label = "Fixed rule, not checked by a person") {
  return h(
    "span",
    { class: "rule-mark" },
    h("span", { class: "glyph g-rule", "aria-hidden": "true", text: "ƒ" }),
    h("span", { class: "rule-label", text: label }),
  );
}

/**
 * A long provenance note from the record, shortened for the eye and kept whole in the DOM.
 * The backend writes a replayed engine's note as "replayed from cassette …: N responses
 * recorded via <who answered> …; … with <models>, <dates>": the first clause (recorded, and
 * by whom) and the models stay in view; the full note is one click away. A note without a
 * second clause is shown as it is.
 */
function provenanceDetail(detail) {
  const full = str(detail);
  const first = provenanceFirst(full);
  if (!first) return full;
  return h("details", { class: "prov-more" }, h("summary", { class: "prov-first", text: first }), h("span", { class: "prov-full", text: full }));
}

/** The short form of a replayed engine's note (see provenanceDetail), or "" when it is not one or is already short. */
function provenanceFirst(detail) {
  const full = str(detail);
  const cut = full.indexOf("; ");
  if (!full.startsWith("replayed from cassette ") || cut < 0) return "";
  let first = full.slice(0, cut);
  const withAt = full.lastIndexOf(" with ");
  if (withAt > cut) first += ` … with ${full.slice(withAt + " with ".length)}`;
  return first;
}

/**
 * Sample mode, answers replayed from a cassette: the masthead's first line says so and who
 * answered, from the run's own note; the configured engine and checker, in full, are one
 * click away and stay in the DOM.
 */
function foldEngineLine(detail) {
  const first = provenanceFirst(detail);
  if (!first) return;
  const rest = [...els.engineLine.childNodes];
  els.engineLine.replaceChildren(
    h(
      "details",
      { class: "prov-more engine-more" },
      h("summary", { class: "prov-first" }, h("span", { class: "engine-name", text: "Recorded answers: " }), first),
      h("span", { class: "prov-full" }, ...rest),
    ),
  );
}

/** ! red: the server refused your input. */
function rejectGlyph() {
  return h("span", { class: "glyph g-reject", "aria-hidden": "true", text: "!" });
}

/**
 * A field that may have been written by a model. `id` names it for the browser
 * test; when `model` is true it carries the violet badge and border. `badge`
 * overrides the badge's words.
 */
function writtenField(tag, id, model, content, badge = MODEL_BADGE) {
  return h(tag, { class: model ? "mw is-model" : "mw", "data-mw": id }, content, model ? modelBadge(badge) : "");
}

/** A claim was assessed by a model when its engine is named and is not the extractive one. */
function modelAssessed(claim) {
  const by = str(claim?.assessed_by);
  return by !== "" && by !== EXTRACTIVE;
}

function verdictLabel(verdict) {
  return state.meta?.verdict_labels?.[verdict] ?? verdict ?? "Not assessed yet";
}

function verdictNote(verdict) {
  return state.meta?.verdict_notes?.[verdict] ?? "";
}

function verdictPill(verdict) {
  const key = verdict ? token(verdict, VERDICT_GLYPH) : "pending";
  return h(
    "span",
    { class: `pill verdict v-${key}`, "data-verdict": verdict ?? "pending", title: verdictNote(verdict) || null },
    h("span", { class: "glyph", "aria-hidden": "true", text: VERDICT_GLYPH[verdict] ?? "…" }),
    h("span", { class: "pill-label", text: verdictLabel(verdict) }),
  );
}

function stancePill(stance) {
  const key = token(stance, STANCE_MARK);
  const [glyph, label] = STANCE_MARK[stance] ?? ["•", String(stance)];
  return h(
    "span",
    { class: `pill stance s-${key}` },
    h("span", { class: "glyph", "aria-hidden": "true", text: glyph }),
    h("span", { class: "pill-label", text: label }),
  );
}

function decisionLabel(value) {
  return str(state.meta?.decision_labels?.[value]) || DECISION_FALLBACK[value] || String(value);
}

/** The reader's decision, as the server recorded it: "accepted", "rejected" or "undecided". */
function decisionMark(value) {
  const key = token(value, DECISION_MARK);
  return h(
    "span",
    { class: `decision-mark d-${key}`, "data-decision": key },
    h("span", { class: "glyph", "aria-hidden": "true", text: DECISION_MARK[key] ?? DECISION_MARK.undecided }),
    h("span", { class: "decision-label", text: decisionLabel(value) }),
  );
}

function statusMark(status) {
  const glyph = STATUS_GLYPH[status] ?? "·";
  return h("span", { class: LIMITING_STATUS.has(status) ? "glyph g-limit" : "glyph g-status", "aria-hidden": "true", text: glyph });
}

function fillList(listEl, items, emptyText, limit = false) {
  listEl.replaceChildren();
  const entries = list(items);
  if (entries.length === 0) {
    if (emptyText) listEl.append(h("li", { class: "muted", text: emptyText }));
    return;
  }
  for (const item of entries) listEl.append(limit ? limitLine("li", String(item)) : h("li", { text: String(item) }));
}

// ---------------------------------------------------------------- API

class ApiError extends Error {
  constructor(message, status, details = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

/** Fetch JSON; on failure throw an ApiError carrying the server's own message. */
async function api(url, options = {}) {
  let response;
  try {
    response = await fetch(url, { ...options, headers: { accept: "application/json", ...(options.headers ?? {}) } });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("the server could not be reached", 0);
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    // The app's refusals carry `error`; FastAPI's own 404s carry `detail`.
    const message =
      typeof payload?.error === "string" ? payload.error : typeof payload?.detail === "string" ? payload.detail : `the server answered HTTP ${response.status}`;
    const details = Array.isArray(payload?.details) ? payload.details : [];
    throw new ApiError(message, response.status, details);
  }
  if (payload === null || typeof payload !== "object") {
    throw new ApiError("the server's answer was not readable JSON", response.status);
  }
  return payload;
}

// ---------------------------------------------------------------- meta

async function loadMeta() {
  els.metaError.hidden = true;
  setFormEnabled(false);
  try {
    applyMeta(await api("/api/meta"));
  } catch (error) {
    showAlert(
      els.metaError,
      `The page could not load its limits and wording from the server: ${error.message}. The form stays disabled until they load.`,
      "Try again",
      loadMeta,
    );
  }
}

/** `sample`: the engine line will be folded by foldEngineLine, so the checker's note is left whole here. */
function applyMeta(meta, { sample = false } = {}) {
  if (!meta || typeof meta !== "object" || !meta.limits) throw new ApiError("the wording and limits are missing", 0);
  state.meta = meta;
  const limits = meta.limits;
  const engine = str(meta.engine);
  // `checker` is absent from servers older than the meaning check: then nothing is said about it.
  const checker = meta.checker && typeof meta.checker === "object" ? meta.checker : null;
  const checkerName = str(checker?.name);
  // A replayed checker's long note keeps its first clause (recorded, and by whom) in view.
  let checkerText = [];
  if (checker) {
    checkerText = checkerName && checkerName !== "none"
      ? [" Configured meaning check: ", sample ? str(checker.detail) || checkerName : provenanceDetail(str(checker.detail) || checkerName), "."]
      : [" No second model is configured to check meaning."];
  }
  els.engineLine.replaceChildren(
    h("span", { class: "engine-name", text: `Configured engine: ${engine || "not stated"}` }),
    ENGINE_GLOSS[engine] ? ` (${ENGINE_GLOSS[engine]}). Each result names the engine that actually did the work.` : "",
    ...checkerText,
  );
  if (Number.isInteger(limits.MAX_DECISION_CHARS)) els.decision.maxLength = limits.MAX_DECISION_CHARS;
  if (Number.isInteger(limits.MAX_SCOPE_CHARS)) els.scope.maxLength = limits.MAX_SCOPE_CHARS;
  els.filings.min = "1";
  els.filings.max = String(limits.MAX_FILINGS);
  if (!els.filings.value) els.filings.value = String(limits.DEFAULT_FILINGS);
  els.scopeHint.textContent = `Definitions and exclusions the engine should respect. Up to ${plural(limits.MAX_SCOPE_CHARS, "character", "characters")}.`;
  els.filingsHint.textContent = `1 to ${limits.MAX_FILINGS}; default ${limits.DEFAULT_FILINGS}. The latest annual report (10-K), then the quarterly reports (10-Q) filed after it, newest first.`;
  els.urlsHint.textContent = `A press release or investor-relations page, one http(s) address per line, up to ${limits.MAX_EXTRA_URLS}.`;
  if (Number.isInteger(limits.MAX_THESIS_NAME_CHARS)) {
    els.thesisName.maxLength = limits.MAX_THESIS_NAME_CHARS;
    $("thesis-name-hint").textContent = `Up to ${plural(limits.MAX_THESIS_NAME_CHARS, "character", "characters")}. Saved with the ticker, decision and claims above, so you can run it again when a new filing arrives.`;
  }
  updateCounts();
  setFormEnabled(!state.sample);
  els.example.disabled = state.sample || !meta.example;
}

function setFormEnabled(enabled) {
  els.submit.disabled = !enabled;
  els.figuresOnly.disabled = !enabled;
  els.filingChanges.disabled = !enabled;
  els.changesForm.disabled = !enabled;
  els.breakdowns.disabled = !enabled;
  els.breakdownsForm.disabled = !enabled;
  els.example.disabled = !enabled;
  els.saveThesis.disabled = !enabled;
}

// ---------------------------------------------------------------- form

/** Non-empty trimmed lines of a textarea. */
function lines(textarea) {
  return textarea.value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function readForm() {
  const filingsText = els.filings.value.trim();
  return {
    ticker: els.ticker.value.trim(),
    decision: els.decision.value.trim(),
    claims: lines(els.claims),
    scope_notes: els.scope.value.trim(),
    filings: filingsText === "" ? state.meta?.limits?.DEFAULT_FILINGS : Number(filingsText),
    extra_urls: lines(els.urls),
    // A strict boolean: the server refuses anything else.
    tagged_figures: els.tagged.checked === true,
  };
}

/** Immediate feedback against the limits from /api/meta. The server re-checks everything. */
function validate(body, limits) {
  const problems = [];
  const add = (field, message) => problems.push({ field, message });

  if (!body.ticker) add("ticker", "Enter a ticker, such as NVDA.");

  const d = body.decision.length;
  if (d < limits.MIN_DECISION_CHARS || d > limits.MAX_DECISION_CHARS) {
    add("decision", `Must be ${limits.MIN_DECISION_CHARS} to ${limits.MAX_DECISION_CHARS} characters; it has ${d}.`);
  }

  if (body.claims.length === 0) add("claims", "Enter at least one claim, one per line.");
  if (body.claims.length > limits.MAX_CLAIMS) {
    add("claims", `At most ${limits.MAX_CLAIMS} claims; there are ${body.claims.length}.`);
  }
  const seen = new Map();
  body.claims.forEach((claim, index) => {
    const text = claim.split(/\s+/).filter(Boolean).join(" ");
    if (text.length < limits.MIN_CLAIM_CHARS || text.length > limits.MAX_CLAIM_CHARS) {
      add("claims", `Claim ${index + 1} must be ${limits.MIN_CLAIM_CHARS} to ${limits.MAX_CLAIM_CHARS} characters; it has ${text.length}.`);
    }
    const key = text.toLowerCase();
    if (seen.has(key)) add("claims", `Claim ${index + 1} repeats claim ${seen.get(key) + 1}.`);
    else seen.set(key, index);
  });

  if (body.scope_notes.length > limits.MAX_SCOPE_CHARS) {
    add("scope_notes", `At most ${limits.MAX_SCOPE_CHARS} characters; it has ${body.scope_notes.length}.`);
  }

  if (!Number.isInteger(body.filings) || body.filings < 1 || body.filings > limits.MAX_FILINGS) {
    add("filings", `Enter a whole number from 1 to ${limits.MAX_FILINGS}.`);
  }

  if (body.extra_urls.length > limits.MAX_EXTRA_URLS) {
    add("extra_urls", `At most ${limits.MAX_EXTRA_URLS} pages; there are ${body.extra_urls.length}.`);
  }
  const seenUrls = new Set();
  body.extra_urls.forEach((url, index) => {
    if (!safeUrl(url)) add("extra_urls", `Line ${index + 1} must start with https:// or http://.`);
    if (seenUrls.has(url)) add("extra_urls", `Line ${index + 1} repeats an earlier address.`);
    seenUrls.add(url);
  });
  return problems;
}

/**
 * The form field a server or client error path belongs to: "claims.2" -> "claims",
 * "path.ticker" -> "ticker", "request.claims.0" (saving a thesis) -> "claims".
 */
function rootField(field) {
  return String(field ?? "")
    .replace(/^(path|query|request)\./, "")
    .split(/[.[]/)[0];
}

function clearFieldErrors() {
  for (const field of Object.keys(FIELD_NAMES)) setFieldError(field, []);
  els.formErrors.replaceChildren();
  els.formErrors.className = "alert form-alert";
  els.formErrors.hidden = true;
}

function setFieldError(field, messages) {
  const input = $(field);
  const slot = $(`err-${field}`);
  if (!input || !slot) return;
  slot.replaceChildren();
  if (messages.length) slot.append(rejectGlyph(), ` ${messages.join(" ")}`);
  slot.hidden = messages.length === 0;
  if (messages.length) input.setAttribute("aria-invalid", "true");
  else input.removeAttribute("aria-invalid");
}

/**
 * Show problems next to their fields and, with their field names, in one list
 * above the buttons. `problems` is [{field, message}] from the client or a 422.
 */
function showProblems(problems, heading) {
  clearFieldErrors();
  if (problems.length === 0) return;
  const byField = new Map();
  for (const { field, message } of problems) {
    const root = rootField(field);
    if (!byField.has(root)) byField.set(root, []);
    byField.get(root).push(String(message));
  }
  for (const [root, messages] of byField) setFieldError(root, messages);
  if ([...byField.keys()].some((root) => ["scope_notes", "filings", "extra_urls"].includes(root))) {
    els.advanced.open = true;
  }
  const items = h("ul");
  for (const { field, message } of problems) {
    const name = FIELD_NAMES[rootField(field)];
    items.append(h("li", null, h("code", { text: String(field ?? "request") }), name ? ` (${name})` : "", `: ${message}`));
  }
  els.formErrors.replaceChildren(h("p", { class: "alert-title" }, rejectGlyph(), ` ${heading}`), items);
  els.formErrors.className = "alert form-alert reject";
  els.formErrors.hidden = false;
  const first = $(rootField(problems[0].field));
  if (first) first.focus();
}

/** A message that is not a rejected input (the service is down, say): neutral, no mark. */
function showFormMessage(message) {
  clearFieldErrors();
  els.formErrors.replaceChildren(h("p", { text: message }));
  els.formErrors.hidden = false;
}

/** Live hints while typing: how many claims and decision characters, against the limits. */
function updateCounts() {
  const limits = state.meta?.limits;
  if (!limits) return;
  const claimCount = lines(els.claims).length;
  const over = claimCount > limits.MAX_CLAIMS;
  els.claimsCount.replaceChildren(over ? rejectGlyph() : "", `${over ? " " : ""}${claimCount} of ${limits.MAX_CLAIMS} claims.`);
  els.claimsCount.classList.toggle("over", over);
  const chars = els.decision.value.trim().length;
  els.decisionCount.textContent = `${chars} of ${limits.MAX_DECISION_CHARS} characters (at least ${limits.MIN_DECISION_CHARS}).`;
}

async function onSubmit(event) {
  event.preventDefault();
  if (state.sample || !state.meta) return;
  const body = readForm();
  const problems = validate(body, state.meta.limits);
  if (problems.length) {
    showProblems(problems, "Check these fields before the run can start:");
    return;
  }
  clearFieldErrors();
  els.submit.disabled = true;
  els.submit.textContent = "Starting…";
  try {
    const started = await api("/api/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (typeof started.id !== "string" || !started.id) throw new ApiError("the server did not return a run id", 0);
    watchRun(started.id);
    refreshRecent();
    focusResults();
  } catch (error) {
    if (error.status === 422 && error.details.length) {
      showProblems(error.details, "The server refused the request:");
    } else if (error.status === 503) {
      showFormMessage(`The service is unavailable: ${error.message}`);
    } else {
      showFormMessage(`The run could not be started: ${error.message}.`);
    }
  } finally {
    els.submit.disabled = false;
    els.submit.textContent = "Test the thesis";
  }
}

function focusResults() {
  els.resultPanel.focus({ preventScroll: true });
  if (window.matchMedia("(max-width: 900px)").matches) {
    els.resultPanel.scrollIntoView({ block: "start", behavior: "smooth" });
  }
}

function loadExample() {
  const example = state.meta?.example;
  if (!example) return;
  els.ticker.value = example.ticker ?? "";
  els.decision.value = example.decision ?? "";
  els.claims.value = list(example.claims).join("\n");
  els.scope.value = example.scope_notes ?? "";
  els.filings.value = String(example.filings ?? state.meta.limits.DEFAULT_FILINGS);
  els.urls.value = list(example.extra_urls).join("\n");
  els.tagged.checked = example.tagged_figures === true;
  els.advanced.open = Boolean(example.scope_notes || list(example.extra_urls).length || els.tagged.checked);
  clearFieldErrors();
  updateCounts();
  els.ticker.focus();
}

// ---------------------------------------------------------------- reported figures only

/** Look up a company's reported figures without starting a run. */
async function onFiguresOnly() {
  if (state.sample || !state.meta) return;
  const ticker = els.ticker.value.trim();
  if (!ticker) {
    showProblems([{ field: "ticker", message: "Enter a ticker, such as NVDA." }], "Check this field before looking up figures:");
    return;
  }
  clearFieldErrors();
  stopWatching();
  const seq = ++state.viewSeq;
  state.runId = null;
  state.run = null;
  state.thesisId = null;
  markRecent();
  history.replaceState(null, "", `${location.pathname}${location.search}`);
  hideRunView();
  els.loading.textContent = `Looking up the reported figures for ${ticker.toUpperCase()}…`;
  els.loading.hidden = false;
  els.figuresOnly.disabled = true;
  try {
    const report = await api(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/metrics`);
    if (seq !== state.viewSeq) return;
    if (!Array.isArray(report.metrics)) throw new ApiError("the answer has no list of figures", 0);
    renderFiguresOnly(report);
    focusResults();
  } catch (error) {
    if (seq !== state.viewSeq) return;
    els.loading.hidden = true;
    if (error.status === 422 && error.details.length) {
      showProblems(error.details, "The server refused the lookup:");
    } else if (error.status === 503) {
      showFormMessage(`The service is unavailable: ${error.message}`);
    } else {
      showLoadError(`The reported figures could not be loaded: ${error.message}.`, onFiguresOnly);
    }
  } finally {
    els.figuresOnly.disabled = state.sample;
  }
}

function renderFiguresOnly(report) {
  renderCommandBar(null);
  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = true;
  els.thesisView.hidden = true;
  els.inboxView.hidden = true;
  els.changesView.hidden = true;
  els.breakdownsView.hidden = true;
  els.figuresView.hidden = false;
  document.body.classList.add("has-run");
  els.figuresHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      companyTitle({ name: str(report.company), cik: report.cik }, str(report.ticker)),
      h("p", { class: "run-meta", text: "Reported figures read from the company's XBRL data. No run was started and no claim was tested." }),
    ),
  );
  renderFigures(els.figuresStandalone, { metrics: report.metrics, series: report.series, notes: report.notes });
}

// ---------------------------------------------------------------- what changed between two filings

/** Compare the company's two latest filings of the chosen form, without starting a run. */
async function onFilingChanges() {
  if (state.sample || !state.meta) return;
  const ticker = els.ticker.value.trim();
  const form = els.changesForm.value;
  if (!ticker) {
    showProblems([{ field: "ticker", message: "Enter a ticker, such as NVDA." }], "Check this field before comparing filings:");
    return;
  }
  clearFieldErrors();
  stopWatching();
  const seq = ++state.viewSeq;
  state.runId = null;
  state.run = null;
  state.thesisId = null;
  markRecent();
  history.replaceState(null, "", `${location.pathname}${location.search}`);
  hideRunView();
  els.loading.textContent = `Comparing the two latest ${form} filings of ${ticker.toUpperCase()}…`;
  els.loading.hidden = false;
  els.filingChanges.disabled = true;
  try {
    const record = await api(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/changes?form=${encodeURIComponent(form)}`);
    if (seq !== state.viewSeq) return;
    renderChanges(record, "");
    focusResults();
  } catch (error) {
    if (seq !== state.viewSeq) return;
    els.loading.hidden = true;
    if (error.status === 422 && error.details.length) {
      // The server names the form choice "form"; on this page it is the "changes_form" select.
      const details = error.details.map((d) => ({ ...d, field: rootField(d.field) === "form" ? "changes_form" : d.field }));
      showProblems(details, "The server refused the comparison:");
    } else {
      // 503: EDGAR could not be read, or it lists fewer than two such filings; the server says which.
      showLoadError(`The filings could not be compared: ${error.message}.`, onFilingChanges);
    }
  } finally {
    els.filingChanges.disabled = state.sample;
  }
}

/** A change mark: its glyph and label, in the change family's own style. */
function changeMark(kind) {
  const [glyph, label] = CHANGE_MARK[kind];
  return h(
    "span",
    { class: `chg-mark c-${kind}` },
    h("span", { class: "glyph g-chg", "aria-hidden": "true", text: glyph }),
    h("span", { class: "chg-label", text: label }),
  );
}

/** Only the glyph of a change mark, for a column of counts; its label is in the column head. */
function changeGlyph(kind) {
  return h("span", { class: `glyph g-chg c-${kind}`, "aria-hidden": "true", text: CHANGE_MARK[kind][0] });
}

/** One filing of the pair in words, as a link to its document. */
function filingLink(side) {
  return externalLink(side?.url, `the ${str(side?.form) || "filing"} for the period ended ${str(side?.period_end) || "—"}, filed ${str(side?.filed_date) || "—"}`);
}

/** Draw a FilingChanges record exactly as the server computed it: message, notes, totals, then each Item. */
function renderChanges(record, sampleNote) {
  if (!record || typeof record !== "object" || !Array.isArray(record.items) || !record.earlier || !record.later) {
    showLoadError("The comparison could not be shown: the record names no filings or Items.", null);
    return;
  }
  renderCommandBar(null);
  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = true;
  els.figuresView.hidden = true;
  els.thesisView.hidden = true;
  els.inboxView.hidden = true;
  els.breakdownsView.hidden = true;
  els.changesView.hidden = false;
  document.body.classList.add("has-run");

  const company = record.company ?? {};
  els.changesHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      state.sample ? h("span", { class: "page-tag inline", text: "Sample record" }) : "",
      companyTitle(company),
      h("p", { class: "run-meta", text: "What changed between two of the company's filings, Item by Item. No run was started and no claim was tested." }),
      sampleNote ? h("p", { class: "run-meta", text: `Sample: ${sampleNote}` }) : "",
    ),
  );

  const later = record.later;
  const earlier = record.earlier;
  const t = record.totals ?? {};
  const total = (field) => h("span", { class: "count-value", "data-chg-total": field, text: num(t[field]) });
  const parts = [
    h("p", { class: "changes-lead" }, "This compares the later filing, ", filingLink(later), ", against the earlier one, ", filingLink(earlier), "."),
    h(
      "p",
      { class: "changes-explain" },
      "Each paragraph is matched with the other filing's paragraphs in the same Item; a paragraph here is a longer line of text that is not a table row. The five counts are of paragraphs. Unchanged: the same text, perhaps moved within its Item. ",
      changeMark("numbers_only"),
      ": the same once numbers, dates and amounts are set aside. ",
      changeMark("reworded"),
      ": a paragraph in the later filing that mostly matches one in the earlier. ",
      changeMark("added"),
      " and ",
      changeMark("removed"),
      ": a paragraph with no counterpart in the other filing. Shorter lines and table rows are counted apart, in the same classes, and never listed. Every line of each filing is in exactly one count. A sub-heading is not a line: the sub-headings found in only one filing are named under their Item.",
    ),
    h(
      "p",
      { class: "changes-unknown" },
      h("strong", { text: "What this does not know: " }),
      "it compares the text this tool extracted from each filing, not the filing as printed; it does not know why anything changed; and a paragraph split in two reads as one reworded paragraph and one added.",
    ),
  ];
  if (Number.isFinite(later.item_coverage) && Number.isFinite(earlier.item_coverage)) {
    parts.push(h("p", { class: "hint", text: `Share of each filing's text that sits under a numbered Item, as the record gives it: later ${later.item_coverage}, earlier ${earlier.item_coverage}.` }));
  }
  const notes = list(record.notes);
  if (notes.length) {
    const notesList = h("ul", { class: "mark-list", id: "changes-notes" });
    fillList(notesList, notes, "", true);
    parts.push(h("section", { class: "block", "aria-label": "Notes on this comparison" }, h("h3", { class: "block-title", text: "Notes on this comparison" }), notesList));
  }
  parts.push(
    h(
      "section",
      { class: "block", "aria-labelledby": "chg-totals-title" },
      h("h3", { class: "block-title", id: "chg-totals-title", text: "All Items" }),
      h(
        "p",
        { class: "rule-note", "data-rule": "totals" },
        ruleMark(),
        " These classes come from a fixed rule, a word-overlap threshold with numbers set aside, that no person has checked against these filings.",
      ),
      h(
        "ul",
        { class: "chg-totals" },
        h("li", null, total("unchanged"), " unchanged"),
        ["numbers_only", "reworded", "added", "removed"].map((kind) => h("li", null, total(kind), " ", changeMark(kind))),
        h("li", { class: "chg-minor" }, minorLine((field) => total(field))),
      ),
    ),
  );
  const items = record.items;
  // Item 1A starts open (the Item people read first); without it, the first Item that lists anything.
  const riskFactors = items.findIndex((item) => str(item.item).startsWith("Item 1A"));
  const firstOpen = riskFactors >= 0 ? riskFactors : items.findIndex(hasListed);
  parts.push(
    h(
      "section",
      { class: "block", "aria-labelledby": "chg-items-title" },
      h("h3", { class: "block-title", id: "chg-items-title", text: "By Item" }),
      h("p", { class: "rule-note", "data-rule": "items" }, ruleMark(), " The same rule sorts each Item's counts and lists."),
      h("p", { class: "hint", text: "Open an Item to read its sub-headings found in one filing only, and the paragraphs added, removed, reworded or changed only in their numbers." }),
      h(
        "div",
        { class: "chg-grid chg-header", "aria-hidden": "true" },
        h("span", { text: "Item" }),
        h("span", { class: "chg-num", text: "Unchanged" }),
        ["numbers_only", "reworded", "added", "removed"].map((kind) => h("span", { class: "chg-num" }, changeGlyph(kind), ` ${CHANGE_MARK[kind][1]}`)),
      ),
      items.length ? items.map((item, index) => renderChangeItem(item, index, index === firstOpen)) : h("p", { class: "muted", text: "The record lists no Item." }),
    ),
  );
  els.changesBody.replaceChildren(...parts);
}

/** One Item: its five paragraph counts and four short-line counts as a row, opening to its lists. */
function renderChangeItem(item, index, open = false) {
  const presence = { later: "Only in the later filing", earlier: "Only in the earlier filing" }[item.present_in] ?? "";
  const word = (field) => (field === "unchanged" ? "unchanged" : CHANGE_MARK[field][1].toLowerCase());
  const cell = (field) =>
    h(
      "span",
      { class: "chg-num" },
      field === "unchanged" ? "" : changeGlyph(field),
      h("span", { class: "chg-count count-value", "data-chg-field": field, text: num(item[field]) }),
      h("span", { class: "visually-hidden", text: ` ${word(field)}` }),
    );
  const summary = h(
    "summary",
    { class: "chg-grid" },
    h(
      "span",
      { class: "chg-name" },
      h("span", { class: "chg-item-title", text: str(item.item) }),
      presence ? h("span", { class: "chg-presence", "data-present-in": item.present_in, text: presence }) : "",
      h("span", { class: "chg-minor" }, minorLine((field) => h("span", { "data-chg-field": field, text: num(item[field]) }))),
    ),
    CHANGE_COUNTS.map(cell),
  );
  return h("details", { class: "chg-item", "data-item-index": index, "data-item": str(item.item), open }, summary, renderChangeLists(item));
}

/** "Short lines and table rows: A unchanged, B numbers only, C added, D removed"; `count` draws each number. */
function minorLine(count) {
  return [
    "Short lines and table rows: ",
    count("minor_unchanged"),
    " unchanged, ",
    count("minor_numbers_only"),
    " numbers only, ",
    count("minor_added"),
    " added, ",
    count("minor_removed"),
    " removed",
  ];
}

/** Whether an Item lists anything: a paragraph, a pair, or a sub-heading in only one filing. */
function hasListed(item) {
  return ["added_paragraphs", "removed_paragraphs", "reworded_paragraphs", "numbers_only_paragraphs", "subheadings_added", "subheadings_removed"].some(
    (key) => list(item[key]).length > 0,
  );
}

/**
 * The words on a link into one of the two filings, by the record's `link_kind`: at the
 * paragraph, at its first line, or the filing only. A record without `link_kind` keeps
 * "at this paragraph". The run view says the same of a quote (`LINK_WORDS`).
 */
function changeLinkWords(paragraph, side) {
  const kind = str(paragraph?.link_kind);
  if (kind === "first-line") return `Open in the ${side} filing, at its first line`;
  if (kind === "document") return `Open the ${side} filing (the link opens the filing only: this text cannot be located in it)`;
  return `Open in the ${side} filing, at this paragraph`;
}

/** An Item's sub-headings found in one filing only, then its four lists, each with its truncation as the record states it. */
function renderChangeLists(item) {
  const body = h("div", { class: "chg-lists" });
  if (!hasListed(item)) {
    body.append(h("p", { class: "muted", text: "No paragraph or sub-heading was added, removed, reworded or changed in its numbers in this Item." }));
    return body;
  }
  const subheadings = (kind, side, title, names) =>
    h(
      "section",
      { class: "chg-list chg-subs", "data-subheadings": side },
      h("h4", { class: "chg-list-title" }, changeMark(kind), ` ${title}`),
      h("ul", { class: "chg-sub-list" }, names.map((name) => h("li", { text: String(name) }))),
    );
  const subsAdded = list(item.subheadings_added);
  const subsRemoved = list(item.subheadings_removed);
  if (subsAdded.length) body.append(subheadings("added", "later", "Sub-headings only in the later filing", subsAdded));
  if (subsRemoved.length) body.append(subheadings("removed", "earlier", "Sub-headings only in the earlier filing", subsRemoved));
  const added = list(item.added_paragraphs);
  const removed = list(item.removed_paragraphs);
  const reworded = list(item.reworded_paragraphs);
  const numbersOnly = list(item.numbers_only_paragraphs);
  const cut = item.truncated ?? {};
  if (added.length) body.append(changeList("added", "Added in the later filing", added, item.added, cut.added, (p) => paragraphEntry(p, "later")));
  if (removed.length) body.append(changeList("removed", "Removed from the earlier filing", removed, item.removed, cut.removed, (p) => paragraphEntry(p, "earlier")));
  if (reworded.length) body.append(changeList("reworded", "Reworded: the later paragraph, with the words it added and dropped", reworded, item.reworded, cut.reworded, (pair) => pairEntry(pair, true)));
  if (numbersOnly.length) body.append(changeList("numbers_only", "Numbers only: the same words, the figures that moved", numbersOnly, item.numbers_only, cut.numbers_only, (pair) => pairEntry(pair, false)));
  return body;
}

function changeList(kind, title, entries, count, truncated, draw) {
  return h(
    "section",
    { class: `chg-list l-${kind}`, "data-list": kind },
    h(
      "h4",
      { class: "chg-list-title" },
      changeMark(kind),
      ` ${title}`,
      truncated ? h("span", { class: "chg-trunc", "data-truncated": kind, text: ` · showing the first ${num(entries.length)} of ${num(count)}` }) : "",
    ),
    h("ol", { class: "chg-paras" }, entries.map(draw)),
  );
}

/**
 * An added or removed paragraph: its text, where it sits, and a link into its filing ("later"
 * or "earlier"). `head` (optional) goes first: the run view puts the mark and shared words there.
 */
function paragraphEntry(paragraph, side, head = null) {
  return h(
    "li",
    null,
    head,
    h("p", { class: "chg-text", text: str(paragraph.text) }),
    h(
      "p",
      { class: "chg-where" },
      h("span", { class: "label", text: "Located under: " }),
      str(paragraph.locator) || "location not recorded",
      " · ",
      externalLink(paragraph.link, changeLinkWords(paragraph, side)),
    ),
  );
}

/**
 * A reworded or numbers-only pair: the later paragraph drawn from `segments`, in reading
 * order, then (for a reworded pair) the record's similarity, and links into both filings.
 */
function pairEntry(pair, withSimilarity, head = null) {
  const quote = h("blockquote", { class: "chg-reworded" });
  list(pair.segments).forEach((segment, position) => {
    if (position > 0) quote.append(" ");
    const words = str(segment.text);
    if (segment.kind === "added") quote.append(h("ins", { class: "seg seg-add" }, h("span", { class: "visually-hidden", text: "[added] " }), words));
    else if (segment.kind === "removed") quote.append(h("del", { class: "seg seg-del" }, h("span", { class: "visually-hidden", text: "[removed] " }), words));
    else quote.append(words);
  });
  return h(
    "li",
    null,
    head,
    quote,
    h(
      "p",
      { class: "chg-where" },
      withSimilarity
        ? [
            h("span", { class: "label", text: "Word overlap with the earlier paragraph (Jaccard similarity of the word sets, common words and figures left out, so 1 does not mean identical; 0 to 1): " }),
            h("span", { "data-similarity": "", text: Number.isFinite(pair.similarity) ? String(pair.similarity) : "not recorded" }),
            " · ",
          ]
        : "",
      h("span", { class: "label", text: "Located under: " }),
      str(pair.after?.locator) || "location not recorded",
      " · ",
      externalLink(pair.after?.link, changeLinkWords(pair.after, "later")),
      " · ",
      externalLink(pair.before?.link, changeLinkWords(pair.before, "earlier")),
    ),
  );
}

// ---------------------------------------------------------------- tagged breakdowns

/** "Segments and customers (tagged facts)": GET /api/companies/{ticker}/breakdowns?form=. Starts no run. */
async function onBreakdowns() {
  if (state.sample || !state.meta) return;
  const ticker = els.ticker.value.trim();
  const form = els.breakdownsForm.value;
  if (!ticker) {
    showProblems([{ field: "ticker", message: "Enter a ticker, such as NVDA." }], "Check this field before reading the tagged facts:");
    return;
  }
  clearFieldErrors();
  stopWatching();
  const seq = ++state.viewSeq;
  state.runId = null;
  state.run = null;
  state.thesisId = null;
  markRecent();
  history.replaceState(null, "", `${location.pathname}${location.search}`);
  hideRunView();
  els.loading.textContent = `Reading the tagged facts in the latest ${form} of ${ticker.toUpperCase()}…`;
  els.loading.hidden = false;
  els.breakdowns.disabled = true;
  try {
    const report = await api(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/breakdowns?form=${encodeURIComponent(form)}`);
    if (seq !== state.viewSeq) return;
    renderBreakdowns(report, "");
    focusResults();
  } catch (error) {
    if (seq !== state.viewSeq) return;
    els.loading.hidden = true;
    if (error.status === 422 && error.details.length) {
      // The server names the form choice "form"; on this page it is the "breakdowns_form" select.
      const details = error.details.map((d) => ({ ...d, field: rootField(d.field) === "form" ? "breakdowns_form" : d.field }));
      showProblems(details, "The server refused the request:");
    } else {
      // 503: EDGAR could not list or deliver the filing; the server says which.
      showLoadError(`The tagged facts could not be read: ${error.message}.`, onBreakdowns);
    }
  } finally {
    els.breakdowns.disabled = state.sample;
  }
}

/** The key that places a value in its column: the period's start and end dates, as the record gives them. */
function periodKey(item) {
  return `${str(item?.period_start)}|${str(item?.period_end)}`;
}

/** Draw a BreakdownReport as the server wrote it: message first, notes, the facts read, then one table per breakdown. */
function renderBreakdowns(report, sampleNote) {
  if (!report || typeof report !== "object" || !Array.isArray(report.breakdowns) || !report.filing) {
    showLoadError("The tagged facts could not be shown: the record names no filing or breakdowns.", null);
    return;
  }
  renderCommandBar(null);
  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = true;
  els.figuresView.hidden = true;
  els.thesisView.hidden = true;
  els.inboxView.hidden = true;
  els.changesView.hidden = true;
  els.breakdownsView.hidden = false;
  document.body.classList.add("has-run");

  const company = report.company ?? {};
  const filing = report.filing;
  els.breakdownsHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      state.sample ? h("span", { class: "page-tag inline", text: "Sample record" }) : "",
      companyTitle(company),
      h("p", { class: "run-meta", text: "The company's latest filing of the form chosen, read when asked for the segments, products, geographies and customers it tags. Not tied to any run: no run was started and no claim was tested." }),
      sampleNote ? h("p", { class: "run-meta", text: `Sample: ${sampleNote}` }) : "",
    ),
  );

  const parts = [
    h(
      "p",
      { class: "changes-lead bd-lead" },
      "These are the numbers that ",
      filingLink(filing),
      " tags for the periods shown, split by segment, product, geography or customer.",
    ),
    h(
      "p",
      { class: "changes-explain bd-not" },
      ruleMark(),
      " What this is not: the row labels are derived from tag names and are not the company's own, and nothing here was checked against the filing's printed tables by a person.",
    ),
  ];
  const notes = list(report.notes);
  if (notes.length) {
    const notesList = h("ul", { class: "mark-list", id: "breakdowns-notes" });
    fillList(notesList, notes, "", true);
    parts.push(notesList);
  }
  parts.push(
    h(
      "p",
      { class: "bd-facts" },
      h("span", { "data-bd-field": "facts_read", text: num(report.facts_read) }),
      ` tagged ${unit(report.facts_read, "fact", "facts")} read, `,
      h("span", { "data-bd-field": "facts_unparsed", text: num(report.facts_unparsed) }),
      " could not be read.",
    ),
  );
  const breakdowns = list(report.breakdowns);
  if (breakdowns.length === 0) parts.push(h("p", { class: "muted", text: "This filing tags no breakdown this tool reads." }));
  breakdowns.forEach((breakdown) => parts.push(breakdownBlock(breakdown)));
  els.breakdownsBody.replaceChildren(...parts);
}

/** One breakdown: its title, concept and axis in small print, the table with the unit once, whether it adds up, its notes. */
function breakdownBlock(breakdown) {
  const id = str(breakdown.id);
  const periods = list(breakdown.periods);
  const total = list(breakdown.total);
  const row = (header, values, attrs) => {
    const byPeriod = new Map(list(values).map((value) => [periodKey(value), value]));
    return h("tr", attrs, header, periods.map((period) => breakdownCell(byPeriod.get(periodKey(period)), period)));
  };
  const table = h(
    "table",
    { class: "bd-table", "aria-label": str(breakdown.title) },
    h(
      "thead",
      null,
      h(
        "tr",
        null,
        h("th", { scope: "col", class: "bd-unit", text: str(breakdown.unit_label) || "Unit not recorded" }),
        periods.map((period) => h("th", { scope: "col", class: "bd-period", "data-period": periodKey(period), text: str(period.label) || str(period.period_end) })),
      ),
    ),
    h("tbody", null, list(breakdown.rows).map((r) => row(h("th", { scope: "row", class: "bd-label", text: str(r.label) || str(r.member) }), r.values, { "data-member": str(r.member) }))),
    total.length ? h("tfoot", null, row(h("th", { scope: "row", class: "bd-label", text: "Total, as tagged" }), total, { class: "bd-total" })) : "",
  );
  return h(
    "section",
    { class: "block bd-block", "data-breakdown-id": id, "aria-labelledby": `bd-title-${id}` },
    h("h3", { class: "block-title bd-title", id: `bd-title-${id}`, text: str(breakdown.title) }),
    h(
      "p",
      { class: "bd-meta" },
      "Tag ",
      h("code", { text: str(breakdown.concept) }),
      " along ",
      h("code", { text: str(breakdown.axis) }),
      str(breakdown.period_kind) ? ` · ${breakdown.period_kind}` : "",
    ),
    h("div", { class: "bd-scroll" }, table),
    addsUpLine(breakdown.adds_up),
    list(breakdown.notes).length ? h("ul", { class: "bd-notes" }, breakdown.notes.map((note) => h("li", { text: String(note) }))) : "",
  );
}

/** One cell: the record's `display`, and its `change_display` opening onto `change_formula`; empty when nothing is tagged. */
function breakdownCell(value, period) {
  const key = periodKey(period);
  if (!value) return h("td", { class: "bd-cell bd-empty", "data-period": key }, h("span", { class: "visually-hidden", text: "No value tagged" }));
  const formula = str(value.change_formula);
  const change = str(value.change_display);
  let changePart = "";
  if (formula) {
    changePart = h(
      "details",
      { class: "bd-change" },
      h("summary", null, change ? h("span", { class: `bd-change-display${signClass(change)}`, text: change }) : h("span", { class: "bd-no-change" }, h("span", { "aria-hidden": "true", text: "—" }), h("span", { class: "visually-hidden", text: "no change stated; open to read why" }))),
      h("span", { class: "bd-formula", text: formula }),
    );
  } else if (change) {
    changePart = h("span", { class: `bd-change-display${signClass(change)}`, text: change });
  }
  return h("td", { class: "bd-cell", "data-period": key }, h("span", { class: `bd-display${signClass(str(value.display))}`, text: str(value.display) }), changePart);
}

/** " num-neg" for a display string the record writes with a leading minus sign; "" otherwise. Reads the sign, computes nothing. */
function signClass(display) {
  return /^\s*[-−(]/.test(str(display)) ? " num-neg" : "";
}

/** Whether the rows add up to the tagged total: yes, no (a limit) or not checked, each drawn differently. */
function addsUpLine(addsUp) {
  if (addsUp === true) {
    return h("p", { class: "bd-adds bd-adds-yes", "data-adds-up": "yes" }, h("span", { class: "glyph g-adds", "aria-hidden": "true", text: "=" }), " Adds up: the rows add up to the tagged total in every period checked.");
  }
  if (addsUp === false) {
    return h("p", { class: "bd-adds bd-adds-no", "data-adds-up": "no" }, limitGlyph(), " Does not add up: in at least one period the rows do not add up to the tagged total. Read the filing's own table.");
  }
  return h("p", { class: "bd-adds bd-adds-unchecked", "data-adds-up": "unchecked" }, "Not checked: nothing here could be checked against a tagged total; the notes below say why.");
}

// ---------------------------------------------------------------- recent runs

async function refreshRecent() {
  if (state.sample) return;
  const seq = ++state.recentSeq;
  try {
    const payload = await api("/api/runs");
    if (seq !== state.recentSeq) return;
    renderRecent(list(payload.runs));
  } catch (error) {
    if (seq !== state.recentSeq) return;
    els.recent.replaceChildren(h("li", { class: "muted", text: `Recent runs could not be loaded: ${error.message}.` }));
  }
}

function renderRecent(runs) {
  els.recent.replaceChildren();
  if (runs.length === 0) {
    els.recent.append(h("li", { class: "muted", text: "No runs yet." }));
    return;
  }
  for (const run of runs) {
    const status = token(run.status, STATUS_GLYPH);
    const button = h(
      "button",
      {
        type: "button",
        class: "recent-item",
        "data-run": run.id,
        "aria-current": run.id === state.runId ? "true" : null,
        onclick: () => watchRun(run.id),
      },
      h("span", { class: "recent-name" }, h("strong", { text: run.ticker ?? "" }), run.company ? ` · ${run.company}` : ""),
      h(
        "span",
        { class: "recent-meta" },
        h("span", { class: `status-word st-${status}` }, statusMark(run.status), ` ${capitalize(run.status)}`),
        ` · ${plural(run.claims, "claim", "claims")} · started ${utc(run.started_at)}`,
      ),
    );
    els.recent.append(h("li", null, button));
  }
}

function markRecent() {
  for (const button of els.recent.querySelectorAll(".recent-item")) {
    if (button.dataset.run === state.runId) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  }
  for (const button of els.theses.querySelectorAll(".recent-item")) {
    if (button.dataset.thesis === state.thesisId) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  }
}

// ---------------------------------------------------------------- saved theses

/** Load the saved theses. A 404 means the server has no theses route: the feature stays hidden. */
async function refreshTheses() {
  if (state.sample) return;
  const seq = ++state.thesesSeq;
  try {
    const payload = await api("/api/theses");
    if (seq !== state.thesesSeq) return;
    const theses = list(payload.theses);
    state.theses = new Map(theses.map((t) => [t.id, t]));
    els.thesesBlock.hidden = false;
    els.saveThesis.hidden = false;
    renderTheses(theses);
    if (state.run?.thesis_id && !els.runView.hidden) renderHead(state.run);
  } catch (error) {
    if (seq !== state.thesesSeq) return;
    if (error.status === 404) {
      els.thesesBlock.hidden = true;
      els.saveThesis.hidden = true;
      els.savePanel.hidden = true;
      return;
    }
    els.thesesBlock.hidden = false;
    els.theses.replaceChildren(h("li", { class: "muted", text: `Saved theses could not be loaded: ${error.message}.` }));
  }
}

function renderTheses(theses) {
  els.theses.replaceChildren();
  if (theses.length === 0) {
    els.theses.append(h("li", { class: "muted", text: 'None yet. Fill in the form and choose "Save this thesis".' }));
    return;
  }
  for (const thesis of theses) {
    const last = thesis.last_status
      ? [" · last run ", h("span", { class: `status-word st-${token(thesis.last_status, STATUS_GLYPH)}` }, statusMark(thesis.last_status), ` ${capitalize(thesis.last_status)}`)]
      : " · not run yet";
    const button = h(
      "button",
      {
        type: "button",
        class: "recent-item",
        "data-thesis": thesis.id,
        "aria-current": thesis.id === state.thesisId ? "true" : null,
        onclick: () => openThesis(thesis.id),
      },
      h("span", { class: "recent-name" }, h("strong", { text: str(thesis.name) }), str(thesis.ticker) ? ` · ${thesis.ticker}` : ""),
      h("span", { class: "recent-meta" }, `${plural(thesis.claims, "claim", "claims")} · ${plural(thesis.runs, "run", "runs")}`, last),
      watchTag(state.watches.get(thesis.id)),
    );
    els.theses.append(h("li", null, button));
  }
}

/** On a saved thesis in the list: on watch, its policy, and its unread items, as the API says. */
function watchTag(watch) {
  if (!watch) return "";
  return h(
    "span",
    { class: "watch-tag", "data-watch-tag": str(watch.policy) },
    h("span", { class: "glyph", "aria-hidden": "true", text: "◉" }),
    ` On watch · ${str(watch.policy_label)}`,
    Number.isFinite(watch.unread) && watch.unread > 0 ? ` · ${num(watch.unread)} unread` : "",
  );
}

function toggleSavePanel(open) {
  els.savePanel.hidden = !open;
  els.saveThesis.setAttribute("aria-expanded", String(open));
  if (open) els.thesisName.focus();
  else setFieldError("thesis_name", []);
}

/** Save the form's request under a name. The server validates both; its 422 is shown by field. */
async function onSaveThesis() {
  if (state.sample || !state.meta) return;
  const request = readForm();
  const limits = state.meta.limits;
  const problems = validate(request, limits);
  const name = els.thesisName.value.split(/\s+/).filter(Boolean).join(" ");
  if (!name) problems.push({ field: "thesis_name", message: "Give the thesis a name." });
  else if (Number.isInteger(limits.MAX_THESIS_NAME_CHARS) && name.length > limits.MAX_THESIS_NAME_CHARS) {
    problems.push({ field: "thesis_name", message: `At most ${limits.MAX_THESIS_NAME_CHARS} characters; it has ${name.length}.` });
  }
  if (problems.length) {
    showProblems(problems, "Check these fields before the thesis can be saved:");
    return;
  }
  clearFieldErrors();
  els.saveConfirm.disabled = true;
  try {
    const thesis = await api("/api/theses", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, request }),
    });
    if (typeof thesis.id !== "string" || !thesis.id) throw new ApiError("the server did not return a thesis id", 0);
    toggleSavePanel(false);
    els.thesisName.value = "";
    els.formNote.textContent = `Saved as "${str(thesis.name) || name}". Run it from the thesis page.`;
    els.formNote.hidden = false;
    refreshTheses();
    openThesis(thesis.id);
  } catch (error) {
    if (error.status === 422 && error.details.length) {
      const details = error.details.map((d) => ({ ...d, field: rootField(d.field) === "name" ? "thesis_name" : d.field }));
      showProblems(details, "The server refused to save the thesis:");
    } else if (error.status === 404) {
      toggleSavePanel(false);
      els.saveThesis.hidden = true;
    } else {
      showFormMessage(`The thesis could not be saved: ${error.message}.`);
    }
  } finally {
    els.saveConfirm.disabled = false;
  }
}

/** Show one saved thesis: its request, its runs, and what moved between its last two runs. */
async function openThesis(thesisId) {
  stopWatching();
  const seq = ++state.viewSeq;
  state.runId = null;
  state.run = null;
  state.thesisId = thesisId;
  markRecent();
  history.replaceState(null, "", `#thesis=${encodeURIComponent(thesisId)}`);
  hideRunView();
  els.loading.textContent = "Loading the saved thesis…";
  els.loading.hidden = false;
  try {
    const payload = await api(`/api/theses/${encodeURIComponent(thesisId)}`);
    if (seq !== state.viewSeq) return;
    if (payload.thesis?.id !== thesisId) throw new ApiError("the server returned a different thesis than the one requested", 0);
    renderThesis(payload.thesis, list(payload.runs));
    loadThesisChanges(thesisId, seq);
    focusResults();
  } catch (error) {
    if (seq !== state.viewSeq) return;
    const reason = error.status === 404 ? "no saved thesis with that id exists" : error.message;
    showLoadError(`The saved thesis could not be loaded: ${reason}.`, () => openThesis(thesisId));
  }
}

function renderThesis(thesis, runs) {
  renderCommandBar(null);
  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = true;
  els.figuresView.hidden = true;
  els.changesView.hidden = true;
  els.breakdownsView.hidden = true;
  els.thesisView.hidden = false;
  document.body.classList.add("has-run");
  const request = thesis.request ?? {};
  const claims = list(request.claims);
  els.thesisHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      h("p", { class: "company-name" }, str(thesis.name)),
      h("p", { class: "company-line company" }, h("span", { class: "label", text: "Saved thesis" }), str(request.ticker) ? h("strong", { class: "ticker-chip", text: str(request.ticker) }) : ""),
      h("p", { class: "decision" }, h("span", { class: "label", text: "Decision: " }), str(request.decision)),
      h("p", { class: "run-meta", text: `${str(request.ticker)} · ${plural(claims.length, "claim", "claims")} · ${plural(request.filings, "filing", "filings")} per run · saved ${utc(thesis.created_at)}` }),
      h("ol", { class: "thesis-claims" }, claims.map((claim) => h("li", { text: String(claim) }))),
    ),
  );
  renderThesisWatch(thesis.id);
  els.runAgain.textContent = runs.length ? "Run again on the latest filings" : "Run it on the latest filings";
  els.runAgain.disabled = false;
  els.runAgainMessage.hidden = true;
  els.thesisRuns.replaceChildren();
  if (runs.length === 0) els.thesisRuns.append(h("li", { class: "muted", text: "No run yet." }));
  for (const run of runs) {
    const status = token(run.status, STATUS_GLYPH);
    els.thesisRuns.append(
      h(
        "li",
        null,
        h(
          "button",
          { type: "button", class: "recent-item", "data-run": run.id, onclick: () => watchRun(run.id) },
          h("span", { class: "recent-name", text: `Run ${run.id}` }),
          h(
            "span",
            { class: "recent-meta" },
            h("span", { class: `status-word st-${status}` }, statusMark(run.status), ` ${capitalize(run.status)}`),
            ` · started ${utc(run.started_at)}`,
            run.finished_at ? ` · finished ${utc(run.finished_at)}` : "",
          ),
        ),
      ),
    );
  }
  els.thesisChangesSection.hidden = false;
  els.thesisChanges.replaceChildren(h("p", { class: "muted", text: "Loading what moved…" }));
}

/**
 * What moved between the thesis's last two finished runs. A 409 (fewer than two)
 * is guidance, not an error; a 404 (no such route) hides the section.
 */
async function loadThesisChanges(thesisId, seq) {
  try {
    const comparison = await api(`/api/theses/${encodeURIComponent(thesisId)}/changes`);
    if (seq !== state.viewSeq) return;
    renderComparison(els.thesisChanges, comparison, null);
  } catch (error) {
    if (seq !== state.viewSeq) return;
    if (error.status === 404) els.thesisChangesSection.hidden = true;
    else if (error.status === 409) els.thesisChanges.replaceChildren(h("p", { class: "guidance", text: error.message }));
    else els.thesisChanges.replaceChildren(h("p", { class: "muted", text: `What moved could not be loaded: ${error.message}.` }));
  }
}

async function onRunAgain() {
  const thesisId = state.thesisId;
  if (state.sample || !thesisId) return;
  els.runAgain.disabled = true;
  els.runAgainMessage.hidden = true;
  try {
    const started = await api(`/api/theses/${encodeURIComponent(thesisId)}/runs`, { method: "POST" });
    if (typeof started.id !== "string" || !started.id) throw new ApiError("the server did not return a run id", 0);
    watchRun(started.id);
    refreshRecent();
    refreshTheses();
  } catch (error) {
    if (state.thesisId !== thesisId) return;
    els.runAgainMessage.textContent = `The run could not be started: ${error.message}.`;
    els.runAgainMessage.hidden = false;
    els.runAgain.disabled = false;
  }
}

// ---------------------------------------------------------------- what moved

/** A run id: a link to that run when it can be opened here, else plain text. */
function runRef(runId, currentRunId) {
  if (state.sample || !runId || runId === currentRunId) {
    return h("span", null, h("code", { text: runId || "—" }), runId && runId === currentRunId ? " (this run)" : "");
  }
  return h("a", { href: `#run=${encodeURIComponent(runId)}`, onclick: (event) => { event.preventDefault(); watchRun(runId); }, text: runId });
}

/** One side of a comparison row: the verdict, and the verdict after review when there is one. */
function comparisonVerdict(verdict, reviewed, side, missingText) {
  const cell = h("td", { class: `cmp-${side}`, "data-verdict": verdict ?? "none" });
  cell.append(verdict ? verdictPill(verdict) : h("span", { class: "muted", text: missingText }));
  if (reviewed) {
    cell.append(h("span", { class: "cmp-reviewed", "data-reviewed-verdict": reviewed }, h("span", { class: "slot-label", text: "After your review" }), verdictPill(reviewed)));
  }
  return cell;
}

/** Draw a RunComparison exactly as the server computed it. */
function renderComparison(container, comparison, currentRunId) {
  const claims = list(comparison.claims);
  container.replaceChildren();
  // A RunComparison has `note` and counts; an inbox item's `moved` has `comparison_note` and no counts.
  const note = str(comparison.note) || str(comparison.comparison_note);
  if (note) container.append(h("p", { class: "changes-note", text: note }));
  const counted = Number.isFinite(comparison.verdicts_moved) && Number.isFinite(comparison.claims_total);
  container.append(
    h(
      "p",
      { class: "changes-runs" },
      counted
        ? [
            h("span", { class: "count-value", "data-cmp": "verdicts_moved", text: num(comparison.verdicts_moved) }),
            " of ",
            h("span", { class: "count-value", "data-cmp": "claims_total", text: num(comparison.claims_total) }),
            ` ${unit(comparison.claims_total, "verdict", "verdicts")} moved. `,
          ]
        : "",
      "Earlier run ",
      comparison.earlier_run_id ? runRef(comparison.earlier_run_id, currentRunId) : "none (the thesis's first run)",
      comparison.earlier_finished_at ? `, finished ${utc(comparison.earlier_finished_at)}` : "",
      "; later run ",
      runRef(comparison.later_run_id, currentRunId),
      comparison.later_finished_at ? `, finished ${utc(comparison.later_finished_at)}` : "",
      ".",
    ),
  );
  const rows = claims.map((change, index) => {
    // A claim with no earlier verdict was not in the earlier run: "moved" or "unchanged" would not apply.
    const newClaim = change.before === null || change.before === undefined;
    const word = newClaim ? "new in the later run" : change.moved ? "moved" : "unchanged";
    return h(
      "tr",
      { "data-change": index, class: change.moved ? "is-moved" : null },
      h("th", { scope: "row", class: "cmp-claim", text: str(change.claim) }),
      comparisonVerdict(change.before, change.reviewed_before, "before", "not in the earlier run"),
      comparisonVerdict(change.after, change.reviewed_after, "after", "not in the later run"),
      h("td", { class: "cmp-move" }, h("span", { class: `move-word ${newClaim ? "is-new" : change.moved ? "is-moved" : "is-same"}`, text: word })),
      h(
        "td",
        { class: "cmp-excerpts" },
        h("span", { class: "cmp-count" }, h("span", { "data-cmp-field": "excerpts_added", text: num(change.excerpts_added) }), ` ${unit(change.excerpts_added, "excerpt", "excerpts")} added`),
        h("span", { class: "cmp-count" }, h("span", { "data-cmp-field": "excerpts_dropped", text: num(change.excerpts_dropped) }), ` ${unit(change.excerpts_dropped, "excerpt", "excerpts")} dropped`),
      ),
    );
  });
  container.append(
    h(
      "div",
      { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Verdicts by claim, earlier run and later run" },
      h(
        "table",
        { class: "changes" },
        h("thead", null, h("tr", null, ["Claim", "Earlier run", "Later run", "Change", "Excerpts"].map((t) => h("th", { scope: "col", text: t })))),
        h("tbody", null, rows.length ? rows : h("tr", null, h("td", { colspan: "5", class: "muted", text: "The comparison lists no claims." }))),
      ),
    ),
  );
  const filings = (title, titles, cls) =>
    h(
      "div",
      { class: `changes-filings ${cls}` },
      h("p", { class: "label", text: title }),
      list(titles).length ? h("ul", { class: "plain-list" }, list(titles).map((t) => h("li", { text: String(t) }))) : h("p", { class: "muted", text: "None." }),
    );
  container.append(
    h(
      "div",
      { class: "changes-filings-wrap" },
      filings("New filings in the later run", comparison.sources_added, "added"),
      Array.isArray(comparison.sources_dropped) ? filings("Filings the later run no longer read", comparison.sources_dropped, "dropped") : "",
    ),
  );
}

/** In the run view: what moved, when the comparison's later run is this run. */
function renderRunChanges(run) {
  // The thesis's latest comparison, else the comparison of the inbox item that opened this run.
  const fromItem = state.itemComparison?.later_run_id === run.id ? state.itemComparison : null;
  const comparison = state.comparison?.later_run_id === run.id ? state.comparison : fromItem;
  const show = Boolean(comparison) && comparison.later_run_id === run.id;
  els.changesSection.hidden = !show;
  if (show) renderComparison(els.changes, comparison, run.id);
  else els.changes.replaceChildren();
}

/** For a finished run that belongs to a thesis, fetch what moved; any failure hides the section quietly. */
async function loadRunChanges(run, seq) {
  if (!run.thesis_id || run.status === "running") return;
  try {
    const comparison = await api(`/api/theses/${encodeURIComponent(run.thesis_id)}/changes`);
    if (seq !== state.viewSeq) return;
    state.comparison = comparison;
    renderRunChanges(run);
  } catch {
    // 404 (no route), 409 (fewer than two finished runs) or unreachable: the thesis page says why.
  }
}

// ---------------------------------------------------------------- review

/** The Review on file for this run, or null. */
function currentReview(run) {
  return state.review && run && state.review.run_id === run.id ? state.review : null;
}

/** Fetch the reader's decisions for a finished run. A 404 hides review quietly. */
async function loadReview(runId, seq) {
  try {
    const review = await api(`/api/runs/${encodeURIComponent(runId)}/review`);
    if (seq !== state.viewSeq) return;
    if (review.run_id !== runId) throw new ApiError("the server returned the review of a different run", 0);
    applyReview(review, null);
  } catch (error) {
    if (seq !== state.viewSeq || error.status === 404) return;
    els.reviewLine.replaceChildren(h("p", { class: "muted", text: `Your review could not be loaded: ${error.message}.` }));
    els.reviewLine.hidden = false;
  }
}

/** Show a Review from the server everywhere it appears. `force` names a finding whose note is reset to the server's. */
function applyReview(review, force) {
  state.review = review;
  const run = state.run;
  if (!run || !review || review.run_id !== run.id) return;
  renderReviewLine(run);
  renderScorecard(run);
  renderReviewSlots(run, force);
}

function renderReviewLine(run) {
  const review = currentReview(run);
  els.reviewLine.hidden = !review;
  if (!review) {
    els.reviewLine.replaceChildren();
    return;
  }
  const count = h(
    "p",
    { class: "review-count" },
    "You have decided ",
    h("span", { class: "count-value", "data-review-field": "decided", text: num(review.decided) }),
    " of ",
    h("span", { class: "count-value", "data-review-field": "findings_total", text: num(review.findings_total) }),
    ` ${unit(review.findings_total, "finding", "findings")}.`,
    state.sample ? h("span", { class: "page-tag inline-tag", text: "sample: decisions are not saved" }) : "",
  );
  const parts = [count];
  if (str(state.meta?.review_note)) parts.push(h("p", { class: "review-note", text: state.meta.review_note }));
  if (review.complete) {
    parts.push(
      state.sample
        ? h("p", { class: "muted small", text: "The reviewed brief is not available for the sample record." })
        : h("p", null, h("a", { class: "download", href: briefHref(run.id, true), download: `evidence-desk-${run.id}-reviewed.md`, text: "Download reviewed brief" })),
    );
  }
  els.reviewLine.replaceChildren(...parts);
}

/** The "After your review" cell of a scorecard row, from the Review's claim entry. */
function reviewedSlot(entry) {
  const verdict = entry?.reviewed_verdict ?? null;
  const slot = h("span", { class: "verdict-slot slot-reviewed", "data-reviewed-verdict": verdict ?? "none" }, h("span", { class: "slot-label visually-hidden", text: "After your review" }));
  if (!verdict) {
    slot.append(h("span", { class: "pill review-pending", text: "not reviewed yet" }));
    return slot;
  }
  slot.append(
    verdictPill(verdict),
    h(
      "span",
      { class: "review-tally" },
      h("span", { "data-review-field": "accepted", text: num(entry.accepted) }),
      " accepted · ",
      h("span", { "data-review-field": "rejected", text: num(entry.rejected) }),
      " rejected",
    ),
  );
  if (Number.isFinite(entry.undecided) && entry.undecided > 0) {
    slot.append(h("span", { class: "undecided" }, h("span", { "data-review-field": "undecided", text: num(entry.undecided) }), " undecided"));
  }
  return slot;
}

/** Fill the review controls under each verified finding from the Review. */
function renderReviewSlots(run, force) {
  const review = currentReview(run);
  const decisions = new Map(list(review?.decisions).map((d) => [d.finding_id, d]));
  for (const slot of els.claimList.querySelectorAll("[data-review-finding]")) {
    if (!review) {
      slot.replaceChildren();
      slot.hidden = true;
      continue;
    }
    if (!slot.firstChild) buildReviewSlot(slot);
    slot.hidden = false;
    const id = slot.dataset.reviewFinding;
    updateReviewSlot(slot, decisions.get(id) ?? null, force === id);
  }
}

function buildReviewSlot(slot) {
  const findingId = slot.dataset.reviewFinding;
  const maxNote = state.meta?.limits?.MAX_NOTE_CHARS;
  const button = (value, text) =>
    h("button", {
      type: "button",
      class: "secondary small decide",
      "data-value": value,
      "aria-pressed": "false",
      text,
      onclick: () => {
        const current = slot.dataset.value || null;
        sendDecision(slot, current === value ? null : value);
      },
    });
  const note = h("input", {
    type: "text",
    class: "decision-note",
    maxlength: Number.isInteger(maxNote) ? maxNote : null,
    placeholder: "Optional note, saved with your decision",
    "aria-label": `Your note on finding ${findingId}`,
    onkeydown: (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        if (slot.dataset.value) sendDecision(slot, slot.dataset.value);
      }
    },
  });
  slot.append(
    h("p", { class: "decision-status" }, h("span", { class: "label", text: "Your decision: " }), h("span", { class: "decision-now" })),
    h(
      "div",
      { class: "decision-controls" },
      button("accepted", "Accept"),
      button("rejected", "Reject"),
      note,
      h("button", { type: "button", class: "secondary small save-note", text: "Save note", onclick: () => slot.dataset.value && sendDecision(slot, slot.dataset.value) }),
      state.sample ? h("span", { class: "page-tag", text: "sample: decisions are not saved" }) : "",
    ),
    h("p", { class: "review-message", role: "status", hidden: true }),
  );
}

/** Show the server's decision on one finding. The note is replaced only if untouched, or when forced. */
function updateReviewSlot(slot, decision, force) {
  const value = decision?.value === "accepted" || decision?.value === "rejected" ? decision.value : "";
  slot.dataset.value = value;
  slot.querySelector(".decision-now").replaceChildren(
    decisionMark(value || "undecided"),
    decision?.decided_at ? h("span", { class: "muted", text: ` · ${utc(decision.decided_at)}` }) : "",
  );
  for (const btn of slot.querySelectorAll(".decide")) {
    const pressed = btn.dataset.value === value;
    btn.setAttribute("aria-pressed", String(pressed));
    btn.title = pressed ? "Press again to clear your decision" : "";
  }
  const note = slot.querySelector(".decision-note");
  const saved = str(decision?.note);
  const dirty = note.value !== note.defaultValue;
  note.defaultValue = saved;
  if (force || !dirty) note.value = saved;
  setSlotBusy(slot, slot.dataset.busy === "1");
}

function setSlotBusy(slot, busy) {
  slot.dataset.busy = busy ? "1" : "";
  const locked = busy || state.sample;
  for (const btn of slot.querySelectorAll(".decide")) btn.disabled = locked;
  slot.querySelector(".decision-note").disabled = locked;
  slot.querySelector(".save-note").disabled = locked || !slot.dataset.value;
}

/** PUT one decision; show the Review the server returns, or its message and its last state. */
async function sendDecision(slot, value) {
  const run = state.run;
  if (state.sample || !run || slot.dataset.busy === "1") return;
  const findingId = slot.dataset.reviewFinding;
  const note = slot.querySelector(".decision-note").value.trim();
  const message = slot.querySelector(".review-message");
  const seq = state.viewSeq;
  message.hidden = true;
  message.className = "review-message";
  setSlotBusy(slot, true);
  try {
    const review = await api(`/api/runs/${encodeURIComponent(run.id)}/findings/${encodeURIComponent(findingId)}/decision`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ value, note }),
    });
    if (seq !== state.viewSeq) return;
    if (review.run_id !== run.id) throw new ApiError("the server returned the review of a different run", 0);
    setSlotBusy(slot, false);
    applyReview(review, findingId);
  } catch (error) {
    if (seq !== state.viewSeq) return;
    setSlotBusy(slot, false);
    applyReview(state.review, findingId); // back to what the server last said
    if (error.status === 422) {
      const lines = error.details.length ? error.details.map((d) => String(d.message)).join(" ") : error.message;
      message.replaceChildren(rejectGlyph(), ` Not saved: ${lines}`);
      message.className = "review-message reject";
    } else {
      message.textContent = `Not saved: ${error.message}.`;
    }
    message.hidden = false;
  }
}

// ---------------------------------------------------------------- run loading

function stopWatching() {
  if (state.timer) clearTimeout(state.timer);
  state.timer = null;
  if (state.controller) state.controller.abort();
  state.controller = null;
}

/** Show one run and poll it while it runs. A newer selection cancels this one. */
function watchRun(runId) {
  stopWatching();
  const seq = ++state.viewSeq;
  const controller = new AbortController();
  state.controller = controller;
  state.runId = runId;
  state.thesisId = null;
  state.run = null;
  state.review = null;
  state.comparison = null;
  state.bannerKey = "";
  history.replaceState(null, "", `#run=${encodeURIComponent(runId)}`);
  markRecent();
  hideRunView();
  els.loading.textContent = `Loading run ${runId}…`;
  els.loading.hidden = false;

  const tick = async () => {
    try {
      const run = await api(`/api/runs/${encodeURIComponent(runId)}`, { signal: controller.signal });
      if (seq !== state.viewSeq) return;
      if (run.id !== runId) throw new ApiError("the server returned a different run than the one requested", 0);
      renderRun(run);
      if (run.status === "running") {
        state.timer = setTimeout(tick, POLL_MS);
      } else {
        refreshRecent();
        loadReview(run.id, seq);
        if (run.thesis_id) {
          refreshTheses();
          loadRunChanges(run, seq);
        }
      }
    } catch (error) {
      if (seq !== state.viewSeq || error.name === "AbortError") return;
      const reason = error.status === 404 ? "no run with that id exists" : error.message;
      showLoadError(`Run ${runId} could not be loaded: ${reason}. The results shown before were cleared so they cannot be mistaken for this run.`, () => watchRun(runId));
    }
  };
  tick();
}

function hideRunView() {
  els.runView.hidden = true;
  els.figuresView.hidden = true;
  els.changesView.hidden = true;
  els.breakdownsView.hidden = true;
  els.thesisView.hidden = true;
  els.inboxView.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  document.body.classList.remove("has-run");
  els.inboxButton?.setAttribute("aria-expanded", "false");
  renderCommandBar(null);
  state.timelineRun = null;
}

function showLoadError(message, retry) {
  hideRunView();
  els.loading.hidden = true;
  state.bannerKey = "";
  showAlert(els.loadError, message, retry ? "Try again" : null, retry);
}

function showAlert(container, message, actionText, action) {
  container.replaceChildren(h("p", { text: message }));
  if (actionText && action) {
    container.append(h("button", { type: "button", class: "secondary small", onclick: action, text: actionText }));
  }
  container.hidden = false;
}

/** `?sample` loads /sample-run.json; `?sample=<name>` loads /sample-<name>.json. */
async function loadSample(name) {
  state.sampleName = name;
  els.sampleTag.hidden = false;
  els.formNote.textContent = "Sample mode: this page shows a stored record and does not start runs. Open the page without ?sample to test a thesis.";
  els.formNote.hidden = false;
  els.recent.replaceChildren(h("li", { class: "muted", text: "Recent runs are not loaded in sample mode." }));
  els.thesesBlock.hidden = false;
  els.theses.replaceChildren(h("li", { class: "muted", text: "Saved theses are not loaded in sample mode." }));
  els.saveThesis.hidden = false;
  // The way out of sample mode sits in the command bar; the sample links are not offered inside one.
  $("sample-link").hidden = true;
  if (els.leaveSample) {
    els.leaveSample.href = location.pathname;
    els.leaveSample.hidden = false;
  }
  $("synthetic-link").hidden = true;
  $("changes-link").hidden = true;
  $("breakdowns-link").hidden = true;
  $("tagged-link").hidden = true;
  $("events-link").hidden = true;
  $("inbox-link").hidden = true;
  hideRunView();
  if (!SAMPLE_NAME.test(name)) {
    showLoadError("That sample name is not valid: use lower-case letters, digits and hyphens.", null);
    return;
  }
  try {
    if (Object.hasOwn(INBOX_SAMPLES, name)) {
      await loadInboxSample(name);
      return;
    }
    const payload = await api(`sample-${name}.json`, { cache: "no-store" });
    // A bare run, copied unedited from a run's record: its note is the page's, its wording /api/meta's.
    if (!payload.run && typeof payload.id === "string" && Array.isArray(payload.claims)) {
      const note = BARE_SAMPLE_NOTES[name];
      if (!note) throw new ApiError("the file is a bare run that this page has no note for", 0);
      applyMeta(await api("/api/meta"), { sample: true });
      state.sampleNote = note;
      els.formNote.textContent = `Sample mode: ${note} This page does not start runs; open it without ?sample to test a thesis.`;
      state.runId = payload.id;
      state.review = null;
      state.comparison = null;
      renderRun(payload);
      return;
    }
    // A recorded filing comparison ({note, changes}) has no run and needs no wording from /api/meta.
    if (payload.changes && !payload.run) {
      if (str(payload.note)) els.formNote.textContent = `Sample mode: ${payload.note} This page does not look anything up; open it without ?sample to compare a company's filings.`;
      renderChanges(payload.changes, str(payload.note));
      return;
    }
    // A recorded reading of one filing's tagged facts ({note, report}): no run, no /api/meta.
    if (payload.report && !payload.run) {
      if (str(payload.note)) els.formNote.textContent = `Sample mode: ${payload.note} This page does not look anything up; open it without ?sample to read a company's tagged facts.`;
      renderBreakdowns(payload.report, str(payload.note));
      return;
    }
    if (!payload.meta || !payload.run) throw new ApiError("the file has no meta or run", 0);
    applyMeta(payload.meta, { sample: true });
    foldEngineLine(payload.run.engine_detail);
    if (str(payload.note)) els.formNote.textContent = `Sample mode: ${payload.note} This page does not start runs; open it without ?sample to test a thesis.`;
    state.sampleNote = str(payload.note);
    state.runId = payload.run.id;
    // Sample mode only: the reader's decisions and the comparison are stored in the file.
    const review = payload.review;
    state.review = review && typeof review === "object" && review.run_id === payload.run.id ? review : null;
    const comparison = payload.comparison;
    state.comparison = comparison && typeof comparison === "object" ? comparison : null;
    renderRun(payload.run);
  } catch (error) {
    showLoadError(`The sample record could not be loaded: ${error.message}.`, null);
  }
}

// ---------------------------------------------------------------- run rendering

function renderRun(run) {
  const claims = list(run.claims);
  const ctx = {
    run,
    sources: new Map(list(run.sources).map((x) => [x.id, x])),
    evidence: new Map(list(run.evidence).map((x) => [x.id, x])),
    findings: new Map([...list(run.findings), ...list(run.unsupported_findings)].map((x) => [x.id, x])),
    claims: new Map(claims.map((x) => [x.id, x])),
    metrics: new Map(list(run.metrics).map((x) => [x.id, x])),
  };

  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.figuresView.hidden = true;
  els.changesView.hidden = true;
  els.breakdownsView.hidden = true;
  els.thesisView.hidden = true;
  els.inboxView.hidden = true;
  els.runView.hidden = false;
  document.body.classList.add("has-run");
  state.run = run;

  renderCommandBar(run);
  renderBanner(run);
  renderStages(run);
  renderHead(run);
  renderTape(run);
  renderTimeline(run);
  renderReviewLine(run);
  renderScorecard(run);
  renderDistinction(run);
  renderRunChanges(run);
  renderSummary(run);
  renderEvents(run);
  renderRunFigures(run);
  renderClaims(run, ctx);
  renderClaimChanges(run);
  renderReviewSlots(run, null);
  renderWithheld(run, ctx);
  renderBriefLists(run);
  renderSources(run);
  const finished = run.status !== "running";
  fillList(els.limits, run.coverage_limits, finished ? "None recorded." : "Listed when the run finishes.", true);
  renderErrors(run, finished);
  // The run's own note (it names any page the user added); a record without one uses /api/meta's.
  els.provenance.textContent = str(run.brief?.provenance_note) || str(state.meta?.provenance_note);
}

/** Status, its note from /api/meta, and the coverage counts exactly as the API gives them. */
function renderBanner(run) {
  const status = token(run.status, STATUS_GLYPH);
  const c = run.coverage ?? {};
  const key = JSON.stringify([run.id, run.status, run.stage, run.stage_detail, c, state.sample]);
  if (key === state.bannerKey) return; // unchanged: do not re-announce to screen readers
  state.bannerKey = key;
  els.banner.className = `banner st-${status}`;

  const head = h(
    "p",
    { class: "banner-head" },
    state.sample ? h("span", { class: "page-tag inline", text: "Sample record" }) : "",
    statusMark(run.status),
    h("strong", { text: ` ${capitalize(run.status)}` }),
    h("span", { class: "banner-note", text: ` ${state.meta?.status_notes?.[run.status] ?? ""}` }),
  );
  const parts = [head];
  if (run.status === "running") {
    const stage = STAGES.find(([id]) => id === run.stage);
    parts.push(h("p", { class: "banner-line", text: `Now: ${stage ? stage[1] : run.stage}${run.stage_detail ? ` — ${run.stage_detail}` : ""}` }));
  } else {
    // Counts kept since a review found the banner claimed more than the record backed. A record
    // from before them lacks them (or, read back through the API, holds 0): it renders as before.
    // `quotes_found` counts every quote located word for word; a record holding 0 for it while
    // it kept excerpts predates the field, so the excerpts count stands in, as it used to.
    const asked = Number.isFinite(c.filings_asked) && c.filings_asked > 0 && c.filings_asked !== c.sources_requested;
    const foundField = Number.isFinite(c.quotes_found) && (c.quotes_found > 0 || !(c.excerpts_verified > 0)) ? "quotes_found" : "excerpts_verified";
    const positive = (field) => Number.isFinite(c[field]) && c[field] > 0;
    const facts = [
      h(
        "li",
        null,
        cov(c, "sources_read"),
        " of ",
        cov(c, "sources_requested"),
        ` ${unit(c.sources_requested, "source", "sources")} read`,
        asked ? [" (", cov(c, "filings_asked"), ` ${unit(c.filings_asked, "filing", "filings")} asked for)`] : "",
      ),
      h("li", null, cov(c, "passages_indexed"), ` ${unit(c.passages_indexed, "passage", "passages")} indexed`),
      h("li", null, cov(c, "claims_with_evidence"), " of ", cov(c, "claims_total"), ` ${unit(c.claims_total, "claim", "claims")} with verified excerpts or figures`),
    ];
    const hasProposed = Number.isFinite(c.findings_proposed) && (c.findings_proposed > 0 || list(run.findings).length === 0);
    facts.push(
      hasProposed
        ? h("li", null, cov(c, "findings_verified"), " of ", cov(c, "findings_proposed"), ` proposed ${unit(c.findings_proposed, "finding", "findings")} verified, `, cov(c, "findings_withheld"), " withheld")
        : h("li", null, cov(c, "findings_verified"), ` ${unit(c.findings_verified, "finding", "findings")} verified, `, cov(c, "findings_withheld"), " withheld"),
    );
    if (positive("findings_without_quote")) {
      facts.push(h("li", null, cov(c, "findings_without_quote"), ` verified ${unit(c.findings_without_quote, "finding rests", "findings rest")} on reported figures only, with no quote`));
    }
    facts.push(
      h(
        "li",
        null,
        cov(c, foundField),
        " of ",
        cov(c, "quotes_offered"),
        ` ${unit(c.quotes_offered, "quote", "quotes")} offered found word for word, `,
        cov(c, "quotes_rejected"),
        " did not pass the check",
        foundField === "quotes_found" ? ["; ", cov(c, "excerpts_verified"), " kept as evidence of verified findings"] : "",
      ),
    );
    if (Number.isFinite(c.metrics_computed)) {
      facts.push(h("li", null, cov(c, "metrics_computed"), ` reported ${unit(c.metrics_computed, "figure", "figures")} computed`));
    }
    if (Number.isFinite(c.figures_offered)) {
      // Two counts, never added up here: the record keeps them apart.
      const tagged = Number.isFinite(c.tagged_figures_offered) && (c.tagged_figures_offered > 0 || run.inputs?.tagged_figures === true);
      facts.push(
        h(
          "li",
          { "data-figures-offered": "" },
          cov(c, "figures_offered"),
          ` reported ${unit(c.figures_offered, "figure", "figures")}`,
          tagged ? [" and ", cov(c, "tagged_figures_offered"), ` tagged ${unit(c.tagged_figures_offered, "figure", "figures")}`] : "",
          " offered to the engine",
          Number.isFinite(c.figures_cited) ? ["; ", cov(c, "figures_cited"), ` ${unit(c.figures_cited, "citation", "citations")} of them in verified findings`] : "",
        ),
      );
    }
    if (Number.isFinite(c.numbers_checked)) {
      facts.push(h("li", null, cov(c, "numbers_checked"), ` ${unit(c.numbers_checked, "number", "numbers")} in findings checked, `, cov(c, "numbers_unmatched"), " unmatched"));
    }
    if (Number.isFinite(c.periods_checked)) {
      // The period check reports; it withholds nothing. Its three counts, as the record gives them.
      facts.push(
        h(
          "li",
          { "data-periods-line": "" },
          cov(c, "periods_checked"),
          ` ${unit(c.periods_checked, "year", "years")} named in verified findings checked against their evidence, `,
          cov(c, "periods_unverified"),
          " not found",
          Number.isFinite(c.periods_unverified) && c.periods_unverified > 0 && Number.isFinite(c.periods_comparative)
            ? [" (", cov(c, "periods_comparative"), ` of them ${unit(c.periods_comparative, "a comparison year", "comparison years")})`]
            : "",
        ),
      );
    }
    if (positive("reasons_withheld")) {
      facts.push(h("li", null, cov(c, "reasons_withheld"), ` ${unit(c.reasons_withheld, "reason", "reasons")} withheld by the number check`));
    }
    if (Number.isFinite(c.findings_checked) && c.findings_checked > 0) {
      facts.push(
        h(
          "li",
          null,
          cov(c, "findings_checked"),
          ` ${unit(c.findings_checked, "finding", "findings")} checked for meaning, `,
          cov(c, "findings_partly"),
          " agreed only in part, ",
          cov(c, "findings_failed_meaning"),
          " withheld",
        ),
      );
    }
    parts.push(h("ul", { class: "coverage-facts", "aria-label": "Coverage" }, facts));
    if (Number.isFinite(c.engine_fallbacks) && c.engine_fallbacks > 0) {
      parts.push(
        limitLine(
          "p",
          "The model engine failed for ",
          cov(c, "engine_fallbacks"),
          ` of its ${unit(c.engine_fallbacks, "step", "steps")}; the deterministic engine answered ${unit(c.engine_fallbacks, "that step", "those")}.`,
        ),
      );
    }
    if (list(run.coverage_limits).length) {
      parts.push(h("p", { class: "banner-line" }, h("a", { href: "#coverage-limits", onclick: jumpTo("coverage-limits"), text: "Read the coverage limits" })));
    }
    // One line under the head, the full counts one click away: every count stays in the record's words.
    const wasOpen = els.banner.querySelector("details.banner-fold")?.open ?? false;
    const sep = () => h("span", { class: "banner-sep", "aria-hidden": "true", text: " · " });
    const line = h(
      "summary",
      { class: "banner-summary" },
      h("span", { class: `status-word st-${status}` }, statusMark(run.status), ` ${capitalize(run.status)}`),
      sep(),
      h("span", null, cov(c, "sources_read"), " of ", cov(c, "sources_requested"), ` ${unit(c.sources_requested, "source", "sources")}`),
      sep(),
      hasProposed
        ? h("span", null, cov(c, "findings_verified"), " of ", cov(c, "findings_proposed"), ` ${unit(c.findings_proposed, "finding", "findings")} verified`)
        : h("span", null, cov(c, "findings_verified"), ` ${unit(c.findings_verified, "finding", "findings")} verified`),
      sep(),
      h("span", null, cov(c, "findings_withheld"), " withheld"),
      list(run.coverage_limits).length ? [sep(), h("span", { class: "banner-limits" }, limitGlyph(), " limits")] : "",
      h("span", { class: "banner-open", text: "all counts" }),
    );
    els.banner.replaceChildren(h("details", { class: "banner-fold", open: wasOpen }, line, h("div", { class: "banner-full" }, ...parts)));
    return;
  }
  els.banner.replaceChildren(...parts);
}

function jumpTo(id) {
  return (event) => {
    event.preventDefault();
    const target = $(id);
    if (!target) return;
    target.scrollIntoView({ block: "start", behavior: "smooth" });
    target.focus({ preventScroll: true });
  };
}

function renderStages(run) {
  const running = run.status === "running";
  els.stagesWrap.hidden = !running;
  if (!running) return;
  const current = STAGES.findIndex(([id]) => id === run.stage);
  els.stages.replaceChildren(
    ...STAGES.map(([, label], index) => {
      const phase = current < 0 || index > current ? "todo" : index < current ? "done" : "now";
      return h(
        "li",
        { class: `stage ${phase}`, "aria-current": phase === "now" ? "step" : null },
        label,
        phase === "done" ? h("span", { class: "visually-hidden", text: " (finished)" }) : "",
      );
    }),
  );
}

/**
 * The note's title: the company's name large, then its ticker and CIK, as the record names
 * them. Used by every view that is about one company.
 */
function companyTitle(company, fallbackTicker = "") {
  const ticker = str(company?.ticker) || fallbackTicker;
  return [
    h("p", { class: "company-name", text: str(company?.name) || ticker || "Company" }),
    h(
      "p",
      { class: "company-line company" },
      ticker ? h("strong", { class: "ticker-chip", text: ticker }) : "",
      Number.isFinite(company?.cik) ? h("span", null, h("abbr", { title: "The SEC's numeric identifier for this company", text: "CIK" }), ` ${company.cik}`) : "",
    ),
  ];
}

/** Where a sample record came from, in the head of the view that shows it. */
function sampleNoteLine() {
  if (!state.sample || !state.sampleNote) return "";
  // Its first sentence in view; the whole note one click away (the same note, not a shorter one).
  const note = state.sampleNote;
  const cut = note.indexOf(". ");
  const first = cut > 0 ? note.slice(0, cut + 1) : note;
  return h(
    "div",
    { class: "sample-note", "data-sample-note": "" },
    cut > 0
      ? h("details", { class: "prov-more" }, h("summary", null, h("span", { class: "label", text: "Sample: " }), first), h("p", { class: "prov-full", text: note }))
      : h("p", null, h("span", { class: "label", text: "Sample: " }), note),
  );
}

/**
 * The command bar's cells for the run on screen: its status, the engine that did the work,
 * and its as-of line, each the record's own words. Hidden for any other view.
 */
function renderCommandBar(run) {
  if (!els.cmdRun) return;
  if (!run) {
    if (els.statusbarRun) els.statusbarRun.textContent = "";
    els.cmdRun.hidden = true;
    els.cmdStatus.replaceChildren();
    els.cmdEngine.replaceChildren();
    els.cmdAsof.replaceChildren();
    return;
  }
  const status = token(run.status, STATUS_GLYPH);
  els.cmdRun.hidden = false;
  els.cmdStatus.replaceChildren(h("span", { class: `status-word st-${status}` }, statusMark(run.status), ` ${capitalize(run.status)}`));
  // The engine's own detail names the model and where its answers came from (the API or a recording).
  const reader = str(run.engine_detail) || str(run.engine) || "not recorded";
  const checker = runMeaningChecked(run) ? str(run.checker_detail) || str(run.checker) : "";
  els.cmdEngine.replaceChildren(
    h("span", { class: "cmd-line", "data-cmd-engine": "", title: reader, tabindex: "0" }, h("span", { class: "cmd-key", text: "read " }), reader),
    checker ? h("span", { class: "cmd-line", "data-cmd-checker": "", title: checker, tabindex: "0" }, h("span", { class: "cmd-key", text: "checked " }), checker) : "",
  );
  if (els.statusbarRun) els.statusbarRun.textContent = `${str(run.id)} · ${str(run.status)}`;
  const line = str(run.as_of?.line);
  els.cmdAsof.replaceChildren(
    line
      ? h("span", { "data-cmd-as-of": "" }, line, " ", h("a", { href: "#events-section", onclick: jumpTo("events-section"), text: "8-Ks" }))
      : h("span", { class: "muted", text: "Not recorded: this run predates the as-of line." }),
  );
}

function renderHead(run) {
  const company = run.company;
  const inputs = run.inputs ?? {};
  const title = companyTitle(company, str(inputs.ticker));
  const decision = h("p", { class: "decision" }, h("span", { class: "label", text: "Decision: " }), inputs.decision ?? "");
  const engine = str(run.engine);
  const engineLine = h(
    "p",
    { class: "run-engine" },
    h("span", { class: "label", text: "Engine that did the work: " }),
    h("span", { class: "engine-used", text: engine || "not recorded" }),
    str(run.engine_detail) ? h("span", { class: "engine-detail" }, " — ", provenanceDetail(run.engine_detail)) : "",
  );
  const checkerLine = runMeaningChecked(run)
    ? h("p", { class: "run-engine run-checker" }, h("span", { class: "label", text: "Meaning checked by: " }), h("span", { class: "checker-used" }, provenanceDetail(str(run.checker_detail) || str(run.checker))))
    : h("p", { class: "run-engine run-checker" }, h("span", { class: "label", text: "Meaning not checked" }));
  const details = h(
    "p",
    { class: "run-meta" },
    `Run ${run.id} · started ${utc(run.started_at)}`,
    run.finished_at ? ` · finished ${utc(run.finished_at)}` : "",
    ` · ${plural(inputs.filings, "filing", "filings")} requested`,
  );
  let download;
  if (state.sample) {
    download = h("span", { class: "muted small", text: "The Markdown brief is not available for the sample record." });
  } else if (run.status === "running") {
    download = h("span", { class: "muted small", text: "The Markdown brief can be downloaded when the run finishes." });
  } else {
    download = h("a", { class: "download", href: briefHref(run.id, false), download: `evidence-desk-${run.id}.md`, text: "Download Markdown brief" });
  }
  els.runHead.replaceChildren(
    h("div", { class: "run-head-main" }, title, decision, engineLine, checkerLine, details, asOfLine(run), thesisLine(run), sampleNoteLine()),
    h("div", { class: "run-head-actions" }, download, run.status !== "running" && !state.sample ? h("span", { class: "muted", text: "Print this page for a paper copy of the note." }) : ""),
  );
}

/**
 * How old the evidence is, as the record's as-of block words it, with a way to the 8-Ks.
 * Nothing for a run recorded before version 12, which has no as-of block.
 */
function asOfLine(run) {
  const line = str(run.as_of?.line);
  if (!line) return "";
  return h(
    "p",
    { class: "as-of", "data-as-of": "" },
    h("span", { class: "label", text: "As of: " }),
    line,
    " ",
    h("a", { href: "#events-section", onclick: jumpTo("events-section"), text: "See the 8-Ks since the annual report" }),
  );
}

/**
 * The Markdown brief of a run, with the changed paragraphs listed for each claim
 * (`changes=true`); `reviewed` adds the reader's decisions.
 */
function briefHref(runId, reviewed) {
  const query = new URLSearchParams();
  if (reviewed) query.set("reviewed", "true");
  query.set("changes", "true");
  return `/api/runs/${encodeURIComponent(runId)}/export.md?${query}`;
}

/** "Part of the saved thesis ..." with a way back, for a run started from a saved thesis. */
function thesisLine(run) {
  const thesisId = str(run.thesis_id);
  if (!thesisId) return "";
  const thesis = state.theses.get(thesisId);
  const name = thesis ? h("strong", { text: `"${str(thesis.name)}"` }) : h("code", { text: thesisId });
  let back;
  if (state.sample) {
    back = state.comparison?.later_run_id === run.id ? h("a", { href: "#changes-section", onclick: jumpTo("changes-section"), text: "See what moved since its earlier run" }) : "";
  } else {
    back = h("a", { href: `#thesis=${encodeURIComponent(thesisId)}`, onclick: (event) => { event.preventDefault(); openThesis(thesisId); }, text: "Open the thesis" });
  }
  return h("p", { class: "run-thesis" }, "Part of the saved thesis ", name, ". ", back);
}

/** Who assessed a claim, in words. */
function assessedText(claim) {
  const by = str(claim.assessed_by);
  if (!by) return "";
  return by === EXTRACTIVE ? "Assessed by: extractive (no model)" : `Assessed by: ${by} (a model)`;
}

/** One row per claim: verdict first, then the claim, then counts the API lists. */
function renderScorecard(run) {
  const claims = list(run.claims);
  const c = run.coverage ?? {};
  els.scorecard.replaceChildren();
  if (claims.length === 0) {
    els.scorecard.append(h("li", { class: "muted", text: run.status === "running" ? "Claims appear once the run has planned them." : "This run recorded no claims." }));
    return;
  }
  const review = currentReview(run);
  const reviewed = new Map(list(review?.claims).map((entry) => [entry.claim_id, entry]));
  // One header over the board's columns when there is a review; each row keeps its own labels for screen readers.
  if (els.boardHead) els.boardHead.hidden = !review;
  els.scorecard.classList.toggle("has-review", Boolean(review));
  claims.forEach((claim, index) => {
    const verdicts = review
      ? h(
          "span",
          { class: "score-verdicts" },
          h("span", { class: "verdict-slot slot-engine" }, h("span", { class: "slot-label visually-hidden", text: "Engine" }), verdictPill(claim.verdict)),
          reviewedSlot(reviewed.get(claim.id)),
        )
      : verdictPill(claim.verdict);
    const passages = Number.isFinite(c.passages_indexed)
      ? [h("span", { "data-claim-field": "passages_considered", text: num(claim.passages_considered ?? 0) }), " of ", cov(c, "passages_indexed"), " passages considered"]
      : [h("span", { "data-claim-field": "passages_considered", text: num(claim.passages_considered ?? 0) }), " passages considered"];
    const row = h(
      "a",
      { class: review ? "score-row has-review" : "score-row", href: `#claim-${index}`, onclick: openClaim(index) },
      verdicts,
      h(
        "span",
        { class: "score-claim" },
        h("span", { class: "claim-id", text: claim.id }),
        " ",
        claim.text,
        assessedText(claim) ? h("span", { class: "assessed", text: assessedText(claim) }) : "",
      ),
      h("span", { class: "score-counts" }, `${plural(list(claim.finding_ids).length, "finding", "findings")} · `, ...passages),
    );
    els.scorecard.append(h("li", { "data-claim-id": claim.id }, row));
  });
}

/** The note under the verdicts as index.html writes it: the wording for a run no second model read. */
const DISTINCTION_DEFAULT = els.distinction ? els.distinction.cloneNode(true) : null;

/** The note under the verdicts: what was checked, and by whom, for this run. */
function renderDistinction(run) {
  if (!els.distinction) return;
  if (!runMeaningChecked(run)) {
    els.distinction.replaceChildren(...DISTINCTION_DEFAULT.cloneNode(true).childNodes);
    return;
  }
  els.distinction.replaceChildren(
    "Each verdict follows by a fixed rule from the findings that passed their checks. ",
    h("strong", { text: "Checked:" }),
    " every quote was found word for word in the stored filing, and numbers were matched to quotes and reported figures. ",
    h("strong", { text: "Read by a second model, not checked by a person:" }),
    " whether a quote supports or challenges the claim is the engine's reading of it; then a second model, which was not shown the first one's reasoning, read each finding's evidence and judged whether it supports the statement and its stance. That is still a model's reading, which your accept or reject is there to test. Read the quotes before you rely on a verdict.",
  );
}

function openClaim(index) {
  return (event) => {
    event.preventDefault();
    const section = $(`claim-${index}`);
    if (!section) return;
    section.open = true;
    section.scrollIntoView({ block: "start", behavior: "smooth" });
    section.querySelector("summary")?.focus({ preventScroll: true });
  };
}

function renderSummary(run) {
  const brief = run.brief;
  els.summarySection.hidden = !brief;
  if (!brief) return;
  const origin = str(brief.summary_origin);
  const model = origin === MODEL_ORIGIN;
  els.summaryBox.className = model ? "mw is-model" : "mw";
  els.summaryOrigin.replaceChildren(
    model
      ? h("span", null, modelBadge(), " Check it against the verdicts and quotes below.")
      : h("span", { class: "origin-tag", text: `Written by: ${origin || "not stated"}${origin === "template" ? " (fixed wording filled in from the record)" : ""}` }),
  );
  els.summary.textContent = str(brief.summary);
}

function renderClaims(run, ctx) {
  const open = new Set([...els.claimList.querySelectorAll("details[open]")].map((d) => d.id));
  els.claimList.replaceChildren();
  list(run.claims).forEach((claim, position) => {
    const id = `claim-${position}`;
    const model = modelAssessed(claim);
    const body = h("div", { class: "claim-body" });
    const note = verdictNote(claim.verdict);
    if (note) body.append(h("p", { class: "verdict-note" }, h("span", { class: "label", text: "Verdict rule: " }), note));
    if (assessedText(claim)) body.append(h("p", { class: "assessed-line", text: assessedText(claim) }));
    if (str(claim.caution)) {
      body.append(h("div", { class: "claim-caution", "data-claim-caution": claim.id }, limitLine("p", h("strong", { text: "Caution: " }), claim.caution)));
    }
    if (str(claim.event_note)) {
      body.append(h("p", { class: "event-note", "data-claim-event-note": claim.id }, h("span", { class: "label", text: "8-Ks since the annual report: " }), claim.event_note));
    }
    if (claim.rationale) {
      body.append(
        writtenField(
          "div",
          `claim:${claim.id}:commentary`,
          model,
          [
            h("p", { class: "label", text: `Engine's commentary (${str(claim.assessed_by) || str(run.engine) || "engine"}), not a verified excerpt` }),
            h("p", { text: claim.rationale }),
          ],
        ),
      );
    }
    if (list(claim.queries).length) {
      body.append(h("p", { class: "queries" }, h("span", { class: "label", text: "Searched with: " }), claim.queries.join(" · ")));
    }
    const ids = list(claim.finding_ids);
    if (ids.length === 0) {
      body.append(h("p", { class: "muted", text: run.status === "running" ? "Findings appear when this claim has been assessed." : "No verified finding is recorded for this claim." }));
    }
    ids.forEach((findingId) => {
      const finding = ctx.findings.get(findingId);
      if (!finding) body.append(h("p", { class: "muted", text: `Finding ${findingId} is listed but missing from the record.` }));
      else if (finding.verified === false) body.append(h("p", { class: "muted", text: `Finding ${findingId} was withheld; it is listed under "Withheld findings" below.` }));
      else body.append(renderFinding(finding, ctx));
    });
    // Filled by drawClaimChanges once the finished run's changed paragraphs have loaded.
    body.append(h("div", { class: "cc-slot", "data-cc-slot": claim.id }));
    const details = h(
      "details",
      { class: "claim", id, open: open.has(id), "data-docket": claim.id },
      h(
        "summary",
        null,
        verdictPill(claim.verdict),
        h("span", { class: "claim-id", text: claim.id }),
        h("span", { class: "claim-text", text: claim.text }),
        docketMeta(claim, run),
      ),
      body,
    );
    els.claimList.append(details);
  });
}

/**
 * The line under a claim on its docket: how many findings the record lists for it and how many
 * passages it considered, then a flag for a caution or an 8-K note the claim carries.
 */
function docketMeta(claim, run) {
  const c = run.coverage ?? {};
  const parts = [
    plural(list(claim.finding_ids).length, "finding", "findings"),
    ` · ${num(claim.passages_considered ?? 0)}`,
    Number.isFinite(c.passages_indexed) ? ` of ${num(c.passages_indexed)}` : "",
    " passages considered",
  ];
  if (str(claim.caution)) parts.push(" · ", h("span", { class: "docket-flag" }, limitGlyph(), " Caution"));
  else if (str(claim.event_note)) parts.push(" · ", h("span", { class: "docket-flag", text: "Note on the 8-Ks since the annual report" }));
  return h("span", { class: "docket-meta" }, ...parts);
}

// ---------------------------------------------------------------- changed paragraphs, by claim

/** What was compared: the newest report of each form the run read, with the one filed before it. */
const CC_EARLIER = "The newest annual report and the newest quarterly report this run read are each compared with the filing of the same form filed before it. An older quarterly report this run read is not compared. The earlier filing of each pair was fetched for the comparison, and this run may not have read it.";

/** Why these paragraphs are listed, said wherever they are. */
const CC_WHY = "These paragraphs are listed because they share words with the claim or the search queries the run wrote for it: no model chose or judged them, they are not findings, and none counts toward the verdict.";

/**
 * For a finished run, which paragraphs changed in the filings it read (each against the filing
 * of its form before it) and share words with each claim: GET /api/runs/{id}/changes, once per
 * run, or the sample's recorded file. Nothing is shown, or asked for, while the run is running
 * or for a sample without such a file.
 */
function renderClaimChanges(run) {
  const wanted = run.status !== "running" && (!state.sample || Object.hasOwn(SAMPLE_RUN_CHANGES, state.sampleName));
  if (!wanted) {
    els.runFilingChanges.hidden = true;
    els.runFilingChanges.replaceChildren();
    return;
  }
  if (state.claimChanges?.runId === run.id) drawClaimChanges();
  else loadClaimChanges(run.id);
}

async function loadClaimChanges(runId) {
  state.claimChanges = { runId, status: "loading", record: null, error: "" };
  drawClaimChanges();
  let next;
  try {
    const url = state.sample ? SAMPLE_RUN_CHANGES[state.sampleName] : `/api/runs/${encodeURIComponent(runId)}/changes`;
    const payload = await api(url, { cache: "no-store" });
    const record = state.sample ? payload.changes : payload;
    if (!record || typeof record !== "object" || !Array.isArray(record.claims)) throw new ApiError("the record lists no claims", 0);
    if (str(record.run_id) !== runId) throw new ApiError("the record is for another run", 0);
    next = { runId, status: "ready", record, error: "" };
  } catch (error) {
    next = { runId, status: "failed", record: null, error: error.message };
  }
  if (state.claimChanges?.runId !== runId) return; // another run is on screen now
  state.claimChanges = next;
  drawClaimChanges();
}

/** Fill the block above the claims and each claim's slot from `state.claimChanges`. */
function drawClaimChanges() {
  const loaded = state.claimChanges;
  if (!loaded || state.run?.id !== loaded.runId) return;
  const top = els.runFilingChanges;
  const slots = [...els.claimList.querySelectorAll("[data-cc-slot]")];
  top.hidden = false;
  if (loaded.status !== "ready") {
    top.replaceChildren(
      loaded.status === "loading"
        ? h("p", { class: "muted", text: "Looking up which paragraphs changed in the filings since the ones before…" })
        : h(
            "p",
            { class: "cc-error", "data-cc-error": "" },
            limitGlyph(),
            ` The changed paragraphs could not be loaded: ${loaded.error}. The rest of the run is shown. `,
            h("button", { type: "button", class: "secondary small", onclick: () => loadClaimChanges(loaded.runId), text: "Try again" }),
          ),
    );
    slots.forEach((slot) => slot.replaceChildren());
    return;
  }
  const record = loaded.record;
  top.replaceChildren(comparedBlock(record));
  const byClaim = new Map(list(record.claims).map((entry) => [entry.claim_id, entry]));
  slots.forEach((slot) => slot.replaceChildren(claimChangesBlock(slot.dataset.ccSlot, byClaim.get(slot.dataset.ccSlot))));
  // The browser's own jump to #claim-<id>-changes happened before these nodes existed: do it now, once per load.
  if (!loaded.jumped) {
    loaded.jumped = true;
    openClaimChangesFromHash();
  }
}

/** The id of a claim's "Changed in the filings" block: the target of a link such as #claim-c4-changes. */
function claimChangesId(claimId) {
  return `claim-${claimId}-changes`;
}

/**
 * Open the claim and the block that `location.hash` names (#claim-<claim id>-changes) and
 * scroll it into view. A hash that names no block on screen does nothing.
 */
function openClaimChangesFromHash() {
  if (!/^#claim-.+-changes$/.test(location.hash)) return;
  let id;
  try {
    id = decodeURIComponent(location.hash.slice(1));
  } catch {
    return;
  }
  const target = document.getElementById(id);
  if (!target || !els.claimList.contains(target)) return;
  const claim = target.closest("details.claim");
  if (claim) claim.open = true;
  if (target.tagName === "DETAILS") {
    target.open = true;
    state.claimChangesOpen.add(target.dataset.claimChanges);
  }
  // After the next frame: the claim and block just opened, and their layout must settle first.
  requestAnimationFrame(() => target.scrollIntoView({ block: "start" }));
}

/** Which filings were compared (form, both period ends, each a link) and the record's notes. */
function comparedBlock(record) {
  const compared = list(record.compared);
  const notes = h("ul", { class: "mark-list cc-notes" });
  fillList(notes, list(record.notes), "", true);
  return h(
    "div",
    { "data-cc-compared": "" },
    h("p", { class: "cc-title" }, h("strong", { text: "Changed since the previous annual and quarterly report" }), " ", ruleMark()),
    h("p", { class: "cc-earlier", text: CC_EARLIER }),
    compared.length
      ? h(
          "ul",
          { class: "cc-pairs" },
          compared.map((pair) =>
            h("li", { "data-form": str(pair.form) }, h("strong", { text: `${str(pair.form) || "Form not recorded"}: ` }), filingLink(pair.later), ", against ", filingLink(pair.earlier)),
          ),
        )
      : h("p", { class: "muted", text: "No pair of filings was compared." }),
    list(record.notes).length ? notes : "",
    h("p", { class: "cc-why", text: `Under each claim, after its findings. ${CC_WHY}` }),
  );
}

/** One claim's changed paragraphs: collapsed, its counts as the record states them, then each entry, best first. */
function claimChangesBlock(claimId, entry) {
  if (!entry) {
    return h("p", { class: "cc-none", id: claimChangesId(claimId), "data-claim-changes": claimId }, ruleMark(), " No list of changed paragraphs was recorded for this claim.");
  }
  const changes = list(entry.changes);
  const field = (name, value) => h("span", { "data-cc-field": name, text: num(value) });
  if (changes.length === 0) {
    return h(
      "p",
      { class: "cc-none", id: claimChangesId(claimId), "data-claim-changes": claimId },
      ruleMark(),
      " Changed since the previous annual and quarterly report: no paragraph shares at least two words with this claim or the search queries the run wrote for it, among ",
      field("considered", entry.considered),
      ` changed ${unit(entry.considered, "paragraph", "paragraphs")} searched.`,
    );
  }
  return h(
    "details",
    {
      class: "claim-changes",
      id: claimChangesId(claimId),
      "data-claim-changes": claimId,
      open: state.claimChangesOpen.has(claimId),
      ontoggle: (event) => {
        if (event.currentTarget.open) state.claimChangesOpen.add(claimId);
        else state.claimChangesOpen.delete(claimId);
      },
    },
    h(
      "summary",
      null,
      h("span", { class: "cc-summary-text" }, `Changed since the previous annual and quarterly report: ${plural(changes.length, "paragraph", "paragraphs")} that share words with this claim or the search queries the run wrote for it`),
      " ",
      ruleMark(),
    ),
    h(
      "div",
      { class: "cc-body" },
      h(
        "p",
        { class: "cc-counts" },
        field("listed", changes.length),
        " listed of ",
        field("distinct_matched", entry.distinct_matched),
        ` distinct ${unit(entry.distinct_matched, "change", "changes")} that share at least two words with this claim or the search queries the run wrote for it, among `,
        field("considered", entry.considered),
        ` changed ${unit(entry.considered, "paragraph", "paragraphs")}.`,
      ),
      h("p", { class: "cc-why", text: `${CC_EARLIER} ${CC_WHY}` }),
      h("ol", { class: "chg-paras cc-list" }, changes.map(changeEntry)),
    ),
  );
}

/** One listed change: its mark, form and Item (and the other Items it repeats under), the shared words, the text and links. */
function changeEntry(change) {
  const kind = Object.hasOwn(CHANGE_MARK, change?.kind) ? change.kind : "";
  const also = list(change?.also_under).map(String);
  const terms = list(change?.matched_terms).map(String);
  const head = h(
    "div",
    { class: "cc-head" },
    h(
      "p",
      { class: "cc-where" },
      kind ? changeMark(kind) : h("span", { class: "muted", text: "Kind not recorded" }),
      " ",
      h("span", { class: "cc-form", text: str(change?.form) || "form not recorded" }),
      " · ",
      h("span", { class: "cc-item", text: str(change?.item) || "Item not recorded" }),
      also.length ? h("span", { class: "cc-also", "data-also-under": also.join("\n") }, ` · also under ${also.join("; ")}`) : "",
    ),
    h(
      "p",
      { class: "cc-terms" },
      h("span", { class: "label", text: "Shared words, as the matcher stems them: " }),
      terms.flatMap((term, position) => [position ? ", " : "", h("span", { class: "cc-term", text: term })]),
    ),
  );
  let entry;
  if ((kind === "added" || kind === "removed") && change.paragraph) entry = paragraphEntry(change.paragraph, kind === "added" ? "later" : "earlier", head);
  else if ((kind === "reworded" || kind === "numbers_only") && change.pair) entry = pairEntry(change.pair, kind === "reworded", head);
  else entry = h("li", null, head, h("p", { class: "muted", text: "The changed text is missing from the record." }));
  entry.classList.add("cc-entry");
  entry.dataset.changeKind = kind || "unknown";
  return entry;
}

/** One finding: stance, statement, the engine's reason, its checks, cited figures and quotes. */
function renderFinding(finding, ctx, withheld = false) {
  const stance = token(finding.stance, STANCE_MARK);
  const model = modelAssessed(ctx.claims.get(finding.claim_id));
  const badge = meaningRead(finding) ? MODEL_BADGE_READ : MODEL_BADGE;
  // The finding in the main column; its quotes in the margin beside it (inline on a narrow note).
  const main = h("div", { class: "finding-main" });
  const margin = h("div", { class: "finding-margin" });
  const article = h("article", { class: `finding s-${stance}${withheld ? " is-withheld" : ""}`, "data-finding-id": finding.id }, main, margin);
  main.append(
    h(
      "header",
      { class: "finding-head" },
      stancePill(finding.stance),
      !withheld && finding.verified !== false && list(finding.evidence_ids).length === 0 && list(finding.metric_ids).length > 0
        ? h("span", { class: "figures-only-tag", "data-figures-only": "" }, "rests on reported figures only: no excerpt")
        : "",
      writtenField("div", `finding:${finding.id}:statement`, model, h("h4", { class: "finding-statement", text: finding.statement }), badge),
    ),
    h(
      "p",
      { class: "finding-meta" },
      h("span", { class: "muted", text: `${finding.id} · ` }),
      h("span", { title: "The engine's own qualitative estimate, not a measured probability", text: `Engine's confidence: ${finding.confidence}` }),
      ` · ${plural(finding.filings_cited, "filing", "filings")} cited`,
    ),
  );
  const counted = countedAsLine(finding);
  if (counted) main.append(counted);
  for (const mark of list(finding.predated_by)) main.append(predatedLine(mark));
  if (withheld) {
    // A finding the second model rejected keeps that model's own words, tagged for the browser test.
    const reason = str(finding.withheld_reason) || "no quote was found in the filing text.";
    const byMeaning = str(finding.checks?.support) === "failed";
    main.append(limitLine("p", h("strong", { text: "Withheld: " }), byMeaning ? h("span", { "data-withheld-reason": "", text: reason }) : reason));
  }
  if (finding.rationale) {
    main.append(writtenField("p", `finding:${finding.id}:reason`, model, [h("span", { class: "label", text: "Engine's reason: " }), finding.rationale], badge));
  }
  const checks = renderChecks(finding.checks);
  if (checks) main.append(checks);
  const cited = renderCitedFigures(finding.metric_ids, ctx.metrics);
  if (cited) main.append(cited);
  for (const evidenceId of list(finding.evidence_ids)) {
    const item = ctx.evidence.get(evidenceId);
    if (!item) {
      margin.append(h("p", { class: "muted", text: `Excerpt ${evidenceId} is listed but missing from the record.` }));
      continue;
    }
    margin.append(renderEvidence(item, ctx.sources.get(item.source_id)));
  }
  if (!withheld && finding.verified !== false) {
    main.append(h("div", { class: "review-slot", "data-review-finding": finding.id, hidden: true }));
  }
  return article;
}

/** "Predates the 8-K of 12 Nov 2026, Item 5.02", the record's words, linking to that 8-K above. */
function predatedLine(mark) {
  const target = eventAnchor(str(mark.event_id));
  const label = str(mark.label) || "Predates a later 8-K";
  return limitLine(
    "p",
    h("span", { class: "predated", "data-predated-by": str(mark.event_id) }, target ? h("a", { href: `#${target}`, onclick: jumpTo(target), text: label }) : label),
  );
}

/**
 * When the verdict rule counted a finding as another stance than the engine's (`counted_as`,
 * set by the backend), that stance's mark and the record's reason. Nothing for a finding
 * counted as its own stance, a withheld one, or a record from before `counted_as` was kept.
 */
function countedAsLine(finding) {
  const counted = str(finding.counted_as);
  if (!counted || counted === str(finding.stance)) return null;
  return h(
    "p",
    { class: "counted-as", "data-counted-as": counted },
    h("span", { class: "label", text: "Counted toward the verdict as: " }),
    stancePill(counted),
    str(finding.count_note) ? h("span", { class: "count-note", "data-count-note": "", text: finding.count_note }) : "",
  );
}

/** The checks a finding went through, as the record states them. A check that did not run says so. */
function renderChecks(checks) {
  if (!checks || typeof checks !== "object") return null;
  const items = [];
  const quotes = str(checks.quotes);
  if (quotes === "passed") items.push(h("li", { text: "Quote: found in the filing" }));
  else if (quotes === "none") items.push(h("li", { text: "No quote cited" }));
  else if (quotes === "failed") items.push(limitLine("li", "Quote: not found in the filing"));
  else if (quotes) items.push(h("li", { text: `Quote check: ${quotes}` }));

  const numbers = str(checks.numbers);
  const detail = list(checks.numbers_detail);
  let numbersItem = null;
  if (numbers === "passed") numbersItem = h("li", { text: "Numbers: all matched" });
  else if (numbers === "none") numbersItem = h("li", { text: "No number to check" });
  else if (numbers === "failed") numbersItem = limitLine("li", "A number did not match");
  else if (numbers) numbersItem = h("li", { text: `Number check: ${numbers}` });
  if (numbersItem && detail.length) {
    numbersItem.append(
      h("details", { class: "check-detail" }, h("summary", { text: "Number check details" }), h("ul", null, detail.map((line) => h("li", { text: String(line) })))),
    );
  }
  if (numbersItem) items.push(numbersItem);

  // The period check, as the record states it. It reports and withholds nothing, so a year it
  // could not place is a caution under the checks, never a failed check. A record without the
  // field (older than the check) says nothing about it.
  // Listed after the meaning check, so that a caution on its own line ends the list.
  let periodItem = null;
  const periods = str(checks.periods);
  const periodLines = list(checks.periods_detail).map(String);
  const periodDetail = periodLines.length
    ? h("details", { class: "check-detail" }, h("summary", { text: "Period check details" }), h("ul", { "data-periods-detail": "" }, periodLines.map((line) => h("li", { text: line }))))
    : "";
  if (periods === "passed") {
    periodItem = h("li", { "data-periods": periods }, "Years named: all in its evidence", periodDetail);
  } else if (periods === "none") {
    periodItem = h("li", { "data-periods": periods, text: "No year checked" });
  } else if (periods === "unverified") {
    const unplaced = list(checks.periods_unverified);
    periodItem = h(
      "li",
      { class: "period-caution", "data-periods": periods },
      h("span", { class: "mark-limit" }, limitGlyph(), " ", h("span", { class: "period-caution-title", text: "Period not found in its evidence:" })),
      h(
        "ul",
        { class: "period-unplaced" },
        unplaced.map((entry) => h("li", { "data-period-mention": str(entry?.mention), "data-comparative": entry?.comparative === true ? "true" : "false", text: str(entry?.detail) || str(entry?.mention) })),
      ),
      periodDetail,
    );
  } else if (periods) {
    periodItem = h("li", { "data-periods": periods, text: `Period check: ${periods}` });
  }

  // The meaning check, as the record states it. A record from before the check reads as not checked.
  const support = str(checks.support) || "unchecked";
  const reason = str(checks.support_detail);
  let supportItem;
  if (support === "passed" || support === "partly") {
    supportItem = h("li", { "data-support": support }, meaningMark(support));
    if (support === "passed" && reason) {
      supportItem.append(h("details", { class: "check-detail" }, h("summary", { text: "Its reason" }), checkerReason(reason, "data-support-detail")));
    }
  } else if (support === "failed") {
    supportItem = limitLine("li", h("span", { class: "meaning-words", text: MEANING_WORDS.failed }));
    supportItem.dataset.support = support;
  } else if (support === "unchecked") {
    supportItem = h("li", { "data-support": support }, h("span", { class: "meaning-words", text: MEANING_WORDS.unchecked }));
  } else {
    supportItem = h("li", { "data-support": support, text: `Meaning check: ${support}` });
  }
  items.push(supportItem);
  if (periodItem) items.push(periodItem);

  // Agreeing only in part is a result the reader must weigh, so its reason is shown in the open.
  const partly = support === "partly" ? checkerReason(reason || "no reason was recorded.", "data-support-detail") : "";
  return h("div", { class: "checks" }, h("span", { class: "label", text: "Checks: " }), h("ul", { class: "check-list" }, items), partly);
}

/** The reported figures a finding cites, resolved against `run.metrics`. */
/** Open a figure's row in the panel and bring it into view, without touching the URL's hash (it holds the run). */
function openFigure(metricId) {
  return (event) => {
    event.preventDefault();
    const row = document.getElementById(figureDomId(metricId));
    if (!row) return;
    row.open = true;
    row.scrollIntoView({ block: "center", behavior: "smooth" });
    row.querySelector("summary")?.focus({ preventScroll: true });
  };
}

function renderCitedFigures(ids, metrics) {
  const cited = list(ids);
  if (cited.length === 0) return null;
  return h(
    "div",
    { class: "cited" },
    h("span", { class: "label", text: "Reported figures cited: " }),
    h(
      "ul",
      { class: "cited-list" },
      cited.map((id) => {
        const metric = metrics.get(id);
        if (!metric) return h("li", { class: "muted", text: `Figure ${id} is listed but missing from the record.` });
        const row = document.getElementById(figureDomId(id));
        return h(
          "li",
          { "data-cited-metric": id },
          `${metric.label} · ${metric.period_label} · `,
          h("span", { class: "fig-value", text: metric.display }),
          row ? [" · ", h("a", { class: "fig-open", href: `#${encodeURIComponent(figureDomId(id))}`, "data-opens-figure": id, onclick: openFigure(id), text: "open it in the figures panel" })] : "",
        );
      }),
    ),
  );
}

/** The verified excerpt in its surrounding text, where it sits, and the filing it came from. */
function renderEvidence(item, source) {
  const quote = h(
    "blockquote",
    { class: "excerpt" },
    item.context_before ? h("span", { class: "context" }, "…", item.context_before) : "",
    h("mark", { text: item.excerpt }),
    item.context_after ? h("span", { class: "context" }, item.context_after, "…") : "",
  );
  const caption = h(
    "figcaption",
    { class: "evidence-caption" },
    h("span", { class: "locator", title: ITEM_GLOSS }, h("span", { class: "label", text: "Located under: " }), item.locator || "location not recorded"),
    h("span", { class: "source-line" }, sourceLine(source, item.source_id)),
    externalLink(item.link || source?.url, evidenceLinkWords(item, source)),
  );
  return h("figure", { class: "evidence", "data-evidence-id": item.id },h("span", { class: "evidence-id", text: `${item.id} · quote found word for word, highlighted` }), quote, caption);
}

/** The words on an evidence link: what the record's `link_kind` says the link opens. */
function evidenceLinkWords(item, source) {
  const page = source?.kind === "public_html";
  const words = Object.hasOwn(LINK_WORDS, str(item.link_kind)) ? LINK_WORDS[item.link_kind] : null;
  if (!words) return page ? "Open the page" : "Open in filing";
  return words[page ? 1 : 0];
}

function sourceLine(source, sourceId) {
  if (!source) return `${sourceId} (not in the source list)`;
  if (source.kind === "public_html") {
    return [`${source.id} · Web page: ${source.title || source.url}`, source.published_date ? ` · published ${source.published_date}` : ""];
  }
  const gloss = formGloss(source.form);
  return [
    `${source.id} · `,
    h("abbr", { title: source.accession ? `${ACCESSION_GLOSS}: ${source.accession}` : null, text: source.form ?? "Filing" }),
    gloss ? ` (${gloss})` : "",
    source.period_end ? ` · period ended ${source.period_end}` : "",
    source.published_date ? ` · filed ${source.published_date}` : "",
  ];
}

/**
 * Withheld findings. Those the second model rejected (`checks.support` "failed") get
 * their own group; with none of them, the list is drawn as it was before the check.
 */
function renderWithheld(run, ctx) {
  const withheld = list(run.unsupported_findings);
  els.withheldSection.hidden = withheld.length === 0;
  const item = (finding) => {
    const claim = ctx.claims.get(finding.claim_id);
    return h(
      "li",
      { class: "withheld-item" },
      h("p", { class: "withheld-for muted", text: `Proposed for ${finding.claim_id}${claim ? `: ${claim.text}` : ""}` }),
      renderFinding(finding, ctx, true),
    );
  };
  const byMeaning = withheld.filter((finding) => str(finding.checks?.support) === "failed");
  const byChecks = withheld.filter((finding) => str(finding.checks?.support) !== "failed");
  // Collapsed behind one line: the record's count, then the kinds of reason present.
  const c = run.coverage ?? {};
  const kinds = [];
  if (byMeaning.length) kinds.push(Number.isFinite(c.findings_failed_meaning) ? [cov(c, "findings_failed_meaning"), " by the meaning check"] : "by the meaning check");
  if (byChecks.length) kinds.push(byMeaning.length ? "the others for a quote or a number" : "for a quote or a number");
  const fold = (...content) =>
    h(
      "details",
      { class: "withheld-fold" },
      h(
        "summary",
        null,
        Number.isFinite(c.findings_withheld) ? [cov(c, "findings_withheld"), ` ${unit(c.findings_withheld, "finding", "findings")} withheld: `] : "Findings withheld: ",
        ...kinds.flatMap((kind, i) => (i ? ["; ", kind] : [kind])),
        h("span", { class: "fold-hint", text: ". None counts toward a verdict." }),
      ),
      h("p", { class: "hint", text: "The engine proposed these findings, but each failed a check. They count toward no verdict." }),
      ...content,
    );
  if (byMeaning.length === 0) {
    els.withheld.replaceChildren(fold(h("ul", { class: "withheld-list" }, byChecks.map(item))));
    return;
  }
  const group = (key, title, hint, findings) =>
    h(
      "div",
      { class: "withheld-group", "data-withheld-group": key },
      h("h4", { class: "withheld-subtitle", text: title }),
      h("p", { class: "hint", text: hint }),
      h("ul", { class: "withheld-list" }, findings.map(item)),
    );
  els.withheld.replaceChildren(fold(
    byChecks.length ? group("checks", "Withheld for a quote or a number", "A quote was not found in the filing, a number did not match, or nothing could be checked.", byChecks) : "",
    group("meaning", "Withheld by the meaning check", "A second model read the quoted evidence and judged that it does not support the statement. That too is a model's reading: read the quote before you dismiss the finding.", byMeaning),
  ));
}

function renderBriefLists(run) {
  const brief = run.brief;
  els.unknownsSection.hidden = !brief;
  els.nextSection.hidden = !brief;
  if (!brief) return;
  fillList(els.unknowns, brief.unknowns, "None recorded.");
  fillList(els.nextSteps, brief.next_steps, "None recorded.");
}

/** The first three errors in full; every error inside a closed disclosure. */
function renderErrors(run, finished) {
  const errors = list(run.errors);
  fillList(els.errors, errors.slice(0, 3), finished ? "None recorded." : "None so far.", true);
  els.errorsMore.replaceChildren();
  if (errors.length > 3) {
    const all = h("ul", { class: "mark-list" });
    fillList(all, errors, "", true);
    els.errorsMore.append(h("details", { id: "errors-all", class: "errors-all" }, h("summary", { text: `All ${errors.length} errors` }), all));
  }
}

function renderSources(run) {
  const sources = list(run.sources);
  els.sourcesBody.replaceChildren();
  if (sources.length === 0) {
    els.sourcesBody.append(h("tr", null, h("td", { colspan: "9", class: "muted", text: run.status === "running" ? "Sources appear as they are retrieved." : "No source was recorded." })));
    return;
  }
  for (const source of sources) {
    const filing = source.kind === "sec_filing";
    const gloss = formGloss(source.form);
    let formCell;
    if (filing) {
      formCell = h("td", null, h("abbr", { title: source.accession ? `${ACCESSION_GLOSS}: ${source.accession}` : null, text: source.form ?? "Filing" }), gloss ? h("span", { class: "gloss", text: ` ${gloss}` }) : "");
    } else if (source.kind === "sec_xbrl") {
      formCell = h("td", null, "XBRL data", h("span", { class: "gloss", text: " reported figures" }));
    } else {
      formCell = h("td", null, "Web page", h("span", { class: "gloss", text: ` ${source.title || ""}` }));
    }
    const read = source.extraction_status === "extracted";
    const statusCell = read
      ? h("td", { class: "ok-read", text: "Read" })
      : h("td", { class: "not-read" }, limitGlyph(), " Not read", source.error ? `: ${source.error}` : "");
    els.sourcesBody.append(
      h(
        "tr",
        null,
        h("th", { scope: "row", text: source.id }),
        formCell,
        h("td", { text: source.period_end ?? "—" }),
        h("td", { text: source.published_date ? `${source.published_date}${filing ? "" : " (published)"}` : "—" }),
        h("td", { text: utc(source.retrieved_at) }),
        h("td", { class: "num", text: read && filing ? num(source.sections ?? 0) : "—" }),
        h("td", { class: "num", text: read ? num(source.characters ?? 0) : "—" }),
        statusCell,
        h("td", null, externalLink(source.url, "Open")),
      ),
    );
  }
}

// ---------------------------------------------------------------- reported figures

// ---------------------------------------------------------------- 8-Ks since the annual report

const EVENT_ID = /^[A-Za-z0-9-]{1,80}$/;

/** The element id of an 8-K in the panel; "" for an id from the record that could not be one. */
function eventAnchor(eventId) {
  return EVENT_ID.test(eventId) ? `event-${eventId}` : "";
}

/**
 * The 8-Ks the record lists after the annual report the run read, newest first, as the record
 * orders and words them: each with its date, form, link, kind and what became of it, then each
 * item with its SEC title, its category and, for an 8-K read, its opening sentences and the
 * roles a 5.02 names. Nothing for a run recorded before version 12.
 */
function renderEvents(run) {
  const asOf = run.as_of;
  els.eventsSection.hidden = !asOf;
  if (!asOf) {
    els.events.replaceChildren();
    return;
  }
  const words = state.meta?.events ?? {};
  els.eventsTitle.textContent = str(words.heading) || "Since the annual report";
  const parts = [];
  if (str(words.note)) parts.push(h("p", { class: "hint", text: words.note }));
  const counts = str(asOf.counts?.line);
  if (counts) {
    parts.push(
      str(asOf.index_error)
        ? limitLine("p", h("span", { class: "event-counts", "data-event-counts": "", text: counts }))
        : h("p", { class: "event-counts", "data-event-counts": "", text: counts }),
    );
  }
  const events = list(run.timeline);
  if (events.length) parts.push(h("ol", { class: "events" }, ...events.map((event) => renderEvent(event, words))));
  els.events.replaceChildren(...parts);
}

function renderEvent(event, words) {
  const substantive = event.substantive === true;
  const kind = substantive ? "substantive" : "routine";
  const kindLabel = str(words.kind_labels?.[kind]) || kind;
  const status = str(event.status);
  const statusLabel = str(words.status_labels?.[status]) || status;
  const anchor = eventAnchor(str(event.id));
  const head = h(
    "p",
    { class: "event-head" },
    h("strong", { class: "event-date", text: str(event.filed_label) || str(event.filed_date) }),
    h(
      "span",
      { class: "event-headline" },
      externalLink(event.url, `${str(event.form)} ${str(event.accession)}`),
      " · ",
      h("span", { class: `event-kind is-${kind}`, "data-event-kind": kind, text: kindLabel }),
      " · ",
      h("span", { class: "event-status", "data-event-status": status, text: statusLabel }),
    ),
  );
  const entry = h("li", { class: `event ev-${kind}`, id: anchor || null, tabindex: anchor ? "-1" : null, "data-event-id": str(event.id) }, head);
  if (str(event.reason)) entry.append(limitLine("p", h("span", { "data-event-reason": "", text: event.reason })));
  const items = h("ul", { class: "event-items" });
  for (const item of list(event.items)) {
    const number = str(item.number);
    const category = str(item.category);
    const row = h(
      "li",
      { class: "event-item", "data-item": number },
      h("span", { class: "event-item-title", text: `Item ${number}. ${str(item.title)}` }),
      " ",
      h("span", { class: "event-category", "data-category": category, text: str(words.category_labels?.[category]) || category }),
    );
    const roles = list(item.roles);
    if (roles.length) {
      row.append(h("p", { class: "event-roles", "data-event-roles": "" }, ruleMark("Found by a fixed rule"), " ", h("span", { class: "label", text: "Roles named: " }), roles.join(", ")));
    }
    const opening = list(item.opening);
    if (opening.length) {
      row.append(h("blockquote", { class: "event-opening", "data-event-opening": number }, ...opening.map((sentence) => h("p", { text: sentence }))));
      row.append(h("p", { class: "event-link" }, externalLink(event.url, `Read Item ${number} in the ${str(event.form)}`)));
    }
    items.append(row);
  }
  entry.append(items);
  return entry;
}

// ---------------------------------------------------------------- the tape

/** The figures on the tape, in order: the run's own metrics of these keys, never computed here. */
const TAPE_KEYS = ["revenue", "revenue_yoy", "gross_margin", "operating_margin", "fcf_margin", "eps_diluted"];

/**
 * The tape: the newest period's key figures in one dense row under the company's name. Each
 * cell is a metric the record sends (its label, display string and period label) with the
 * sparkline of its series; the quarter's metric when the record has one, else the year's.
 * Selecting a cell opens that figure, with its arithmetic, among the reported figures.
 */
function renderTape(run) {
  if (!els.tape) return;
  const metrics = list(run.metrics);
  const series = list(run.series);
  const pick = (key) => metrics.find((m) => m.key === key && m.period === "quarter") ?? metrics.find((m) => m.key === key && m.period === "annual");
  const chosen = TAPE_KEYS.map(pick).filter(Boolean);
  els.tapeSection.hidden = chosen.length === 0;
  if (chosen.length === 0) {
    els.tape.replaceChildren();
    return;
  }
  const period = str(chosen[0].period_label);
  const cells = chosen.map((metric) =>
    h(
      "a",
      { class: "tape-cell", href: `#figures-section`, "data-tape-metric": metric.id, onclick: openFigure(metric.id) },
      h("span", { class: "tape-label", text: metric.label }),
      h("span", { class: `tape-value ${valueClass(metric)} dec` }, ...decimalParts(metric.display)),
      sparkline(metric, series),
      str(metric.period_label) !== period ? h("span", { class: "tape-period", text: metric.period_label }) : "",
    ),
  );
  els.tape.replaceChildren(h("p", { class: "tape-head" }, h("span", { class: "tape-code", "aria-hidden": "true", text: "FIG" }), period), h("div", { class: "tape-row" }, cells));
}

/** Open one figure among the reported figures and bring it into view. */
function openFigure(metricId) {
  return (event) => {
    const row = document.querySelector(`#figures details.fig-row[data-metric-id="${CSS.escape(metricId)}"]`);
    if (!row) return;
    event.preventDefault();
    row.open = true;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    row.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    row.querySelector("summary")?.focus({ preventScroll: true });
  };
}

// ---------------------------------------------------------------- the time line

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY_MS = 86400000;

/** A record date ("YYYY-MM-DD", or an ISO timestamp) as milliseconds at UTC midnight; NaN when it is not one. */
function dayOf(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(str(value));
  return match ? Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : Number.NaN;
}

/** "2026-11-12" as "12 Nov 2026", the way the record's own labels write a date. Presentation only. */
function dateLabel(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(str(value));
  if (!match) return str(value) || "date not recorded";
  return `${Number(match[3])} ${MONTHS[Number(match[2]) - 1]} ${match[1]}`;
}

/**
 * What the time line draws, read from the run: the annual and quarterly reports it read, the
 * 8-Ks its record lists, which of those its quotes come from, the run's own date and the
 * newest filing read. Selection and lookup only.
 */
function timelineData(run) {
  const sources = list(run.sources).filter((x) => x.kind === "sec_filing" && Number.isFinite(dayOf(x.published_date)));
  const quotedSources = new Set(list(run.evidence).map((e) => e.source_id));
  const quotedAccessions = new Set(sources.filter((x) => quotedSources.has(x.id)).map((x) => str(x.accession)));
  const periodic = sources
    .filter((x) => !str(x.form).toUpperCase().startsWith("8-K"))
    .map((x) => ({ source: x, day: dayOf(x.published_date), quoted: quotedSources.has(x.id) }));
  const events = list(run.timeline)
    .filter((e) => Number.isFinite(dayOf(e.filed_date)))
    .map((e) => ({ event: e, day: dayOf(e.filed_date), quoted: quotedAccessions.has(str(e.accession)) }));
  const runDay = dayOf(run.started_at);
  const newest = dayOf(run.as_of?.newest_filed);
  return { periodic, events, runDay, newest };
}

/** The categories of an 8-K's items that the record's wording calls substantive, as labels. */
function eventCategories(event) {
  const words = state.meta?.events ?? {};
  const substantive = new Set(list(words.substantive));
  const seen = [];
  for (const item of list(event.items)) {
    const category = str(item.category);
    if (event.substantive === true && substantive.size && !substantive.has(category)) continue;
    const label = str(words.category_labels?.[category]) || category;
    if (label && !seen.includes(label)) seen.push(label);
  }
  return seen;
}

/** Show the time line for a run whose record has dated filings; hide it otherwise. */
function renderTimeline(run) {
  if (!els.timeline) return;
  const data = timelineData(run);
  const show = Number.isFinite(data.runDay) && (data.periodic.length > 0 || data.events.length > 0);
  els.timelineSection.hidden = !show;
  state.timelineRun = show ? run : null;
  if (!show) {
    els.timeline.replaceChildren();
    return;
  }
  drawTimeline(els.timeline, run);
}

/**
 * One horizontal date axis in SVG, drawn at the container's own width so its text keeps its
 * size: reports above the axis, 8-Ks below, the run as a rule, the time between the newest
 * filing read and the run hatched. Each mark is a link to its filing with a tooltip on hover
 * or focus.
 */
function drawTimeline(container, run) {
  const data = timelineData(run);
  const width = Math.max(Math.round(container.clientWidth || 880), 300);
  const narrow = width < 560;
  // Without 8-Ks the space below the axis holds only the gap's label and the months.
  const H = data.events.length ? (narrow ? 186 : 196) : Number.isFinite(data.newest) ? 176 : 132;
  const axisY = 84;
  const left = 10;
  const right = 14;
  const days = [...data.periodic.map((x) => x.day), ...data.events.map((x) => x.day), data.runDay];
  if (Number.isFinite(data.newest)) days.push(data.newest);
  let lo = Math.min(...days);
  let hi = Math.max(...days);
  const span = Math.max(hi - lo, 30 * DAY_MS);
  lo -= span * 0.03;
  hi += span * 0.04;
  const xAt = (day) => left + ((day - lo) / (hi - lo)) * (width - left - right);

  const svg = s(
    "svg",
    { viewBox: `0 0 ${width} ${H}`, width, height: H, role: "group", "aria-labelledby": "timeline-title", "data-timeline": "" },
    s("defs", null, s("pattern", { id: "tl-hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, s("line", { x1: 0, y1: 0, x2: 0, y2: 6, class: "tl-hatch-line" }))),
  );

  // The time between the newest filing read and the run: what the record cannot know.
  if (Number.isFinite(data.newest) && data.runDay > data.newest) {
    const x0 = xAt(data.newest);
    const x1 = xAt(data.runDay);
    const daysWord = Number.isFinite(run.as_of?.days_since_newest) ? plural(run.as_of.days_since_newest, "day", "days") : "";
    svg.append(
      s(
        "g",
        { "data-tl": "gap" },
        s("title", { text: `Between the newest filing read (${dateLabel(run.as_of.newest_filed)}) and this run${daysWord ? `: ${daysWord}` : ""}. Nothing filed in this time is in the record.` }),
        s("rect", { x: x0, y: 18, width: Math.max(x1 - x0, 2), height: axisY + 26 - 18, class: "tl-gap" }),
      ),
    );
    if (daysWord) {
      // Under the 8-K labels, ending at the run's line: how long the record cannot see.
      const text = `${daysWord} between the newest filing read and the run`;
      svg.append(s("text", { x: x1, y: axisY + 72, class: "tl-gap-label", "text-anchor": "end", text }));
    }
  }

  // Month ticks along the axis, a year label on each January and on the first tick.
  const first = new Date(lo);
  let tick = Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 1);
  let firstTick = true;
  const ticks = s("g", { class: "tl-ticks", "aria-hidden": "true" });
  let lastLabel = -Infinity;
  while (tick <= hi) {
    const d = new Date(tick);
    const x = xAt(tick);
    ticks.append(s("line", { x1: x, x2: x, y1: axisY, y2: axisY + 5, class: "tl-tick" }));
    const month = d.getUTCMonth();
    if (x - lastLabel > (narrow ? 34 : 30)) {
      const yearLabel = month === 0 || firstTick;
      ticks.append(s("text", { x: x + 2, y: H - 6, class: yearLabel ? "tl-year" : "tl-tick-label", text: yearLabel ? `${MONTHS[month]} ${d.getUTCFullYear()}` : MONTHS[month] }));
      lastLabel = x + (yearLabel ? 30 : 0);
      firstTick = false;
    }
    tick = Date.UTC(d.getUTCFullYear(), month + 1, 1);
  }
  svg.append(ticks, s("line", { x1: left - 6, x2: width - 4, y1: axisY, y2: axisY, class: "tl-axis" }));

  // The annual and quarterly reports: bars above the axis, a dot on top when quoted.
  let lastFormX = -Infinity;
  let formRow = 0;
  for (const item of data.periodic.sort((a, b) => a.day - b.day)) {
    const x = xAt(item.day);
    const source = item.source;
    const annual = str(source.form).toUpperCase().startsWith("10-K");
    formRow = x - lastFormX < 46 ? 1 - formRow : 0;
    lastFormX = x;
    const tip = [
      `${str(source.form)} · filed ${dateLabel(source.published_date)}`,
      source.period_end ? `For the period ended ${dateLabel(source.period_end)}` : "",
      item.quoted ? "Quoted in this run's findings" : "Read by this run; not quoted in a verified finding",
    ];
    const shape = [
      s("rect", { x: x - 7, y: 22, width: 14, height: axisY - 22, class: "tl-hit" }),
      s("rect", { x: x - 1.5, y: 40, width: 3, height: axisY - 40, class: `tl-filing ${annual ? "is-annual" : "is-quarterly"}` }),
      item.quoted ? s("circle", { cx: x, cy: 40, r: 4.5, class: "tl-quoted-dot" }) : "",
      s("text", { x, y: 33 - formRow * 12, "text-anchor": "middle", class: "tl-label is-form", text: str(source.form) }),
    ];
    svg.append(timelineMark("filing", { "data-source-id": source.id, "data-quoted": item.quoted ? "true" : "false" }, source.url, tip, shape, container));
  }

  // The 8-Ks: below the axis; substantive ones a filled diamond with their category, routine ones a small circle.
  const labelRows = [-Infinity, -Infinity];
  for (const item of data.events.sort((a, b) => a.day - b.day)) {
    const event = item.event;
    const x = xAt(item.day);
    const y = axisY + 18;
    const substantive = event.substantive === true;
    const categories = eventCategories(event);
    const words = state.meta?.events ?? {};
    const kind = substantive ? "substantive" : "routine";
    const tip = [
      `${str(event.form)} · filed ${str(event.filed_label) || dateLabel(event.filed_date)} · ${str(words.kind_labels?.[kind]) || kind}`,
      list(event.items).map((it) => `Item ${str(it.number)}${str(it.title) ? ` ${str(it.title)}` : ""}`).join("; "),
      str(words.status_labels?.[str(event.status)]) || str(event.status),
      item.quoted ? "Quoted in this run's findings" : "",
    ];
    const shape = [
      s("rect", { x: x - 8, y: axisY + 4, width: 16, height: 28, class: "tl-hit" }),
      substantive
        ? s("path", { d: `M ${x} ${y - 7} L ${x + 6} ${y} L ${x} ${y + 7} L ${x - 6} ${y} Z`, class: "tl-8k is-substantive" })
        : s("circle", { cx: x, cy: y, r: 3.6, class: "tl-8k is-routine" }),
      item.quoted ? s("circle", { cx: x, cy: axisY + 6, r: 3, class: "tl-quoted-dot" }) : "",
    ];
    if (substantive && categories.length && !narrow) {
      const row = x - labelRows[0] > 96 ? 0 : x - labelRows[1] > 96 ? 1 : 0;
      labelRows[row] = x;
      const labelX = Math.min(Math.max(x, left + 40), width - 50);
      shape.push(s("text", { x: labelX, y: axisY + 42 + row * 13, "text-anchor": "middle", class: "tl-label is-cat", text: categories.join(", ") }));
    }
    svg.append(timelineMark("8k", { "data-event-id": str(event.id), "data-kind": kind, "data-quoted": item.quoted ? "true" : "false" }, event.url, tip, shape, container));
  }

  // The run itself.
  const rx = xAt(data.runDay);
  const runEnd = rx > width - 110;
  svg.append(
    s(
      "g",
      { "data-tl": "run", class: "tl-run-mark" },
      s("title", { text: `This run, started ${utc(run.started_at)}` }),
      s("line", { x1: rx, x2: rx, y1: 12, y2: axisY + 30, class: "tl-run" }),
      s("path", { d: `M ${rx - 4} 12 L ${rx + 4} 12 L ${rx} 18 Z`, class: "tl-run-head" }),
      s("text", { x: runEnd ? rx - 7 : rx + 7, y: 16, "text-anchor": runEnd ? "end" : "start", class: "tl-label is-run", text: `Run ${dateLabel(run.started_at)}` }),
    ),
  );

  const tipBox = h("div", { class: "tl-tip", role: "tooltip", id: "tl-tip", hidden: true });
  container.replaceChildren(svg, tipBox);
  container.dataset.width = String(width);
}

/** One mark of the time line: a link to its filing (or a focusable group without one), its title and tooltip. */
function timelineMark(kind, attrs, url, tipLines, shape, container) {
  const lines = tipLines.filter(Boolean);
  const href = safeUrl(url);
  const props = { class: "tl-mark", "data-tl": kind, ...attrs, "aria-label": `${lines.join(". ")}.${href ? " Opens the filing in a new tab." : ""}`, "aria-describedby": "tl-tip" };
  const node = href ? s("a", { ...props, href, target: "_blank", rel: "noopener noreferrer" }) : s("g", { ...props, tabindex: 0 });
  node.append(s("title", { text: lines.join("\n") }), ...shape.filter(Boolean));
  const show = () => {
    const tip = container.querySelector(".tl-tip");
    if (!tip) return;
    tip.replaceChildren(
      h("p", { class: "tl-tip-head", text: lines[0] ?? "" }),
      ...lines.slice(1).map((line) => h("p", { class: "tl-tip-items", text: line })),
      href ? h("p", { class: "tl-tip-open", text: "Select to open the filing ↗" }) : "",
    );
    tip.hidden = false;
    const box = node.getBoundingClientRect();
    const frame = container.getBoundingClientRect();
    const x = box.left + box.width / 2 - frame.left;
    tip.style.left = `${Math.max(0, Math.min(x - 120, frame.width - 260))}px`;
    tip.style.top = `${box.bottom - frame.top + 6}px`;
  };
  const hide = () => {
    const tip = container.querySelector(".tl-tip");
    if (tip) tip.hidden = true;
  };
  node.addEventListener("mouseenter", show);
  node.addEventListener("focus", show);
  node.addEventListener("mouseleave", hide);
  node.addEventListener("blur", hide);
  return node;
}

function renderRunFigures(run) {
  const metrics = list(run.metrics);
  const notes = list(run.metrics_notes);
  els.figuresSection.hidden = metrics.length === 0 && notes.length === 0;
  if (els.figuresSection.hidden) {
    els.figures.replaceChildren();
    return;
  }
  renderFigures(els.figures, { metrics, series: run.series, notes });
}

/** The latest period end of one kind; ISO dates compare as strings. Selection, not a result. */
function latestEnd(metrics, kind) {
  let latest = "";
  for (const metric of metrics) {
    if (metric.period === kind && str(metric.period_end) > latest) latest = metric.period_end;
  }
  return latest;
}

/** The newest quarter and newest fiscal year side by side, then notes and charts. */
function renderFigures(container, data) {
  const metrics = list(data.metrics);
  const notes = list(data.notes);
  const series = list(data.series);
  const row = (metric) => figureRow(metric, series);
  container.replaceChildren();
  if (str(state.meta?.figures_note)) container.append(h("p", { class: "hint", text: state.meta.figures_note }));
  if (metrics.length === 0) {
    container.append(h("p", { class: "muted", text: "The record holds no reported figures." }));
  } else {
    const columns = [
      ["quarter", "Newest quarter in the record"],
      ["annual", "Newest fiscal year in the record"],
    ];
    const grid = h("div", { class: "fig-grid" });
    const facts = metrics.filter((m) => !isTagged(m));
    for (const [kind, heading] of columns) {
      const end = latestEnd(facts, kind);
      if (!end) continue;
      const rows = facts.filter((m) => (m.period === kind || m.period === "instant") && m.period_end === end);
      const periodLabel = rows.find((m) => m.period === kind)?.period_label ?? end;
      grid.append(
        h(
          "section",
          { class: "fig-col", "aria-label": `${heading}: ${periodLabel}` },
          h("h4", { class: "fig-head" }, periodLabel, h("span", { class: "muted small", text: ` · ${heading.toLowerCase()}` })),
          h("ul", { class: "fig-list" }, rows.map(row)),
        ),
      );
    }
    container.append(grid, h("p", { class: "hint", text: "Open a figure to see its arithmetic and the reported values it used. The line beside each value is its series in the record, oldest to newest, with this period circled." }));
    const tagged = metrics.filter(isTagged);
    if (tagged.length) container.append(taggedGroup(tagged));
  }
  if (notes.length) {
    const notesList = h("ul", { class: "mark-list" });
    fillList(notesList, notes, "", true);
    container.append(h("div", { class: "fig-notes" }, h("p", { class: "label", text: "Notes on the figures" }), notesList));
  }
  const charts = renderCharts(list(data.series));
  if (charts) container.append(charts);
}

/** A figure read from a filing's own inline XBRL tags: the backend gives it an id starting "tagged:". */
function isTagged(metric) {
  return str(metric?.id).startsWith("tagged:");
}

/** The DOM id of a figure's row. Metric ids hold colons and "+": fine in an id, encoded in a link. */
function figureDomId(metricId) {
  return `fig-${metricId}`;
}

/** The tagged figures offered to the engine, in the record's order, after the company-facts figures. */
function taggedGroup(tagged) {
  return h(
    "section",
    { class: "fig-tagged", "aria-labelledby": "fig-tagged-title", "data-figure-group": "tagged" },
    h("h4", { class: "fig-head", id: "fig-tagged-title" }, "Figures tagged in the filings ", ruleMark()),
    h(
      "p",
      { class: "fig-tagged-source" },
      "Read from the filings' own inline XBRL tags, in the newest annual and the newest quarterly report the run read, and offered to the engine because the run asked for them.",
    ),
    h(
      "p",
      { class: "fig-tagged-caution", "data-tagged-caution": "" },
      "The row labels are made from tag names, not taken from the company's own tables, and no person has compared them with the printed tables.",
    ),
    h("ul", { class: "fig-list" }, tagged.map((metric) => figureRow(metric, []))),
  );
}

/**
 * A sparkline of the series the record sends for this figure's key and period: the values
 * placed in a small box, oldest to newest, the figure's own period circled. Drawing only; the
 * values and the period are the record's. Nothing when the record has no such series.
 */
function sparkline(metric, series) {
  const match = series.find((x) => x.key === metric.key && x.period === metric.period);
  const points = list(match?.points);
  const values = points.map((p) => p.value).filter((v) => Number.isFinite(v));
  if (values.length < 2) return h("span", { class: "spark-empty", "aria-hidden": "true" });
  const W = 88;
  const H = 20;
  const pad = 2.5;
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (!(hi > lo)) {
    hi += 1;
    lo -= 1;
  }
  const xAt = (i) => pad + (i * (W - 2 * pad)) / Math.max(points.length - 1, 1);
  const yAt = (v) => pad + ((hi - v) / (hi - lo)) * (H - 2 * pad);
  let path = "";
  let pen = false;
  points.forEach((point, i) => {
    if (!Number.isFinite(point.value)) {
      pen = false;
      return;
    }
    path += `${pen ? "L" : "M"}${xAt(i).toFixed(1)} ${yAt(point.value).toFixed(1)} `;
    pen = true;
  });
  const svg = s("svg", { class: "spark", viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true", focusable: "false", "data-spark": metric.key });
  if (lo < 0 && hi > 0) svg.append(s("line", { x1: 0, x2: W, y1: yAt(0), y2: yAt(0), class: "spark-zero" }));
  svg.append(s("path", { d: path.trim(), class: "spark-line" }));
  const here = points.findIndex((p) => p.period_end === metric.period_end);
  if (here >= 0 && Number.isFinite(points[here].value)) svg.append(s("circle", { cx: xAt(here), cy: yAt(points[here].value), r: 2.6, class: "spark-now" }));
  return svg;
}

/** The class of a value cell: missing, negative (by the sign of the record's value) or plain. */
/**
 * A display string split at its decimal point, so a column of values lines up on it. The
 * characters are the record's own, in order; nothing is rounded or reformatted.
 */
function decimalParts(display) {
  const text = str(display);
  const match = /^(.*?\d)(\.\d.*)$/.exec(text);
  if (!match) return [h("span", { class: "dec-int", text }), h("span", { class: "dec-frac" })];
  return [h("span", { class: "dec-int", text: match[1] }), h("span", { class: "dec-frac", text: match[2] })];
}

function valueClass(metric) {
  if (metric.value === null || metric.value === undefined) return "fig-value is-missing";
  return Number.isFinite(metric.value) && metric.value < 0 ? "fig-value is-neg" : "fig-value";
}

function figureRow(metric, series = []) {
  const body = h("div", { class: "fig-body" });
  body.append(
    h("p", null, h("span", { class: "label", text: "Formula: " }), str(metric.formula) ? h("code", { text: metric.formula }) : "none; the value was read directly from one reported fact."),
  );
  if (str(metric.note)) body.append(h("p", null, h("span", { class: "label", text: "Note: " }), metric.note));
  const inputs = list(metric.inputs);
  if (inputs.length) {
    body.append(
      h(
        "div",
        { class: "table-wrap", tabindex: "0", role: "region", "aria-label": `Reported values behind ${metric.label}` },
        h(
          "table",
          { class: "inputs" },
          h(
            "thead",
            null,
            h("tr", null, ["Concept", "Period", "Value as given", "Form", "Filed", "Accession", "Flags"].map((t) => h("th", { scope: "col", text: t }))),
          ),
          h("tbody", null, inputs.map(inputRow)),
        ),
      ),
    );
  } else {
    body.append(h("p", { class: "muted", text: "No reported value was used." }));
  }
  return h(
    "li",
    null,
    h(
      "details",
      { class: "fig-row", id: figureDomId(metric.id), "data-metric-id": metric.id },
      h(
        "summary",
        null,
        h("span", { class: "fig-label" }, metric.label, metric.period === "instant" ? h("span", { class: "muted small", text: ` · ${metric.period_label}` }) : ""),
        sparkline(metric, series),
        h("span", { class: `${valueClass(metric)} dec` }, ...decimalParts(metric.display)),
      ),
      body,
    ),
  );
}

function inputRow(ref) {
  const flags = [];
  if (ref.derived) flags.push("derived");
  if (ref.restated) flags.push("restated");
  const period = ref.start ? `${ref.start} to ${ref.end}` : `as of ${ref.end}`;
  const value = Number.isFinite(ref.value) ? `${ref.value.toLocaleString("en-US", { maximumFractionDigits: 20 })} ${str(ref.unit)}` : "—";
  return h(
    "tr",
    null,
    h("td", null, h("code", { text: ref.concept })),
    h("td", { text: period }),
    h("td", { class: "num", text: value }),
    h("td", { text: ref.form ?? "—" }),
    h("td", { text: ref.filed ?? "—" }),
    h("td", null, h("code", { text: ref.accession ?? "—" })),
    h("td", null, flags.length ? flags.join(", ") : "—", str(ref.note) ? h("span", { class: "muted", text: ` — ${ref.note}` }) : ""),
  );
}

// ---------------------------------------------------------------- charts

function findSeries(series, key) {
  return series.find((x) => x.key === key && x.period === "quarter") ?? series.find((x) => x.key === key && x.period === "annual") ?? null;
}

function renderCharts(series) {
  const blocks = [];
  for (const spec of CHARTS) {
    const chosen = spec.keys.map((key) => findSeries(series, key)).filter((x) => x && list(x.points).length);
    if (chosen.length === 0) continue;
    blocks.push(renderChart(spec, chosen));
  }
  if (blocks.length === 0) return null;
  return h("div", { class: "charts" }, h("p", { class: "label", text: "Over time" }), h("div", { class: "chart-grid" }, blocks));
}

const CH = { width: 520, height: 250, left: 14, right: 144, top: 30, bottom: 48 };

/** One chart as inline SVG, with its title, unit, period ends, and a table alternative. */
function renderChart(spec, seriesList) {
  const id = `chart-${++state.chartSeq}`;
  const periodWord = seriesList[0].period === "annual" ? "fiscal year" : "quarter";
  const title = `${spec.title}, by ${periodWord}`;
  const right = spec.kind === "bars" ? 14 : seriesList.length > 1 ? CH.right : 64;
  const plotW = CH.width - CH.left - right;
  const plotH = CH.height - CH.top - CH.bottom;
  const ends = seriesList[0].points.map((p) => p.period_end);
  const slot = plotW / Math.max(ends.length, 1);
  const xAt = (i) => CH.left + slot * (i + 0.5);

  const values = seriesList.flatMap((x) => x.points.map((p) => p.value)).filter((v) => Number.isFinite(v));
  let lo = values.length ? Math.min(...values) : 0;
  let hi = values.length ? Math.max(...values) : 1;
  if (spec.kind === "bars") {
    lo = Math.min(lo, 0);
    hi = Math.max(hi, 0);
  } else {
    const pad = (hi - lo || Math.abs(hi) || 1) * 0.12;
    lo -= pad;
    hi += pad;
  }
  if (!(hi > lo)) hi = lo + 1;
  const yAt = (v) => CH.top + ((hi - v) / (hi - lo)) * plotH;

  const svg = s(
    "svg",
    { viewBox: `0 0 ${CH.width} ${CH.height}`, role: "img", "aria-labelledby": `${id}-title`, class: "chart", preserveAspectRatio: "xMidYMid meet" },
    s("title", { id: `${id}-title`, text: `${title}. Each point shows its reported value on hover or focus; the same values are in the table below.` }),
    s("text", { x: CH.left, y: 14, class: "axis-title", text: spec.axis }),
    s("line", { x1: CH.left, x2: CH.left + plotW, y1: CH.top + plotH, y2: CH.top + plotH, class: "axis" }),
  );
  if (lo < 0 && hi > 0) {
    svg.append(
      s("line", { x1: CH.left, x2: CH.left + plotW, y1: yAt(0), y2: yAt(0), class: "zero" }),
      s("text", { x: CH.left + plotW + 4, y: yAt(0) + 4, class: "tick", text: "0" }),
    );
  }
  ends.forEach((end, i) => {
    const [year, rest] = [String(end).slice(0, 4), String(end).slice(5)];
    svg.append(
      s(
        "text",
        { x: xAt(i), y: CH.top + plotH + 16, class: "tick", "text-anchor": "middle" },
        s("tspan", { x: xAt(i), text: rest }),
        s("tspan", { x: xAt(i), dy: 13, text: year }),
      ),
    );
  });
  svg.append(s("text", { x: CH.left + plotW, y: CH.height - 2, class: "tick", "text-anchor": "end", text: `${capitalize(periodWord)} end` }));

  if (spec.kind === "bars") drawBars(svg, seriesList[0], { xAt, yAt, slot });
  else drawLines(svg, seriesList, { xAt, yAt, right: CH.left + plotW });

  return h(
    "figure",
    { class: "chart-block" },
    h("figcaption", { class: "chart-title", text: title }),
    svg,
    chartTable(title, seriesList),
  );
}

function pointTitle(seriesItem, point) {
  return `${seriesItem.label}, ${seriesItem.period === "annual" ? "fiscal year" : "quarter"} ended ${point.period_end}: ${point.display}`;
}

/** Bars; a missing value is a gap labelled with its display string, never a zero bar. */
function drawBars(svg, seriesItem, { xAt, yAt, slot }) {
  const width = Math.min(slot * 0.62, 46);
  seriesItem.points.forEach((point, i) => {
    const group = s("g", { class: "pt", tabindex: 0 }, s("title", { text: pointTitle(seriesItem, point) }));
    if (Number.isFinite(point.value)) {
      const top = Math.min(yAt(point.value), yAt(0));
      const bottom = Math.max(yAt(point.value), yAt(0));
      group.append(
        s("rect", { x: xAt(i) - width / 2, y: top, width, height: Math.max(bottom - top, 1), class: "bar" }),
        s("text", { x: xAt(i), y: top - 5, class: "bar-label", "text-anchor": "middle", text: point.display }),
      );
    } else {
      group.append(s("text", { x: xAt(i), y: yAt(0) - 6, class: "gap-label", "text-anchor": "middle", text: point.display }));
    }
    svg.append(group);
  });
}

function marker(kind, x, y) {
  if (kind === "square") return s("rect", { x: x - 3.5, y: y - 3.5, width: 7, height: 7, class: "marker" });
  if (kind === "triangle") return s("path", { d: `M ${x} ${y - 4.5} L ${x + 4.5} ${y + 3.5} L ${x - 4.5} ${y + 3.5} Z`, class: "marker" });
  return s("circle", { cx: x, cy: y, r: 3.8, class: "marker" });
}

/** Lines broken at missing values, a distinct dash and marker per series, labelled at the end. */
function drawLines(svg, seriesList, { xAt, yAt, right }) {
  const labels = [];
  seriesList.forEach((seriesItem, index) => {
    const style = LINE_STYLES[index % LINE_STYLES.length];
    const group = s("g", { class: `series series-${index}` });
    let path = "";
    let pen = false;
    seriesItem.points.forEach((point, i) => {
      if (!Number.isFinite(point.value)) {
        pen = false;
        return;
      }
      path += `${pen ? "L" : "M"} ${xAt(i).toFixed(1)} ${yAt(point.value).toFixed(1)} `;
      pen = true;
    });
    if (path) group.append(s("path", { d: path.trim(), class: "line", "stroke-dasharray": style.dash || null }));
    let last = null;
    const points = seriesItem.points;
    points.forEach((point, i) => {
      if (!Number.isFinite(point.value)) {
        // The gap's label sits on its own series, between the neighbouring points' heights.
        const near = [points[i - 1], points[i + 1]].filter((p) => p && Number.isFinite(p.value)).map((p) => yAt(p.value));
        const y = near.length ? near.reduce((a, b) => a + b, 0) / near.length : CH.top + 10;
        group.append(s("g", { class: "pt gap", tabindex: 0 }, s("title", { text: pointTitle(seriesItem, point) }), s("text", { x: xAt(i), y: y + 4, class: "gap-label", "text-anchor": "middle", text: point.display })));
        return;
      }
      last = { point, y: yAt(point.value) };
      const x = xAt(i);
      const y = yAt(point.value);
      group.append(
        s(
          "g",
          { class: "pt", tabindex: 0 },
          s("title", { text: pointTitle(seriesItem, point) }),
          marker(style.marker, x, y),
          s("text", { x, y: y - 9, class: "pt-label", "text-anchor": "middle", text: point.display }),
        ),
      );
    });
    svg.append(group);
    if (last) labels.push({ y: last.y, name: seriesList.length > 1 ? seriesItem.label : "", display: last.point.display, index });
  });
  // Direct labels at the right edge (name, then the newest value), nudged apart so they never overlap.
  const step = seriesList.length > 1 ? 30 : 16;
  labels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i += 1) {
    if (labels[i].y - labels[i - 1].y < step) labels[i].y = labels[i - 1].y + step;
  }
  for (const label of labels) {
    const style = LINE_STYLES[label.index % LINE_STYLES.length];
    const text = s("text", { x: right + 22, y: label.y + 4, class: "direct-label" });
    if (label.name) {
      text.append(s("tspan", { x: right + 22, text: label.name }), s("tspan", { x: right + 22, dy: 13, class: "direct-value", text: label.display }));
    } else {
      text.append(s("tspan", { class: "direct-value", text: label.display }));
    }
    svg.append(
      s(
        "g",
        { class: `series series-${label.index} direct` },
        s("line", { x1: right + 4, x2: right + 18, y1: label.y, y2: label.y, class: "line", "stroke-dasharray": style.dash || null }),
        text,
      ),
    );
  }
}

/** The chart's values as a table, in a disclosure: the text alternative. */
function chartTable(title, seriesList) {
  const ends = [];
  for (const seriesItem of seriesList) for (const point of seriesItem.points) if (!ends.includes(point.period_end)) ends.push(point.period_end);
  const lookup = seriesList.map((seriesItem) => new Map(seriesItem.points.map((p) => [p.period_end, p])));
  return h(
    "details",
    { class: "chart-table" },
    h("summary", { text: "Show these figures as a table" }),
    h(
      "div",
      { class: "table-wrap", tabindex: "0", role: "region", "aria-label": title },
      h(
        "table",
        { class: "inputs" },
        h("caption", { class: "visually-hidden", text: title }),
        h("thead", null, h("tr", null, h("th", { scope: "col", text: "Period end" }), seriesList.map((x) => h("th", { scope: "col", text: x.label })))),
        h(
          "tbody",
          null,
          ends.map((end) =>
            h(
              "tr",
              null,
              h("th", { scope: "row", text: end }),
              lookup.map((points, index) => {
                const point = points.get(end);
                return point
                  ? h("td", { class: "num", "data-series": seriesList[index].key, "data-period-end": end, text: point.display })
                  : h("td", { class: "num muted", text: "—" });
              }),
            ),
          ),
        ),
      ),
    ),
  );
}

// ---------------------------------------------------------------- start

/** The run or saved thesis named in the hash: {kind: "run" | "thesis", id}, or null. */
function hashTarget() {
  if (location.hash === "#inbox") return { kind: "inbox", id: "" };
  const match = /^#(run|thesis)=(.+)$/.exec(location.hash);
  if (!match) return null;
  try {
    return { kind: match[1], id: decodeURIComponent(match[2]) };
  } catch {
    return null;
  }
}

function openHashTarget() {
  const target = hashTarget();
  if (!target) return;
  if (target.kind === "run" && target.id !== state.runId) watchRun(target.id);
  if (target.kind === "thesis" && target.id !== state.thesisId) openThesis(target.id);
  if (target.kind === "inbox" && els.inboxView.hidden) openInbox();
}

// ---------------------------------------------------------------- version 14 components
//
// Drawn on the specimen page (specimen.html) from made-up data until the backend sends them.
// Each takes the record's shape documented in docs/design.md and computes nothing: outcomes,
// arithmetic, margins, flips, changes and percentiles are all the record's own strings.

/** A compiled test's outcome: its own glyphs (⊨ holds, ⊭ fails, ⊘ cannot compute), never a verdict's. */
const TEST_MARK = { holds: "⊨", fails: "⊭", cannot_compute: "⊘" };
const TEST_FALLBACK = { holds: "Holds", fails: "Fails", cannot_compute: "Cannot compute" };

function testOutcome(outcome, label) {
  const key = token(outcome, TEST_MARK);
  return h(
    "span",
    { class: `ct-outcome o-${key}`, "data-outcome": key },
    h("span", { class: "glyph", "aria-hidden": "true", text: TEST_MARK[key] ?? "·" }),
    h("span", { text: str(label) || TEST_FALLBACK[key] || String(outcome) }),
  );
}

/**
 * (1) A compiled test on a claim: the expression in monospace, its outcome, each operand with
 * the filing and date it comes from, the arithmetic and the margin.
 */
function compiledTest(test) {
  const operands = list(test.operands);
  return h(
    "section",
    { class: "ct", "data-compiled-test": str(test.claim_id) },
    h("div", { class: "ct-head" }, h("p", { class: "ct-expr" }, h("code", { text: str(test.expression) })), testOutcome(test.outcome, test.outcome_label)),
    h(
      "div",
      { class: "table-wrap", tabindex: "0", role: "region", "aria-label": `Operands of ${str(test.expression)}` },
      h(
        "table",
        { class: "ct-table" },
        h("thead", null, h("tr", null, ["Operand", "Value", "Period", "Filing", "Filed"].map((t) => h("th", { scope: "col", class: t === "Value" ? "num" : null, text: t })))),
        h(
          "tbody",
          null,
          operands.map((op) =>
            h(
              "tr",
              null,
              h("th", { scope: "row" }, h("code", { text: str(op.name) }), str(op.label) ? h("span", { class: "muted", text: ` ${op.label}` }) : ""),
              h("td", { class: `num${signClass(str(op.display))}`, text: str(op.display) || "—" }),
              h("td", { text: str(op.period_label) || "—" }),
              h("td", null, externalLink(op.url, `${str(op.form)} ${str(op.accession)}`.trim() || "filing")),
              h("td", { text: str(op.filed_label) || str(op.filed) || "—" }),
            ),
          ),
        ),
      ),
    ),
    h(
      "div",
      { class: "ct-foot" },
      h("p", null, h("span", { class: "label", text: "Arithmetic: " }), h("span", { class: "ct-arith", text: str(test.arithmetic) || "none recorded" })),
      h("p", null, h("span", { class: "label", text: "Margin: " }), h("span", { class: `ct-margin${signClass(str(test.margin_display))}`, text: str(test.margin_display) || "—" }), str(test.note) ? h("span", { class: "muted", text: ` ${test.note}` }) : ""),
    ),
  );
}

/**
 * (2) The thesis over time: per claim a step line over the filing dates the record tested it
 * at, holds above, cannot compute between, fails below, the flips the record names ringed and
 * labelled with their filing.
 */
function thesisOverTime(record, width = 880) {
  const claims = list(record.claims);
  const labels = { ...TEST_FALLBACK, ...(record.outcome_labels ?? {}) };
  const level = { holds: 0, cannot_compute: 1, fails: 2 };
  const days = claims.flatMap((c) => list(c.points).map((p) => dayOf(p.filed))).filter(Number.isFinite);
  if (days.length === 0) return h("p", { class: "muted", text: "The record tests no claim over time." });
  const lo = Math.min(...days);
  const hi = Math.max(...days);
  const laneH = 64;
  const top = 8;
  const labelW = Math.min(250, width * 0.3);
  const plotL = labelW + 74;
  const plotR = width - 16;
  const xAt = (day) => plotL + ((day - lo) / Math.max(hi - lo, DAY_MS)) * (plotR - plotL);
  const H = top + claims.length * laneH + 24;
  const svg = s("svg", { viewBox: `0 0 ${width} ${H}`, role: "img", "aria-label": "Each claim's test outcome at each filing date, with the filings where it flipped" });
  claims.forEach((claim, index) => {
    const y0 = top + index * laneH;
    const yAt = (outcome) => y0 + 12 + (level[outcome] ?? 1) * 16;
    svg.append(s("rect", { x: plotL - 6, y: y0 + 4, width: plotR - plotL + 12, height: laneH - 12, class: "tot-band" }));
    for (const [outcome, l] of Object.entries(level)) {
      svg.append(s("text", { x: plotL - 10, y: y0 + 15 + l * 16, "text-anchor": "end", class: "tot-state", text: str(labels[outcome]) }));
    }
    const text = str(claim.text);
    svg.append(s("text", { x: 0, y: y0 + 18, class: "tot-lane-label" }, s("tspan", { class: "claim-id-svg", text: `${str(claim.claim_id)} ` }), text.length > 38 ? `${text.slice(0, 37)}…` : text), s("title", { text }));
    const points = list(claim.points).filter((p) => Number.isFinite(dayOf(p.filed)));
    let d = "";
    points.forEach((p, i) => {
      const x = xAt(dayOf(p.filed));
      const y = yAt(p.outcome);
      d += i === 0 ? `M ${x} ${y}` : ` H ${x} V ${y}`;
    });
    svg.append(s("path", { d, class: "tot-step" }));
    for (const p of points) {
      const key = token(p.outcome, TEST_MARK);
      svg.append(
        s("circle", { cx: xAt(dayOf(p.filed)), cy: yAt(p.outcome), r: 3.4, class: `tot-pt o-${key}` }, s("title", { text: `${str(p.form)} filed ${str(p.filed_label) || dateLabel(p.filed)}: ${str(labels[key])}` })),
      );
    }
    for (const flip of list(claim.flips)) {
      svg.append(
        s("circle", { cx: xAt(dayOf(flip.filed)), cy: yAt(flip.to), r: 7, class: "tot-flip", "data-flip": str(flip.filed) }, s("title", { text: `${str(claim.claim_id)}: ${str(flip.label)}` })),
      );
    }
  });
  const ticks = s("g", { "aria-hidden": "true" });
  const firstYear = new Date(lo).getUTCFullYear();
  const lastYear = new Date(hi).getUTCFullYear();
  for (let year = firstYear; year <= lastYear + 1; year += 1) {
    const day = Date.UTC(year, 0, 1);
    if (day < lo || day > hi) continue;
    ticks.append(s("line", { x1: xAt(day), x2: xAt(day), y1: top, y2: H - 18, class: "tot-grid" }), s("text", { x: xAt(day) + 3, y: H - 6, class: "tot-date", text: String(year) }));
  }
  svg.prepend(ticks);
  // The flips, in the record's words, under the chart rather than crowded into it.
  const flips = h(
    "ul",
    { class: "tot-flips" },
    claims.flatMap((claim) => list(claim.flips).map((flip) => h("li", null, h("span", { class: "claim-id", text: str(claim.claim_id) }), "Flipped: ", str(flip.label)))),
  );
  return h("div", { class: "tot", "data-thesis-over-time": "" }, svg, flips);
}

/** (3a) The as-of date control for the thesis form: empty means today; the server checks the bounds it states. */
function asOfControl(spec) {
  return h(
    "div",
    { class: "field asof-control" },
    h("label", { for: "as_of", text: "As of" }),
    h("p", { id: "as-of-hint", class: "hint", text: str(spec.hint) || "Read the record as it stood on this date: no filing made after it is read. Leave it empty to read everything filed up to today." }),
    h(
      "div",
      { class: "asof-row" },
      h("input", { id: "as_of", name: "as_of", type: "date", min: str(spec.min) || null, max: str(spec.max) || null, value: str(spec.value) || null, "aria-describedby": "as-of-hint err-as_of" }),
      h("button", { type: "button", class: "secondary small", text: "Today" }),
    ),
    h("p", { id: "err-as_of", class: "field-error", hidden: true }),
  );
}

/** (3b) The banner on a run made as of a past date, in the record's words. */
function asOfBanner(request) {
  return h(
    "div",
    { class: "asof-banner", role: "note", "data-as-of-request": str(request.date) },
    h("span", { class: "asof-banner-date", text: str(request.label) || dateLabel(request.date) }),
    h("p", { class: "label", text: "A run as of a past date" }),
    h("p", { class: "asof-banner-line", text: str(request.line) }),
  );
}

/** (4) The restatement ledger: what a later filing reported differently, both filings named. */
function restatementLedger(record) {
  const rows = list(record.rows);
  const side = (entry, cls) =>
    h(
      "td",
      { class: `num ${cls}` },
      h("span", { class: `num-val${signClass(str(entry?.display))}`, text: str(entry?.display) || "—" }),
      h("span", { class: "ledger-filing" }, externalLink(entry?.url, `${str(entry?.form)} ${str(entry?.filed_label)}`.trim() || "filing")),
    );
  return h(
    "div",
    { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Restatement ledger" },
    h(
      "table",
      { class: "ledger", "data-ledger": "" },
      h("thead", null, h("tr", null, ["Metric", "Period", "First reported", "Reported later", "Change"].map((t, i) => h("th", { scope: "col", class: i >= 2 ? "num" : null, text: t })))),
      h(
        "tbody",
        null,
        rows.map((row) =>
          h(
            "tr",
            null,
            h("th", { scope: "row", text: str(row.metric_label) }),
            h("td", { text: str(row.period_label) }),
            side(row.first, "ledger-first"),
            side(row.later, "ledger-later"),
            h("td", { class: `num ledger-change${signClass(str(row.change_display))}` }, str(row.change_display) || "—", str(row.note) ? h("span", { class: "ledger-filing", text: row.note }) : ""),
          ),
        ),
      ),
    ),
  );
}

/**
 * (5) The peer strip: the company's value as a dot on its industry's distribution, the
 * quartile box and median, and the record's own percentile line ("97th percentile of 212").
 */
function peerStrip(record) {
  const rows = list(record.metrics).map((metric) => {
    const W = 520;
    const H = 40;
    const lo = metric.min?.value;
    const hi = metric.max?.value;
    const ok = Number.isFinite(lo) && Number.isFinite(hi) && hi > lo;
    const xAt = (v) => 8 + ((v - lo) / (hi - lo)) * (W - 16);
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", "aria-hidden": "true", focusable: "false" });
    if (ok) {
      for (const v of list(metric.peers)) if (Number.isFinite(v)) svg.append(s("circle", { cx: xAt(v), cy: 14 + ((v * 7919) % 7) - 3, r: 1.6, class: "peer-dot" }));
      svg.append(s("line", { x1: xAt(lo), x2: xAt(hi), y1: 14, y2: 14, class: "peer-range" }));
      if (Number.isFinite(metric.q1?.value) && Number.isFinite(metric.q3?.value)) {
        svg.append(s("rect", { x: xAt(metric.q1.value), y: 8, width: Math.max(xAt(metric.q3.value) - xAt(metric.q1.value), 1), height: 12, class: "peer-iqr" }));
      }
      if (Number.isFinite(metric.median?.value)) svg.append(s("line", { x1: xAt(metric.median.value), x2: xAt(metric.median.value), y1: 5, y2: 23, class: "peer-median" }));
      if (Number.isFinite(metric.company?.value)) svg.append(s("circle", { cx: xAt(metric.company.value), cy: 14, r: 6, class: "peer-you" }));
      svg.append(
        s("text", { x: 8, y: H - 2, class: "peer-tick", text: str(metric.min?.display) }),
        s("text", { x: W - 8, y: H - 2, "text-anchor": "end", class: "peer-tick", text: str(metric.max?.display) }),
        Number.isFinite(metric.median?.value) ? s("text", { x: xAt(metric.median.value), y: H - 2, "text-anchor": "middle", class: "peer-tick", text: `median ${str(metric.median.display)}` }) : "",
      );
    }
    return h(
      "div",
      { class: "peer", "data-peer-metric": str(metric.metric_label) },
      h("p", { class: "peer-metric" }, str(metric.metric_label), h("span", { class: "muted", text: str(metric.unit_label) })),
      svg,
      h("p", { class: "peer-read" }, h("strong", { class: signClass(str(metric.company?.display)).trim() || null, text: `${str(metric.company?.ticker)} ${str(metric.company?.display)}`.trim() }), str(metric.percentile_label)),
    );
  });
  return h("div", { class: "peers", "data-peer-strip": "" }, h("p", { class: "hint", text: str(record.industry_label) }), rows);
}

// ---------------------------------------------------------------- the specimen page

/** The specimen: the design system on made-up data, every component once, both themes by the toggle. */
function initSpecimen() {
  initTheme();
  document.addEventListener("keydown", onKey);
  els.keysButton?.addEventListener("click", openKeys);
  let data;
  try {
    data = JSON.parse(document.getElementById("specimen-data")?.textContent ?? "");
  } catch (error) {
    document.getElementById("specimen-root")?.replaceChildren(h("p", { class: "alert", text: `The specimen data could not be read: ${error.message}.` }));
    return;
  }
  // The note is the page's own run view, drawn by the same code from the made-up record.
  // ?only=<part> shows one part of the specimen (a capture is limited in height).
  const only = new URLSearchParams(location.search).get("only");
  if (only && /^[a-z0-9]{1,20}$/.test(only)) {
    for (const part of document.querySelectorAll(".spec-section[data-part]")) part.hidden = part.dataset.part !== only;
  }
  state.sample = true;
  state.sampleName = "specimen";
  state.meta = data.meta;
  state.sampleNote = str(data.note);
  state.runId = data.run.id;
  state.review = data.review && data.review.run_id === data.run.id ? data.review : null;
  state.comparison = data.comparison ?? null;
  renderRun(data.run);
  // Open the first claims, so the specimen shows findings with their quotes in the margin.
  for (const docket of [...document.querySelectorAll("#claim-list details.claim")].slice(0, 3)) docket.open = true;
  watchTimelineWidth();

  const v14 = data.v14;
  const width = Math.max(Math.round(document.getElementById("spec-tot")?.clientWidth || 880), 320);
  document.getElementById("spec-compiled")?.replaceChildren(...list(v14.compiled_tests).map(compiledTest));
  document.getElementById("spec-tot")?.replaceChildren(thesisOverTime(v14.thesis_over_time, width));
  document.getElementById("spec-asof")?.replaceChildren(asOfControl(v14.as_of_control), h("span", { class: "spec-label", text: "The banner on a run made as of a past date" }), asOfBanner(v14.as_of_request));
  document.getElementById("spec-ledger")?.replaceChildren(restatementLedger(v14.restatements));
  document.getElementById("spec-peers")?.replaceChildren(peerStrip(v14.peers));

  const marks = document.getElementById("spec-marks");
  if (marks) {
    marks.replaceChildren(
      h("span", { class: "spec-label", text: "Verdict stamps" }),
      h("div", { class: "spec-row" }, Object.keys(VERDICT_GLYPH).map(verdictPill), h("span", { class: "pill review-pending", text: "not reviewed yet" })),
      h("span", { class: "spec-label", text: "Stances, decisions, the second model" }),
      h("div", { class: "spec-row" }, Object.keys(STANCE_MARK).map(stancePill), ["accepted", "rejected", "undecided"].map(decisionMark), meaningMark("passed"), meaningMark("partly")),
      h("span", { class: "spec-label", text: "Provenance and limits" }),
      h("div", { class: "spec-row" }, modelBadge(), ruleMark(), limitLine("span", "A limit of the record"), h("span", { class: "mark-reject" }, rejectGlyph(), " Refused"), h("span", { class: "page-tag", text: "Sample record" })),
      h("span", { class: "spec-label", text: "What changed between two filings" }),
      h("div", { class: "spec-row" }, Object.keys(CHANGE_MARK).map(changeMark), h("ins", { class: "seg seg-add", text: "added words" }), h("del", { class: "seg seg-del", text: "removed words" })),
      h("span", { class: "spec-label", text: "Run status (never a filled tag)" }),
      h("div", { class: "spec-row" }, ["complete", "running", "partial", "failed"].map((st) => h("span", { class: `status-word st-${st}` }, statusMark(st), ` ${capitalize(st)}`))),
      h("span", { class: "spec-label", text: "Test outcomes (version 14)" }),
      h("div", { class: "spec-row" }, Object.keys(TEST_MARK).map((k) => testOutcome(k, ""))),
      h("span", { class: "spec-label", text: "Numbers" }),
      h("div", { class: "spec-row" }, h("span", { class: "fig-value", text: "$96.22B" }), h("span", { class: "fig-value is-neg", text: "−$1.40B" }), h("span", { class: "fig-value is-missing", text: "not reported" }), h("code", { text: "0001045810-26-000082" })),
      h("span", { class: "spec-label", text: "Controls" }),
      h(
        "div",
        { class: "spec-row" },
        h("button", { type: "button", class: "primary", text: "Test the thesis" }),
        h("button", { type: "button", class: "secondary", text: "Load example" }),
        h("button", { type: "button", class: "secondary small", text: "Accept" }),
        h("button", { type: "button", class: "primary", disabled: true, text: "Disabled" }),
        h("a", { href: "#spec-marks", text: "A link" }),
        h("kbd", { text: "j" }),
      ),
    );
  }
  const swatches = document.getElementById("spec-swatches");
  if (swatches) {
    const tokens = ["--bg", "--surface", "--surface-2", "--ink", "--ink-2", "--line", "--accent", "--support", "--challenge", "--neutral", "--limit", "--model", "--reject", "--rule", "--change", "--neg", "--mark-bg"];
    const paint = () => {
      const styles = getComputedStyle(document.documentElement);
      swatches.replaceChildren(
        ...tokens.map((name) =>
          h("div", { class: "swatch" }, h("div", { class: "swatch-chip", style: `background: var(${name})` }), h("p", null, h("strong", { text: name })), h("p", { class: "muted", text: styles.getPropertyValue(name).trim() })),
        ),
      );
    };
    paint();
    els.themeToggle?.addEventListener("click", () => requestAnimationFrame(paint));
    document.addEventListener("keydown", (event) => {
      if (event.key === "t") requestAnimationFrame(paint);
    });
  }
}

// ---------------------------------------------------------------- the standing watch (version 13)
//
// Watches, the inbox and the watcher's health, drawn from /api/watch, /api/inbox and
// /api/watch/health, with the words of /api/watch/meta. Every headline, count, label and
// reason is the backend's; the page orders nothing (the inbox comes unread first, as the
// API sends it) and counts nothing but the folded items it draws on one line.

/** The recorded inbox (?sample=inbox): the watch's example payloads, copied unedited by `make sample-inbox`. */
const INBOX_SAMPLES = { inbox: "sample-inbox.json", "inbox-page-2": "sample-inbox-page-2.json" };
const INBOX_SAMPLE_NOTE =
  "The standing watch's example payloads (docs/examples/v13), written by `make watch-examples` from an offline scenario: a made-up EDGAR index of NVIDIA filings, a fake clock that starts at 18 Nov 2026 09:00 UTC, and scripted verdicts (no model, no cassette). They are copied unedited. In sample mode the page sends nothing: no watch changes, no run starts, nothing is marked read.";
const INBOX_KIND = { not_relevant: "○", waiting: "◇", running: "◌", moved: "◆", nothing_moved: "·", failed: "▲" };
const WATCH_POLL_MS = 60000;

function kindLabel(kind) {
  return str(state.watchMeta?.kind_labels?.[kind]) || String(kind ?? "");
}

function policyLabels() {
  const labels = state.watchMeta?.policy_labels;
  return labels && typeof labels === "object" ? labels : { ask: "Ask before running", auto: "Run at once" };
}

/** A refusal in the server's words: the 422's fields, else its one sentence. */
function refusal(error) {
  if (error.status === 422 && error.details.length) {
    return `${error.message}: ${error.details.map((d) => `${str(d.field) || "request"}: ${str(d.message)}`).join("; ")}`;
  }
  return error.message;
}

function setMessage(node, text, kind = "error") {
  if (!node) return;
  node.textContent = text;
  node.className = `watch-message ${kind === "error" ? "is-error" : "is-ok"}`;
  node.hidden = !text;
}

// ---- health

/** The watcher's health, in the bar: alive or not, its last cycle, the queue and the runs waiting. */
function renderHealth() {
  const node = els.watchHealth;
  const health = state.health;
  if (!node) return;
  const inboxSample = state.sample && Object.hasOwn(INBOX_SAMPLES, state.sampleName);
  if (!health || (state.sample && !inboxSample)) {
    node.hidden = true;
    return;
  }
  const alive = health.alive === true;
  node.hidden = false;
  node.className = `watch-health ${alive ? "is-alive" : "is-down"}`;
  node.dataset.alive = String(alive);
  node.title = [str(health.note), health.last_cycle_at ? `Last cycle ${utc(health.last_cycle_at)}.` : ""].filter(Boolean).join(" ");
  node.replaceChildren(
    h("span", { class: "glyph health-dot", "aria-hidden": "true", text: alive ? "●" : "○" }),
    h("span", { class: "health-word", text: alive ? "Watch alive" : "Watch not running" }),
    h(
      "span",
      { class: "health-detail" },
      // The time of day only; the whole date and time are in the title, with the watcher's note.
      health.last_cycle_at ? ` · last cycle ${utc(health.last_cycle_at).slice(11)}` : "",
      " · queue ",
      h("span", { "data-health": "queue_depth", text: num(health.queue_depth) }),
      " · ",
      h("span", { "data-health": "waiting_runs", text: num(health.waiting_runs) }),
      " waiting",
    ),
  );
  renderWatchDown();
}

/** Near every watch control: when the watcher is not alive, nothing new will be noticed until it runs. */
function watchDownLine() {
  const health = state.health;
  if (!health || health.alive === true) return null;
  return limitLine(
    "p",
    h("strong", { text: "The watcher is not running." }),
    " No new filing will be noticed, and no watched thesis run, until it runs. ",
    str(health.note),
  );
}

function renderWatchDown() {
  const line = watchDownLine();
  if (els.watchDown) {
    els.watchDown.hidden = !line;
    els.watchDown.replaceChildren(...(line ? [line] : []));
  }
  const card = els.thesisWatch?.querySelector(".watch-down-slot");
  if (card) card.replaceChildren(...(line ? [line] : []));
}

// ---- the unread count

function renderInboxCount() {
  const node = els.inboxCount;
  if (!node) return;
  const unread = state.inboxUnread;
  node.hidden = !Number.isFinite(unread);
  node.textContent = Number.isFinite(unread) ? num(unread) : "";
  node.dataset.unread = Number.isFinite(unread) ? String(unread) : "";
  els.inboxButton?.setAttribute("aria-label", Number.isFinite(unread) ? `Inbox, ${num(unread)} unread` : "Inbox");
}

/** Health, watches, the words and the unread count, from the server. A 404 means a server without the watch: it stays hidden. */
async function refreshWatchState() {
  if (state.sample) return;
  try {
    if (!state.watchMeta) state.watchMeta = await api("/api/watch/meta");
  } catch (error) {
    if (error.status === 404) {
      els.inboxButton.hidden = true;
      return;
    }
  }
  const [health, watches, inbox] = await Promise.allSettled([api("/api/watch/health"), api("/api/watch"), api("/api/inbox?limit=1")]);
  state.health = health.status === "fulfilled" ? health.value : null;
  if (watches.status === "fulfilled") {
    state.watches = new Map(list(watches.value.watches).map((w) => [w.thesis_id, w]));
    state.watchesLoaded = true;
  }
  if (inbox.status === "fulfilled" && Number.isFinite(inbox.value.unread)) state.inboxUnread = inbox.value.unread;
  renderHealth();
  renderInboxCount();
  if (state.theses.size) renderTheses([...state.theses.values()]);
  if (state.thesisId && !els.thesisView.hidden) renderThesisWatch(state.thesisId);
}

function startWatchPolling() {
  refreshWatchState();
  setInterval(() => {
    if (!document.hidden) refreshWatchState();
  }, WATCH_POLL_MS);
}

// ---- a watch: put on, policy, take off

/**
 * The watch of one saved thesis: its policy (changeable), the last and next check, the last
 * errors and its unread items; or, when it is not watched, a control to put it on watch.
 */
function watchCard(thesisId, watch, sample = state.sample) {
  const labels = policyLabels();
  const current = watch ? str(watch.policy) : str(state.watchMeta?.default_policy) || "ask";
  const message = h("p", { class: "watch-message", role: "status", hidden: true });
  const name = `policy-${thesisId}`;
  const choice = h(
    "fieldset",
    { class: "watch-policy" },
    h("legend", { text: watch ? "When a new filing bears on a claim" : "Put it on watch: when a new filing bears on a claim" }),
    ...Object.entries(labels).map(([value, label]) =>
      h(
        "label",
        { class: "watch-choice" },
        h("input", {
          type: "radio",
          name,
          value,
          checked: value === current,
          disabled: sample,
          "data-policy": value,
          onchange: watch ? () => putWatch(thesisId, value, message) : null,
        }),
        ` ${label}`,
        value === "auto" ? h("span", { class: "hint", text: " (each run uses the model, within the daily cap)" }) : "",
      ),
    ),
  );
  const parts = [h("div", { class: "watch-down-slot" }, ...(watchDownLine() ? [watchDownLine()] : []))];
  if (watch) {
    const check = (iso) => (iso ? utc(iso) : str(watch.next_check_note) || "—");
    parts.push(
      h(
        "p",
        { class: "watch-state" },
        h("span", { class: "watch-on", text: "On watch" }),
        ` since ${utc(watch.watching_since)} · `,
        h("strong", { "data-watch": "policy_label", text: str(watch.policy_label) || labels[watch.policy] || "" }),
      ),
      h(
        "dl",
        { class: "watch-facts" },
        h("div", null, h("dt", { text: "Last check" }), h("dd", { "data-watch": "last_check_at", text: check(watch.last_check_at) })),
        h("div", null, h("dt", { text: "Next check" }), h("dd", { "data-watch": "next_check_at", text: check(watch.next_check_at) })),
        h("div", null, h("dt", { text: "Last error" }), h("dd", { "data-watch": "last_error", class: watch.last_error ? "is-error" : null, text: str(watch.last_error) || "None" })),
        str(watch.last_job_error) ? h("div", null, h("dt", { text: "Last failed job" }), h("dd", { "data-watch": "last_job_error", class: "is-error", text: watch.last_job_error })) : "",
        h(
          "div",
          null,
          h("dt", { text: "Inbox" }),
          h(
            "dd",
            null,
            h("span", { "data-watch": "unread", text: num(watch.unread) }),
            " unread · ",
            h("span", { "data-watch": "waiting_runs", text: num(watch.waiting_runs) }),
            ` ${unit(watch.waiting_runs, "run", "runs")} waiting · `,
            h("a", { href: "#inbox", onclick: (event) => { event.preventDefault(); openInbox({ thesisId }); }, text: "open its inbox" }),
          ),
        ),
      ),
      choice,
      h(
        "div",
        { class: "watch-actions" },
        h("button", { type: "button", class: "secondary small", "data-unwatch": thesisId, disabled: sample, onclick: () => deleteWatch(thesisId, message), text: "Take it off watch" }),
      ),
    );
  } else {
    parts.push(
      h("p", { class: "watch-state muted", text: "Not on watch. On watch, the watcher reads the company's filing index every few minutes and says here and in the inbox what each new filing means for these claims." }),
      choice,
      h(
        "div",
        { class: "watch-actions" },
        h("button", {
          type: "button",
          class: "primary small",
          "data-watch-put": thesisId,
          disabled: sample,
          onclick: () => putWatch(thesisId, choice.querySelector("input:checked")?.value ?? current, message),
          text: "Put it on watch",
        }),
      ),
    );
  }
  if (sample) parts.push(h("span", { class: "page-tag inline-tag", text: "sample: nothing is saved" }));
  parts.push(message);
  return h("div", { class: watch ? "watch-card is-on" : "watch-card", "data-watch-thesis": thesisId }, ...parts);
}

/** Put a thesis on watch, or change its policy. 201 or 200 answer with the watch. */
async function putWatch(thesisId, policy, message) {
  if (state.sample) return;
  setMessage(message, "Saving…", "ok");
  try {
    const answer = await api(`/api/theses/${encodeURIComponent(thesisId)}/watch`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ policy }),
    });
    if (!answer.watch || answer.watch.thesis_id !== thesisId) throw new ApiError("the server did not return this thesis's watch", 0);
    state.watches.set(thesisId, answer.watch);
    rerenderWatch(thesisId, answer.created ? `On watch: ${str(answer.watch.policy_label)}.` : `Policy changed: ${str(answer.watch.policy_label)}.`);
  } catch (error) {
    const reason =
      error.status === 404 ? "no saved thesis with that id exists" : error.status === 503 ? `${error.message}. Nothing was saved` : refusal(error);
    setMessage(message, `The watch could not be saved: ${reason}.`);
    resetPolicy(thesisId);
  }
}

async function deleteWatch(thesisId, message) {
  if (state.sample) return;
  try {
    const answer = await api(`/api/theses/${encodeURIComponent(thesisId)}/watch`, { method: "DELETE" });
    if (answer.watching !== false) throw new ApiError("the server did not say the watch ended", 0);
    state.watches.delete(thesisId);
    rerenderWatch(thesisId, "Taken off watch. Its inbox items stay.");
  } catch (error) {
    if (error.status === 409) {
      // Not watched any more (taken off elsewhere): show it as the server has it.
      state.watches.delete(thesisId);
      rerenderWatch(thesisId, `${error.message}.`);
      return;
    }
    setMessage(message, `The watch could not be ended: ${error.status === 404 ? "no saved thesis with that id exists" : refusal(error)}.`);
  }
}

/** A refused policy change leaves the radio on the policy the server has. */
function resetPolicy(thesisId) {
  const watch = state.watches.get(thesisId);
  if (!watch) return;
  for (const card of document.querySelectorAll(`[data-watch-thesis="${CSS.escape(thesisId)}"]`)) {
    for (const input of card.querySelectorAll("input[data-policy]")) input.checked = input.value === watch.policy;
  }
}

/** Draw a thesis's watch again wherever it is on screen, with a message under it. */
function rerenderWatch(thesisId, note) {
  if (state.thesisId === thesisId && !els.thesisView.hidden) renderThesisWatch(thesisId, note);
  if (!els.inboxView.hidden) renderWatches(note, thesisId);
  if (state.theses.size) renderTheses([...state.theses.values()]);
  refreshWatchState();
}

function renderThesisWatch(thesisId, note = "") {
  if (!els.thesisWatchSection) return;
  if (!state.watchMeta || !state.watchesLoaded) {
    els.thesisWatchSection.hidden = true;
    return;
  }
  els.thesisWatchSection.hidden = false;
  const card = watchCard(thesisId, state.watches.get(thesisId) ?? null);
  els.thesisWatch.replaceChildren(card);
  if (note) setMessage(card.querySelector(".watch-message"), note, "ok");
}

/** Every watch, oldest first as the API lists them, in the inbox view. */
function renderWatches(note = "", noteThesis = "") {
  const watches = [...state.watches.values()];
  // A note about a watch no longer listed (taken off) goes above the list.
  if (note && noteThesis && !state.watches.has(noteThesis)) setMessage(els.inboxMessage, note, "ok");
  if (watches.length === 0) {
    els.watches.replaceChildren(
      h("p", { class: "muted", "data-empty": "watches", text: "No thesis is on watch. Open a saved thesis and put it on watch; its new filings then arrive here." }),
    );
    return;
  }
  els.watches.replaceChildren(
    h(
      "ul",
      { class: "watch-list" },
      watches.map((watch) =>
        h(
          "li",
          { "data-watch-id": watch.thesis_id },
          h(
            "p",
            { class: "watch-name" },
            h("strong", { text: str(watch.thesis_name) }),
            " · ",
            h("span", { class: "ticker-chip", text: str(watch.ticker) }),
            ` ${str(watch.company_name)}`,
          ),
          watchCard(watch.thesis_id, watch),
        ),
      ),
    ),
  );
  if (note && noteThesis) {
    const card = els.watches.querySelector(`[data-watch-thesis="${CSS.escape(noteThesis)}"] .watch-message`);
    setMessage(card, note, "ok");
  }
}

// ---- the inbox

/** Open the inbox view: from the bar, the `i` key, #inbox, or a thesis's "open its inbox". */
function openInbox({ thesisId = null, offset = 0 } = {}) {
  closeDrawer(false);
  if (state.sample) {
    if (Object.hasOwn(INBOX_SAMPLES, state.sampleName)) {
      showInboxView();
      els.inboxItems.querySelector("article")?.focus?.({ preventScroll: true });
      return;
    }
    showInboxView();
    renderInboxHead(null);
    els.watchesSection.hidden = true;
    els.inboxItems.replaceChildren();
    els.inboxCollapsed.replaceChildren();
    els.inboxPaging.replaceChildren();
    setMessage(els.inboxMessage, "", "ok");
    els.inboxItems.append(
      h("li", { class: "muted", "data-empty": "sample" }, "This sample holds no inbox. ", h("a", { href: "?sample=inbox", text: "See the recorded inbox of the standing watch" }), "."),
    );
    return;
  }
  state.inboxThesis = thesisId;
  state.inboxOffsets = [];
  loadInbox(offset);
}

function showInboxView() {
  stopWatching();
  state.viewSeq += 1;
  hideRunView();
  els.loading.hidden = true;
  els.inboxView.hidden = false;
  document.body.classList.add("has-run");
  els.watchesSection.hidden = false;
  els.inboxButton?.setAttribute("aria-expanded", "true");
  if (!state.sample) history.replaceState(null, "", "#inbox");
}

async function loadInbox(offset) {
  showInboxView();
  const seq = ++state.inboxSeq;
  setMessage(els.inboxMessage, "Loading the inbox…", "ok");
  const query = new URLSearchParams({ offset: String(offset) });
  if (state.inboxThesis) query.set("thesis_id", state.inboxThesis);
  try {
    if (!state.watchMeta) state.watchMeta = await api("/api/watch/meta");
    const [page, watches, health] = await Promise.all([api(`/api/inbox?${query}`), api("/api/watch"), api("/api/watch/health").catch(() => null)]);
    if (seq !== state.inboxSeq) return;
    state.watches = new Map(list(watches.watches).map((w) => [w.thesis_id, w]));
    state.watchesLoaded = true;
    state.health = health;
    renderHealth();
    setMessage(els.inboxMessage, "", "ok");
    renderInbox(page);
  } catch (error) {
    if (seq !== state.inboxSeq) return;
    renderInboxHead(null);
    els.inboxItems.replaceChildren();
    els.inboxCollapsed.replaceChildren();
    els.inboxPaging.replaceChildren(h("button", { type: "button", class: "secondary small", onclick: () => loadInbox(offset), text: "Try again" }));
    const reason = error.status === 404 ? "this server has no inbox (it is older than version 13)" : refusal(error);
    setMessage(els.inboxMessage, `The inbox could not be loaded: ${reason}.`);
  }
}

function renderInboxHead(page) {
  const thesis = state.inboxThesis ? state.watches.get(state.inboxThesis) : null;
  els.inboxHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      h("p", { class: "company-name", text: "Inbox" }),
      h(
        "p",
        { class: "run-meta" },
        page
          ? [
              h("span", { class: "count-value", "data-inbox": "unread", text: num(page.unread) }),
              " unread of ",
              h("span", { class: "count-value", "data-inbox": "total", text: num(page.total) }),
              ` ${unit(page.total, "item", "items")}`,
              thesis ? ` for “${str(thesis.thesis_name)}”` : state.inboxThesis ? " for one thesis" : "",
              ". Unread first, then newest first.",
            ]
          : "The standing watch's new filings, each with what it means for the watched theses.",
        state.inboxThesis && !state.sample ? [" ", h("a", { href: "#inbox", onclick: (event) => { event.preventDefault(); openInbox(); }, text: "Show every thesis" })] : "",
      ),
      sampleNoteLine(),
    ),
  );
}

/** One page of the inbox exactly as the API ordered it; the folded kinds go on one line under it. */
function renderInbox(page) {
  if (!page || !Array.isArray(page.items)) throw new ApiError("the inbox page has no items", 0);
  state.inboxPage = page;
  if (Number.isFinite(page.unread) && !state.inboxThesis) state.inboxUnread = page.unread;
  renderInboxCount();
  renderInboxHead(page);
  renderWatches();
  renderWatchDown();
  const open = page.items.filter((item) => item.collapsed !== true);
  const folded = page.items.filter((item) => item.collapsed === true);
  els.inboxItems.replaceChildren(...open.map((item) => h("li", null, inboxItem(item))));
  if (page.items.length === 0) {
    els.inboxItems.append(h("li", { class: "muted", "data-empty": "inbox", text: page.offset > 0 ? "No items on this page." : "The inbox is empty: no watched thesis has a new filing yet." }));
  }
  renderFolded(folded);
  renderPaging(page);
}

/**
 * The folded items ("seen, not relevant"): one line with how many this page holds, opening to
 * each one's headline and filing. The count is of the items drawn here, not a figure of the record.
 */
function renderFolded(folded) {
  if (folded.length === 0) {
    els.inboxCollapsed.replaceChildren();
    return;
  }
  const kinds = [...new Set(folded.map((item) => item.kind))];
  els.inboxCollapsed.replaceChildren(
    h(
      "details",
      { class: "inbox-folded", "data-folded-count": String(folded.length) },
      h(
        "summary",
        null,
        h("span", { class: "glyph", "aria-hidden": "true", text: INBOX_KIND.not_relevant }),
        ` ${kinds.map(kindLabel).join(", ")}: `,
        h("span", { class: "count-value", "data-folded": "count", text: num(folded.length) }),
        ` ${unit(folded.length, "filing", "filings")} on this page`,
        h("span", { class: "fold-hint", text: ". No run was needed." }),
      ),
      h("ol", { class: "inbox-items is-folded" }, folded.map((item) => h("li", null, inboxItem(item)))),
    ),
  );
}

function renderPaging(page) {
  const parts = [];
  if (state.sample) {
    if (page.offset > 0) parts.push(h("a", { class: "tool", href: "?sample=inbox", "data-page": "first", text: "First page" }));
  } else {
    if (state.inboxOffsets.length) {
      parts.push(
        h("button", {
          type: "button",
          class: "secondary small",
          "data-page": "newer",
          onclick: () => loadInbox(state.inboxOffsets.pop()),
          text: "Newer items",
        }),
      );
    }
    if (Number.isInteger(page.next_offset)) {
      parts.push(
        h("button", {
          type: "button",
          class: "secondary small",
          "data-page": "older",
          onclick: () => {
            state.inboxOffsets.push(page.offset);
            loadInbox(page.next_offset);
          },
          text: "Older items",
        }),
      );
    }
    const unreadIds = page.items.filter((item) => !item.read_at).map((item) => item.id);
    if (unreadIds.length) parts.push(h("button", { type: "button", class: "secondary small", "data-mark-page": "", onclick: () => markRead(unreadIds, true), text: "Mark this page read" }));
  }
  if (Number.isInteger(page.next_offset)) parts.push(h("span", { class: "hint", "data-next-offset": String(page.next_offset), text: "More items are on the next page." }));
  els.inboxPaging.replaceChildren(...parts);
}

/** One inbox item: its kind, headline, the filing, the triage per claim, the run and what moved. */
function inboxItem(item) {
  const kind = token(item.kind, INBOX_KIND);
  const unread = !item.read_at;
  const message = h("p", { class: "watch-message", role: "status", hidden: true });
  const node = h(
    "article",
    { class: `inbox-item k-${kind}${unread ? " is-unread" : ""}`, "data-item-id": str(item.id), "data-kind": kind, "data-unread": String(unread), tabindex: "-1" },
    h(
      "header",
      { class: "inbox-item-head" },
      h("span", { class: `kind-tag k-${kind}`, "data-kind-label": "" }, h("span", { class: "glyph", "aria-hidden": "true", text: INBOX_KIND[kind] ?? "·" }), ` ${kindLabel(item.kind)}`),
      unread ? h("span", { class: "unread-mark", text: "Unread" }) : h("span", { class: "read-mark", text: `Read ${utc(item.read_at)}` }),
      h("span", { class: "inbox-when", text: `${str(item.ticker)} · ${str(item.thesis_name)} · ${utc(item.updated_at)}` }),
    ),
    h("p", { class: "inbox-headline", text: str(item.headline) }),
    item.collapsed ? "" : inboxFiling(item.filing),
    item.collapsed ? h("p", { class: "inbox-filing-line" }, externalLink(item.filing?.url, str(item.filing?.label) || "the filing")) : inboxTriage(item.triage),
    inboxRun(item, message),
    inboxMoved(item.moved),
    h(
      "div",
      { class: "inbox-actions" },
      h("button", {
        type: "button",
        class: "linklike",
        "data-mark": unread ? "read" : "unread",
        disabled: state.sample,
        onclick: () => markRead([item.id], unread),
        text: unread ? "Mark read" : "Mark unread",
      }),
    ),
    message,
  );
  return node;
}

/** The filing that arrived: form and accession linked to sec.gov, its dates and, for an 8-K, its items. */
function inboxFiling(filing) {
  if (!filing) return "";
  const items = list(filing.items);
  return h(
    "div",
    { class: "inbox-filing" },
    h(
      "p",
      null,
      externalLink(filing.url, [h("strong", { text: str(filing.form) }), ` ${str(filing.accession)}`]),
      ` · filed ${str(filing.filed_date)}`,
      str(filing.report_date) ? ` · report date ${filing.report_date}` : "",
    ),
    items.length
      ? h(
          "ul",
          { class: "inbox-filing-items" },
          items.map((it) => h("li", { "data-item-number": str(it.number) }, h("strong", { text: `Item ${str(it.number)}` }), ` ${str(it.title)}`, str(it.category) ? h("span", { class: "event-cat", text: ` (${it.category})` }) : "")),
        )
      : "",
  );
}

/** Does it bear on the thesis, and why: the rules, then each claim with its reasons and paragraphs. */
function inboxTriage(triage) {
  if (!triage) return "";
  const rules = list(triage.rules);
  const ruleLabels = state.watchMeta?.rule_labels ?? {};
  return h(
    "div",
    { class: "inbox-triage" },
    h(
      "p",
      { class: "triage-summary" },
      ruleMark("By rule, no model"),
      " ",
      str(triage.summary),
      rules.length ? h("span", { class: "triage-rules" }, " · ", rules.map((r) => str(ruleLabels[r]) || r).join(", ")) : "",
    ),
    h(
      "ul",
      { class: "triage-claims" },
      list(triage.claims).map((claim) =>
        h(
          "li",
          { "data-claim-id": str(claim.claim_id), "data-bears": String(claim.bears === true) },
          h(
            "p",
            { class: "triage-claim" },
            h("span", { class: "claim-id", text: str(claim.claim_id) }),
            " ",
            str(claim.claim),
            h("span", { class: claim.bears ? "bears is-yes" : "bears is-no", text: claim.bears ? " bears on it" : " does not bear on it" }),
          ),
          list(claim.reasons).length ? h("ul", { class: "triage-reasons" }, list(claim.reasons).map((r) => h("li", { text: String(r) }))) : "",
          list(claim.paragraphs).length
            ? h(
                "ul",
                { class: "triage-paragraphs" },
                list(claim.paragraphs).map((p) =>
                  h(
                    "li",
                    null,
                    // The record's own kind; "changed" has no mark of its own, so it keeps its word.
                    Object.hasOwn(CHANGE_MARK, p.kind) ? changeMark(p.kind) : h("span", { class: "chg-mark c-reworded" }, h("span", { class: "chg-label", text: capitalize(str(p.kind)) })),
                    ` ${str(p.item)}`,
                    h("blockquote", { class: "triage-paragraph", text: str(p.text) }),
                    list(p.matched_terms).length ? h("span", { class: "hint", text: `Shared words: ${list(p.matched_terms).join(", ")} · ` }) : "",
                    externalLink(p.link, "Open in the filing, at this paragraph"),
                  ),
                ),
              )
            : "",
        ),
      ),
    ),
    list(triage.notes).length ? h("ul", { class: "triage-notes" }, list(triage.notes).map((n) => h("li", { text: String(n) }))) : "",
  );
}

/** The run the filing caused: waiting (with the button), under way, finished or failed. */
function inboxRun(item, message) {
  const run = item.run;
  if (!run) return item.error ? limitLine("p", str(item.error)) : "";
  const openRun = run.run_id
    ? h("button", { type: "button", class: "secondary small", "data-open-run": run.run_id, onclick: () => openItemRun(item, message), text: run.state === "running" ? "Open the run under way" : "Open the run in the note" })
    : "";
  const parts = [];
  if (run.state === "waiting") {
    parts.push(
      h("p", { class: "waiting-reason", text: str(run.waiting_reason) }),
      h("button", { type: "button", class: "primary small", "data-run-now": str(item.id), onclick: (event) => runNow(item, event.currentTarget, message), text: "Run now (uses the model)" }),
    );
  } else {
    parts.push(
      h(
        "p",
        { class: "inbox-run-line" },
        "Run ",
        h("code", { text: str(run.run_id) || "—" }),
        run.status ? [" · ", h("span", { class: `status-word st-${token(run.status, STATUS_GLYPH)}` }, statusMark(run.status), ` ${capitalize(run.status)}`)] : run.state === "running" ? " · under way" : "",
        str(run.started_by) ? ` · started by ${run.started_by === "owner" ? "you, from the inbox" : "the watch"}` : "",
        " ",
        openRun,
      ),
    );
  }
  if (item.error) parts.push(limitLine("p", str(item.error)));
  return h("div", { class: `inbox-run r-${token(run.state, { waiting: 1, running: 1, finished: 1, failed: 1 })}` }, ...parts);
}

/** What the run changed: the record's line, the verdicts that moved, new cautions, notes and 8-Ks; the comparison one click away. */
function inboxMoved(moved) {
  if (!moved) return "";
  const parts = [h("p", { class: "moved-line", "data-moved": String(moved.moved === true), text: str(moved.line) })];
  const verdicts = list(moved.verdicts);
  if (verdicts.length) {
    parts.push(h("ul", { class: "moved-verdicts" }, verdicts.map((v) => h("li", null, h("span", { class: "moved-claim", text: str(v.claim) }), " ", verdictPill(v.before), h("span", { class: "moved-arrow", "aria-label": "became", text: " → " }), verdictPill(v.after)))));
  }
  for (const caution of list(moved.new_cautions)) parts.push(limitLine("p", h("strong", { text: "New caution: " }), `${str(caution.claim)} `, str(caution.text)));
  for (const note of list(moved.new_notes)) parts.push(h("p", { class: "moved-note" }, h("strong", { text: "New note on the 8-Ks: " }), `${str(note.claim)} `, str(note.text)));
  if (list(moved.new_events).length) {
    parts.push(h("p", { class: "moved-events" }, h("strong", { text: "New on the time line: " }), ...list(moved.new_events).flatMap((e, i) => [i ? "; " : "", externalLink(e.url, str(e.label) || str(e.accession)), list(e.items).length ? ` (Items ${list(e.items).join(", ")})` : ""])));
  }
  if (list(moved.claims).length) {
    const body = h("div", { class: "moved-compare-body" });
    parts.push(
      h(
        "details",
        { class: "moved-compare", ontoggle: (event) => event.currentTarget.open && !body.childElementCount && renderComparison(body, moved, null) },
        h("summary", { text: "Compare with the previous run, claim by claim" }),
        body,
      ),
    );
  }
  return h("div", { class: "inbox-moved" }, ...parts);
}

/** Open the run an item made in the note, with its comparison (the item's own) under the head. */
function openItemRun(item, message) {
  const runId = item.run?.run_id;
  if (!runId) return;
  if (state.sample) {
    setMessage(message, `Run ${runId} is not part of this sample: the scenario's runs are not recorded beside it.`);
    return;
  }
  state.itemComparison = item.moved && item.moved.later_run_id === runId ? item.moved : null;
  watchRun(runId);
}

/** Start a waiting run (it uses the model). 202: the run; 409: nothing waits any more, so the item is read again. */
async function runNow(item, button, message) {
  if (state.sample) {
    setMessage(message, "Sample: nothing is started. On a live inbox this starts the run, which uses the model.");
    return;
  }
  button.disabled = true;
  setMessage(message, "Starting the run…", "ok");
  try {
    const started = await api(`/api/inbox/${encodeURIComponent(item.id)}/run`, { method: "POST" });
    if (typeof started.id !== "string" || !started.id) throw new ApiError("the server did not return a run id", 0);
    await reloadItem(item.id, `Run ${started.id} started.`);
  } catch (error) {
    if (error.status === 409) {
      await reloadItem(item.id, `The run was not started: ${error.message}.`, true);
      return;
    }
    button.disabled = false;
    setMessage(message, `The run could not be started: ${error.status === 404 ? "this inbox item no longer exists" : refusal(error)}.`);
  }
}

/** Read one item again (after its run started, or after a 409) and draw it in its place. */
async function reloadItem(itemId, note, isError = false) {
  const slot = [...document.querySelectorAll("article.inbox-item")].find((node) => node.dataset.itemId === itemId);
  try {
    const fresh = await api(`/api/inbox/${encodeURIComponent(itemId)}`);
    const node = inboxItem(fresh);
    slot?.replaceWith(node);
    setMessage(node.querySelector(".watch-message"), note, isError ? "error" : "ok");
  } catch (error) {
    setMessage(slot?.querySelector(".watch-message"), `${note} The item could not be read again: ${refusal(error)}.`);
  }
  refreshWatchState();
}

/** Mark items read (or unread again); the answer carries the inbox's unread count. */
async function markRead(ids, read) {
  if (state.sample || ids.length === 0) return;
  try {
    const answer = await api("/api/inbox/read", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ids, read }) });
    if (Number.isFinite(answer.unread)) state.inboxUnread = answer.unread;
    renderInboxCount();
    loadInbox(state.inboxPage?.offset ?? 0);
  } catch (error) {
    setMessage(els.inboxMessage, `Could not mark ${ids.length === 1 ? "the item" : "the items"} ${read ? "read" : "unread"}: ${refusal(error)}.`);
  }
}

/** ?sample=inbox: the example payloads, drawn as a live inbox would be, with nothing sent. */
async function loadInboxSample(name) {
  const [page, watches, health, watchMeta] = await Promise.all([
    api(INBOX_SAMPLES[name], { cache: "no-store" }),
    api("sample-inbox-watches.json", { cache: "no-store" }),
    api("sample-inbox-health.json", { cache: "no-store" }),
    api("sample-inbox-meta.json", { cache: "no-store" }),
  ]);
  applyMeta(await api("/api/meta"), { sample: true });
  state.watchMeta = watchMeta;
  state.watches = new Map(list(watches.watches).map((w) => [w.thesis_id, w]));
  state.watchesLoaded = true;
  state.health = health;
  state.sampleNote = INBOX_SAMPLE_NOTE;
  els.formNote.textContent = `Sample mode: ${INBOX_SAMPLE_NOTE}`;
  showInboxView();
  renderHealth();
  renderInbox(page);
}

// ---------------------------------------------------------------- the first screen, the thesis drawer, the guide

/** Whether the first screen is showing: no run or other record, so the form is the page. */
function onFirstScreen() {
  return Boolean(els.empty) && !els.empty.hidden;
}

/** Lay the page out for the first screen or for a result, when the empty state appears or goes. */
function syncFirstScreen() {
  const first = onFirstScreen();
  document.body.classList.toggle("is-first", first);
  if (els.thesisButton) els.thesisButton.hidden = first;
  if (els.howtoButton) els.howtoButton.hidden = first;
  // On the first screen the guide's opening (what this is, the samples) is the page's lead.
  if (els.howto) setHowto(first);
  if (first) closeDrawer(false);
}

function setHowto(open) {
  els.howto.hidden = !open;
  els.howtoButton?.setAttribute("aria-expanded", String(open));
}

function toggleHowto() {
  setHowto(els.howto.hidden);
  if (!els.howto.hidden) els.howto.querySelector("a, button, summary")?.focus({ preventScroll: true });
}

function drawerOpen() {
  return document.body.classList.contains("drawer-open");
}

function openDrawer() {
  if (onFirstScreen() || !els.formPanel) return;
  document.body.classList.add("drawer-open");
  els.thesisButton?.setAttribute("aria-expanded", "true");
  if (els.drawerScrim) els.drawerScrim.hidden = false;
  els.decision?.focus({ preventScroll: true });
}

function closeDrawer(returnFocus = true) {
  if (!drawerOpen()) return;
  document.body.classList.remove("drawer-open");
  els.thesisButton?.setAttribute("aria-expanded", "false");
  if (els.drawerScrim) els.drawerScrim.hidden = true;
  if (returnFocus) els.thesisButton?.focus({ preventScroll: true });
}

function toggleDrawer() {
  if (drawerOpen()) closeDrawer();
  else openDrawer();
}

function initLayout() {
  if (!els.empty) return;
  new MutationObserver(syncFirstScreen).observe(els.empty, { attributes: true, attributeFilter: ["hidden"] });
  syncFirstScreen();
  els.thesisButton?.addEventListener("click", toggleDrawer);
  els.drawerClose?.addEventListener("click", () => closeDrawer());
  els.drawerScrim?.addEventListener("click", () => closeDrawer());
  els.howtoButton?.addEventListener("click", toggleHowto);
  els.inboxButton?.addEventListener("click", () => openInbox());
  els.keysHowto?.addEventListener("click", () => {
    els.keysDialog?.close?.();
    if (onFirstScreen()) return;
    setHowto(true);
    els.howto.scrollIntoView({ block: "start" });
  });
  // A refused field opens the drawer, so the reader sees what to fix.
  if (els.formErrors) new MutationObserver(() => !els.formErrors.hidden && openDrawer()).observe(els.formErrors, { attributes: true, attributeFilter: ["hidden"] });
}

// ---------------------------------------------------------------- theme, keys, print

/** The reader's stored theme, or "" when none is stored or the browser refuses storage. */
function storedTheme() {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return THEMES.includes(value) ? value : "";
  } catch {
    return "";
  }
}

function systemTheme() {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "terminal" : "paper";
}

/** ?theme=paper|terminal for this page load only (screenshots, a shared link); never stored. */
function urlTheme() {
  const value = new URLSearchParams(location.search).get("theme");
  return THEMES.includes(value) ? value : "";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  if (!els.themeToggle) return;
  const other = theme === "paper" ? "terminal" : "paper";
  els.themeToggle.setAttribute("aria-label", `Theme: ${THEME_NAMES[theme]}. Switch to ${THEME_NAMES[other]}`);
  els.themeToggle.dataset.theme = theme;
  if (state.timelineRun) drawTimeline(els.timeline, state.timelineRun);
}

/** Switch theme and remember the choice when the browser lets the page store it. */
function toggleTheme() {
  const now = document.documentElement.getAttribute("data-theme") === "terminal" ? "terminal" : "paper";
  const next = now === "paper" ? "terminal" : "paper";
  try {
    window.localStorage.setItem(THEME_KEY, next);
  } catch {
    // Storage refused (a private window, a sandbox): the switch still holds for this page.
  }
  applyTheme(next);
}

function initTheme() {
  applyTheme(urlTheme() || storedTheme() || systemTheme());
  els.themeToggle?.addEventListener("click", toggleTheme);
  // With no stored choice, follow the system when it changes.
  window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
    if (!urlTheme() && !storedTheme()) applyTheme(systemTheme());
  });
}

/** Whether a key press belongs to a field the reader is typing in. */
function typing(target) {
  if (!(target instanceof Element)) return false;
  return Boolean(target.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']"));
}

/** Move the focus to the next (+1) or previous (-1) claim's docket, from the one in focus or in view. */
function moveClaim(step) {
  const dockets = [...document.querySelectorAll("#claim-list details.claim")];
  if (dockets.length === 0) return;
  const active = document.activeElement?.closest?.("details.claim");
  let index = dockets.indexOf(active);
  if (index < 0) {
    // From the first docket whose top is below the top of the window.
    const below = dockets.findIndex((d) => d.getBoundingClientRect().top > 8);
    index = step > 0 ? (below < 0 ? dockets.length - 1 : below - 1) : below < 0 ? dockets.length : below;
  }
  const next = dockets[Math.max(0, Math.min(dockets.length - 1, index + step))];
  const summary = next.querySelector("summary");
  summary.focus({ preventScroll: true });
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  next.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
}

function openKeys() {
  if (!els.keysDialog) return;
  if (typeof els.keysDialog.showModal === "function") {
    if (!els.keysDialog.open) els.keysDialog.showModal();
  } else {
    els.keysDialog.setAttribute("open", "");
  }
}

/** The page's keys: / ticker, j and k claims, t theme, ? the list. Ignored while typing or with a modifier. */
function onKey(event) {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.key === "Escape" && drawerOpen()) {
    event.preventDefault();
    closeDrawer();
    return;
  }
  if (typing(event.target)) {
    if (event.key === "Escape" && event.target === els.ticker) els.ticker.blur();
    return;
  }
  if (els.keysDialog?.open && event.key !== "Escape") return;
  switch (event.key) {
    case "/":
      event.preventDefault();
      els.ticker?.focus();
      els.ticker?.select();
      break;
    case "j":
      event.preventDefault();
      moveClaim(1);
      break;
    case "k":
      event.preventDefault();
      moveClaim(-1);
      break;
    case "t":
      event.preventDefault();
      toggleTheme();
      break;
    case "i":
      event.preventDefault();
      openInbox();
      break;
    case "e":
      if (onFirstScreen()) break;
      event.preventDefault();
      toggleDrawer();
      break;
    case "?":
      event.preventDefault();
      openKeys();
      break;
    default:
      break;
  }
}

/** Printing opens every closed disclosure so the note prints whole, and closes them after. */
const printOpened = [];
function beforePrint() {
  for (const node of document.querySelectorAll("#result-panel details:not([open])")) {
    node.open = true;
    printOpened.push(node);
  }
}
function afterPrint() {
  while (printOpened.length) printOpened.pop().open = false;
}

/** Redraw the time line when the note changes width (a resized window, a rotated phone). */
function watchTimelineWidth() {
  if (!els.timeline || typeof ResizeObserver !== "function") return;
  let frame = 0;
  new ResizeObserver(() => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      if (!state.timelineRun || els.timelineSection.hidden) return;
      const width = Math.round(els.timeline.clientWidth);
      if (Math.abs(width - Number(els.timeline.dataset.width || 0)) > 4) drawTimeline(els.timeline, state.timelineRun);
    });
  }).observe(els.timeline);
}

function initChrome() {
  initTheme();
  initLayout();
  document.addEventListener("keydown", onKey);
  els.keysButton?.addEventListener("click", openKeys);
  window.addEventListener("beforeprint", beforePrint);
  window.addEventListener("afterprint", afterPrint);
  watchTimelineWidth();
}

function init() {
  if (document.body.dataset.page === "specimen") {
    initSpecimen();
    return;
  }
  initChrome();
  els.form.addEventListener("submit", onSubmit);
  els.figuresOnly.addEventListener("click", onFiguresOnly);
  els.filingChanges.addEventListener("click", onFilingChanges);
  els.breakdowns.addEventListener("click", onBreakdowns);
  els.example.addEventListener("click", loadExample);
  els.saveThesis.addEventListener("click", () => toggleSavePanel(els.savePanel.hidden));
  els.saveConfirm.addEventListener("click", onSaveThesis);
  els.saveCancel.addEventListener("click", () => toggleSavePanel(false));
  els.thesisName.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      onSaveThesis();
    }
  });
  els.runAgain.addEventListener("click", onRunAgain);
  els.claims.addEventListener("input", updateCounts);
  els.decision.addEventListener("input", updateCounts);
  for (const field of Object.keys(FIELD_NAMES)) {
    $(field).addEventListener("input", () => setFieldError(field, []));
  }
  window.addEventListener("hashchange", openClaimChangesFromHash);
  const params = new URLSearchParams(location.search);
  state.sample = params.has("sample");
  if (state.sample) {
    setFormEnabled(false);
    loadSample(params.get("sample") || "run");
    return;
  }
  window.addEventListener("hashchange", openHashTarget);
  loadMeta();
  refreshRecent();
  refreshTheses();
  startWatchPolling();
  openHashTarget();
}

init();
