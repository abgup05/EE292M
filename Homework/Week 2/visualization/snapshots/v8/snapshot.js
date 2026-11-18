/*
 * Recorded snapshot of an Evidence Desk version: answers the page's calls to its API from
 * the files recorded beside this script, and refuses everything else with a message the page
 * shows. It was added when the snapshot was exported (tools/snapshots/export.py) and is not
 * part of the tagged code. It computes nothing: every answer is a recorded file, unchanged.
 */
(() => {
  "use strict";
  const SNAPSHOT = {
  "openRun": null,
  "routes": {
    "/api/meta": "api/meta.json",
    "/api/runs": "api/runs.json",
    "/api/theses": "api/theses.json"
  },
  "version": 8
};
  const base = new URL(".", document.currentScript.src);
  const realFetch = window.fetch.bind(window);
  const STARTS_WORK = `This is a recorded snapshot of Evidence Desk version ${SNAPSHOT.version}: it cannot start a run or change anything. Live runs need the app running locally.`;

  function notRecorded(what) {
    return `This recorded snapshot of version ${SNAPSHOT.version} has no answer for ${what}. Live runs need the app running locally.`;
  }

  /** An error answer in the shape the pages read: {"error": "..."}. */
  function refusal(status, message) {
    return new Response(JSON.stringify({ error: message, detail: message }), {
      status,
      statusText: "Recorded snapshot",
      headers: { "content-type": "application/json" },
    });
  }

  /** The recorded file for a same-origin API URL, or null. */
  function recorded(url) {
    const file = SNAPSHOT.routes[url.pathname + url.search];
    return file ? new URL(file, base) : null;
  }

  window.fetch = async (input, init = {}) => {
    const isRequest = typeof Request !== "undefined" && input instanceof Request;
    const url = new URL(isRequest ? input.url : String(input), location.href);
    if (url.origin !== location.origin || url.pathname.startsWith(base.pathname)) {
      return realFetch(input, init);
    }
    const method = String(init.method ?? (isRequest ? input.method : "GET")).toUpperCase();
    if (method !== "GET" && method !== "HEAD") {
      return refusal(405, STARTS_WORK);
    }
    const file = recorded(url);
    if (!file) return refusal(404, notRecorded(`GET ${url.pathname}${url.search}`));
    return realFetch(file.href, { method, signal: init.signal ?? (isRequest ? input.signal : undefined) });
  };

  function note(text) {
    const slot = document.querySelector(".snapshot-banner .snapshot-note");
    if (!slot) return;
    slot.textContent = text;
    slot.hidden = false;
  }

  // A link into the API (a Markdown brief) opens the recorded file, or says it was not recorded.
  document.addEventListener(
    "click",
    (event) => {
      const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!link) return;
      const url = new URL(link.getAttribute("href"), location.href);
      if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return;
      event.preventDefault();
      const file = recorded(url);
      if (!file) {
        note(notRecorded(`${url.pathname}${url.search}`));
        return;
      }
      const copy = document.createElement("a");
      copy.href = file.href;
      if (link.hasAttribute("download")) copy.download = link.getAttribute("download");
      document.body.append(copy);
      copy.click();
      copy.remove();
    },
    true,
  );

  // A page with no sample of its own (version 1) opens the stored run that was recorded.
  if (SNAPSHOT.openRun) {
    window.addEventListener("load", () => {
      if (typeof window.watchRun === "function") window.watchRun(SNAPSHOT.openRun);
    });
  }
})();
