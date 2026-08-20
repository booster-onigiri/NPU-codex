from __future__ import annotations

import asyncio
import gzip
import hmac
import io
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .backends import InferenceBackend, create_backend
from .config import AppConfig, is_loopback_host
from .protocol import (
    ResponsesRequest,
    failed_response,
    new_response_id,
    sse_encode,
    stream_events,
)
from .runtime import AgentRuntime
from .version import __version__


ASGIReceive = Callable[[], Awaitable[dict[str, Any]]]
ASGISend = Callable[[dict[str, Any]], Awaitable[None]]


async def _send_json_error(send: ASGISend, status: int, message: str) -> None:
    body = json.dumps({"error": {"message": message, "type": "invalid_request_error"}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class DecodeContentEncodingMiddleware:
    """Decode gzip/zstd request bodies before FastAPI parses JSON."""

    def __init__(self, app: Any, max_request_bytes: int) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope: dict[str, Any], receive: ASGIReceive, send: ASGISend) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = list(scope.get("headers") or [])
        header_map = {key.lower(): value for key, value in headers}
        content_length = header_map.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_request_bytes:
                    await _send_json_error(send, 413, "request body is too large")
                    return
            except ValueError:
                await _send_json_error(send, 400, "invalid Content-Length header")
                return

        chunks: list[bytes] = []
        total = 0
        more_body = True
        while more_body:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_request_bytes:
                await _send_json_error(send, 413, "request body is too large")
                return
            chunks.append(chunk)
            more_body = bool(message.get("more_body"))

        body = b"".join(chunks)
        encoding = header_map.get(b"content-encoding", b"identity").decode("ascii", "ignore").lower()
        try:
            if encoding in {"", "identity"}:
                decoded = body
            elif encoding == "gzip":
                with gzip.GzipFile(fileobj=io.BytesIO(body), mode="rb") as stream:
                    decoded = stream.read(self.max_request_bytes + 1)
            elif encoding == "zstd":
                import zstandard  # type: ignore[import-not-found]

                with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(body)) as stream:
                    decoded = stream.read(self.max_request_bytes + 1)
            else:
                await _send_json_error(send, 415, f"unsupported Content-Encoding: {encoding}")
                return
        except Exception as exc:
            await _send_json_error(send, 400, f"could not decode request body: {exc}")
            return

        if len(decoded) > self.max_request_bytes:
            await _send_json_error(send, 413, "decoded request body is too large")
            return

        filtered_headers = [
            (key, value)
            for key, value in headers
            if key.lower() not in {b"content-encoding", b"content-length"}
        ]
        filtered_headers.append((b"content-length", str(len(decoded)).encode()))
        child_scope = dict(scope)
        child_scope["headers"] = filtered_headers
        delivered = False

        async def decoded_receive() -> dict[str, Any]:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": decoded, "more_body": False}
            # StreamingResponse runs a disconnect watcher in parallel.  Once the
            # decoded request body has been delivered, delegate to the original
            # receive channel so that watcher can observe http.disconnect.
            return await receive()

        await self.app(child_scope, decoded_receive, send)


def _error_body(message: str) -> dict[str, Any]:
    return {
        "error": {
            "message": message,
            "type": "server_error",
            "code": "npu_codex_error",
        }
    }


def create_app(config: AppConfig, backend: InferenceBackend | None = None) -> FastAPI:
    active_backend = backend or create_backend(config.model)
    runtime = AgentRuntime(config, active_backend)
    app = FastAPI(
        title="NPU Codex local Responses bridge",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = config
    app.state.backend = active_backend
    app.state.runtime = runtime
    app.add_middleware(
        DecodeContentEncodingMiddleware,
        max_request_bytes=config.security.max_request_bytes,
    )

    @app.middleware("http")
    async def security_guard(request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        if config.security.validate_host_header:
            hostname = request.url.hostname or ""
            if not is_loopback_host(hostname):
                return JSONResponse(
                    status_code=400,
                    content=_error_body("Host header must identify a loopback address"),
                )

        token_env = config.security.api_token_env
        if token_env:
            expected = os.environ.get(token_env)
            if not expected:
                return JSONResponse(
                    status_code=503,
                    content=_error_body(f"required token environment variable {token_env!r} is unset"),
                )
            supplied = request.headers.get("authorization", "")
            prefix = "Bearer "
            candidate = supplied[len(prefix) :] if supplied.startswith(prefix) else ""
            if not hmac.compare_digest(candidate, expected):
                return JSONResponse(
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                    content={
                        "error": {
                            "message": "invalid bearer token",
                            "type": "authentication_error",
                        }
                    },
                )

        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/")
    async def root() -> dict[str, Any]:
        return {
            "name": "npu-codex",
            "version": __version__,
            "message": "Local OpenAI Responses API bridge for Codex",
        }

    @app.get("/healthz")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "model": config.model.id,
            **active_backend.status(),
        }

    @app.get("/readyz")
    async def readiness() -> JSONResponse:
        status = active_backend.status()
        ready = bool(status.get("loaded")) or config.model.backend == "mock"
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"ready": ready, **status},
        )

    @app.get("/v1/models")
    async def list_models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {
                    "id": config.model.id,
                    "object": "model",
                    "created": 0,
                    "owned_by": "local",
                }
            ],
        }

    @app.post("/v1/responses")
    async def responses(payload: ResponsesRequest) -> Any:
        response_id = new_response_id()
        if not payload.stream:
            try:
                plan = await asyncio.to_thread(runtime.run, payload, response_id=response_id)
                return JSONResponse(content=plan.response())
            except ValueError as exc:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "message": str(exc),
                            "type": "invalid_request_error",
                            "code": "npu_codex_invalid_request",
                        }
                    },
                )
            except Exception as exc:
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": {
                            "message": f"{type(exc).__name__}: {exc}",
                            "type": "server_error",
                            "code": "npu_codex_error",
                        }
                    },
                )

        async def event_stream() -> Any:
            yield b": npu-codex connected\n\n"
            task = asyncio.create_task(
                asyncio.to_thread(runtime.run, payload, response_id=response_id)
            )
            while not task.done():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(task), timeout=config.server.keepalive_seconds
                    )
                except TimeoutError:
                    yield b": keep-alive\n\n"
            try:
                plan = task.result()
                for event in stream_events(
                    plan, chunk_chars=config.agent.response_chunk_chars
                ):
                    yield sse_encode(event)
            except Exception as exc:
                failure = failed_response(
                    response_id,
                    payload.model,
                    f"{type(exc).__name__}: {exc}",
                )
                yield sse_encode({"type": "response.failed", "sequence_number": 0, "response": failure})
            yield b"data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app
