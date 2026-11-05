"""Turns Luma API failures into NodeError.

Node files import this module as `luma_utils.luma_errors`. The engine loads each node file on its own with
the manifest's folder (`luma/`) on `sys.path`, so neither the repository's package name nor a relative
import resolves.
"""

from __future__ import annotations

from typing import Any

from griptape_nodes.exe_types.core_types import NodeError, NodeErrorLink
from luma_agents import APIConnectionError, APIError, APIStatusError, APITimeoutError
from luma_agents.types import Generation

API_KEY_NAME = "LUMA_AGENTS_API_KEY"
API_KEY_URL = "https://platform.lumalabs.ai"

_KEY_REFUSED_STATUSES = (401, 403)
_RATE_LIMITED_STATUS = 429
_MAX_TEXT_CHARS = 2000


def missing_key_error() -> NodeError:
    """The error for a missing LUMA_AGENTS_API_KEY, linking to Settings and to Luma's key page."""
    return NodeError(
        f"{API_KEY_NAME} is not set. Add it in Settings → API Keys & Secrets, then run the node again.",
        links=[
            NodeErrorLink(label="Add the API key", url=f"#settings-secrets?filter={API_KEY_NAME}"),
            NodeErrorLink(label="Get a Luma API key", url=API_KEY_URL),
        ],
    )


def input_error(message: str, parameter: str) -> NodeError:
    """The error for a bad or missing input, naming the parameter in `fields`."""
    return NodeError(message, fields={"parameter": parameter})


def error_from_api_exception(error: Exception, *, generation_id: str | None = None) -> NodeError:
    """Build a NodeError from an exception raised by the Luma SDK."""
    if isinstance(error, APIStatusError):
        return _error_from_status(error, generation_id)

    fields: dict[str, str | int | float | bool] = {}
    if generation_id:
        fields["generation_id"] = generation_id
    if isinstance(error, APITimeoutError):
        message = "The request to Luma timed out. Run the node again."
    elif isinstance(error, APIConnectionError):
        message = "Could not connect to Luma. Check your network connection and run the node again."
    elif isinstance(error, APIError):
        message = f"The request to Luma failed: {error.message}"
    else:
        message = f"The request to Luma failed: {error}"
    return NodeError(message, fields=fields or None)


def generation_failed_error(generation: Generation) -> NodeError:
    """Build a NodeError from a generation that finished in the `failed` state."""
    fields: dict[str, str | int | float | bool] = {"generation_id": generation.id, "status": generation.state}
    if generation.failure_code:
        fields["error_code"] = generation.failure_code
    reason = (generation.failure_reason or "").strip()
    message = reason or "Luma could not complete the generation."
    response = {"failure_code": generation.failure_code, "failure_reason": generation.failure_reason}
    return NodeError(message, fields=fields, response=response)


def generation_timeout_error(generation: Generation, waited_seconds: int) -> NodeError:
    """Build a NodeError for a generation that was still running when the node stopped waiting."""
    return NodeError(
        f"Luma was still working after {waited_seconds} seconds, so the node stopped waiting. "
        "Run the node again, or try a simpler request.",
        fields={"generation_id": generation.id, "status": generation.state},
    )


def no_output_error(generation: Generation) -> NodeError:
    """Build a NodeError for a completed generation that carries no output file."""
    return NodeError(
        "Luma reported the generation as completed but returned no output file. Run the node again.",
        fields={"generation_id": generation.id, "status": generation.state},
    )


def _error_from_status(error: APIStatusError, generation_id: str | None) -> NodeError:
    status = error.status_code
    body = error.body if isinstance(error.body, dict) and error.body else None
    reason = _reason(body)

    fields: dict[str, str | int | float | bool] = {"status_code": status}
    request_id = error.response.headers.get("x-request-id")
    if request_id:
        fields["request_id"] = request_id
    if generation_id:
        fields["generation_id"] = generation_id

    links: list[NodeErrorLink] = []
    if status in _KEY_REFUSED_STATUSES:
        message = f"Luma refused the API key: {reason.rstrip('.')}." if reason else "Luma refused the API key."
        message += " Update it in Settings and run the node again."
        links.append(NodeErrorLink(label="Update the API key", url=f"#settings-secrets?filter={API_KEY_NAME}"))
        links.append(NodeErrorLink(label="Get a Luma API key", url=API_KEY_URL))
    elif status == _RATE_LIMITED_STATUS:
        message = reason or "Luma is rate-limiting requests. Wait a minute and run the node again."
    else:
        message = reason or f"Luma returned an error (HTTP {status})."

    response = body
    if response is None and isinstance(error.body, str) and error.body:
        response = {"text": error.body[:_MAX_TEXT_CHARS]}
    return NodeError(message, fields=fields, response=response, links=links or None)


def _reason(body: dict[str, Any] | None) -> str | None:
    """Luma's own explanation: `detail`, `error` or `message` as text, or the messages in a validation list."""
    if body is None:
        return None
    for key in ("detail", "error", "message"):
        text = _text(body.get(key))
        if text:
            return text
    return None


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return _text(value.get("message") or value.get("msg"))
    if isinstance(value, list):
        parts = []
        for item in value:
            if not isinstance(item, dict):
                continue
            msg = _text(item.get("msg") or item.get("message"))
            if not msg:
                continue
            loc = item.get("loc")
            where = ".".join(str(p) for p in loc if p != "body") if isinstance(loc, list) else ""
            parts.append(f"{where}: {msg}" if where else msg)
        return "; ".join(parts) or None
    return None
