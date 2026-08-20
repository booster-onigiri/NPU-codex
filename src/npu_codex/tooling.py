from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal


ToolKind = Literal["function", "custom"]
ActionKind = Literal["message", "tool_call", "custom_tool_call"]


@dataclass(frozen=True)
class ToolSpec:
    prompt_name: str
    outbound_name: str
    kind: ToolKind
    description: str
    parameters: dict[str, Any]
    custom_format: dict[str, Any] | None = None


@dataclass(frozen=True)
class ModelAction:
    kind: ActionKind
    text: str | None = None
    name: str | None = None
    arguments: dict[str, Any] | None = None
    custom_input: str | None = None
    call_id: str | None = None


class ActionParseError(ValueError):
    pass


class ToolValidationError(ValueError):
    pass


def _description(value: Any) -> str:
    return str(value or "").strip()


def _normalize_function_tool(raw: dict[str, Any], *, prefix: str = "") -> ToolSpec | None:
    function = raw.get("function") if isinstance(raw.get("function"), dict) else raw
    name = function.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    outbound_name = name.strip()
    prompt_name = f"{prefix}.{outbound_name}" if prefix else outbound_name
    parameters = function.get("parameters") or function.get("input_schema") or {}
    if not isinstance(parameters, dict):
        parameters = {}
    return ToolSpec(
        prompt_name=prompt_name,
        outbound_name=prompt_name if prefix else outbound_name,
        kind="function",
        description=_description(function.get("description")),
        parameters=parameters,
    )


def _normalize_custom_tool(raw: dict[str, Any], *, prefix: str = "") -> ToolSpec | None:
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    outbound_name = name.strip()
    prompt_name = f"{prefix}.{outbound_name}" if prefix else outbound_name
    format_value = raw.get("format")
    return ToolSpec(
        prompt_name=prompt_name,
        outbound_name=prompt_name if prefix else outbound_name,
        kind="custom",
        description=_description(raw.get("description")),
        parameters={},
        custom_format=format_value if isinstance(format_value, dict) else None,
    )


def normalize_tools(raw_tools: list[dict[str, Any]] | None) -> list[ToolSpec]:
    tools: list[ToolSpec] = []
    for raw in raw_tools or []:
        if not isinstance(raw, dict):
            continue
        tool_type = str(raw.get("type") or "function").lower()
        if tool_type == "namespace":
            namespace = raw.get("name")
            children = raw.get("tools")
            if not isinstance(namespace, str) or not isinstance(children, list):
                continue
            for child in children:
                if not isinstance(child, dict):
                    continue
                child_type = str(child.get("type") or "function").lower()
                spec = (
                    _normalize_custom_tool(child, prefix=namespace)
                    if child_type == "custom"
                    else _normalize_function_tool(child, prefix=namespace)
                )
                if spec:
                    tools.append(spec)
            continue
        spec = _normalize_custom_tool(raw) if tool_type == "custom" else _normalize_function_tool(raw)
        if spec:
            tools.append(spec)

    # Preserve order while preventing ambiguous duplicate model-facing names.
    unique: dict[str, ToolSpec] = {}
    for tool in tools:
        unique.setdefault(tool.prompt_name, tool)
    return list(unique.values())


def _compact_schema(schema: dict[str, Any], *, max_properties: int = 24) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in ("type", "required", "enum", "additionalProperties"):
        if key in schema:
            compact[key] = schema[key]
    properties = schema.get("properties")
    if isinstance(properties, dict):
        compact_properties: dict[str, Any] = {}
        for index, (name, value) in enumerate(properties.items()):
            if index >= max_properties:
                compact_properties["…"] = {"description": "additional properties omitted"}
                break
            if isinstance(value, dict):
                property_view = {
                    key: value[key]
                    for key in ("type", "description", "enum", "default")
                    if key in value
                }
                if isinstance(value.get("items"), dict):
                    property_view["items"] = {
                        key: value["items"][key]
                        for key in ("type", "enum")
                        if key in value["items"]
                    }
                compact_properties[name] = property_view
            else:
                compact_properties[name] = {}
        compact["properties"] = compact_properties
    return compact


def tool_catalog_json(tools: list[ToolSpec], char_budget: int) -> str:
    entries: list[dict[str, Any]] = []
    used = 2
    for tool in tools:
        entry: dict[str, Any] = {
            "name": tool.prompt_name,
            "kind": tool.kind,
            "description": tool.description[:320],
        }
        if tool.kind == "function":
            entry["parameters"] = _compact_schema(tool.parameters)
        elif tool.custom_format:
            entry["format"] = tool.custom_format
        encoded = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        if entries and used + len(encoded) + 1 > char_budget:
            break
        if not entries and len(encoded) > char_budget:
            encoded = encoded[: max(0, char_budget - 32)]
            entries.append({"truncated": encoded})
            break
        entries.append(entry)
        used += len(encoded) + 1
    if len(entries) < len(tools):
        entries.append({"notice": f"{len(tools) - len(entries)} tool definitions omitted by budget"})
    return json.dumps(entries, ensure_ascii=False, separators=(",", ":"))


