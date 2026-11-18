"""Export recorded, read-only snapshots of the running Evidence Desk versions.

Each tagged version N runs locally at http://127.0.0.1:87NN (``make versions-up``). This
script reads such an instance over HTTP and writes, under ``OUT/vN/``:

- the page's own files exactly as the instance serves them (``index.html``, ``app.js``,
  ``styles.css`` and every ``sample-*.json`` the page names), with two changes made to the
  exported ``index.html`` only: absolute references to the page's own files become relative
  so the copy works under ``/vN/``, and a banner and ``snapshot.js`` are inserted;
- the answers of the GET endpoints the page calls when it loads and when a stored run or a
  saved thesis is opened, byte for byte, under ``api/``;
- ``snapshot.js``: a small script that answers the page's ``fetch`` calls to ``/api/...``
  from those files and refuses anything else (any POST, PUT or DELETE, or a GET that was
  not recorded) with an error the page shows.

Nothing is fabricated and no captured answer is edited. The output is deterministic: no
timestamp is added, files are written in a fixed order, and JSON written by this script is
sorted. Run it through ``make site-export``; it uses the standard library only.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPOSITORY = "https://github.com/abgup05/EE292M"
USER_AGENT = "ee292m-site-export"
SAMPLE_FILE = re.compile(r"sample-[a-z0-9-]{1,40}\.json")
SAMPLE_LINK = re.compile(r"[?&]sample(?:=([a-z0-9-]{1,40}))?(?=[\"'&#])")
LOCAL_REF = re.compile(r"""(\b(?:href|src)=")(/?)([A-Za-z0-9_./-]+\.(?:css|js|json|png|svg|ico|woff2?))(")""")
CSS_URL = re.compile(r"""url\(\s*["']?(?!data:|https?:|#)([^"')]+)["']?\s*\)""")
SAFE_PART = re.compile(r"[^A-Za-z0-9._-]")
#: How a page's script asks for a run's review, its changes and a thesis's changes.
RUN_REVIEW = "/api/runs/${encodeURIComponent(runId)}/review`"
RUN_CHANGES = "/api/runs/${encodeURIComponent(runId)}/changes`"
THESIS_CHANGES = "/changes`);"
#: The page's own runs and theses that are recorded, newest first, unless --runs says otherwise.
DEFAULT_RUNS = 2


class ExportError(RuntimeError):
    """A version could not be exported as asked; nothing partial is kept for it."""


@dataclass
class Capture:
    """One recorded answer: the URL the page asks for and the file that answers it."""

    key: str
    file: str
    body: bytes
    content_type: str


@dataclass
class Snapshot:
    """Everything recorded for one version, before it is written."""

    version: int
    source: str
    files: dict[str, bytes] = field(default_factory=dict)
    routes: list[Capture] = field(default_factory=list)
    open_run: str | None = None
    notes: list[str] = field(default_factory=list)


def fetch(url: str, timeout: float) -> tuple[int, bytes, str]:
    """GET a URL; return the status, the body and the content type, never raising on 4xx/5xx."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), response.headers.get_content_type()
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers.get_content_type()


def capture_file(key: str, content_type: str) -> str:
    """The file, relative to the version's directory, that records the answer to ``key``.

    ``/api/runs/abc/export.md?reviewed=true`` becomes ``api/runs/abc/export.md__reviewed-true.md``;
    a JSON answer without an extension gets ``.json``.
    """
    parsed = urllib.parse.urlsplit(key)
    parts = [SAFE_PART.sub("_", urllib.parse.unquote(p)) for p in parsed.path.strip("/").split("/")]
    if any(part in ("", ".", "..") for part in parts):
        raise ExportError(f"cannot name a file for {key!r}")
    stem = Path(parts[-1])
    suffix = {"application/json": ".json", "text/markdown": ".md"}.get(content_type, stem.suffix or ".txt")
    name = stem.stem if stem.suffix == suffix else parts[-1]
    if parsed.query:
        name += "__" + SAFE_PART.sub("-", parsed.query.replace("=", "-").replace("&", "_"))
    return "/".join([*parts[:-1], name + suffix])


