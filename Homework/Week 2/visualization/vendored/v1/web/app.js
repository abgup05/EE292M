// Evidence Desk frontend: validates input for immediate feedback, starts a run,
// polls its status and renders the structured brief the backend returns.
// It draws and handles interaction only; every result comes from the API.

"use strict";

const LIMITS = {
  question: [20, 2000],
  decision: [10, 500],
  scope_notes: [0, 5000],
  seed_urls: 20,
  source_budget: [6, 15],
};

const EXAMPLE = {
  question:
    "What opportunities and risks should an organization examine before using generative AI in internal workflows?",
  decision: "Whether to investigate a limited internal pilot",
  scope_notes: "Public evidence; distinguish documented findings from open questions.",
  seed_urls: [
    "https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10",
    "https://www.gao.gov/products/gao-24-106946",
  ],
  source_budget: 10,
};

const STATUS_TEXT = {
  running: "RUNNING - retrieving sources and verifying citations.",
  complete: "COMPLETE - all acceptance conditions were met.",
  partial: "PARTIAL - evidence is incomplete; read the coverage limits before relying on this brief.",
  failed: "FAILED - no usable source; no answer was produced.",
};

const form = document.getElementById("research-form");
const formErrors = document.getElementById("form-errors");
const submitButton = document.getElementById("submit");
const resultPanel = document.getElementById("result-panel");
let pollTimer = null;
let currentRunId = null;