def _extract_json_object(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    start = cleaned.find("{")
    if start < 0:
        raise ActionParseError("model output did not contain a JSON object")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : index + 1]
    raise ActionParseError("model output contained an unterminated JSON object")


def parse_model_action(raw_text: str) -> ModelAction:
    try:
        payload = json.loads(_extract_json_object(raw_text))
    except json.JSONDecodeError as exc:
        raise ActionParseError(f"model output was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ActionParseError("model action must be a JSON object")

    raw_type = str(payload.get("type") or payload.get("kind") or "").lower()
    aliases = {
        "final": "message",
        "answer": "message",
        "function_call": "tool_call",
        "tool": "tool_call",
        "custom": "custom_tool_call",
    }
    action_type = aliases.get(raw_type, raw_type)

    if action_type == "message":
        text = payload.get("text", payload.get("content", payload.get("message")))
        if not isinstance(text, str) or not text.strip():
            raise ActionParseError("message action requires non-empty text")
        return ModelAction(kind="message", text=text.strip())

    if action_type == "tool_call":
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ActionParseError("tool_call action requires a tool name")
        arguments = payload.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ActionParseError(f"tool arguments were not valid JSON: {exc}") from exc
        if not isinstance(arguments, dict):
            raise ActionParseError("tool_call arguments must be a JSON object")
        return ModelAction(
            kind="tool_call",
            name=name.strip(),
            arguments=arguments,
            call_id=str(payload.get("call_id")) if payload.get("call_id") else None,
        )

    if action_type == "custom_tool_call":
        name = payload.get("name")
        custom_input = payload.get("input", payload.get("text", ""))
        if not isinstance(name, str) or not name.strip():
            raise ActionParseError("custom_tool_call action requires a tool name")
        if not isinstance(custom_input, str):
            raise ActionParseError("custom_tool_call input must be a string")
        return ModelAction(
            kind="custom_tool_call",
            name=name.strip(),
            custom_input=custom_input,
            call_id=str(payload.get("call_id")) if payload.get("call_id") else None,
        )

    raise ActionParseError(
        "model action type must be message, tool_call, or custom_tool_call"
    )


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _validate_schema(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if len(errors) >= 12:
        return
    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        for candidate in schema["anyOf"]:
            candidate_errors: list[str] = []
            if isinstance(candidate, dict):
                _validate_schema(value, candidate, path, candidate_errors)
            if not candidate_errors:
                return
        errors.append(f"{path}: value did not match anyOf")
        return
    if "oneOf" in schema and isinstance(schema["oneOf"], list):
        matches = 0
        for candidate in schema["oneOf"]:
            candidate_errors: list[str] = []
            if isinstance(candidate, dict):
                _validate_schema(value, candidate, path, candidate_errors)
            if not candidate_errors:
                matches += 1
        if matches != 1:
            errors.append(f"{path}: value must match exactly one oneOf schema")
        return

    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(isinstance(item, str) and _matches_type(value, item) for item in expected):
            errors.append(f"{path}: expected one of {expected}, got {type(value).__name__}")
            return
    elif isinstance(expected, str) and not _matches_type(value, expected):
        errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
        return

    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        errors.append(f"{path}: value is not in enum {enum}")

    if isinstance(value, dict):
        required = schema.get("required")
        if isinstance(required, list):
            for name in required:
                if isinstance(name, str) and name not in value:
                    errors.append(f"{path}.{name}: required property is missing")
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for name, child_value in value.items():
                child_schema = properties.get(name)
                if isinstance(child_schema, dict):
                    _validate_schema(child_value, child_schema, f"{path}.{name}", errors)
                elif schema.get("additionalProperties") is False:
                    errors.append(f"{path}.{name}: additional property is not allowed")
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value[:100]):
            _validate_schema(item, schema["items"], f"{path}[{index}]", errors)


def validate_action(action: ModelAction, tools: list[ToolSpec]) -> ModelAction:
    if action.kind == "message":
        return action
    by_name = {tool.prompt_name: tool for tool in tools}
    tool = by_name.get(action.name or "")
    if tool is None:
        available = ", ".join(sorted(by_name)) or "none"
        raise ToolValidationError(f"unknown tool {action.name!r}; available tools: {available}")
    if action.kind == "tool_call" and tool.kind != "function":
        raise ToolValidationError(f"tool {tool.prompt_name!r} requires custom_tool_call")
    if action.kind == "custom_tool_call" and tool.kind != "custom":
        raise ToolValidationError(f"tool {tool.prompt_name!r} requires tool_call with JSON arguments")
    if action.kind == "tool_call":
        errors: list[str] = []
        schema = tool.parameters or {"type": "object"}
        _validate_schema(action.arguments or {}, schema, "arguments", errors)
        if errors:
            raise ToolValidationError("; ".join(errors))
        return ModelAction(
            kind=action.kind,
            name=tool.outbound_name,
            arguments=action.arguments or {},
            call_id=action.call_id,
        )
    return ModelAction(
        kind=action.kind,
        name=tool.outbound_name,
        custom_input=action.custom_input or "",
        call_id=action.call_id,
    )