def relative_refs(page: str) -> str:
    """Make the page's absolute references to its own files relative (``/app.js`` → ``app.js``)."""
    return LOCAL_REF.sub(lambda m: m.group(1) + m.group(3) + m.group(4), page)


def asset_names(page: str) -> list[str]:
    """The page's own local files that ``index.html`` loads, in order of first appearance."""
    names: list[str] = []
    for match in LOCAL_REF.finditer(page):
        name = match.group(3)
        if name not in names and not name.startswith(("api/", "http")):
            names.append(name)
    return names


def sample_names(page: str, script: str) -> list[str]:
    """Every ``sample-<name>.json`` the page links to or the script names, sorted."""
    names = set(SAMPLE_FILE.findall(page)) | set(SAMPLE_FILE.findall(script))
    for match in SAMPLE_LINK.finditer(page):
        names.add(f"sample-{match.group(1) or 'run'}.json")
    return sorted(names)


def brief_queries(script: str) -> list[str]:
    """The query strings with which this version's page links to a run's Markdown brief."""
    if 'query.set("changes", "true")' in script:
        return ["changes=true", "reviewed=true&changes=true"]
    queries = [""]
    if "export.md?reviewed=true" in script:
        queries.append("reviewed=true")
    return queries


def banner(version: int) -> str:
    """The snapshot's banner: static HTML, so it shows even if the page's script fails."""
    tag = f"capstone-v{version}"
    return (
        f'<div class="snapshot-banner" role="note" data-snapshot-version="{version}">'
        f"Recorded snapshot of Evidence Desk version {version}. "
        "Live runs need the app running locally. "
        '<a href="/versions">All versions</a> · '
        f'<a href="{REPOSITORY}/tree/{tag}">Tag {tag} on GitHub</a>'
        '<span class="snapshot-note" hidden></span></div>\n'
    )


BANNER_STYLE = """<style>
  .snapshot-banner { font: 13px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 6px 16px; background: #f3f1ea; color: #3a3a35; border-bottom: 1px solid #d9d5c7; }
  .snapshot-banner a { color: inherit; text-decoration: underline; }
  .snapshot-banner .snapshot-note { display: block; margin-top: 2px; color: #8a3b12; }
  .snapshot-banner .snapshot-note[hidden] { display: none; }
  @media (prefers-color-scheme: dark) {
    .snapshot-banner { background: #24231f; color: #d8d5cb; border-bottom-color: #3b3a34; }
    .snapshot-banner .snapshot-note { color: #f0a77c; }
  }
</style>
"""


def inject(page: str, version: int) -> str:
    """The exported page: relative references, the banner style and shim in the head, the banner first in the body."""
    page = relative_refs(page)
    head_end = page.find("</head>")
    body = re.search(r"<body[^>]*>", page)
    if head_end < 0 or body is None or body.start() < head_end:
        raise ExportError("the page has no <head> followed by a <body>; cannot add the banner")
    head = BANNER_STYLE + '<script src="snapshot.js"></script>\n'
    page = page[:head_end] + head + page[head_end:]
    body = re.search(r"<body[^>]*>", page)
    assert body is not None
    return page[: body.end()] + "\n" + banner(version) + page[body.end() :]


def shim(snapshot: Snapshot) -> str:
    """``snapshot.js``: the recorded routes and the code that answers the page's API calls from them."""
    config = {
        "version": snapshot.version,
        "openRun": snapshot.open_run,
        "routes": {c.key: c.file for c in sorted(snapshot.routes, key=lambda c: c.key)},
    }
    template = (Path(__file__).with_name("shim.js")).read_text(encoding="utf-8")
    return template.replace("/*SNAPSHOT*/null", json.dumps(config, indent=2, sort_keys=True))


