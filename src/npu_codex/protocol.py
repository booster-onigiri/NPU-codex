from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .tooling import ModelAction


class ResponsesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1)
    input: Any
    instructions: str | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    stream: bool = False
    max_output_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    tool_choice: Any = None
    previous_response_id: str | None = None


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": self.output_tokens,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": self.input_tokens + self.output_tokens,
        }


@dataclass(frozen=True)
class ResponsePlan:
    response_id: str
    model: str
    created_at: int
    action: ModelAction
    item: dict[str, Any]
    usage: Usage
    device: str
    included_history_items: int
    omitted_history_items: int

    def response(self, *, status: str = "completed", include_output: bool = True) -> dict[str, Any]:
        return {
            "id": self.response_id,
            "object": "response",
            "created_at": self.created_at,
            "status": status,
            "background": False,
            "error": None,
            "incomplete_details": None,
            "instructions": None,
            "max_output_tokens": None,
            "model": self.model,
            "output": [self.item] if include_output else [],
            "parallel_tool_calls": False,
            "previous_response_id": None,
            "reasoning": {"effort": None, "summary": None},
            "store": False,
            "temperature": 0.0,
            "text": {"format": {"type": "text"}},
            "tool_choice": "auto",
            "tools": [],
            "top_p": 1.0,
            "truncation": "disabled",
            "usage": self.usage.as_dict() if status == "completed" else None,
            "metadata": {
                "npu_codex_device": self.device,
                "npu_codex_history_items": str(self.included_history_items),
                "npu_codex_omitted_history_items": str(self.omitted_history_items),
            },
        }


def new_response_id() -> str:
    return "resp_" + uuid.uuid4().hex


def new_call_id() -> str:
    return "call_" + uuid.uuid4().hex


def build_item(action: ModelAction) -> dict[str, Any]:
    item_id = "item_" + uuid.uuid4().hex
    if action.kind == "message":
        return {
            "id": item_id,
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": action.text or "",
                    "annotations": [],
                    "logprobs": [],
                }
            ],
        }
    call_id = action.call_id or new_call_id()
    if action.kind == "tool_call":
        return {
            "id": item_id,
            "type": "function_call",
            "status": "completed",
            "call_id": call_id,
            "name": action.name,
            "arguments": json.dumps(action.arguments or {}, ensure_ascii=False, separators=(",", ":")),
        }
    return {
        "id": item_id,
        "type": "custom_tool_call",
        "status": "completed",
        "call_id": call_id,
        "name": action.name,
        "input": action.custom_input or "",
    }


def create_plan(
    *,
    response_id: str,
    model: str,
    action: ModelAction,
    input_tokens: int,
    output_tokens: int,
    device: str,
    included_history_items: int,
    omitted_history_items: int,
) -> ResponsePlan:
    return ResponsePlan(
        response_id=response_id,
        model=model,
        created_at=int(time.time()),
        action=action,
        item=build_item(action),
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
        device=device,
        included_history_items=included_history_items,
        omitted_history_items=omitted_history_items,
    )


def _chunks(text: str, size: int) -> Iterable[str]:
    for start in range(0, len(text), size):
        yield text[start : start + size]


def _event(event_type: str, sequence_number: int, **payload: Any) -> dict[str, Any]:
    return {"type": event_type, "sequence_number": sequence_number, **payload}


def stream_events(plan: ResponsePlan, *, chunk_chars: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    sequence = 0

    def add(event_type: str, **payload: Any) -> None:
        nonlocal sequence
        events.append(_event(event_type, sequence, **payload))
        sequence += 1

    add("response.created", response=plan.response(status="in_progress", include_output=False))
    add("response.in_progress", response=plan.response(status="in_progress", include_output=False))

    item = plan.item
    if plan.action.kind == "message":
        added_item = {**item, "status": "in_progress", "content": []}
        add("response.output_item.added", output_index=0, item=added_item)
        part = {"type": "output_text", "text": "", "annotations": [], "logprobs": []}
        add("response.content_part.added", item_id=item["id"], output_index=0, content_index=0, part=part)
        text = plan.action.text or ""
        for chunk in _chunks(text, chunk_chars):
            add(
                "response.output_text.delta",
                item_id=item["id"],
                output_index=0,
                content_index=0,
                delta=chunk,
                logprobs=[],
            )
        add(
            "response.output_text.done",
            item_id=item["id"],
            output_index=0,
            content_index=0,
            text=text,
            logprobs=[],
        )
        add(
            "response.content_part.done",
            item_id=item["id"],
            output_index=0,
            content_index=0,
            part=item["content"][0],
        )
        add("response.output_item.done", output_index=0, item=item)
    elif plan.action.kind == "tool_call":
        arguments = item["arguments"]
        added_item = {**item, "status": "in_progress", "arguments": ""}
        add("response.output_item.added", output_index=0, item=added_item)
        for chunk in _chunks(arguments, chunk_chars):
            add(
                "response.function_call_arguments.delta",
                item_id=item["id"],
                output_index=0,
                delta=chunk,
            )
        add(
            "response.function_call_arguments.done",
            item_id=item["id"],
            output_index=0,
            arguments=arguments,
        )
        add("response.output_item.done", output_index=0, item=item)
    else:
        custom_input = item["input"]
        added_item = {**item, "status": "in_progress", "input": ""}
        add("response.output_item.added", output_index=0, item=added_item)
        for chunk in _chunks(custom_input, chunk_chars):
            add(
                "response.custom_tool_call_input.delta",
                item_id=item["id"],
                call_id=item["call_id"],
                output_index=0,
                delta=chunk,
            )
        add(
            "response.custom_tool_call_input.done",
            item_id=item["id"],
            call_id=item["call_id"],
            output_index=0,
            input=custom_input,
        )
        add("response.output_item.done", output_index=0, item=item)

    add("response.completed", response=plan.response())
    return events


def failed_response(response_id: str, model: str, message: str) -> dict[str, Any]:
    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": "failed",
        "model": model,
        "output": [],
        "error": {
            "type": "server_error",
            "code": "npu_codex_error",
            "message": message,
        },
        "usage": None,
    }


def sse_encode(event: dict[str, Any]) -> bytes:
    event_type = str(event.get("type") or "message")
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_type}\ndata: {data}\n\n".encode()
