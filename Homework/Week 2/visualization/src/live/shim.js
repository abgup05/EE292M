/*
 * Live version of Evidence Desk on the public website: the page is the version's own, served
 * under /vN/, and this script is the only thing added to it (src/live/shim.js in the Week 2
 * app; docs/site-live.md). It computes nothing. It:
 *
 * - sends the page's own calls to /api/... (and /sample-...) to this version, under /vN/;
 * - asks the server to hold a run-start request open until the run has finished, hands the
 *   page the server's first answer (the run id) at once, and keeps every later line of that
 *   answer: the run as it progresses, and the finished run with the answers the page reads
 *   next (its review, its brief);
 * - answers the page's polling for that run from what it has received, and keeps a finished
 *   run in sessionStorage, so the run is still there if a later request reaches a fresh
 *   server instance that never saw it (within this browser tab's session).
 */
(() => {
  "use strict";
  const LIVE = /*LIVE*/null;
  const realFetch = window.fetch.bind(window);
  const starts = LIVE.starts.map(([pattern, poll]) => [new RegExp(`^${pattern}$`), poll]);
  const memory = new Map(); // key -> {run: string|null, done: boolean, extras: {path: {content_type, body}}}

  function stored(key) {
    if (memory.has(key)) return memory.get(key);
    try {
      const text = window.sessionStorage.getItem(LIVE.storage + key);
      if (text) {
        const entry = JSON.parse(text);
        memory.set(key, entry);
        return entry;
      }
    } catch {
      /* storage may be off or full: the in-memory copy is all there is */
    }
    return null;
  }

  function keep(key, entry) {
    memory.set(key, entry);
    if (!entry.done) return;
    try {
      window.sessionStorage.setItem(LIVE.storage + key, JSON.stringify(entry));
    } catch {
      /* too large or storage off: kept for this page only */
    }
  }

  function note(text) {
    const slot = document.querySelector(".live-banner .live-note");
    if (!slot) return;
    slot.textContent = text;
    slot.hidden = false;
  }

  /** The address under this version for a same-origin URL the page wrote as /api/... */
  function underBase(url) {
    if (url.pathname.startsWith(LIVE.base)) return url;
    const moved = new URL(url.href);
    moved.pathname = LIVE.base + url.pathname.replace(/^\/+/, "");
    return moved;
  }

  /** The path inside the version (/api/runs/x) of a URL under /vN/. */
  function inner(url) {
    return url.pathname.slice(LIVE.base.length - 1);
  }

  function json(body, status) {
    return new Response(body, { status, headers: { "content-type": "application/json" } });
  }

  async function* lines(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let end;
      while ((end = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, end).trim();
        buffer = buffer.slice(end + 1);
        if (line) yield JSON.parse(line);
      }
    }
    if (buffer.trim()) yield JSON.parse(buffer);
  }

  async function follow(stream, key) {
    const entry = stored(key);
    try {
      for (;;) {
        const { value: line, done } = await stream.next();
        if (done) break;
        if (line.kind === "progress" && line.run) entry.run = JSON.stringify(line.run);
        if (line.kind === "finished") {
          if (line.run) entry.run = JSON.stringify(line.run);
          entry.extras = line.extras || {};
          entry.done = true;
          keep(key, entry);
          return;
        }
        if (line.kind === "timeout") {
          note(line.message);
          break;
        }
      }
    } catch {
      /* the connection was cut: the page's polling goes to the server from here on */
    }
    memory.delete(key);
  }

  async function startRun(url, init, poll) {
    const headers = new Headers(init.headers || {});
    headers.set("x-live-hold", "ndjson");
    const response = await realFetch(url.href, { ...init, headers });
    if (!(response.headers.get("content-type") || "").includes("ndjson")) return response;
    const stream = lines(response);
    const first = await stream.next();
    if (first.done || first.value.kind !== "started") {
      return json(JSON.stringify({ error: "the server ended the run's answer early" }), 502);
    }
    const started = first.value;
    if (started.body && typeof started.body.id === "string") {
      const key = poll.replace("{id}", encodeURIComponent(started.body.id));
      keep(key, { run: started.run ? JSON.stringify(started.run) : null, done: false, extras: {} });
      follow(stream, key);
    }
    return json(JSON.stringify(started.body), started.status);
  }

  /** A run being followed or finished, for a GET of its own address. */
  function answerFor(path) {
    const entry = stored(path);
    if (entry && entry.run) return json(entry.run, 200);
    return null;
  }

  /** A kept answer the page reads after a run (its review, its brief), if the server has none. */
  function extraFor(path) {
    for (const key of memory.keys()) {
      const entry = memory.get(key);
      if (entry.extras && entry.extras[path]) return entry.extras[path];
    }
    try {
      for (let i = 0; i < window.sessionStorage.length; i += 1) {
        const name = window.sessionStorage.key(i);
        if (!name || !name.startsWith(LIVE.storage)) continue;
        const entry = stored(name.slice(LIVE.storage.length));
        if (entry && entry.extras && entry.extras[path]) return entry.extras[path];
      }
    } catch {
      /* storage off */
    }
    return null;
  }

  window.fetch = async (input, init = {}) => {
    const isRequest = typeof Request !== "undefined" && input instanceof Request;
    const original = new URL(isRequest ? input.url : String(input), location.href);
    if (original.origin !== location.origin) return realFetch(input, init);
    const url = underBase(original);
    const path = inner(url);
    const method = String(init.method || (isRequest ? input.method : "GET")).toUpperCase();
    if (isRequest) {
      input = new Request(url.href, input);
    }
    if (method === "POST" && !isRequest) {
      for (const [pattern, poll] of starts) {
        if (pattern.test(path)) return startRun(url, init, poll);
      }
    }
    if (method === "GET" && !url.search) {
      const kept = answerFor(path);
      if (kept) return kept;
    }
    const response = await realFetch(isRequest ? input : url.href, isRequest ? init : init);
    if (method === "GET" && response.status === 404) {
      const extra = extraFor(path + url.search);
      if (extra) return new Response(extra.body, { status: 200, headers: { "content-type": extra.content_type } });
    }
    if (LIVE.watch && method === "PUT" && /\/watch$/.test(path) && response.ok) {
      note("Watch saved for this visit only: no watcher process runs on the public server, so nothing checks it for new filings.");
    }
    return response;
  };

  // A link into the API (a Markdown brief) opens it under this version, or the kept copy.
  document.addEventListener(
    "click",
    (event) => {
      const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!link) return;
      const url = new URL(link.getAttribute("href"), location.href);
      if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return;
      event.preventDefault();
      const moved = underBase(url);
      window.fetch(url.pathname + url.search).then(async (response) => {
        const copy = document.createElement("a");
        if (response.ok) {
          copy.href = URL.createObjectURL(new Blob([await response.text()], { type: response.headers.get("content-type") || "text/plain" }));
        } else {
          copy.href = moved.href;
        }
        if (link.hasAttribute("download")) copy.download = link.getAttribute("download");
        else copy.target = link.target || "_self";
        document.body.append(copy);
        copy.click();
        copy.remove();
      });
    },
    true,
  );
})();