class Exporter:
    """Reads one running version over HTTP and records what its page needs."""

    def __init__(self, version: int, base: str, runs: int, timeout: float) -> None:
        self.snapshot = Snapshot(version=version, source=f"http://127.0.0.1:{87 * 100 + version}")
        self.base = base.rstrip("/")
        self.runs = runs
        self.timeout = timeout

    def get(self, path: str, *, required: bool = False) -> tuple[int, bytes, str]:
        status, body, content_type = fetch(self.base + path, self.timeout)
        if required and status != 200:
            raise ExportError(f"GET {path} answered HTTP {status}")
        return status, body, content_type

    def record(self, key: str) -> bytes | None:
        """GET ``key`` and record the answer if it is 200; return the body, or None."""
        status, body, content_type = self.get(key)
        if status != 200:
            self.snapshot.notes.append(f"GET {key}: HTTP {status}, not recorded")
            return None
        self.snapshot.routes.append(Capture(key, capture_file(key, content_type), body, content_type))
        return body

    def page(self) -> str:
        """The page and its own files; returns the page's script for the steps after it."""
        _, raw, _ = self.get("/", required=True)
        page = raw.decode("utf-8")
        script = ""
        for name in asset_names(page):
            _, body, _ = self.get("/" + name, required=True)
            self.snapshot.files[name] = body
            if name.endswith(".js"):
                script += body.decode("utf-8")
            if name.endswith(".css"):
                for ref in CSS_URL.findall(body.decode("utf-8")):
                    ref = ref.lstrip("/")
                    _, extra, _ = self.get("/" + ref, required=True)
                    self.snapshot.files[ref] = extra
        for name in sample_names(page, script):
            status, body, _ = self.get("/" + name)
            if status == 200:
                self.snapshot.files[name] = body
            else:
                self.snapshot.notes.append(f"the page names {name}, which answered HTTP {status}")
        self.snapshot.files["index.html"] = inject(page, self.snapshot.version).encode("utf-8")
        return script

    def stored(self, script: str) -> None:
        """The answers the page reads on load and when a stored run or thesis is opened."""
        meta_status, _, _ = self.get("/api/meta")
        if meta_status != 200:
            self.research()
            return
        self.record("/api/meta")
        listing = json.loads(self.record("/api/runs") or b'{"runs": []}')
        finished = [r for r in listing.get("runs", []) if r.get("status") not in ("running", "queued")]
        chosen = [r["id"] for r in finished[: self.runs]]
        theses_body = self.record("/api/theses") if "/api/theses" in script else None
        theses = json.loads(theses_body)["theses"][: self.runs] if theses_body else []
        for thesis in theses:
            quoted = urllib.parse.quote(thesis["id"], safe="")
            self.record(f"/api/theses/{quoted}")
            self.record(f"/api/theses/{quoted}/changes")
            last = thesis.get("last_run_id")
            if last and last not in chosen and thesis.get("last_status") not in ("running", None):
                chosen.append(last)
        recorded_theses = {thesis["id"] for thesis in theses}
        for run_id in chosen:
            quoted = urllib.parse.quote(run_id, safe="")
            detail = json.loads(self.record(f"/api/runs/{quoted}") or b"{}")
            if RUN_REVIEW in script:
                self.record(f"/api/runs/{quoted}/review")
            if RUN_CHANGES in script:
                self.record(f"/api/runs/{quoted}/changes")
            thesis_id = detail.get("thesis_id")
            if thesis_id and THESIS_CHANGES in script and thesis_id not in recorded_theses:
                recorded_theses.add(thesis_id)
                self.record(f"/api/theses/{urllib.parse.quote(thesis_id, safe='')}/changes")
            for query in brief_queries(script):
                self.record(f"/api/runs/{quoted}/export.md" + (f"?{query}" if query else ""))
        if not chosen:
            self.snapshot.notes.append("the instance holds no finished run")

    def research(self) -> None:
        """Version 1: one research question per run under /api/research; its page has no sample."""
        listing = json.loads(self.record("/api/research") or b'{"runs": []}')
        finished = [r for r in listing.get("runs", []) if r.get("status") != "running"]
        for run in finished[: self.runs]:
            quoted = urllib.parse.quote(run["id"], safe="")
            self.record(f"/api/research/{quoted}")
            self.record(f"/api/research/{quoted}/export.md")
        if finished:
            self.snapshot.open_run = finished[0]["id"]
        else:
            self.snapshot.notes.append("the instance holds no finished run: make one (make site-run-v1)")

    def run(self) -> Snapshot:
        script = self.page()
        self.stored(script)
        return self.snapshot