function $(id) {
  return document.getElementById(id);
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function fillList(id, items, empty) {
  const list = $(id);
  list.replaceChildren();
  if (!items || items.length === 0) {
    list.appendChild(el("li", empty, "muted"));
    return;
  }
  for (const item of items) list.appendChild(el("li", item));
}

function readForm() {
  const seedLines = $("seed_urls")
    .value.split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  const budget = $("source_budget").value.trim();
  return {
    question: $("question").value.trim(),
    decision: $("decision").value.trim(),
    scope_notes: $("scope_notes").value.trim(),
    seed_urls: seedLines,
    source_budget: budget === "" ? null : Number(budget),
  };
}

function looksLikePublicHttpUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch (error) {
    return false;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return false;
  if (!url.hostname || url.username || url.password) return false;
  const host = url.hostname.toLowerCase();
  if (host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local")) return false;
  if (/^(127\.|10\.|192\.168\.|169\.254\.|0\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host)) return false;
  if (host === "[::1]" || host.startsWith("[fc") || host.startsWith("[fd") || host.startsWith("[fe80")) return false;
  return true;
}

function validate(body) {
  const errors = [];
  const [qMin, qMax] = LIMITS.question;
  if (body.question.length < qMin || body.question.length > qMax) {
    errors.push(`Question must be ${qMin}-${qMax} characters (currently ${body.question.length}).`);
  }
  const [dMin, dMax] = LIMITS.decision;
  if (body.decision.length < dMin || body.decision.length > dMax) {
    errors.push(`Decision must be ${dMin}-${dMax} characters (currently ${body.decision.length}).`);
  }
  if (body.scope_notes.length > LIMITS.scope_notes[1]) {
    errors.push(`Scope notes must be at most ${LIMITS.scope_notes[1]} characters.`);
  }
  if (body.seed_urls.length > LIMITS.seed_urls) {
    errors.push(`At most ${LIMITS.seed_urls} seed URLs.`);
  }
  const seen = new Set();
  for (const url of body.seed_urls) {
    if (!looksLikePublicHttpUrl(url)) errors.push(`Not a public http(s) URL: ${url}`);
    const key = url.toLowerCase().replace(/\/+$/, "");
    if (seen.has(key)) errors.push(`Duplicate seed URL: ${url}`);
    seen.add(key);
  }
  const [bMin, bMax] = LIMITS.source_budget;
  if (!Number.isInteger(body.source_budget) || body.source_budget < bMin || body.source_budget > bMax) {
    errors.push(`Source budget must be a whole number from ${bMin} to ${bMax}.`);
  }
  return errors;
}

function showFormErrors(errors) {
  formErrors.replaceChildren();
  for (const message of errors) formErrors.appendChild(el("li", message));
  formErrors.hidden = errors.length === 0;
}

async function startRun(body) {
  const response = await fetch("/api/research", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const details = (payload.details || []).map((d) => `${d.field}: ${d.message}`);
    throw new Error([payload.error || `HTTP ${response.status}`, ...details].join(" - "));
  }
  return payload.id;
}

async function loadRun(runId) {
  const response = await fetch(`/api/research/${encodeURIComponent(runId)}`);
  if (!response.ok) throw new Error(`Run ${runId}: HTTP ${response.status}`);
  return response.json();
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function watchRun(runId) {
  stopPolling();
  currentRunId = runId;
  const tick = async () => {
    try {
      const run = await loadRun(runId);
      if (currentRunId !== runId) return; // a newer selection replaced this one
      render(run);
      if (run.status === "running") pollTimer = setTimeout(tick, 1500);
      else refreshRecent();
    } catch (error) {
      showBanner("failed", `Could not load run: ${error.message}`);
    }
  };
  tick();
}

function showBanner(status, text) {
  const banner = $("status-banner");
  banner.textContent = text;
  banner.className = `banner banner-${status}`;
  resultPanel.hidden = false;
}

function utc(iso) {
  if (!iso) return "n/a";
  return iso.replace("T", " ").replace(/\.\d+/, "").replace(/\+00:00$|Z$/, " UTC");
}

function render(run) {
  showBanner(run.status, STATUS_TEXT[run.status] || run.status);
  const meta = $("run-meta");
  meta.replaceChildren();
  meta.appendChild(el("div", `Run ${run.id} - synthesizer: ${run.synthesizer}`));
  meta.appendChild(el("div", `Started ${utc(run.started_at)}; finished ${utc(run.finished_at)}`));
  meta.appendChild(el("div", `Question: ${run.inputs.question}`));
  meta.appendChild(el("div", `Decision: ${run.inputs.decision}`));
  if (run.status !== "running") {
    const link = el("a", "Download Markdown brief");
    link.href = `/api/research/${encodeURIComponent(run.id)}/export.md`;
    link.className = "export";
    meta.appendChild(link);
  }

  const brief = run.brief;
  $("direct-answer").textContent = brief ? brief.direct_answer : run.status === "running" ? "Working..." : "No answer: the run did not produce a verified brief.";

  const sources = new Map(run.sources.map((s) => [s.id, s]));
  const evidence = new Map(run.evidence.map((e) => [e.id, e]));
  const findings = $("findings");
  findings.replaceChildren();
  const list = brief ? brief.findings : [];
  if (list.length === 0) {
    findings.appendChild(el("p", run.status === "running" ? "" : "No finding passed citation verification.", "muted"));
  }
  list.forEach((finding, index) => {
    const card = el("article", null, "finding");
    card.appendChild(el("h3", `${index + 1}. ${finding.statement}`));
    const tags = el("div", null, "tags");
    tags.appendChild(el("span", `confidence: ${finding.confidence}`, `tag tag-${finding.confidence}`));
    tags.appendChild(el("span", finding.verified ? "citation verified" : "unverified", "tag tag-verified"));
    if (finding.single_source) tags.appendChild(el("span", "single source", "tag tag-warn"));
    card.appendChild(tags);
    card.appendChild(el("p", finding.rationale, "rationale"));
    for (const evidenceId of finding.evidence_ids) {
      const item = evidence.get(evidenceId);
      if (!item) continue;
      const source = sources.get(item.source_id);
      const block = el("div", null, `evidence stance-${item.stance}`);
      const head = el("div", null, "evidence-head");
      head.appendChild(el("span", item.stance, "stance"));
      head.appendChild(el("span", ` - section "${item.locator}" - `));
      const link = el("a", source ? source.title || source.canonical_url : item.source_id);
      link.href = source ? source.canonical_url : "#";
      link.target = "_blank";
      link.rel = "noopener";
      head.appendChild(link);
      block.appendChild(head);
      block.appendChild(el("blockquote", item.excerpt));
      card.appendChild(block);
    }
    findings.appendChild(card);
  });
  if (run.unsupported_findings && run.unsupported_findings.length > 0) {
    const withheld = el("div", null, "withheld");
    withheld.appendChild(el("h3", "Withheld: findings without a verified citation"));
    for (const finding of run.unsupported_findings) withheld.appendChild(el("p", finding.statement));
    findings.appendChild(withheld);
  }

  fillList("disagreements", brief ? brief.disagreements : [], "No conflicting evidence was identified.");
  fillList("unknowns", brief ? brief.unknowns : [], "None recorded.");
  fillList("next-steps", brief ? brief.next_steps : [], "None recorded.");
  fillList(
    "subquestions",
    run.subquestions.map((s) => `[${s.status}] ${s.text} (query: ${s.search_query})`),
    "Not planned yet.",
  );
  fillList("coverage", run.coverage_limits, "None recorded.");
  fillList("run-errors", run.errors, "None.");

  const tbody = $("sources").querySelector("tbody");
  tbody.replaceChildren();
  for (const source of run.sources) {
    const row = document.createElement("tr");
    row.appendChild(el("td", source.id));
    const titleCell = document.createElement("td");
    const link = el("a", source.title || source.requested_url);
    link.href = source.canonical_url;
    link.target = "_blank";
    link.rel = "noopener";
    titleCell.appendChild(link);
    row.appendChild(titleCell);
    row.appendChild(el("td", source.publisher || "-"));
    row.appendChild(el("td", source.published_date || "not available"));
    row.appendChild(el("td", utc(source.retrieved_at)));
    row.appendChild(el("td", source.extraction_status === "extracted" ? "extracted" : `failed: ${source.error}`));
    tbody.appendChild(row);
  }
}

async function refreshRecent() {
  try {
    const response = await fetch("/api/research");
    const payload = await response.json();
    const recent = $("recent");
    recent.replaceChildren();
    if (payload.runs.length === 0) recent.appendChild(el("li", "No runs yet.", "muted"));
    for (const run of payload.runs) {
      const item = el("li");
      const button = el("button", `${run.status.toUpperCase()} - ${run.question}`, "link");
      button.type = "button";
      button.addEventListener("click", () => watchRun(run.id));
      item.appendChild(button);
      item.appendChild(el("span", ` ${utc(run.started_at)}`, "muted"));
      recent.appendChild(item);
    }
  } catch (error) {
    // The list is a convenience; a failure here must not hide the form.
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = readForm();
  const errors = validate(body);
  showFormErrors(errors);
  if (errors.length > 0) return;
  submitButton.disabled = true;
  try {
    const runId = await startRun(body);
    watchRun(runId);
  } catch (error) {
    showFormErrors([error.message]);
  } finally {
    submitButton.disabled = false;
  }
});

$("load-example").addEventListener("click", () => {
  $("question").value = EXAMPLE.question;
  $("decision").value = EXAMPLE.decision;
  $("scope_notes").value = EXAMPLE.scope_notes;
  $("seed_urls").value = EXAMPLE.seed_urls.join("\n");
  $("source_budget").value = String(EXAMPLE.source_budget);
  showFormErrors([]);
});

refreshRecent();
