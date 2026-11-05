"""Errors the Luma nodes raise beyond what `NodeError` builds itself.

A refused or missing API key and a failed Luma call come from `NodeError.from_missing_secret` and
`NodeError.from_request_exception`. This module wraps them with Luma's key name, and covers a generation
that ends without a usable result.
"""

from __future__ import annotations

from griptape_nodes.exe_types.core_types import NodeError
from luma_agents import APIConnectionError
from luma_agents.types import Generation

API_KEY_NAME = "LUMA_AGENTS_API_KEY"
API_KEY_URL = "https://platform.lumalabs.ai"
PROVIDER = "Luma"


def missing_key_error() -> NodeError:
    return NodeError.from_missing_secret(API_KEY_NAME, key_url=API_KEY_URL)


def input_error(message: str, parameter: str) -> NodeError:
    return NodeError(message, fields={"parameter": parameter})


def error_from_api_exception(error: Exception, *, generation_id: str | None = None) -> NodeError:
    """The error for a failed Luma SDK call. The SDK wraps connection and timeout errors, so unwrap them."""
    cause = error.__cause__
    if isinstance(error, APIConnectionError) and isinstance(cause, Exception):
        error = cause
    fields = {"generation_id": generation_id} if generation_id else None
    return NodeError.from_request_exception(error, provider=PROVIDER, secret_name=API_KEY_NAME, fields=fields)


def generation_error(generation: Generation, message: str) -> NodeError:
    """The error for a generation that ended without a result (timed out or no output)."""
    return NodeError(message, fields={"generation_id": generation.id, "status": generation.state})


def generation_failed_error(generation: Generation) -> NodeError:
    """The error for a generation that finished in the `failed` state, with Luma's code and reason."""
    fields: dict[str, str | int | float | bool] = {"generation_id": generation.id, "status": generation.state}
    if generation.failure_code:
        fields["error_code"] = generation.failure_code
    response = {"failure_code": generation.failure_code, "failure_reason": generation.failure_reason}
    message = (generation.failure_reason or "").strip() or "Luma could not complete the generation."
    return NodeError(message, fields=fields, response=response)
