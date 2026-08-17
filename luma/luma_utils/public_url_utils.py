"""Shared helpers for uploading local images to Griptape Cloud and building Luma API URL lists."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from griptape.artifacts import ErrorArtifact
from griptape.artifacts.url_artifact import UrlArtifact
from griptape_nodes.common.parameter_hydration import hydrate_value
from griptape_nodes.exe_types.node_types import BaseNode
from griptape_nodes.files.file import File


def _is_public_url(url: str) -> bool:
    """Return True if url points at a non-local http/https host."""
    if not url.startswith(("http://", "https://")):
        return False
    hostname = urlparse(url).hostname or ""
    return hostname not in {"localhost", "127.0.0.1"}


def build_public_url_list(
    node: BaseNode,
    param_names: list[str],
    storage_driver: Any,
) -> tuple[list[dict], list[Path]]:
    """Resolve a list of image parameters to public URLs, uploading local ones to GTC.

    Iterates param_names in order, skipping any that resolve to None. For each valid
    value, if the URL is local it is uploaded via storage_driver so the Luma API can
    reach it.

    If any upload fails mid-loop, already-uploaded files are cleaned up before the
    exception propagates so no paths are orphaned in the bucket.

    Returns:
        url_dicts: [{url: ...}] list ready to pass to the Luma API.
        uploaded_paths: GTC paths that were uploaded — pass to cleanup_uploaded_paths()
            in the node's finally block.
    """
    url_dicts: list[dict] = []
    uploaded_paths: list[Path] = []

    try:
        for param_name in param_names:
            img_value = hydrate_value(node.get_parameter_value(param_name))
            if img_value is None:
                continue

            if isinstance(img_value, ErrorArtifact):
                raise RuntimeError(f"Parameter '{param_name}' contains an upstream error: {img_value.value}")

            url = img_value.value if isinstance(img_value, UrlArtifact) else str(img_value)

            if not _is_public_url(url):
                file_contents = File(url).read_bytes()
                filename = Path(urlparse(url).path).name
                gtc_path = Path("artifact_url_storage") / uuid4().hex / filename
                url = storage_driver.upload_file(path=gtc_path, file_content=file_contents)
                uploaded_paths.append(gtc_path)

            url_dicts.append({"url": url})

    except Exception:
        cleanup_uploaded_paths(storage_driver, uploaded_paths)
        raise

    return url_dicts, uploaded_paths


def cleanup_uploaded_paths(storage_driver: Any, uploaded_paths: list[Path]) -> None:
    """Delete files previously uploaded to GTC storage.

    Continues past individual delete failures so all paths are attempted.
    """
    for path in uploaded_paths:
        try:
            storage_driver.delete_file(path)
        except Exception:  # noqa: BLE001
            pass
