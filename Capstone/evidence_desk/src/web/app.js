// Evidence Desk frontend (version 5).
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
//   ! red     your input was rejected
//   verdicts  ✓ supported, ✕ challenged, ± mixed, ? unjudged, ∅ not addressed
//   stances   reuse ✓ and ✕; context is •
//   decisions ▣ accepted, ☒ rejected (dark, inverted tag: the reader's own);
//             ☐ undecided is dashed, because the verdict after review is provisional
//   changes   between two filings (`/api/companies/{ticker}/changes`), cyan, square tags:
//             # numbers only, ~ reworded, + added, − removed; inside a reworded
//             paragraph, added words are underlined and removed ones struck through

"use strict";

const POLL_MS = 1500;

/** Pipeline stages in order, with the words shown on the progress line. */
const STAGES = [
  ["queued", "Queued"],
  ["company", "Company"],
  ["filings", "Filings"],
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
const STATUS_GLYPH = { running: "⋯", complete: "■", partial: "▲", failed: "▲" };
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
};

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
  claimList: $("claim-list"),
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

/** ! red: your input was rejected. */
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
  return h("span", { class: LIMITING_STATUS.has(status) ? "glyph g-limit" : "glyph", "aria-hidden": "true", text: glyph });
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
    const message = typeof payload?.error === "string" ? payload.error : `the server answered HTTP ${response.status}`;
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

function applyMeta(meta) {
  if (!meta || typeof meta !== "object" || !meta.limits) throw new ApiError("the wording and limits are missing", 0);
  state.meta = meta;
  const limits = meta.limits;
  const engine = str(meta.engine);
  // `checker` is absent from servers older than the meaning check: then nothing is said about it.
  const checker = meta.checker && typeof meta.checker === "object" ? meta.checker : null;
  const checkerName = str(checker?.name);
  let checkerText = "";
  if (checker) {
    checkerText = checkerName && checkerName !== "none"
      ? ` Configured meaning check: ${str(checker.detail) || checkerName}.`
      : " No second model is configured to check meaning.";
  }
  els.engineLine.replaceChildren(
    h("span", { class: "engine-name", text: `Configured engine: ${engine || "not stated"}` }),
    ENGINE_GLOSS[engine] ? ` (${ENGINE_GLOSS[engine]}). Each result names the engine that actually did the work.` : "",
    checkerText,
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
  els.advanced.open = Boolean(example.scope_notes || list(example.extra_urls).length);
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
  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = true;
  els.thesisView.hidden = true;
  els.changesView.hidden = true;
  els.figuresView.hidden = false;
  document.body.classList.add("has-run");
  els.figuresHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      h(
        "p",
        { class: "company" },
        h("strong", { text: str(report.company) || "Company" }),
        Number.isFinite(report.cik) ? h("span", { class: "muted small" }, " · ", h("abbr", { title: "The SEC's numeric identifier for this company", text: "CIK" }), ` ${report.cik}`) : "",
      ),
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
  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = true;
  els.figuresView.hidden = true;
  els.thesisView.hidden = true;
  els.changesView.hidden = false;
  document.body.classList.add("has-run");

  const company = record.company ?? {};
  els.changesHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      h(
        "p",
        { class: "company" },
        state.sample ? h("span", { class: "page-tag inline", text: "Sample record" }) : "",
        h("strong", { text: str(company.ticker) || "Company" }),
        str(company.name) ? ` · ${company.name}` : "",
        Number.isFinite(company.cik) ? h("span", { class: "muted small" }, " · ", h("abbr", { title: "The SEC's numeric identifier for this company", text: "CIK" }), ` ${company.cik}`) : "",
      ),
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
      "Each paragraph is matched with the other filing's paragraphs in the same Item. Unchanged: the same text, perhaps moved within its Item. ",
      changeMark("numbers_only"),
      ": the same once numbers, dates and amounts are set aside. ",
      changeMark("reworded"),
      ": a paragraph in the later filing that mostly matches one in the earlier. ",
      changeMark("added"),
      " and ",
      changeMark("removed"),
      ": a paragraph with no counterpart in the other filing. Short lines and table rows found in only one filing are counted, not listed.",
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
        "ul",
        { class: "chg-totals" },
        h("li", null, total("unchanged"), " unchanged"),
        ["numbers_only", "reworded", "added", "removed"].map((kind) => h("li", null, total(kind), " ", changeMark(kind))),
        h("li", { class: "chg-minor" }, "Short lines and table rows: ", total("minor_added"), " added, ", total("minor_removed"), " removed"),
      ),
    ),
  );
  const items = record.items;
  // The first Item that lists any paragraph starts open, so a reader sees one example of each list.
  const listed = (item) => list(item.added_paragraphs).length + list(item.removed_paragraphs).length + list(item.reworded_paragraphs).length > 0;
  const firstOpen = items.findIndex(listed);
  parts.push(
    h(
      "section",
      { class: "block", "aria-labelledby": "chg-items-title" },
      h("h3", { class: "block-title", id: "chg-items-title", text: "By Item" }),
      h("p", { class: "hint", text: "Open an Item to read what was added, removed and reworded in it." }),
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

/** One Item: its five counts as a row, opening to its three lists. */
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
      h(
        "span",
        { class: "chg-minor" },
        "Short lines and table rows: ",
        h("span", { "data-chg-field": "minor_added", text: num(item.minor_added) }),
        " added, ",
        h("span", { "data-chg-field": "minor_removed", text: num(item.minor_removed) }),
        " removed",
      ),
    ),
    CHANGE_COUNTS.map(cell),
  );
  return h("details", { class: "chg-item", "data-item-index": index, "data-item": str(item.item), open }, summary, renderChangeLists(item));
}

