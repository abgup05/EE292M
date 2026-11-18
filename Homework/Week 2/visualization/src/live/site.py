"""Version N's app at ``/vN``: its own page with a banner and the shim, its API behind the guard.

:class:`LiveVersionApp` is a plain ASGI app mounted at ``/vN`` by the Week 2 app. For each request:

- ``/vN/`` is the version's own ``index.html`` with its references made relative, a banner and
  ``live-shim.js`` added (the vendored file itself is not changed); ``/vN/live-shim.js`` is the
  shim with this version's settings;
- everything else passes :mod:`live.guard` and then goes to the version's own app, unchanged;
- a version that cannot be built on this server is answered by its recorded snapshot instead
  (``snapshots/vN``, read-only, with its own banner), and ``/live/status`` says so;
- a request that starts a run is held open until the run has finished (or until
  ``LIVE_HOLD_SECONDS``): a serverless instance may be frozen once a response is sent, and the
  next request may reach another instance. With ``x-live-hold: ndjson`` (sent by the shim) the
  answer is a stream of JSON lines: ``started`` (the version's own answer and the run as first
  saved), ``progress`` when the run record changes, ``tick`` every few seconds, and ``finished``
  (the run, and the answers the page asks for next) or ``timeout``. Without that header the
  answer is the version's own answer, sent once the run has finished, after blank heartbeats.

:class:`Site` holds what all versions share and answers ``/live/status``.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, MutableMapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

import anyio

from live.guard import (
    Caps,
    Guard,
    Refusal,
    check_body,
    check_request,
    client_of,
    costly_read,
    key_present,
    run_start,
    user_agent_present,
)
from live.seed import Seed
from live.versions import VENDOR_DIR, Version, discover

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

REPOSITORY = "https://github.com/abgup05/EE292M"
SHIM_FILE = Path(__file__).with_name("shim.js")
POLL_SECONDS = 1.0
PROGRESS_SECONDS = 3.0
TICK_SECONDS = 5.0
FINISHED = frozenset({"complete", "partial", "failed"})
OUTER_KEYS = frozenset({"router", "endpoint", "path_params", "route", "app_root_path"})
#: Answers a page reads once its run has finished, kept with the run by the shim.
EXTRAS = {
    "research": ["/api/research/{id}/export.md"],
    "thesis": ["/api/runs/{id}/review", "/api/runs/{id}/export.md"],
}
LOCAL_REF = re.compile(
    r"""(\b(?:href|src)=")/([A-Za-z0-9_./-]+\.(?:css|js|json|png|svg|ico|woff2?|html))(")"""
)
log = logging.getLogger(__name__)


class Site:
    """The live versions, the guard and the seed of this process."""

    def __init__(self, vendor_dir: Path = VENDOR_DIR) -> None:
        self.caps, self.invalid_caps = Caps.from_env()
        self.guard = Guard(self.caps)
        self.seed = Seed(vendor_dir / "seed")
        self.versions = {
            number: Version(info, self.seed) for number, info in discover(vendor_dir).items()
        }

    async def status(self, imports: bool) -> dict[str, Any]:
        """Booleans and counts only: never the key, the contact string or a client address."""
        if imports:
            for version in self.versions.values():
                try:
                    await anyio.to_thread.run_sync(version.load)
                except RuntimeError:
                    pass  # recorded in the version's state
        return {
            "key_present": key_present(),
            "sec_user_agent_present": user_agent_present(),
            "model_engine": "on" if key_present() else "off",
            "caps": self.caps.as_dict(),
            "caps_invalid": self.invalid_caps,
            "caps_scope": "per server instance: counts are kept in memory and are not shared",
            "counts": self.guard.counts(),
            "seed": self.seed.counts(),
            "versions": {str(n): v.state() for n, v in self.versions.items()},
        }


def _headers(scope: Scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


async def _respond(send: Send, status: int, body: bytes, content_type: str, head: bool = False) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", content_type.encode()),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": b"" if head else body})


async def _refuse(send: Send, refusal: Refusal) -> None:
    await _respond(send, refusal.status, refusal.body(), "application/json")


async def call(app: Any, scope: Scope, method: str, path: str, body: bytes = b"") -> tuple[int, dict[str, str], bytes]:
    """Send one request to a version's app in this process; return status, headers and body."""
    inner = dict(scope)
    inner.update(
        method=method,
        path=scope["root_path"] + path,
        raw_path=(scope["root_path"] + path).encode(),
        query_string=b"",
        headers=[
            (k, v)
            for k, v in scope.get("headers", [])
            if k.lower() not in (b"content-length", b"x-live-hold", b"accept-encoding")
        ]
        + [(b"content-length", str(len(body)).encode())],
    )
    status = 500
    headers: dict[str, str] = {}
    chunks: list[bytes] = []
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    async def collect(message: Message) -> None:
        nonlocal status, headers
        if message["type"] == "http.response.start":
            status = message["status"]
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in message.get("headers", [])}
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    async with anyio.create_task_group() as group:

        async def run() -> None:
            try:
                await app(inner, receive, collect)
            except Exception:  # noqa: BLE001 - the version already answered 500; keep holding
                log.exception("version app failed on %s %s", method, path)
            group.cancel_scope.cancel()

        group.start_soon(run)
    return status, headers, b"".join(chunks)


