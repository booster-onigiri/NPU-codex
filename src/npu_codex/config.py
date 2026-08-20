from __future__ import annotations

import ipaddress
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1024, le=65535)
    log_level: Literal["critical", "error", "warning", "info", "debug", "trace"] = "info"
    keepalive_seconds: float = Field(default=5.0, gt=0, le=60)


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["openvino", "mock"] = "openvino"
    path: Path = Path("models/local-coder")
    id: str = Field(default="local-coder", min_length=1, max_length=128)
    device: str = "NPU"
    allow_cpu_fallback: bool = False
    max_prompt_tokens: int = Field(default=4096, ge=256, le=32768)
    min_response_tokens: int = Field(default=512, ge=32, le=8192)
    max_new_tokens: int = Field(default=768, ge=1, le=8192)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    cache_dir: Path = Path(".cache/openvino")
    prefill_hint: Literal["DYNAMIC", "STATIC"] = "DYNAMIC"
    generate_hint: Literal["FAST_COMPILE", "BEST_PERF"] = "BEST_PERF"

    @model_validator(mode="after")
    def validate_device(self) -> "ModelConfig":
        self.device = self.device.strip().upper()
        if not self.device:
            raise ValueError("model.device must not be empty")
        return self


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_char_budget: int = Field(default=10000, ge=2000, le=200000)
    tool_schema_char_budget: int = Field(default=4500, ge=500, le=100000)
    max_history_items: int = Field(default=20, ge=1, le=200)
    max_repair_attempts: int = Field(default=1, ge=0, le=3)
    response_chunk_chars: int = Field(default=96, ge=8, le=2048)


class SecurityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loopback_only: bool = True
    validate_host_header: bool = True
    max_request_bytes: int = Field(default=16 * 1024 * 1024, ge=1024, le=256 * 1024 * 1024)
    api_token_env: str | None = Field(
        default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"
    )
    redact_request_bodies: bool = True


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: ServerConfig = Field(default_factory=ServerConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)


def is_loopback_host(host: str) -> bool:
    candidate = host.strip().lower()
    if candidate == "localhost":
        return True
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def enforce_loopback(config: AppConfig) -> None:
    if config.security.loopback_only and not is_loopback_host(config.server.host):
        raise ValueError(
            "security.loopback_only is enabled, but server.host is not a literal loopback "
            f"address: {config.server.host!r}"
        )


def _resolve_path(base: Path, value: Path) -> Path:
    value = value.expanduser()
    return value.resolve() if value.is_absolute() else (base / value).resolve()


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    config = AppConfig.model_validate(raw)
    base = config_path.parent
    config.model.path = _resolve_path(base, config.model.path)
    config.model.cache_dir = _resolve_path(base, config.model.cache_dir)
    enforce_loopback(config)
    return config


def example_config_text(*, mock: bool = False) -> str:
    backend = "mock" if mock else "openvino"
    return f'''# NPU Codex local bridge configuration

[server]
host = "127.0.0.1"
port = 8765
log_level = "info"
keepalive_seconds = 5.0

[model]
backend = "{backend}"
path = "models/local-coder"
id = "local-coder"
device = "NPU"
allow_cpu_fallback = false
max_prompt_tokens = 4096
min_response_tokens = 512
max_new_tokens = 768
temperature = 0.0
cache_dir = ".cache/openvino"
prefill_hint = "DYNAMIC"
generate_hint = "BEST_PERF"

[agent]
prompt_char_budget = 10000
tool_schema_char_budget = 4500
max_history_items = 20
max_repair_attempts = 1
response_chunk_chars = 96

[security]
loopback_only = true
validate_host_header = true
max_request_bytes = 16777216
# api_token_env = "NPU_CODEX_API_TOKEN"
redact_request_bodies = true
'''