/** An Item's added, removed and reworded paragraphs, each list with its truncation as the record states it. */
function renderChangeLists(item) {
  const body = h("div", { class: "chg-lists" });
  const added = list(item.added_paragraphs);
  const removed = list(item.removed_paragraphs);
  const reworded = list(item.reworded_paragraphs);
  if (!added.length && !removed.length && !reworded.length) {
    body.append(h("p", { class: "muted", text: "No paragraph was added, removed or reworded in this Item." }));
    return body;
  }
  const cut = item.truncated ?? {};
  if (added.length) body.append(changeList("added", "Added in the later filing", added, item.added, cut.added, (p) => paragraphEntry(p, "Open in the later filing, at this paragraph")));
  if (removed.length) body.append(changeList("removed", "Removed from the earlier filing", removed, item.removed, cut.removed, (p) => paragraphEntry(p, "Open in the earlier filing, at this paragraph")));
  if (reworded.length) body.append(changeList("reworded", "Reworded: the later paragraph, with the words it added and dropped", reworded, item.reworded, cut.reworded, rewordedEntry));
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

/** An added or removed paragraph: its text, where it sits, and a link into its filing. */
function paragraphEntry(paragraph, linkText) {
  return h(
    "li",
    null,
    h("p", { class: "chg-text", text: str(paragraph.text) }),
    h("p", { class: "chg-where" }, h("span", { class: "label", text: "Located under: " }), str(paragraph.locator) || "location not recorded", " · ", externalLink(paragraph.link, linkText)),
  );
}

/** A reworded pair: the later paragraph drawn from `segments`, in reading order, then the record's similarity. */
function rewordedEntry(pair) {
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
    quote,
    h(
      "p",
      { class: "chg-where" },
      h("span", { class: "label", text: "Word overlap with the earlier paragraph (Jaccard similarity, 0 to 1): " }),
      h("span", { "data-similarity": "", text: Number.isFinite(pair.similarity) ? String(pair.similarity) : "not recorded" }),
      " · ",
      h("span", { class: "label", text: "Located under: " }),
      str(pair.after?.locator) || "location not recorded",
      " · ",
      externalLink(pair.after?.link, "Open in the later filing"),
      " · ",
      externalLink(pair.before?.link, "Open the earlier paragraph"),
    ),
  );
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
    );
    els.theses.append(h("li", null, button));
  }
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
  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = true;
  els.figuresView.hidden = true;
  els.changesView.hidden = true;
  els.thesisView.hidden = false;
  document.body.classList.add("has-run");
  const request = thesis.request ?? {};
  const claims = list(request.claims);
  els.thesisHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      h("p", { class: "company" }, h("span", { class: "label", text: "Saved thesis: " }), h("strong", { text: str(thesis.name) })),
      h("p", { class: "decision" }, h("span", { class: "label", text: "Decision: " }), str(request.decision)),
      h("p", { class: "run-meta", text: `${str(request.ticker)} · ${plural(claims.length, "claim", "claims")} · ${plural(request.filings, "filing", "filings")} per run · saved ${utc(thesis.created_at)}` }),
      h("ol", { class: "thesis-claims" }, claims.map((claim) => h("li", { text: String(claim) }))),
    ),
  );
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
  if (str(comparison.note)) container.append(h("p", { class: "changes-note", text: comparison.note }));
  container.append(
    h(
      "p",
      { class: "changes-runs" },
      h("span", { class: "count-value", "data-cmp": "verdicts_moved", text: num(comparison.verdicts_moved) }),
      " of ",
      h("span", { class: "count-value", "data-cmp": "claims_total", text: num(comparison.claims_total) }),
      ` ${unit(comparison.claims_total, "verdict", "verdicts")} moved. Earlier run `,
      runRef(comparison.earlier_run_id, currentRunId),
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
  container.append(h("div", { class: "changes-filings-wrap" }, filings("New filings in the later run", comparison.sources_added, "added"), filings("Filings the later run no longer read", comparison.sources_dropped, "dropped")));
}

/** In the run view: what moved, when the comparison's later run is this run. */
function renderRunChanges(run) {
  const comparison = state.comparison;
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
        : h("p", null, h("a", { class: "download", href: `/api/runs/${encodeURIComponent(run.id)}/export.md?reviewed=true`, download: `evidence-desk-${run.id}-reviewed.md`, text: "Download reviewed brief" })),
    );
  }
  els.reviewLine.replaceChildren(...parts);
}

