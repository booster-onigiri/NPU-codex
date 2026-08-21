from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .backends import GenerationOptions, InferenceBackend
from .config import AppConfig
from .prompting import PromptBuilder
from .protocol import ResponsePlan, ResponsesRequest, create_plan, new_response_id
from .tooling import (
    ActionParseError,
    ModelAction,
    ToolSpec,
    ToolValidationError,
    normalize_tools,
    parse_model_action,
    validate_action,
)


@dataclass(frozen=True)
class ToolChoicePolicy:
    tools: list[ToolSpec]
    required_name: str | None = None
    require_tool: bool = False


def _tool_choice_policy(tools: list[ToolSpec], raw_choice: Any) -> ToolChoicePolicy:
    if raw_choice in (None, "auto"):
        return ToolChoicePolicy(tools=tools)
    if raw_choice == "none":
        return ToolChoicePolicy(tools=[])
    if raw_choice == "required":
        return ToolChoicePolicy(tools=tools, require_tool=True)
    if isinstance(raw_choice, dict):
        name = raw_choice.get("name")
        if not name and isinstance(raw_choice.get("function"), dict):
            name = raw_choice["function"].get("name")
        if isinstance(name, str):
            selected = [tool for tool in tools if tool.prompt_name == name]
            return ToolChoicePolicy(
                tools=selected,
                required_name=name,
                require_tool=True,
            )
    return ToolChoicePolicy(tools=tools)


def _validate_choice(action: ModelAction, policy: ToolChoicePolicy) -> None:
    if policy.require_tool and action.kind == "message":
        raise ToolValidationError("tool_choice requires a tool call, but the model returned a message")
    if policy.required_name and action.name != policy.required_name:
        raise ToolValidationError(
            f"tool_choice requires {policy.required_name!r}, but the model selected {action.name!r}"
        )


class AgentRuntime:
    def __init__(self, config: AppConfig, backend: InferenceBackend) -> None:
        self.config = config
        self.backend = backend
        self.prompt_builder = PromptBuilder(config.agent)

    def run(self, request: ResponsesRequest, *, response_id: str | None = None) -> ResponsePlan:
        if request.model != self.config.model.id:
            raise ValueError(
                f"unknown local model {request.model!r}; configured model is {self.config.model.id!r}"
            )

        raw_tools = normalize_tools(request.tools)
        policy = _tool_choice_policy(raw_tools, request.tool_choice)
        max_new_tokens = min(
            request.max_output_tokens or self.config.model.max_new_tokens,
            self.config.model.max_new_tokens,
        )
        temperature = (
            self.config.model.temperature
            if request.temperature is None
            else request.temperature
        )
        options = GenerationOptions(
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )

        repair_error: str | None = None
        previous_output: str | None = None
        input_tokens = 0
        output_tokens = 0
        last_prompt_stats = (0, 0)

        for attempt in range(self.config.agent.max_repair_attempts + 1):
            built = self.prompt_builder.build(
                model=request.model,
                instructions=request.instructions,
                input_value=request.input,
                tools=policy.tools,
                repair_error=repair_error,
                previous_output=previous_output,
            )
            last_prompt_stats = (
                built.included_history_items,
                built.omitted_history_items,
            )
            generation = self.backend.generate(built.text, options)
            input_tokens += generation.prompt_tokens
            output_tokens += generation.output_tokens
            previous_output = generation.text
            try:
                action = parse_model_action(generation.text)
                action = validate_action(action, policy.tools)
                _validate_choice(action, policy)
                return create_plan(
                    response_id=response_id or new_response_id(),
                    model=request.model,
                    action=action,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    device=generation.device,
                    included_history_items=built.included_history_items,
                    omitted_history_items=built.omitted_history_items,
                )
            except (ActionParseError, ToolValidationError) as exc:
                repair_error = str(exc)
                if attempt >= self.config.agent.max_repair_attempts:
                    break

        safe_action = ModelAction(
            kind="message",
            text=(
                "The local model returned an invalid agent action, so no tool was executed. "
                f"Validation error: {repair_error or 'unknown error'}"
            ),
        )
        return create_plan(
            response_id=response_id or new_response_id(),
            model=request.model,
            action=safe_action,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            device=self.backend.device,
            included_history_items=last_prompt_stats[0],
            omitted_history_items=last_prompt_stats[1],
        )
