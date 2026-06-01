from ss2json.ai_env import (
    detect_ai_environment,
    mask_secret,
    resolve_vision_connection,
)
from ss2json.config import AIConfig


def test_mask_secret_keeps_values_private() -> None:
    assert mask_secret("sk-1234567890") == "sk-1...7890"
    assert mask_secret("short") == "set"


def test_detect_ai_environment_marks_vision_capable_keys() -> None:
    report = detect_ai_environment(
        env={
            "OPENAI_API_KEY": "sk-openai",
            "GROQ_API_KEY": "sk-groq",
            "ANTHROPIC_API_KEY": "sk-claude",
        },
        which=lambda command: f"/usr/bin/{command}" if command == "ollama" else None,
    )

    keys = {item["name"]: item for item in report["api_keys"]}
    assert keys["OPENAI_API_KEY"]["vision"] is True
    assert keys["GROQ_API_KEY"]["vision"] is False
    assert "ANTHROPIC_API_KEY" not in keys
    assert report["cli_harnesses"] == ["ollama"]


def test_resolve_vision_connection_prefers_vision_capable_provider() -> None:
    connection = resolve_vision_connection(
        api_key_arg=None,
        api_base_arg="https://api.openai.com/v1",
        model_arg=None,
        env={
            "GROQ_API_KEY": "sk-groq",
            "GEMINI_API_KEY": "sk-gemini",
        },
    )

    assert connection.provider == "gemini"
    assert connection.api_key == "sk-gemini"
    assert connection.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert connection.model == "gemini-3.5-flash"


def test_resolve_vision_connection_honors_explicit_values() -> None:
    connection = resolve_vision_connection(
        api_key_arg="explicit-key",
        api_base_arg="http://localhost:11434/v1",
        model_arg="llama3.2-vision",
        env={},
    )

    assert connection.provider == "custom"
    assert connection.api_key == "explicit-key"
    assert connection.base_url == "http://localhost:11434/v1"
    assert connection.model == "llama3.2-vision"


def test_resolve_vision_connection_uses_config_before_detected_environment() -> None:
    connection = resolve_vision_connection(
        api_key_arg=None,
        api_base_arg="https://api.openai.com/v1",
        model_arg=None,
        env={"OPENAI_API_KEY": "sk-openai", "GEMINI_API_KEY": "sk-gemini"},
        config=AIConfig(
            provider="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model="gemini-3.5-flash",
        ),
    )

    assert connection.provider == "gemini"
    assert connection.api_key == "sk-gemini"
    assert connection.model == "gemini-3.5-flash"


def test_resolve_vision_connection_prefers_cli_model_over_config() -> None:
    connection = resolve_vision_connection(
        api_key_arg=None,
        api_base_arg="https://api.openai.com/v1",
        model_arg="manual-model",
        env={"OPENROUTER_API_KEY": "sk-openrouter"},
        config=AIConfig(
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            model="saved-model",
        ),
    )

    assert connection.model == "manual-model"
