from npu_codex.cli import codex_config_text
from npu_codex.config import AppConfig


def test_codex_config_uses_custom_responses_provider() -> None:
    config = AppConfig.model_validate(
        {
            "server": {"host": "127.0.0.1", "port": 8765},
            "model": {
                "backend": "mock",
                "id": "local-coder",
                "max_prompt_tokens": 4096,
                "min_response_tokens": 512,
            },
        }
    )
    text = codex_config_text(config)
    assert 'model_provider = "npu_codex"' in text
    assert 'base_url = "http://127.0.0.1:8765/v1"' in text
    assert 'wire_api = "responses"' in text
    assert "model_context_window = 4608" in text


def test_codex_config_can_source_optional_bearer_token() -> None:
    config = AppConfig.model_validate(
        {
            "server": {"host": "127.0.0.1", "port": 8765},
            "model": {"backend": "mock", "id": "local-coder"},
            "security": {"api_token_env": "NPU_CODEX_API_TOKEN"},
        }
    )
    text = codex_config_text(config)
    assert 'env_key = "NPU_CODEX_API_TOKEN"' in text
