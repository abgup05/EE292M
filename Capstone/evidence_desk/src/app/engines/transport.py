"""How a model request reaches a model: the transport port and its Anthropic API adapter.

The Claude engine builds each request (system prompt, user prompt, JSON schema)
and parses each answer; a :data:`Transport` only carries a :class:`ModelRequest`
to a model and brings back the JSON object it answered. The API adapter here
sends it with the official SDK; :mod:`app.engines.cassette` replays recorded
answers instead.

The request shape (beta header, ``output_config`` and ``fallbacks`` in the
body) is the one verified against the live API for the first milestone.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_API_MESSAGE_CHARS = 200
API_VIA = "the Anthropic API"

# The model steps, in the order a run makes them: each depends on the answers before it. A
# claim's "check" (app.engines.checker) reads that claim's assessment; the summary reads the
# verdicts the checks decide; the corollaries are proposed from the final verdicts
# ("propose", app.engines.analyser) and the argued analysis reads the corollaries computed
# from them ("analyse").
STEPS = ("plan", "assess", "check", "summarize", "propose", "analyse", "conclude")


class EngineError(RuntimeError):
    """The model call failed or returned something unusable. The message is safe to show."""


@dataclass(frozen=True)
class ModelRequest:
    """One structured-output request, complete: what a model needs to answer it.

    ``step`` names the model step (one of :data:`STEPS`, or a model reader's);
    ``schema`` is the JSON schema the answer must satisfy; ``max_tokens``
    bounds the answer's length. ``timeout`` (seconds) bounds one API call and turns off
    the SDK's retries, so the request cannot run past it; None keeps the SDK's defaults.
    It is not part of what was asked, so it is not part of a cassette's key.
    """

    step: str
    system: str
    user: str
    schema: dict[str, Any]
    max_tokens: int
    timeout: float | None = field(default=None, compare=False)


# A transport takes a request and returns the model's answer as one JSON object.
# Every failure is raised as :class:`EngineError`.
Transport = Callable[[ModelRequest], dict[str, Any]]


def describe_api_error(exc: Exception) -> str:
    """A safe account of a failed SDK call.

    For an HTTP status error, the status and the API's own error type and
    message (which describe our request, never the key) are included, cut to
    ``MAX_API_MESSAGE_CHARS``. For anything else, the class name only.
    """
    description = f"Model request failed: {exc.__class__.__name__}"
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        return description
    body = getattr(exc, "body", None)
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return f"{description} (HTTP {status})"
    kind = str(error.get("type", "error"))
    message = " ".join(str(error.get("message", "")).split())[:MAX_API_MESSAGE_CHARS]
    return f"{description} (HTTP {status}, {kind}: {message})"


class AnthropicTransport:
    """Sends a :class:`ModelRequest` to Claude through the official SDK.

    ``model`` defaults to ``$ANTHROPIC_MODEL``, then :data:`DEFAULT_MODEL`. The
    SDK client is created on first use, so building this needs no key.
    """

    via = API_VIA

    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        self.model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
        self._client = client
        self._client_lock = threading.Lock()

    @property
    def client(self) -> Any:
        """The SDK client, created on first use so tests and the extractive path need no key.

        Claims are assessed on several threads at once; the lock makes them share one client.
        """
        with self._client_lock:
            if self._client is None:
                import anthropic

                self._client = anthropic.Anthropic()
            return self._client

    @property
    def detail(self) -> str:
        """Which model answers, and how: shown on the run record."""
        return f"{self.model} via {self.via}"

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        """One structured-output request; every failure becomes :class:`EngineError`."""
        try:
            import anthropic

            api_errors: tuple[type[Exception], ...] = (anthropic.APIError,)
        except ImportError:  # pragma: no cover - the SDK is installed in the image
            api_errors = ()
        client = self.client
        if request.timeout is not None and hasattr(client, "with_options"):
            client = client.with_options(timeout=request.timeout, max_retries=0)
        try:
            response = client.beta.messages.create(
                model=self.model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=[{"role": "user", "content": request.user}],
                betas=[FALLBACK_BETA],
                extra_body={
                    "output_config": {"format": {"type": "json_schema", "schema": request.schema}},
                    "fallbacks": "default",
                },
            )
        except api_errors as exc:
            raise EngineError(describe_api_error(exc)) from exc
        if response.stop_reason == "refusal":
            raise EngineError("The model declined this request")
        if response.stop_reason == "max_tokens":
            raise EngineError("The model response was truncated")
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise EngineError("The model returned no text")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise EngineError("The model returned malformed JSON") from exc
        if not isinstance(data, dict):
            raise EngineError("The model returned a non-object JSON value")
        return data