def write(snapshot: Snapshot, out: Path) -> int:
    """Replace ``out/vN`` with the snapshot; return the number of bytes written."""
    target = out / f"v{snapshot.version}"
    staging = out / f".v{snapshot.version}.partial"
    if staging.exists():
        shutil.rmtree(staging)
    files: dict[str, bytes] = dict(snapshot.files)
    for capture in snapshot.routes:
        if capture.file in files:
            raise ExportError(f"two answers would be written to {capture.file}")
        files[capture.file] = capture.body
    files["snapshot.js"] = shim(snapshot).encode("utf-8")
    manifest = {
        "version": snapshot.version,
        "tag": f"capstone-v{snapshot.version}",
        "exported_from": snapshot.source,
        "open_run": snapshot.open_run,
        "page_files": sorted(snapshot.files),
        "routes": {c.key: c.file for c in sorted(snapshot.routes, key=lambda c: c.key)},
        "notes": snapshot.notes,
    }
    files["snapshot.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    for name, body in sorted(files.items()):
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    return sum(len(body) for body in files.values())


def survey(base: str, timeout: float) -> None:
    """Print what an instance holds: its runs, their status and size, and its theses."""
    status, body, _ = fetch(base + "/api/meta", timeout)
    listing_path = "/api/runs" if status == 200 else "/api/research"
    _, body, _ = fetch(base + listing_path, timeout)
    runs = json.loads(body).get("runs", [])
    print(f"  {len(runs)} runs at {listing_path}")
    for run in runs[:6]:
        _, detail, _ = fetch(f"{base}{listing_path}/{urllib.parse.quote(run['id'], safe='')}", timeout)
        label = run.get("ticker") or html.unescape(str(run.get("question", "")))[:50]
        print(f"    {run['id']}  {run['status']:<10} {label}  {len(detail):>8} bytes")
    status, body, _ = fetch(base + "/api/theses", timeout)
    if status == 200:
        print(f"  {len(json.loads(body).get('theses', []))} saved theses")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("versions", nargs="+", type=int, help="version numbers, e.g. 1 2 12")
    parser.add_argument("--out", type=Path, required=True, help="directory that receives vN/")
    parser.add_argument("--host", default="host.docker.internal", help="where the instances listen")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="stored runs and theses to record")
    parser.add_argument("--timeout", type=float, default=180.0, help="seconds per request")
    parser.add_argument("--survey", action="store_true", help="only print what each instance holds")
    args = parser.parse_args(argv)
    failed = 0
    for version in args.versions:
        if not 1 <= version <= 99:
            parser.error(f"version {version} has no port under the 87NN rule")
        base = f"http://{args.host}:{8700 + version}"
        print(f"version {version}  {base}")
        try:
            if args.survey:
                survey(base, args.timeout)
                continue
            snapshot = Exporter(version, base, args.runs, args.timeout).run()
            size = write(snapshot, args.out)
        except (ExportError, OSError, ValueError, KeyError) as error:
            print(f"  FAILED: {error}", file=sys.stderr)
            failed += 1
            continue
        print(f"  {len(snapshot.files)} page files, {len(snapshot.routes)} recorded answers, {size:,} bytes")
        for note in snapshot.notes:
            print(f"  note: {note}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
