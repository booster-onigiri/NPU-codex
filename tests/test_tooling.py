import pytest

from npu_codex.tooling import (
    ToolValidationError,
    normalize_tools,
    parse_model_action,
    validate_action,
)


def test_parse_fenced_tool_call() -> None:
    action = parse_model_action(
        '```json\n{"type":"tool_call","name":"read_file","arguments":{"path":"a.py"}}\n```'
    )
    assert action.kind == "tool_call"
    assert action.name == "read_file"
    assert action.arguments == {"path": "a.py"}


def test_normalize_and_validate_function_tool() -> None:
    tools = normalize_tools(
        [
            {
                "type": "function",
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string"}},
                    "additionalProperties": False,
                },
            }
        ]
    )
    action = parse_model_action(
        '{"type":"tool_call","name":"read_file","arguments":{"path":"a.py"}}'
    )
    validated = validate_action(action, tools)
    assert validated.name == "read_file"


def test_rejects_missing_required_argument() -> None:
    tools = normalize_tools(
        [
            {
                "type": "function",
                "name": "read_file",
                "parameters": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string"}},
                },
            }
        ]
    )
    action = parse_model_action('{"type":"tool_call","name":"read_file","arguments":{}}')
    with pytest.raises(ToolValidationError, match="required"):
        validate_action(action, tools)


def test_namespace_tools_are_flattened() -> None:
    tools = normalize_tools(
        [
            {
                "type": "namespace",
                "name": "repo",
                "tools": [
                    {
                        "type": "function",
                        "name": "search",
                        "parameters": {"type": "object"},
                    }
                ],
            }
        ]
    )
    assert tools[0].prompt_name == "repo.search"
    assert tools[0].outbound_name == "repo.search"
