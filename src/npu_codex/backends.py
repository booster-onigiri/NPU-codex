from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import ModelConfig


def estimate_tokens(text: str) -> int:
    """Return a conservative tokenizer-free estimate suitable for usage metadata."""
    if not text:
        return 0
    # Source code and JSON generally tokenize more densely than prose.
    return max(1, (len(text) + 2) // 3)


@dataclass(frozen=True)
class GenerationOptions:
    max_new_tokens: int
    temperature: float


@dataclass(frozen=True)
class GenerationResult:
    text: str
    prompt_tokens: int
    output_tokens: int
    device: str


class InferenceBackend(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def device(self) -> str: ...

    def generate(self, prompt: str, options: GenerationOptions) -> GenerationResult: ...

    def status(self) -> dict[str, Any]: ...


class MockBackend:
    """Deterministic backend for protocol checks; it does not execute tools."""

    _tool_pattern = re.compile(r"\[\[MOCK_TOOL:([^:\]]+):(\{.*?\})\]\]", re.DOTALL)
    _custom_pattern = re.compile(r"\[\[MOCK_CUSTOM:([^:\]]+):(.*?)\]\]", re.DOTALL)

    def __init__(self, model_id: str = "local-coder-mock") -> None:
        self.model_id = model_id

    @property
    def name(self) -> str:
        return "mock"

    @property
    def device(self) -> str:
        return "CPU"

    def generate(self, prompt: str, options: GenerationOptions) -> GenerationResult:
        tool_match = self._tool_pattern.search(prompt)
        if tool_match:
            try:
                arguments = json.loads(tool_match.group(2))
            except json.JSONDecodeError:
                arguments = {}
            text = json.dumps(
                {"type": "tool_call", "name": tool_match.group(1), "arguments": arguments},
                ensure_ascii=False,
            )
        else:
            custom_match = self._custom_pattern.search(prompt)
            if custom_match:
                text = json.dumps(
                    {
                        "type": "custom_tool_call",
                        "name": custom_match.group(1),
                        "input": custom_match.group(2).strip(),
                    },
                    ensure_ascii=False,
                )
            else:
                text = json.dumps(
                    {
                        "type": "message",
                        "text": (
                            "Mock backend is active. The Responses API bridge is working; "
                            "switch model.backend to 'openvino' for NPU inference."
                        ),
                    },
                    ensure_ascii=False,
                )
        return GenerationResult(
            text=text,
            prompt_tokens=estimate_tokens(prompt),
            output_tokens=estimate_tokens(text),
            device=self.device,
        )

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "device": self.device,
            "loaded": True,
            "model_id": self.model_id,
        }


class OpenVINOBackend:
    """Lazy, serialized OpenVINO GenAI LLMPipeline wrapper."""

    def __init__(self, config: ModelConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._load_lock = threading.Lock()
        self._pipe: Any | None = None
        self._ov: Any | None = None
        self._ov_genai: Any | None = None
        self._available_devices: list[str] = []
        self._effective_device = config.device
        self._load_error: str | None = None

    @property
    def name(self) -> str:
        return "openvino"

    @property
    def device(self) -> str:
        return self._effective_device

    def _validate_model_directory(self, model_path: Path) -> None:
        if not model_path.is_dir():
            raise RuntimeError(f"OpenVINO model directory does not exist: {model_path}")
        xml_files = list(model_path.glob("*.xml"))
        if not xml_files:
            raise RuntimeError(
                f"No OpenVINO IR .xml files were found in the model directory: {model_path}"
            )

    def load(self) -> None:
        if self._pipe is not None:
            return
        with self._load_lock:
            if self._pipe is not None:
                return
            try:
                import openvino as ov  # type: ignore[import-not-found]
                import openvino_genai as ov_genai  # type: ignore[import-not-found]

                self._validate_model_directory(self.config.path)
                core = ov.Core()
                self._available_devices = [str(device).upper() for device in core.available_devices]
                requested = self.config.device.upper()
                if requested not in self._available_devices:
                    if self.config.allow_cpu_fallback and "CPU" in self._available_devices:
                        requested = "CPU"
                    else:
                        available = ", ".join(self._available_devices) or "none"
                        raise RuntimeError(
                            f"Requested device {self.config.device!r} is unavailable. "
                            f"OpenVINO reports: {available}"
                        )

                self.config.cache_dir.mkdir(parents=True, exist_ok=True)
                pipeline_config: dict[str, Any] = {
                    "CACHE_DIR": str(self.config.cache_dir),
                }
                if requested == "NPU":
                    pipeline_config.update(
                        {
                            "MAX_PROMPT_LEN": self.config.max_prompt_tokens,
                            "MIN_RESPONSE_LEN": self.config.min_response_tokens,
                            "PREFILL_HINT": self.config.prefill_hint,
                            "GENERATE_HINT": self.config.generate_hint,
                        }
                    )

                try:
                    pipe = ov_genai.LLMPipeline(
                        str(self.config.path), requested, pipeline_config
                    )
                except TypeError:
                    # Compatibility with releases that expose config through keyword arguments.
                    pipe = ov_genai.LLMPipeline(
                        str(self.config.path), requested, **pipeline_config
                    )

                self._ov = ov
                self._ov_genai = ov_genai
                self._pipe = pipe
                self._effective_device = requested
                self._load_error = None
            except Exception as exc:
                self._load_error = f"{type(exc).__name__}: {exc}"
                raise

    @staticmethod
    def _normalize_output(result: Any) -> str:
        if isinstance(result, str):
            return result
        texts = getattr(result, "texts", None)
        if isinstance(texts, (list, tuple)) and texts:
            return str(texts[0])
        if isinstance(result, (list, tuple)) and result:
            return str(result[0])
        return str(result)

    def _count_with_tokenizer(self, text: str) -> int:
        if self._pipe is None:
            return estimate_tokens(text)
        try:
            tokenizer = self._pipe.get_tokenizer()
            encoded = tokenizer.encode(text)
            input_ids = getattr(encoded, "input_ids", None)
            if input_ids is not None:
                shape = getattr(input_ids, "shape", None)
                if shape:
                    return int(shape[-1])
                return len(input_ids)
        except Exception:
            pass
        return estimate_tokens(text)

    def generate(self, prompt: str, options: GenerationOptions) -> GenerationResult:
        self.load()
        assert self._pipe is not None
        assert self._ov_genai is not None

        prompt_tokens = self._count_with_tokenizer(prompt)
        if prompt_tokens > self.config.max_prompt_tokens:
            raise RuntimeError(
                "Prompt exceeds the configured NPU input budget: "
                f"{prompt_tokens} > {self.config.max_prompt_tokens} tokens. "
                "Reduce agent.prompt_char_budget or model.max_prompt_tokens usage."
            )

        with self._lock:
            generation_config = self._ov_genai.GenerationConfig()
            generation_config.max_new_tokens = options.max_new_tokens
            generation_config.do_sample = options.temperature > 0
            if options.temperature > 0:
                generation_config.temperature = options.temperature

            try:
                result = self._pipe.generate(prompt, generation_config=generation_config)
            except TypeError:
                result = self._pipe.generate(prompt, generation_config)

        output = self._normalize_output(result).strip()
        return GenerationResult(
            text=output,
            prompt_tokens=prompt_tokens,
            output_tokens=self._count_with_tokenizer(output),
            device=self.device,
        )

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "device": self.device,
            "requested_device": self.config.device,
            "available_devices": self._available_devices,
            "loaded": self._pipe is not None,
            "model_path": str(self.config.path),
            "load_error": self._load_error,
        }


def create_backend(config: ModelConfig) -> InferenceBackend:
    if config.backend == "mock":
        return MockBackend(config.id)
    return OpenVINOBackend(config)