class LiveVersionApp:
    """The ASGI app at ``/vN`` for one version (see the module's description)."""

    def __init__(self, site: Site, number: int, recorded: Any = None) -> None:
        """``recorded`` is the ASGI app of the version's recorded snapshot, if it has one.

        It answers in the live version's place when the version cannot be built on this
        server, so a visitor gets the read-only recording and its own banner, not an error.
        """
        self.site = site
        self.version = site.versions[number]
        self.version.has_recording = recorded is not None
        self.recorded = recorded
        self.info = self.version.info
        self.prefix = f"/v{number}"

    # -- the page

    def banner(self) -> str:
        info, caps = self.info, self.site.caps
        tag = info.ref
        if key_present():
            engine = (
                "Model engine on: runs use Claude, paid by the site's owner, one at a time, at most "
                f"{caps.LIVE_MODEL_RUNS_PER_CLIENT_PER_DAY} per visitor and "
                f"{caps.LIVE_MODEL_RUNS_PER_DAY} in all per day, counted by each server instance "
                "separately (so not a hard total)."
            )
        else:
            engine = "The model engine is off on this server: runs use this version's engine without a model."
        notes = [
            f"Evidence Desk version {info.number} as tagged ({html.escape(tag)}), running live on a "
            "shared public server.",
            html.escape(engine),
            "Runs and saved items are not kept: they last until this server instance recycles, and "
            "other visitors may see them meanwhile.",
        ]
        if info.era == "research":
            notes.append("It reads only the two pages of its own example; it fetches no other address.")
        else:
            notes.append("Extra web pages are off: it fetches no address a visitor supplies.")
        if info.watch:
            notes.append(
                "A watch can be set, but no watcher process runs online, so nothing checks a "
                "watched thesis for new filings."
            )
        links = (
            '<a href="/versions">All versions</a> · '
            f'<a href="{REPOSITORY}/tree/{quote(tag)}">Tag {html.escape(tag)} on GitHub</a>'
        )
        return (
            f'<div class="live-banner" role="note" data-live-version="{info.number}" '
            f'data-live-ref="{html.escape(tag)}">{" ".join(notes)} {links}'
            '<span class="live-note" hidden></span></div>\n'
        )

    def page(self) -> bytes:
        """The version's own index.html with relative references, the banner and the shim."""
        page = (self.info.web_dir / "index.html").read_text(encoding="utf-8")
        page = LOCAL_REF.sub(lambda m: m.group(1) + m.group(2) + m.group(3), page)
        head_end = page.find("</head>")
        body = re.search(r"<body[^>]*>", page)
        if head_end < 0 or body is None or body.start() < head_end:
            raise RuntimeError("the page has no <head> followed by a <body>")
        page = page[:head_end] + BANNER_STYLE + '<script src="live-shim.js"></script>\n' + page[head_end:]
        body = re.search(r"<body[^>]*>", page)
        assert body is not None
        return (page[: body.end()] + "\n" + self.banner() + page[body.end() :]).encode("utf-8")

    def shim(self) -> bytes:
        info = self.info
        config = {
            "version": info.number,
            "ref": info.ref,
            "base": f"{self.prefix}/",
            "starts": [[p.pattern, poll] for p, poll in _starts(info.era)],
            "extras": EXTRAS[info.era],
            "storage": f"evidence-desk-live:v{info.number}:{info.commit[:12]}:",
            "watch": info.watch,
        }
        template = SHIM_FILE.read_text(encoding="utf-8")
        return template.replace("/*LIVE*/null", json.dumps(config, sort_keys=True)).encode("utf-8")

    # -- requests

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            return
        path: str = scope["path"]
        sub = path[len(self.prefix) :] if path == self.prefix or path.startswith(self.prefix + "/") else path
        # The version's app is a whole app of its own: it gets no trace of the Week 2 router.
        scope = {k: v for k, v in scope.items() if k not in OUTER_KEYS}
        scope.update(root_path=self.prefix, path=self.prefix + sub, raw_path=(self.prefix + sub).encode())
        method = scope["method"]
        head = method == "HEAD"
        try:
            app = await anyio.to_thread.run_sync(self.version.load)
        except RuntimeError as exc:
            if self.recorded is not None:
                await self.recorded(scope, receive, send)
                return
            log.error("version %s could not be built: %s", self.info.number, exc)
            message = f"Version {self.info.number} could not be started on this server ({exc})."
            await _refuse(send, Refusal(503, message))
            return
        if sub in ("", "/", "/index.html") and method in ("GET", "HEAD"):
            await _respond(send, 200, self.page(), "text/html; charset=utf-8", head)
            return
        if sub == "/live-shim.js" and method in ("GET", "HEAD"):
            await _respond(send, 200, self.shim(), "text/javascript; charset=utf-8", head)
            return
        era = self.info.era
        caps = self.site.caps
        refusal = check_request(era, method, sub, scope.get("query_string", b""), caps)
        if refusal:
            await _refuse(send, refusal)
            return
        body, too_long = await _read_body(receive, caps.LIVE_MAX_BODY_BYTES)
        if too_long:
            await _refuse(send, Refusal(413, f"The request is longer than {caps.LIVE_MAX_BODY_BYTES} bytes."))
            return
        refusal = check_body(era, method, sub, body)
        headers = _headers(scope)
        client = client_of(headers, (scope.get("client") or ("unknown", 0))[0])
        if refusal is None and costly_read(method, sub, scope.get("query_string", b"")):
            refusal = self.site.guard.admit_read(client)
        if refusal:
            await _refuse(send, refusal)
            return
        poll = run_start(era, method, sub)
        if poll is not None:
            await self.hold(app, scope, sub, body, poll, client, headers.get("x-live-hold") == "ndjson", send)
            return
        await _forward(app, scope, body, receive, send)

    async def hold(
        self,
        app: Any,
        scope: Scope,
        sub: str,
        body: bytes,
        poll: str,
        client: str,
        stream: bool,
        send: Send,
    ) -> None:
        """Start the run through the version, then hold the answer open until it has finished."""
        ticket = self.site.guard.admit_run(client)
        if isinstance(ticket, Refusal):
            await _refuse(send, ticket)
            return
        try:
            status, headers, answer = await call(app, scope, "POST", sub, body)
            run_id = _run_id(answer) if 200 <= status < 300 else None
            if run_id is None:
                await _respond(send, status, answer, headers.get("content-type", "application/json"))
                return
            ticket.accept()
            await self._hold(app, scope, status, answer, poll.format(id=quote(run_id, safe="")), run_id, stream, send)
        finally:
            ticket.release()

    async def _hold(
        self,
        app: Any,
        scope: Scope,
        status: int,
        answer: bytes,
        poll_path: str,
        run_id: str,
        stream: bool,
        send: Send,
    ) -> None:
        connected = True

        async def emit(chunk: bytes, more: bool = True) -> None:
            nonlocal connected
            if not connected:
                return
            try:
                await send({"type": "http.response.body", "body": chunk, "more_body": more})
            except Exception:  # noqa: BLE001 - the visitor left; the run still finishes here
                connected = False

        content_type = "application/x-ndjson" if stream else "application/json"
        await send(
            {
                "type": "http.response.start",
                "status": 200 if stream else status,
                "headers": [
                    (b"content-type", content_type.encode()),
                    (b"cache-control", b"no-store"),
                    (b"x-accel-buffering", b"no"),
                ],
            }
        )
        deadline = time.monotonic() + self.site.caps.LIVE_HOLD_SECONDS
        run_status, run_body = await self._run(app, scope, poll_path)
        if stream:
            await emit(_line("started", status=status, body=answer, run=run_body))
        last_digest = _digest(run_body)
        last_progress = last_tick = time.monotonic()
        while run_status not in FINISHED and time.monotonic() < deadline:
            await anyio.sleep(POLL_SECONDS)
            run_status, run_body = await self._run(app, scope, poll_path)
            now = time.monotonic()
            digest = _digest(run_body)
            if stream and run_body and digest != last_digest and (
                now - last_progress >= PROGRESS_SECONDS or run_status in FINISHED
            ):
                await emit(_line("progress", run=run_body))
                last_digest, last_progress, last_tick = digest, now, now
            elif now - last_tick >= TICK_SECONDS:
                await emit(_line("tick", seconds=round(now - (deadline - self.site.caps.LIVE_HOLD_SECONDS))) if stream else b" ")
                last_tick = now
        if not stream:
            await emit(answer, more=False)
            return
        if run_status not in FINISHED:
            message = (
                f"The run was still going after {self.site.caps.LIVE_HOLD_SECONDS} seconds, the "
                "longest this server holds a request; it may not finish here."
            )
            await emit(_line("timeout", message=message), more=False)
            return
        extras: dict[str, dict[str, str]] = {}
        for template in EXTRAS[self.info.era]:
            path = template.format(id=quote(run_id, safe=""))
            extra_status, extra_headers, extra_body = await call(app, scope, "GET", path)
            if extra_status == 200:
                extras[path] = {
                    "content_type": extra_headers.get("content-type", "application/json"),
                    "body": extra_body.decode("utf-8", errors="replace"),
                }
        await emit(_line("finished", run=run_body, extras=extras), more=False)

    async def _run(self, app: Any, scope: Scope, poll_path: str) -> tuple[str | None, bytes | None]:
        """The run's status and record as the version answers for it now."""
        status, _, body = await call(app, scope, "GET", poll_path)
        if status != 200:
            return None, None
        try:
            record = json.loads(body)
        except ValueError:
            return None, None
        return (record.get("status") if isinstance(record, dict) else None), body


