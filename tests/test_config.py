from pathlib import Path

import pytest

from ss2json.config import (
    AIConfig,
    config_path,
    format_config,
    load_config,
    parse_config_text,
    reset_config,
    save_config,
)


def test_config_path_uses_xdg_config_home(tmp_path: Path) -> None:
    path = config_path(env={"XDG_CONFIG_HOME": str(tmp_path)}, home=tmp_path / "home")

    assert path == tmp_path / "ss2json" / "config.toml"


def test_config_round_trip_without_storing_secrets(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = AIConfig(
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="openai/gpt-4o",
    )

    save_config(path, config)
    text = path.read_text(encoding="utf-8")

    assert "api_key" not in text
    assert load_config(path) == config


def test_parse_config_rejects_secret_fields() -> None:
    with pytest.raises(ValueError, match="Secrets do not belong"):
        parse_config_text('provider = "openai"\ntoken = "secret"\n')


def test_format_config_can_store_cli_harness_choice() -> None:
    text = format_config(AIConfig(harness="ollama", model="llama3.2-vision"))

    assert 'harness = "ollama"' in text
    assert 'model = "llama3.2-vision"' in text


def test_reset_config_removes_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('provider = "openai"\n', encoding="utf-8")

    assert reset_config(path) is True
    assert reset_config(path) is False
