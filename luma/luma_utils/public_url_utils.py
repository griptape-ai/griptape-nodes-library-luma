"""Shared helpers for uploading local images to Griptape Cloud and building Luma API URL lists."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from griptape.artifacts import ImageUrlArtifact
from griptape_nodes.exe_types.node_types import BaseNode
from griptape_nodes.files.file import File


def build_public_url_list(
    node: BaseNode,
    param_names: list[str],
    storage_driver: Any,
) -> tuple[list[dict], list[Path]]:
    """Resolve a list of image parameters to public URLs, uploading local ones to GTC.

    Iterates param_names in order, skipping any that resolve to None. For each valid
    value, if the URL is local or a localhost address it is uploaded via storage_driver
    so the Luma API can reach it.

    Returns:
        url_dicts: [{url: ...}] list ready to pass to the Luma API.
        uploaded_paths: GTC paths that were uploaded — pass to cleanup_uploaded_paths()
            in the node's finally block.
    """
    url_dicts: list[dict] = []
    uploaded_paths: list[Path] = []

    for param_name in param_names:
        img_value = node.get_parameter_value(param_name)
        if img_value is None:
            continue

        if isinstance(img_value, dict) and img_value.get("value"):
            img_value = ImageUrlArtifact(value=img_value["value"], name=img_value.get("name", "image"))

        url = img_value.value if isinstance(img_value, ImageUrlArtifact) else str(img_value)

        if not (url.startswith(("http://", "https://")) and "localhost" not in url):
            file_contents = File(url).read_bytes()
            filename = Path(urlparse(url).path).name
            gtc_path = Path("artifact_url_storage") / uuid4().hex / filename
            url = storage_driver.upload_file(path=gtc_path, file_content=file_contents)
            uploaded_paths.append(gtc_path)

        url_dicts.append({"url": url})

    return url_dicts, uploaded_paths


def cleanup_uploaded_paths(storage_driver: Any, uploaded_paths: list[Path]) -> None:
    """Delete files previously uploaded to GTC storage."""
    for path in uploaded_paths:
        storage_driver.delete_file(path)
