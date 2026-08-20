from npu_codex.config import AppConfig
from npu_codex.protocol import ResponsesRequest
from npu_codex.runtime import AgentRuntime
from tests.support import QueueBackend


def test_runtime_repairs_invalid_tool_call() -> None:
    config = AppConfig.model_validate(
        {
            "model": {"backend": "mock", "id": "local-coder"},
            "agent": {"max_repair_attempts": 1},
        }
    )
    backend = QueueBackend(
        [
            '{"type":"tool_call","name":"missing","arguments":{}}',
            '{"type":"tool_call","name":"read_file","arguments":{"path":"a.py"}}',
        ]
    )
    runtime = AgentRuntime(config, backend)
    request = ResponsesRequest.model_validate(
        {
            "model": "local-coder",
            "input": "Read a.py",
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
        }
    )
    plan = runtime.run(request)
    assert plan.action.kind == "tool_call"
    assert plan.action.name == "read_file"
    assert len(backend.prompts) == 2
    assert "previous model output was rejected" in backend.prompts[1]
