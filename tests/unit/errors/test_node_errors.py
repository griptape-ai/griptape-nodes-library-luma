"""NodeError behaviour of the Luma nodes, through the real Luma SDK path.

A local HTTP server stands in for the Luma API (the SDK reads `LUMA_BASE_URL`), so each error comes from the
SDK's own exception types rather than one built by hand.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from griptape_nodes.exe_types.core_types import NodeError
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

LIBRARY_DIR = Path(__file__).resolve().parents[3] / "luma"
MANIFEST = json.loads((LIBRARY_DIR / "griptape_nodes_library.json").read_text())
NODES = [(n["class_name"], n["file_path"]) for n in MANIFEST["nodes"]]

KEY_NAME = "LUMA_AGENTS_API_KEY"
SOURCE_URL = "https://files.example.com/source.png"
VIDEO_URL = "https://files.example.com/source.mp4"


@pytest.fixture(autouse=True)
def cloud_credential(monkeypatch):
    # PublicArtifactUrlParameter raises in __init__ without a Griptape Cloud credential.
    monkeypatch.setenv("GT_CLOUD_API_KEY", "test-cloud-key")


def load_node_class(class_name: str, file_name: str):
    """Load a node file the way the engine does: standalone, library folder on sys.path, no package."""
    sys.path.insert(0, str(LIBRARY_DIR))
    sys.modules["luma"] = None  # type: ignore[assignment]
    try:
        spec = importlib.util.spec_from_file_location(f"_engine_style_{file_name[:-3]}", LIBRARY_DIR / file_name)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(LIBRARY_DIR))
        del sys.modules["luma"]
    return getattr(module, class_name)


class FakeLuma:
    """Serves scripted responses: `create` answers POST /generations, `polls` answer GET in order (last repeats)."""

    def __init__(self, create: tuple[int, object], polls: list[tuple[int, object]] | None = None) -> None:
        outer = self
        self.create = create
        self.polls = polls or []
        self.poll_count = 0

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status: int, body: object) -> None:
                payload = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("x-request-id", "req-123")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers.get("content-length", 0)))
                self._send(*outer.create)

            def do_GET(self):  # noqa: N802
                index = min(outer.poll_count, len(outer.polls) - 1)
                outer.poll_count += 1
                self._send(*outer.polls[index])

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def generation(state: str, **extra: object) -> dict:
    return {
        "id": "gen-1",
        "created_at": "2026-01-01T00:00:00Z",
        "model": "uni-1",
        "state": state,
        "type": "image",
        **extra,
    }


@pytest.fixture
def luma(monkeypatch):
    servers = []

    def make(create, polls=None):
        server = FakeLuma(create, polls)
        servers.append(server)
        monkeypatch.setenv("LUMA_BASE_URL", server.url)
        return server

    yield make
    for server in servers:
        server.close()


def set_luma_key(monkeypatch, value: str | None) -> None:
    """Set only the Luma key. Other secrets, such as the Griptape Cloud credential, keep resolving."""

    def get_secret(name, *_args, **_kwargs):
        return value if name == KEY_NAME else "test-cloud-key"

    monkeypatch.setattr(GriptapeNodes.SecretsManager(), "get_secret", get_secret, raising=False)


@pytest.fixture
def with_key(monkeypatch):
    set_luma_key(monkeypatch, "test-key")


@pytest.fixture
def no_wait(monkeypatch):
    async def _instant(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


def make_node(class_name: str, file_name: str, **values):
    node = load_node_class(class_name, file_name)(name="luma-node")
    node.parameter_values["prompt"] = "a cat"
    if class_name in {"LumaImageEdit", "LumaImageLayer"}:
        node.parameter_values["source_image"] = SOURCE_URL
        node._public_source_parameter.get_public_url_for_parameter = lambda: SOURCE_URL
    if class_name in {"LumaVideoReframe", "LumaVideoModify"}:
        node.parameter_values["input_video"] = VIDEO_URL
        node._public_input_video_parameter.get_public_url_for_parameter = lambda: VIDEO_URL
    for name, value in values.items():
        node.parameter_values[name] = value
    return node


def run(node, *, failed_wired: bool) -> None:
    node._has_outgoing_connections = lambda _param: failed_wired
    asyncio.run(node.aprocess())


def raised_by(node) -> NodeError:
    with pytest.raises(NodeError) as caught:
        run(node, failed_wired=False)
    return caught.value


GEN = ("LumaImageGeneration", "image_generation.py")


@pytest.mark.parametrize(("class_name", "file_name"), NODES)
def test_node_loads_engine_style(class_name, file_name):
    assert load_node_class(class_name, file_name).__name__ == class_name


@pytest.mark.parametrize(("class_name", "file_name"), NODES)
def test_missing_key_is_the_only_validation_error(class_name, file_name, monkeypatch):
    set_luma_key(monkeypatch, None)
    node = make_node(class_name, file_name, prompt="")
    errors = node.validate_before_node_run()
    assert errors is not None
    assert len(errors) == 1
    error = errors[0]
    assert isinstance(error, NodeError)
    assert str(error) == f"{KEY_NAME} is not set. Add it in Settings → API Keys & Secrets, then run the node again."
    assert error.links[0].url == f"#settings-secrets?filter={KEY_NAME}"
    assert error.links[1].url == "https://platform.lumalabs.ai"


@pytest.mark.parametrize(("class_name", "file_name"), NODES)
def test_workflow_run_validation_is_not_overridden(class_name, file_name):
    cls = load_node_class(class_name, file_name)
    assert "validate_before_workflow_run" not in vars(cls)


@pytest.mark.parametrize(("class_name", "file_name"), NODES)
def test_missing_key_at_run_time(class_name, file_name, monkeypatch):
    set_luma_key(monkeypatch, None)
    error = raised_by(make_node(class_name, file_name))
    assert str(error).startswith(f"{KEY_NAME} is not set.")
    assert error.links[0].url == f"#settings-secrets?filter={KEY_NAME}"


def test_input_problems_carry_no_node_name_prefix(with_key):
    node = make_node(*GEN, prompt="")
    errors = node.validate_before_node_run()
    assert errors is not None
    assert [str(e) for e in errors] == ["Enter a prompt in 'Prompt'."]
    assert errors[0].fields == {"parameter": "prompt"}


def test_video_generation_keyframe_problems(with_key):
    node = make_node("LumaVideoGeneration", "video_generation.py", hdr=True, resolution="360p", loop=True)
    messages = [str(e) for e in node.validate_before_node_run() or []]
    assert messages == [
        "'HDR Output' needs 'Resolution' set to 720p or 1080p.",
        "'Loop Video' is not supported with 'HDR Output'. Turn one of them off.",
    ]


def test_403_is_not_treated_as_a_refused_key(luma, with_key):
    luma((403, {"detail": "Your plan does not include this model"}))
    error = raised_by(make_node(*GEN))
    assert str(error) == "Your plan does not include this model"
    assert error.fields["status_code"] == 403
    assert error.links == []


def test_refused_key(luma, with_key):
    luma((401, {"detail": "Missing or invalid API key"}))
    error = raised_by(make_node(*GEN))
    assert str(error).startswith("Luma refused the API key.")
    assert error.fields == {"status_code": 401, "request_id": "req-123"}
    assert error.response == {"detail": "Missing or invalid API key"}
    assert [link.url for link in error.links] == [f"#settings-secrets?filter={KEY_NAME}"]


def test_connection_failure(with_key, monkeypatch):
    monkeypatch.setenv("LUMA_BASE_URL", "http://127.0.0.1:9/v1")
    error = raised_by(make_node(*GEN))
    assert str(error) == "Could not reach Luma. Check your internet connection and run the node again."


def test_generation_failed_state(luma, with_key, no_wait):
    luma(
        (200, generation("queued")),
        [(200, generation("failed", failure_code="content_moderated", failure_reason="The prompt was moderated."))],
    )
    error = raised_by(make_node(*GEN))
    assert str(error) == "The prompt was moderated."
    assert error.fields == {"generation_id": "gen-1", "status": "failed", "error_code": "content_moderated"}
    assert error.response == {"failure_code": "content_moderated", "failure_reason": "The prompt was moderated."}


def test_poll_failure_carries_generation_id(luma, with_key, no_wait):
    luma((200, generation("queued")), [(404, {"detail": "Not Found"})])
    error = raised_by(make_node(*GEN))
    assert str(error) == "Not Found"
    assert error.fields == {"status_code": 404, "request_id": "req-123", "generation_id": "gen-1"}


def test_timeout(luma, with_key, no_wait):
    server = luma((200, generation("queued")), [(200, generation("processing"))])
    error = raised_by(make_node(*GEN))
    assert str(error).startswith("Luma was still working after 240 seconds")
    assert error.fields == {"generation_id": "gen-1", "status": "processing"}
    assert server.poll_count == 120


def test_completed_without_output(luma, with_key, no_wait):
    luma((200, generation("queued")), [(200, generation("completed", output=[]))])
    error = raised_by(make_node(*GEN))
    assert str(error) == "Luma reported the generation as completed but returned no output file. Run the node again."
    assert error.fields == {"generation_id": "gen-1", "status": "completed"}


def test_failure_follows_wired_failed_output(luma, with_key):
    luma((401, {"detail": "Missing or invalid API key"}))
    node = make_node(*GEN)
    run(node, failed_wired=True)
    assert node.parameter_output_values["was_successful"] is False
    assert "Luma refused the API key" in node.parameter_output_values["result_details"]


@pytest.mark.parametrize(
    ("class_name", "file_name", "list_attr", "set_up", "label", "list_name"),
    [
        (
            "LumaImageGeneration",
            "image_generation.py",
            "_image_refs_list",
            {"reference_type": "image_reference"},
            "Reference Images",
            "image_refs",
        ),
        ("LumaImageEdit", "image_edit.py", "_image_refs_list", {}, "Additional References", "image_refs"),
        (
            "LumaVideoGeneration",
            "video_generation.py",
            "_keyframe_images_list",
            {"image_input_mode": "keyframes"},
            "Keyframe Images",
            "keyframe_images",
        ),
    ],
)
def test_upstream_error_in_a_list_names_the_list_not_the_child_id(
    class_name, file_name, list_attr, set_up, label, list_name, with_key
):
    from griptape.artifacts import ErrorArtifact

    node = make_node(class_name, file_name, **set_up)
    getattr(node, list_attr).add_child_parameter()
    child = getattr(node, list_attr).get_child_parameters()[0]
    assert "ParameterListUniqueParamID" in child.name
    node.parameter_values[child.name] = ErrorArtifact("upstream blew up")
    if class_name == "LumaVideoGeneration":
        node._keyframe_indexes_list.add_child_parameter()
    error = raised_by(node)
    assert str(error) == f"An image connected to '{label}' comes from a node that failed: upstream blew up"
    assert "ParameterListUniqueParamID" not in str(error)
    assert error.fields == {"parameter": list_name}