def _starts(era: str) -> list[tuple[re.Pattern[str], str]]:
    from live.guard import RUN_STARTS

    return RUN_STARTS[era]  # type: ignore[index]


def _run_id(answer: bytes) -> str | None:
    try:
        payload = json.loads(answer)
    except ValueError:
        return None
    run_id = payload.get("id") if isinstance(payload, dict) else None
    return run_id if isinstance(run_id, str) and run_id else None


def _digest(body: bytes | None) -> str:
    return hashlib.sha256(body or b"").hexdigest()


def _line(kind: str, **fields: Any) -> bytes:
    """One JSON line; recorded answers (bytes) are embedded as they came, not re-encoded."""
    parts = [b'{"kind":' + json.dumps(kind).encode()]
    for name, value in fields.items():
        encoded = value if isinstance(value, bytes) else json.dumps(value).encode()
        parts.append(json.dumps(name).encode() + b":" + (encoded if value is not None else b"null"))
    return b",".join(parts) + b"}\n"


async def _read_body(receive: Receive, limit: int) -> tuple[bytes, bool]:
    """The request body, or (b"", True) once it passes ``limit`` bytes."""
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return b"".join(chunks), False
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > limit:
            return b"", True
        chunks.append(chunk)
        if not message.get("more_body", False):
            return b"".join(chunks), False


async def _forward(app: Any, scope: Scope, body: bytes, receive: Receive, send: Send) -> None:
    """Pass the request to the version's app with its body, and its answer back as it comes."""
    sent = False

    async def replay() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    await app(scope, replay, send)


BANNER_STYLE = """<style>
  .live-banner { font: 13px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 6px 16px; background: #eef3ea; color: #2f3a2c; border-bottom: 1px solid #cdd8c5; }
  .live-banner a { color: inherit; text-decoration: underline; }
  .live-banner .live-note { display: block; margin-top: 2px; color: #8a3b12; }
  .live-banner .live-note[hidden] { display: none; }
  @media (prefers-color-scheme: dark) {
    .live-banner { background: #1f241d; color: #d3dccd; border-bottom-color: #36402f; }
    .live-banner .live-note { color: #f0a77c; }
  }
</style>
"""