/** The "After your review" cell of a scorecard row, from the Review's claim entry. */
function reviewedSlot(entry) {
  const verdict = entry?.reviewed_verdict ?? null;
  const slot = h("span", { class: "verdict-slot slot-reviewed", "data-reviewed-verdict": verdict ?? "none" }, h("span", { class: "slot-label", text: "After your review" }));
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
  els.thesisView.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  document.body.classList.remove("has-run");
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
  els.sampleTag.hidden = false;
  els.formNote.textContent = "Sample mode: this page shows a stored record and does not start runs. Open the page without ?sample to test a thesis.";
  els.formNote.hidden = false;
  els.recent.replaceChildren(h("li", { class: "muted", text: "Recent runs are not loaded in sample mode." }));
  els.thesesBlock.hidden = false;
  els.theses.replaceChildren(h("li", { class: "muted", text: "Saved theses are not loaded in sample mode." }));
  els.saveThesis.hidden = false;
  const link = $("sample-link");
  link.textContent = "Leave the sample";
  link.href = location.pathname;
  $("synthetic-link").hidden = true;
  $("changes-link").hidden = true;
  hideRunView();
  if (!SAMPLE_NAME.test(name)) {
    showLoadError("That sample name is not valid: use lower-case letters, digits and hyphens.", null);
    return;
  }
  try {
    const payload = await api(`sample-${name}.json`, { cache: "no-store" });
    // A recorded filing comparison ({note, changes}) has no run and needs no wording from /api/meta.
    if (payload.changes && !payload.run) {
      if (str(payload.note)) els.formNote.textContent = `Sample mode: ${payload.note} This page does not look anything up; open it without ?sample to compare a company's filings.`;
      renderChanges(payload.changes, str(payload.note));
      return;
    }
    if (!payload.meta || !payload.run) throw new ApiError("the file has no meta or run", 0);
    applyMeta(payload.meta);
    if (str(payload.note)) els.formNote.textContent = `Sample mode: ${payload.note} This page does not start runs; open it without ?sample to test a thesis.`;
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
  els.thesisView.hidden = true;
  els.runView.hidden = false;
  document.body.classList.add("has-run");
  state.run = run;

  renderBanner(run);
  renderStages(run);
  renderHead(run);
  renderReviewLine(run);
  renderScorecard(run);
  renderDistinction(run);
  renderRunChanges(run);
  renderSummary(run);
  renderRunFigures(run);
  renderClaims(run, ctx);
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
        " rejected",
        foundField === "quotes_found" ? ["; ", cov(c, "excerpts_verified"), " kept as evidence of verified findings"] : "",
      ),
    );
    if (Number.isFinite(c.metrics_computed)) {
      facts.push(h("li", null, cov(c, "metrics_computed"), ` reported ${unit(c.metrics_computed, "figure", "figures")} computed`));
    }
    if (Number.isFinite(c.numbers_checked)) {
      facts.push(h("li", null, cov(c, "numbers_checked"), ` ${unit(c.numbers_checked, "number", "numbers")} in findings checked, `, cov(c, "numbers_unmatched"), " unmatched"));
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

function renderHead(run) {
  const company = run.company;
  const inputs = run.inputs ?? {};
  const title = h(
    "p",
    { class: "company" },
    h("strong", { text: company?.ticker ?? inputs.ticker ?? "" }),
    company ? ` · ${company.name}` : "",
    company ? h("span", { class: "muted small" }, " · ", h("abbr", { title: "The SEC's numeric identifier for this company", text: "CIK" }), ` ${company.cik}`) : "",
  );
  const decision = h("p", { class: "decision" }, h("span", { class: "label", text: "Decision: " }), inputs.decision ?? "");
  const engine = str(run.engine);
  const engineLine = h(
    "p",
    { class: "run-engine" },
    h("span", { class: "label", text: "Engine that did the work: " }),
    h("span", { class: "engine-used", text: engine || "not recorded" }),
    str(run.engine_detail) ? h("span", { class: "engine-detail", text: ` — ${run.engine_detail}` }) : "",
  );
  const checkerLine = runMeaningChecked(run)
    ? h("p", { class: "run-engine run-checker" }, h("span", { class: "label", text: "Meaning checked by: " }), h("span", { class: "checker-used", text: str(run.checker_detail) || str(run.checker) }))
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
    download = h("a", { class: "download", href: `/api/runs/${encodeURIComponent(run.id)}/export.md`, download: `evidence-desk-${run.id}.md`, text: "Download Markdown brief" });
  }
  els.runHead.replaceChildren(h("div", { class: "run-head-main" }, title, decision, engineLine, checkerLine, details, thesisLine(run)), h("div", { class: "run-head-actions" }, download));
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
  claims.forEach((claim, index) => {
    const verdicts = review
      ? h(
          "span",
          { class: "score-verdicts" },
          h("span", { class: "verdict-slot slot-engine" }, h("span", { class: "slot-label", text: "Engine" }), verdictPill(claim.verdict)),
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
const DISTINCTION_DEFAULT = els.distinction.cloneNode(true);

/** The note under the verdicts: what was checked, and by whom, for this run. */
function renderDistinction(run) {
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
    const details = h(
      "details",
      { class: "claim", id, open: open.has(id) },
      h("summary", null, verdictPill(claim.verdict), h("span", { class: "claim-id", text: claim.id }), h("span", { class: "claim-text", text: claim.text })),
      body,
    );
    els.claimList.append(details);
  });
}

/** One finding: stance, statement, the engine's reason, its checks, cited figures and quotes. */
function renderFinding(finding, ctx, withheld = false) {
  const stance = token(finding.stance, STANCE_MARK);
  const model = modelAssessed(ctx.claims.get(finding.claim_id));
  const badge = meaningRead(finding) ? MODEL_BADGE_READ : MODEL_BADGE;
  const article = h(
    "article",
    { class: `finding s-${stance}${withheld ? " is-withheld" : ""}`, "data-finding-id": finding.id },
    h(
      "header",
      { class: "finding-head" },
      stancePill(finding.stance),
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
  if (counted) article.append(counted);
  if (withheld) {
    // A finding the second model rejected keeps that model's own words, tagged for the browser test.
    const reason = str(finding.withheld_reason) || "no quote was found in the filing text.";
    const byMeaning = str(finding.checks?.support) === "failed";
    article.append(limitLine("p", h("strong", { text: "Withheld: " }), byMeaning ? h("span", { "data-withheld-reason": "", text: reason }) : reason));
  }
  if (finding.rationale) {
    article.append(writtenField("p", `finding:${finding.id}:reason`, model, [h("span", { class: "label", text: "Engine's reason: " }), finding.rationale], badge));
  }
  const checks = renderChecks(finding.checks);
  if (checks) article.append(checks);
  const cited = renderCitedFigures(finding.metric_ids, ctx.metrics);
  if (cited) article.append(cited);
  for (const evidenceId of list(finding.evidence_ids)) {
    const item = ctx.evidence.get(evidenceId);
    if (!item) {
      article.append(h("p", { class: "muted", text: `Excerpt ${evidenceId} is listed but missing from the record.` }));
      continue;
    }
    article.append(renderEvidence(item, ctx.sources.get(item.source_id)));
  }
  if (!withheld && finding.verified !== false) {
    article.append(h("div", { class: "review-slot", "data-review-finding": finding.id, hidden: true }));
  }
  return article;
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

  // Agreeing only in part is a result the reader must weigh, so its reason is shown in the open.
  const partly = support === "partly" ? checkerReason(reason || "no reason was recorded.", "data-support-detail") : "";
  return h("div", { class: "checks" }, h("span", { class: "label", text: "Checks: " }), h("ul", { class: "check-list" }, items), partly);
}

/** The reported figures a finding cites, resolved against `run.metrics`. */
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
        return h(
          "li",
          { "data-cited-metric": id },
          `${metric.label} · ${metric.period_label} · `,
          h("span", { class: "fig-value", text: metric.display }),
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
  if (byMeaning.length === 0) {
    els.withheld.replaceChildren(h("ul", { class: "withheld-list" }, byChecks.map(item)));
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
  els.withheld.replaceChildren(
    byChecks.length ? group("checks", "Withheld for a quote or a number", "A quote was not found in the filing, a number did not match, or nothing could be checked.", byChecks) : "",
    group("meaning", "Withheld by the meaning check", "A second model read the quoted evidence and judged that it does not support the statement. That too is a model's reading: read the quote before you dismiss the finding.", byMeaning),
  );
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
    for (const [kind, heading] of columns) {
      const end = latestEnd(metrics, kind);
      if (!end) continue;
      const rows = metrics.filter((m) => (m.period === kind || m.period === "instant") && m.period_end === end);
      const periodLabel = rows.find((m) => m.period === kind)?.period_label ?? end;
      grid.append(
        h(
          "section",
          { class: "fig-col", "aria-label": `${heading}: ${periodLabel}` },
          h("h4", { class: "fig-head" }, periodLabel, h("span", { class: "muted small", text: ` · ${heading.toLowerCase()}` })),
          h("ul", { class: "fig-list" }, rows.map(figureRow)),
        ),
      );
    }
    container.append(grid, h("p", { class: "hint", text: "Open a figure to see its arithmetic and the reported values it used." }));
  }
  if (notes.length) {
    const notesList = h("ul", { class: "mark-list" });
    fillList(notesList, notes, "", true);
    container.append(h("div", { class: "fig-notes" }, h("p", { class: "label", text: "Notes on the figures" }), notesList));
  }
  const charts = renderCharts(list(data.series));
  if (charts) container.append(charts);
}

function figureRow(metric) {
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
      { class: "fig-row", "data-metric-id": metric.id },
      h(
        "summary",
        null,
        h("span", { class: "fig-label" }, metric.label, metric.period === "instant" ? h("span", { class: "muted small", text: ` · ${metric.period_label}` }) : ""),
        h("span", { class: metric.value === null ? "fig-value is-missing" : "fig-value", text: metric.display }),
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
}

function init() {
  els.form.addEventListener("submit", onSubmit);
  els.figuresOnly.addEventListener("click", onFiguresOnly);
  els.filingChanges.addEventListener("click", onFilingChanges);
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
  openHashTarget();
}

init();
