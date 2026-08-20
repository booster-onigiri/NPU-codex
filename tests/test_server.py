import gzip
import json

import pytest
from fastapi.testclient import TestClient

from npu_codex.config import AppConfig
from npu_codex.server import create_app
from tests.support import QueueBackend


def make_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "server": {"host": "127.0.0.1", "port": 8765, "keepalive_seconds": 0.1},
            "model": {"backend": "mock", "id": "local-coder"},
            "agent": {"max_repair_attempts": 0, "response_chunk_chars": 8},
        }
    )


def test_non_streaming_message_response() -> None:
    backend = QueueBackend(['{"type":"message","text":"hello"}'])
    client = TestClient(create_app(make_config(), backend), base_url="http://127.0.0.1")
    response = client.post(
        "/v1/responses",
        json={"model": "local-coder", "input": "hi", "stream": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["output"][0]["content"][0]["text"] == "hello"


def test_function_call_response() -> None:
    backend = QueueBackend(
        ['{"type":"tool_call","name":"read_file","arguments":{"path":"a.py"}}']
    )
    client = TestClient(create_app(make_config(), backend), base_url="http://127.0.0.1")
    response = client.post(
        "/v1/responses",
        json={
            "model": "local-coder",
            "input": "read",
            "tools": [
                {
                    "type": "function",
                    "name": "read_file",
                    "parameters": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {"path": {"type": "string"}},
                    },
                }
            ],
        },
    )
    item = response.json()["output"][0]
    assert item["type"] == "function_call"
    assert json.loads(item["arguments"]) == {"path": "a.py"}


def test_streaming_sse() -> None:
    backend = QueueBackend(['{"type":"message","text":"streamed"}'])
    client = TestClient(create_app(make_config(), backend), base_url="http://127.0.0.1")
    with client.stream(
        "POST",
        "/v1/responses",
        json={"model": "local-coder", "input": "hi", "stream": True},
    ) as response:
        text = "".join(response.iter_text())
    assert response.status_code == 200
    assert "event: response.created" in text
    assert "event: response.output_text.delta" in text
    assert "event: response.completed" in text
    assert "data: [DONE]" in text


def test_gzip_request_body() -> None:
    backend = QueueBackend(['{"type":"message","text":"gzip-ok"}'])
    client = TestClient(create_app(make_config(), backend), base_url="http://127.0.0.1")
    payload = json.dumps({"model": "local-coder", "input": "hi"}).encode()
    response = client.post(
        "/v1/responses",
        content=gzip.compress(payload),
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert response.status_code == 200
    assert response.json()["output"][0]["content"][0]["text"] == "gzip-ok"


def test_rejects_non_loopback_host_header() -> None:
    backend = QueueBackend(['{"type":"message","text":"no"}'])
    client = TestClient(create_app(make_config(), backend), base_url="http://example.test")
    response = client.get("/healthz")
    assert response.status_code == 400


def test_rejects_gzip_body_that_expands_past_limit() -> None:
    config = AppConfig.model_validate(
        {
            "server": {"host": "127.0.0.1", "port": 8765},
            "model": {"backend": "mock", "id": "local-coder"},
            "security": {"max_request_bytes": 1024},
        }
    )
    backend = QueueBackend(['{"type":"message","text":"not-called"}'])
    client = TestClient(create_app(config, backend), base_url="http://127.0.0.1")
    payload = json.dumps(
        {"model": "local-coder", "input": "x" * 4096}, separators=(",", ":")
    ).encode()
    response = client.post(
        "/v1/responses",
        content=gzip.compress(payload),
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert response.status_code == 413
    assert backend.prompts == []


def test_optional_bearer_token(monkeypatch) -> None:
    config = AppConfig.model_validate(
        {
            "server": {"host": "127.0.0.1", "port": 8765},
            "model": {"backend": "mock", "id": "local-coder"},
            "security": {"api_token_env": "NPU_CODEX_TEST_TOKEN"},
        }
    )
    monkeypatch.setenv("NPU_CODEX_TEST_TOKEN", "local-secret")
    backend = QueueBackend(['{"type":"message","text":"authorized"}'])
    client = TestClient(create_app(config, backend), base_url="http://127.0.0.1")

    unauthorized = client.get("/healthz")
    assert unauthorized.status_code == 401

    authorized = client.get(
        "/healthz", headers={"Authorization": "Bearer local-secret"}
    )
    assert authorized.status_code == 200


def test_custom_tool_call_response() -> None:
    backend = QueueBackend(
        ['{"type":"custom_tool_call","name":"apply_patch","input":"*** Begin Patch"}']
    )
    client = TestClient(create_app(make_config(), backend), base_url="http://127.0.0.1")
    response = client.post(
        "/v1/responses",
        json={
            "model": "local-coder",
            "input": "patch",
            "tools": [
                {
                    "type": "custom",
                    "name": "apply_patch",
                    "description": "Apply a patch",
                    "format": {"type": "grammar", "syntax": "lark", "definition": "start: /.+/"},
                }
            ],
        },
    )
    assert response.status_code == 200
    item = response.json()["output"][0]
    assert item["type"] == "custom_tool_call"
    assert item["name"] == "apply_patch"
    assert item["input"] == "*** Begin Patch"


def test_streaming_function_call_events() -> None:
    backend = QueueBackend(
        ['{"type":"tool_call","name":"read_file","arguments":{"path":"a.py"}}']
    )
    client = TestClient(create_app(make_config(), backend), base_url="http://127.0.0.1")
    with client.stream(
        "POST",
        "/v1/responses",
        json={
            "model": "local-coder",
            "input": "read",
            "stream": True,
            "tools": [
                {
                    "type": "function",
                    "name": "read_file",
                    "parameters": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {"path": {"type": "string"}},
                    },
                }
            ],
        },
    ) as response:
        text = "".join(response.iter_text())
    assert response.status_code == 200
    assert "event: response.function_call_arguments.delta" in text
    assert "event: response.function_call_arguments.done" in text
    assert "event: response.output_item.done" in text


def test_unknown_model_is_invalid_request() -> None:
    backend = QueueBackend(['{"type":"message","text":"unused"}'])
    client = TestClient(create_app(make_config(), backend), base_url="http://127.0.0.1")
    response = client.post(
        "/v1/responses",
        json={"model": "not-configured", "input": "hi"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert backend.prompts == []


def test_zstd_request_body() -> None:
    zstandard = pytest.importorskip("zstandard")
    backend = QueueBackend(['{"type":"message","text":"zstd-ok"}'])
    client = TestClient(create_app(make_config(), backend), base_url="http://127.0.0.1")
    payload = json.dumps({"model": "local-coder", "input": "hi"}).encode()
    response = client.post(
        "/v1/responses",
        content=zstandard.ZstdCompressor().compress(payload),
        headers={"Content-Type": "application/json", "Content-Encoding": "zstd"},
    )
    assert response.status_code == 200
    assert response.json()["output"][0]["content"][0]["text"] == "zstd-ok"
