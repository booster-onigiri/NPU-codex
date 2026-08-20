from __future__ import annotations

from collections import deque
from typing import Any

from npu_codex.backends import GenerationOptions, GenerationResult, estimate_tokens


class QueueBackend:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = deque(outputs)
        self.prompts: list[str] = []

    @property
    def name(self) -> str:
        return "queue"

    @property
    def device(self) -> str:
        return "TEST"

    def generate(self, prompt: str, options: GenerationOptions) -> GenerationResult:
        self.prompts.append(prompt)
        if not self.outputs:
            raise RuntimeError("queue backend has no output")
        text = self.outputs.popleft()
        return GenerationResult(
            text=text,
            prompt_tokens=estimate_tokens(prompt),
            output_tokens=estimate_tokens(text),
            device=self.device,
        )

    def status(self) -> dict[str, Any]:
        return {"backend": self.name, "device": self.device, "loaded": True}
