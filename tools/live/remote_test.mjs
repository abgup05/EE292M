// The live versions on a deployed site (make site-live-test URL=https://... VERSIONS="1 8 14").
//
//   node tools/live/remote_test.mjs URL [VERSION ...]
//
// What only the deployment can show, with as few requests as it takes: one run per version
// named, none with a key the test knows of. For each version it reports
//
// - how long the first request to its page took, and whether the instance that answered
//   /live/status just before had built the version yet (a cold first request builds it);
// - a run of the version's own example started through the shim exactly as the page starts
//   it, which must finish with at least one source read and one verified finding;
// - how the held run start arrived: when its first and its last piece came, in how many
//   pieces, and plainly whether the platform buffered it (everything in one piece at the end);
// - the poll after the run, asked of the server directly (200: an instance that has the run;
//   404: one that does not) and through a new copy of the shim with the same session storage,
//   which must answer 200 either way.
//
// With COMPANY=TICKER it then starts one more run on the newest version named, of a company
// the seed does not hold, and prints exactly what the server answered: whether EDGAR answers
// the deployment's addresses under whatever identifier the server sends.
//
// /live/status is read before and after and the two are compared. Counts are per instance,
// so the comparison says so when the answers cannot have come from one instance.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const [site, ...only] = process.argv.slice(2);
if (!site) {
  console.error('Usage: remote_test.mjs URL [VERSION ...]   (env COMPANY=COST for a company outside the seed)');
  process.exit(2);
}
const base = site.replace(/\/+$/, "");
const versions = (only.length ? only : ["1", "8", "14"]).map(Number);
const V1_EXAMPLE = JSON.parse(readFileSync(new URL("../snapshots/v1-example.json", import.meta.url), "utf8"));
const RUN_SECONDS = 290;
const AGENT = { "user-agent": "ee292m-site-live-test" };

const get = (path, init = {}) => fetch(base + path, { ...init, headers: { ...AGENT, ...(init.headers ?? {}) } });

function session() {
  const values = new Map();
  return {
    get length() { return values.size; },
    key: (i) => [...values.keys()][i] ?? null,
    getItem: (k) => (values.has(k) ? values.get(k) : null),
    setItem: (k, v) => values.set(k, String(v)),
    removeItem: (k) => values.delete(k),
  };
}

/** The page's own fetch as the shim leaves it; `seen` gets the arrival of each piece of a held run start. */
function page(n, shim, storage, seen) {
  const notes = [];
  const sandbox = {
    URL, Request, Response, Headers, JSON, TextDecoder, TextEncoder, Blob, ReadableStream,
    location: new URL(`${base}/v${n}/`),
    document: {
      addEventListener() {},
      querySelector: () => ({ set textContent(text) { notes.push(text); }, hidden: true }),
    },
    sessionStorage: storage,
    setTimeout,
    fetch: async (input, init = {}) => {
      const headers = new Headers(init.headers || {});
      headers.set("user-agent", AGENT["user-agent"]);
      const began = Date.now();
      const response = await fetch(input, { ...init, headers });
      if (!seen || headers.get("x-live-hold") !== "ndjson" || !response.body) return response;
      seen.headersAt = Date.now() - began;
      seen.contentType = response.headers.get("content-type");
      seen.instance = response.headers.get("x-vercel-id");
      const decoder = new TextDecoder();
      const watched = response.body.pipeThrough(new TransformStream({
        transform(chunk, controller) {
          const text = decoder.decode(chunk, { stream: true });
          const kinds = [...text.matchAll(/"kind":"([a-z]+)"/g)].map((m) => m[1]);
          seen.pieces.push({ at: Date.now() - began, bytes: chunk.byteLength, kinds });
          controller.enqueue(chunk);
        },
      }));
      return new Response(watched, { status: response.status, headers: response.headers });
    },
  };
  sandbox.window = sandbox;
  vm.runInNewContext(shim, sandbox);
  return { api: sandbox.window.fetch, notes };
}

async function status() {
  const began = Date.now();
  const response = await get("/live/status");
  assert.equal(response.status, 200, `/live/status answered ${response.status}`);
  return { report: await response.json(), ms: Date.now() - began };
}

