from pathlib import Path

import pytest
from pydantic import ValidationError

from npu_codex.config import AppConfig, enforce_loopback, is_loopback_host, load_config


def test_loopback_detection() -> None:
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("example.com")


def test_enforce_loopback_rejects_lan_bind() -> None:
    config = AppConfig.model_validate({"server": {"host": "0.0.0.0"}})
    with pytest.raises(ValueError, match="loopback"):
        enforce_loopback(config)


def test_load_config_resolves_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "bridge.toml"
    config_path.write_text(
        """
[model]
backend = "mock"
path = "models/test"
cache_dir = ".cache/test"
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.model.path == (tmp_path / "models/test").resolve()
    assert config.model.cache_dir == (tmp_path / ".cache/test").resolve()


def test_rejects_invalid_token_environment_variable_name() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {
                "security": {"api_token_env": "BAD-NAME"},
                "model": {"backend": "mock"},
            }
        )
