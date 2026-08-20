from npu_codex.config import AgentConfig
from npu_codex.prompting import PromptBuilder
from npu_codex.tooling import normalize_tools


def test_prompt_respects_budget_and_keeps_latest_history() -> None:
    builder = PromptBuilder(
        AgentConfig(
            prompt_char_budget=4000,
            tool_schema_char_budget=800,
            max_history_items=10,
        )
    )
    history = [
        {"type": "message", "role": "user", "content": f"old-{index}-" + "x" * 700}
        for index in range(8)
    ]
    history.append({"type": "message", "role": "user", "content": "LATEST-TASK"})
    tools = normalize_tools(
        [
            {
                "type": "function",
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object"},
            }
        ]
    )
    prompt = builder.build(
        model="local-coder",
        instructions="Be careful",
        input_value=history,
        tools=tools,
    )
    assert len(prompt.text) <= 4000
    assert "LATEST-TASK" in prompt.text
    assert "read_file" in prompt.text
    assert prompt.omitted_history_items > 0