function describeStream(seen) {
  if (!seen.pieces.length) return "the run start was not answered as a stream";
  const lines = seen.pieces.flatMap((piece) => piece.kinds);
  const firstAt = seen.pieces[0].at;
  const lastAt = seen.pieces.at(-1).at;
  const firstHasEnd = seen.pieces[0].kinds.some((kind) => kind === "finished" || kind === "timeout");
  const buffered = firstHasEnd && lines.length > 1;
  const how = buffered
    ? "BUFFERED: the first piece already held the last line, so nothing reached the page before the run ended"
    : "STREAMED: the first line reached the page before the run ended";
  return `held run start ${how}; first line after ${firstAt} ms, last after ${lastAt} ms, ` +
    `${seen.pieces.length} pieces, lines: ${lines.join(", ")}`;
}

async function follow(api, runPath) {
  const began = Date.now();
  for (;;) {
    const run = await (await api(runPath)).json();
    if (run.status !== "running" && run.status !== "queued") return { run, seconds: Math.round((Date.now() - began) / 1000) };
    assert.ok(Date.now() - began < RUN_SECONDS * 1000, `still ${run.status} after ${RUN_SECONDS} s`);
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}

async function one(n, before) {
  const state = before.versions[String(n)];
  assert.ok(state, `the site has no version ${n}`);
  const began = Date.now();
  const first = await get(`/v${n}/`);
  const firstMs = Date.now() - began;
  const html = await first.text();
  assert.equal(first.status, 200, `GET /v${n}/ answered ${first.status}`);
  assert.ok(html.includes(`data-live-version="${n}"`), "the page is not the live one (no live banner)");
  console.log(`      v${n} first request to its page: ${firstMs} ms (the instance that answered /live/status had ` +
    `${state.serving === "live" ? "already built it" : "not built it yet"})`);
  const shim = await (await get(`/v${n}/live-shim.js`)).text();
  const storage = session();
  const seen = { pieces: [] };
  const { api } = page(n, shim, storage, seen);
  const research = n === 1;
  const body = research ? V1_EXAMPLE : { ...(await (await api("/api/meta")).json()).example, extra_urls: [] };
  const started = await api(research ? "/api/research" : "/api/runs", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  const answer = await started.json();
  assert.equal(started.status, 202, `the run did not start: HTTP ${started.status} ${JSON.stringify(answer).slice(0, 300)}`);
  const runPath = `${research ? "/api/research" : "/api/runs"}/${encodeURIComponent(answer.id)}`;
  const { run, seconds } = await follow(api, runPath);
  console.log(`      v${n} ${describeStream(seen)}`);
  const count = (list) => (Array.isArray(list) ? list.length : 0);
  const why = [...(run.coverage_limits ?? []), ...(run.errors ?? [])].join(" | ").slice(0, 600);
  assert.ok(["complete", "partial"].includes(run.status), `the run ended ${run.status}: ${why}`);
  assert.ok(count(run.sources) > 0, `the run read no source: ${why}`);
  assert.ok(count(run.findings) > 0, `the run has no verified finding: ${why}`);

  // The poll after the run: the server directly, then a new page of the same browser session.
  const direct = await get(`/v${n}${runPath}`);
  await direct.arrayBuffer();
  const where = direct.status === 200 ? "an instance that has the run (200)"
    : direct.status === 404 ? "an instance that never saw the run (404)" : `HTTP ${direct.status}`;
  const again = page(n, await (await get(`/v${n}/live-shim.js`)).text(), storage, null);
  const kept = await again.api(runPath);
  assert.equal(kept.status, 200, `the shim answered ${kept.status} for the finished run`);
  assert.equal((await kept.json()).status, run.status);
  return `run ${answer.id} ${run.status} (${count(run.sources)} sources, ${count(run.findings)} findings, ` +
    `${count(run.errors)} errors) in ${seconds} s; poll after it: the server answered from ${where}, the shim 200` +
    (why ? `\n      v${n} is ${run.status} because: ${why}` : "");
}

/** One run of a company the seed does not hold; prints what the server answered, as it answered. */
async function outside(n, ticker) {
  const shim = await (await get(`/v${n}/live-shim.js`)).text();
  const { api } = page(n, shim, session(), { pieces: [] });
  const request = {
    ticker,
    decision: `Whether to keep a position in ${ticker} into the next earnings report`,
    claims: ["Revenue is growing year over year.", "Gross margin is expanding."],
    extra_urls: [],
  };
  const started = await api("/api/runs", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(request),
  });
  const text = await started.text();
  if (started.status !== 202) {
    return { ok: false, line: `the run of ${ticker} was not started: HTTP ${started.status} ${text.slice(0, 600)}` };
  }
  const { id } = JSON.parse(text);
  const { run, seconds } = await follow(api, `/api/runs/${encodeURIComponent(id)}`);
  const sources = (run.sources ?? []).map((s) => `${s.form ?? s.kind ?? "?"} ${s.status ?? ""}`.trim()).join("; ");
  const seeded = JSON.stringify(run).includes("x-live-seed");
  return {
    ok: ["complete", "partial"].includes(run.status) && (run.sources ?? []).length > 0,
    line: `run ${id} of ${ticker} (${run.company?.name ?? "no company"}) ended ${run.status} in ${seconds} s: ` +
      `${(run.sources ?? []).length} sources [${sources}], ${(run.findings ?? []).length} findings, ` +
      `${(run.metrics ?? []).length} metrics${seeded ? ", seed named in the record" : ""}` +
      `\n      limits: ${(run.coverage_limits ?? []).join(" | ").slice(0, 700) || "none"}` +
      `\n      errors: ${(run.errors ?? []).join(" | ").slice(0, 900) || "none"}`,
  };
}

function summary(report) {
  const c = report.counts;
  const s = report.seed;
  return `live_versions ${report.live_versions}, key_present ${report.key_present}, sec_user_agent_present ` +
    `${report.sec_user_agent_present}, model_engine ${report.model_engine}; runs_today ${c.runs_today}, ` +
    `model_runs_today ${c.model_runs_today}, runs_in_progress ${c.runs_in_progress}, clients_today ${c.clients_today}; ` +
    `seed: ${s.served_without_asking_edgar} without asking EDGAR, ${s.served_because_edgar_did_not_answer} because EDGAR did not answer; ` +
    `EDGAR's answers by host: ${report.edgar ? JSON.stringify(report.edgar) : "not reported by this deployment"}; ` +
    `built: ${Object.entries(report.versions).filter(([, v]) => v.serving === "live").map(([n]) => n).join(" ") || "none"}`;
}

const before = await status();
console.log(`before  /live/status in ${before.ms} ms: ${summary(before.report)}`);
if (before.report.key_present && process.env.WITH_KEY !== "1") {
  console.log("The server has a model key: a run here would be paid for. Nothing was started (WITH_KEY=1 to go on).");
  process.exit(1);
}
let failed = 0;
let started = 0;
for (const n of versions) {
  try {
    const line = await one(n, before.report);
    started += 1;
    console.log(`ok    v${String(n).padEnd(3)} ${line}`);
  } catch (error) {
    failed += 1;
    console.log(`FAIL  v${String(n).padEnd(3)} ${error.message}`);
  }
}
const company = (process.env.COMPANY ?? "").trim().toUpperCase();
if (company) {
  const n = Math.max(...versions.filter((v) => v >= 2));
  try {
    const result = await outside(n, company);
    started += result.line.startsWith("run ") ? 1 : 0;
    failed += result.ok ? 0 : 1;
    console.log(`${result.ok ? "ok   " : "FAIL "} v${String(n).padEnd(3)} outside the seed: ${result.line}`);
  } catch (error) {
    failed += 1;
    console.log(`FAIL  v${String(n).padEnd(3)} outside the seed: ${error.message}`);
  }
}
const after = await status();
console.log(`after   /live/status in ${after.ms} ms: ${summary(after.report)}`);
const moved = after.report.counts.runs_today - before.report.counts.runs_today;
console.log(
  moved === started
    ? `runs_today moved by ${moved}, the ${started} runs this test started: one instance answered both readings and every run.`
    : `runs_today moved by ${moved} while this test started ${started} runs: the two readings, or the runs, were ` +
      "answered by different instances (each counts only its own), or other visitors started runs meanwhile.",
);
console.log(failed ? `${failed} checks failed.` : "Every check passed.");
process.exit(failed ? 1 : 0);
