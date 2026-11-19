// Tests of the live shim (Homework/Week 2/visualization/src/live/shim.js) in Node (make site-test):
// it moves the page's /api calls under /vN/, hands the page the first line of a held run start,
// answers the page's polling from the lines that follow, keeps the finished run for a fresh page
// in the same session, and falls back to the kept review when the server has never seen the run.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const template = readFileSync(new URL("../../Homework/Week 2/visualization/src/live/shim.js", import.meta.url), "utf8");
const config = {
  version: 14, ref: "capstone-v14", base: "/v14/", watch: true, storage: "test:v14:",
  starts: [["/api/runs", "/api/runs/{id}"], ["/api/theses/[^/]+/runs", "/api/runs/{id}"]],
  extras: ["/api/runs/{id}/review"],
};

function storage() {
  const values = new Map();
  return {
    get length() { return values.size; },
    key: (i) => [...values.keys()][i] ?? null,
    getItem: (k) => (values.has(k) ? values.get(k) : null),
    setItem: (k, v) => values.set(k, String(v)),
    removeItem: (k) => values.delete(k),
  };
}

function ndjson(lines, { hold } = {}) {
  const encoder = new TextEncoder();
  return new ReadableStream({
    async start(controller) {
      for (const [i, line] of lines.entries()) {
        controller.enqueue(encoder.encode(JSON.stringify(line) + "\n"));
        if (i === 0 && hold) await hold;
      }
      controller.close();
    },
  });
}

function load(server, session) {
  const calls = [];
  const sandbox = {
    URL, Request, Response, Headers, JSON, TextDecoder, TextEncoder, Blob, ReadableStream,
    location: new URL("https://site.test/v14/"),
    document: { addEventListener() {}, querySelector: () => null },
    sessionStorage: session,
    fetch: async (input, init = {}) => {
      const url = String(input instanceof Request ? input.url : input);
      calls.push([String(init.method || "GET"), url, new Headers(init.headers || {}).get("x-live-hold")]);
      return server(url, init);
    },
  };
  sandbox.window = sandbox;
  vm.runInNewContext(template.replace("/*LIVE*/null", JSON.stringify(config)), sandbox);
  return { fetch: sandbox.window.fetch, calls };
}

const RUN = (status) => ({ id: "r1", status, findings: [] });

test("the page's /api calls go to this version, and other origins are left alone", async () => {
  const { fetch, calls } = load(async () => new Response("{}"), storage());
  await fetch("/api/meta");
  await fetch("sample-run.json");
  await fetch("/sample-run.json");
  await fetch("https://www.sec.gov/x");
  assert.deepEqual(calls.map((c) => c[1]), [
    "https://site.test/v14/api/meta", "https://site.test/v14/sample-run.json",
    "https://site.test/v14/sample-run.json", "https://www.sec.gov/x",
  ]);
});

test("a run start is held; the page gets the run id at once and its polls are answered from the stream", async () => {
  let release;
  const hold = new Promise((resolve) => (release = resolve));
  const session = storage();
  const server = async (url) => {
    if (url.endsWith("/v14/api/runs")) {
      return new Response(ndjson([
        { kind: "started", status: 202, body: { id: "r1", status: "running" }, run: RUN("running") },
        { kind: "progress", run: RUN("running") },
        { kind: "finished", run: RUN("complete"), extras: { "/api/runs/r1/review": { content_type: "application/json", body: '{"run_id":"r1"}' } } },
      ], { hold }), { headers: { "content-type": "application/x-ndjson" } });
    }
    return new Response('{"error":"Run not found"}', { status: 404 });
  };
  const { fetch, calls } = load(server, session);
  const started = await fetch("/api/runs", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
  assert.equal(started.status, 202);
  assert.deepEqual(await started.json(), { id: "r1", status: "running" });
  assert.equal(calls[0][2], "ndjson");
  const polled = await fetch("/api/runs/r1");
  assert.equal((await polled.json()).status, "running");
  release();
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal((await (await fetch("/api/runs/r1")).json()).status, "complete");
  assert.equal(calls.length, 1, "no poll reached the server");

  // A fresh page in the same session, whose requests reach an instance that never saw the run.
  const fresh = load(server, session);
  assert.equal((await (await fresh.fetch("/api/runs/r1")).json()).status, "complete");
  const review = await fresh.fetch("/api/runs/r1/review");
  assert.equal(review.status, 200);
  assert.equal((await review.json()).run_id, "r1");
  assert.deepEqual(fresh.calls.map((c) => c[1]), ["https://site.test/v14/api/runs/r1/review"]);
});

test("a refusal is handed to the page as the server sent it", async () => {
  const server = async () => new Response('{"error":"limit"}', { status: 429, headers: { "content-type": "application/json" } });
  const { fetch } = load(server, storage());
  const response = await fetch("/api/theses/t1/runs", { method: "POST" });
  assert.equal(response.status, 429);
  assert.equal((await response.json()).error, "limit");
});

test("a run that the server stopped holding is polled from the server again", async () => {
  const server = async (url) => {
    if (url.endsWith("/api/runs")) {
      return new Response(ndjson([
        { kind: "started", status: 202, body: { id: "r2", status: "running" }, run: { id: "r2", status: "running" } },
        { kind: "timeout", message: "still going" },
      ]), { headers: { "content-type": "application/x-ndjson" } });
    }
    return new Response('{"id":"r2","status":"partial"}');
  };
  const { fetch, calls } = load(server, storage());
  await fetch("/api/runs", { method: "POST", body: "{}" });
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal((await (await fetch("/api/runs/r2")).json()).status, "partial");
  assert.equal(calls.at(-1)[1], "https://site.test/v14/api/runs/r2");
});
