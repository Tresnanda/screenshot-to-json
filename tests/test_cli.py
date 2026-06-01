import io
import json
import subprocess

import pytest

from ss2json import cli


def test_build_user_prompt_uses_mode_defaults() -> None:
    assert cli._build_user_prompt(None, "table") == (
        "Extract all data from this image as a JSON array of row-objects."
    )
    assert cli._build_user_prompt("extract totals", "table") == "extract totals"


def test_parse_json_content_handles_fenced_json() -> None:
    content = """```json
{"total": 42, "items": ["a", "b"]}
```"""

    assert cli._parse_json_content(content) == {"total": 42, "items": ["a", "b"]}


def test_parse_json_content_wraps_non_json_text() -> None:
    assert cli._parse_json_content("not json") == {
        "result": "not json",
        "_warning": "Response was not valid JSON; returned as text",
    }


def test_resolve_provider_prefers_openai_key() -> None:
    provider, model = cli._resolve_provider_and_model(
        provider_arg=None,
        api_key_arg=None,
        model_arg=None,
        env={
            "OPENAI_API_KEY": "sk-openai",
            "ANTHROPIC_API_KEY": "sk-ant",
        },
        api_base="https://api.openai.com/v1",
    )

    assert provider == "openai"
    assert model == "gpt-4o"


def test_resolve_provider_uses_anthropic_when_only_anthropic_key_exists() -> None:
    provider, model = cli._resolve_provider_and_model(
        provider_arg=None,
        api_key_arg=None,
        model_arg=None,
        env={"ANTHROPIC_API_KEY": "sk-ant"},
        api_base="https://api.openai.com/v1",
    )

    assert provider == "anthropic"
    assert model == "claude-sonnet-4-20250514"


def test_resolve_provider_treats_custom_api_base_as_openai_compatible() -> None:
    provider, model = cli._resolve_provider_and_model(
        provider_arg=None,
        api_key_arg="local-key",
        model_arg="llama3.2-vision",
        env={},
        api_base="http://localhost:11434/v1",
    )

    assert provider == "openai"
    assert model == "llama3.2-vision"


def test_resolve_provider_honors_explicit_provider() -> None:
    provider, model = cli._resolve_provider_and_model(
        provider_arg="anthropic",
        api_key_arg="explicit-key",
        model_arg=None,
        env={"OPENAI_API_KEY": "sk-openai"},
        api_base="https://api.openai.com/v1",
    )

    assert provider == "anthropic"
    assert model == "claude-sonnet-4-20250514"


def test_resolve_api_key_uses_explicit_provider_environment() -> None:
    assert (
        cli._resolve_api_key(
            api_key_arg=None,
            provider="anthropic",
            env={"OPENAI_API_KEY": "sk-openai", "ANTHROPIC_API_KEY": "sk-ant"},
        )
        == "sk-ant"
    )


def test_resolve_openai_compatible_config_uses_gemini_key() -> None:
    provider, model, api_key, api_base = cli._resolve_openai_compatible_config(
        provider_arg=None,
        api_key_arg=None,
        model_arg=None,
        api_base_arg="https://api.openai.com/v1",
        env={"GEMINI_API_KEY": "sk-gemini"},
    )

    assert provider == "openai"
    assert model == "gemini-3.5-flash"
    assert api_key == "sk-gemini"
    assert api_base == "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_detect_mime_type_uses_image_suffixes() -> None:
    assert cli._detect_mime_type("screenshot.png") == "image/png"
    assert cli._detect_mime_type("photo.jpg") == "image/jpeg"
    assert cli._detect_mime_type("capture.webp") == "image/webp"


def test_platform_guard_allows_existing_file_on_non_macos() -> None:
    assert cli._requires_macos(file_path="image.png", clipboard=False) is False


def test_platform_guard_requires_macos_for_capture_modes() -> None:
    assert cli._requires_macos(file_path=None, clipboard=False) is True
    assert cli._requires_macos(file_path=None, clipboard=True) is True


def test_main_prints_valid_json_for_missing_file(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--file", "missing.png"])

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().out) == {"error": "File not found: missing.png"}


def test_main_writes_json_to_output_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys,
) -> None:
    image = tmp_path / "capture.png"
    image.write_bytes(b"image-bytes")
    output = tmp_path / "result.json"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(cli, "_call_vision_api", lambda **_: {"ok": True})

    cli.main(["--file", str(image), "--output", str(output)])

    assert capsys.readouterr().out == ""
    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}


def test_main_accepts_positional_image_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys,
) -> None:
    image = tmp_path / "capture.png"
    image.write_bytes(b"image-bytes")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(cli, "_call_vision_api", lambda **_: {"ok": True})

    cli.main([str(image), "--compact"])

    assert capsys.readouterr().out == '{"ok":true}\n'


def test_main_accepts_mode_subcommand_and_out_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys,
) -> None:
    image = tmp_path / "capture.png"
    image.write_bytes(b"image-bytes")
    output = tmp_path / "result.json"
    captured: dict[str, str] = {}

    def fake_call_vision_api(**kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        return [{"row": 1}]

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(cli, "_call_vision_api", fake_call_vision_api)

    cli.main(["table", str(image), "--out", str(output)])

    assert capsys.readouterr().out == ""
    assert json.loads(output.read_text(encoding="utf-8")) == [{"row": 1}]
    assert "tabular data" in captured["system_prompt"]


def test_main_uses_detected_gemini_vision_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    image = tmp_path / "capture.png"
    image.write_bytes(b"image-bytes")
    captured: dict[str, str] = {}

    def fake_call_vision_api(**kwargs):
        captured["api_key"] = kwargs["api_key"]
        captured["api_base"] = kwargs["api_base"]
        captured["model"] = kwargs["model"]
        return {"ok": True}

    monkeypatch.setenv("GEMINI_API_KEY", "sk-gemini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "_call_vision_api", fake_call_vision_api)

    cli.main([str(image), "--compact"])

    assert captured == {
        "api_key": "sk-gemini",
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-3.5-flash",
    }


def test_main_compact_outputs_single_line_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys,
) -> None:
    image = tmp_path / "capture.png"
    image.write_bytes(b"image-bytes")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(cli, "_call_vision_api", lambda **_: {"ok": True})

    cli.main(["--file", str(image), "--compact"])

    assert capsys.readouterr().out == '{"ok":true}\n'


def test_file_dash_can_be_used_without_file_flag(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    class FakeStdin:
        buffer = io.BytesIO(b"stdin-image-bytes")

    captured: dict[str, str] = {}

    def fake_call_vision_api(**kwargs):
        captured["image_b64"] = kwargs["image_b64"]
        return {"ok": True}

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(cli.sys, "stdin", FakeStdin())
    monkeypatch.setattr(cli, "_call_vision_api", fake_call_vision_api)

    cli.main(["-", "--compact"])

    assert captured["image_b64"] == "c3RkaW4taW1hZ2UtYnl0ZXM="
    assert capsys.readouterr().out == '{"ok":true}\n'


def test_file_dash_reads_image_bytes_from_stdin(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    class FakeStdin:
        buffer = io.BytesIO(b"stdin-image-bytes")

    captured: dict[str, str] = {}

    def fake_call_vision_api(**kwargs):
        captured["image_b64"] = kwargs["image_b64"]
        return {"ok": True}

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(cli.sys, "stdin", FakeStdin())
    monkeypatch.setattr(cli, "_call_vision_api", fake_call_vision_api)

    cli.main(["--file", "-", "--compact"])

    assert captured["image_b64"] == "c3RkaW4taW1hZ2UtYnl0ZXM="
    assert capsys.readouterr().out == '{"ok":true}\n'


def test_parse_args_accepts_wizard_command() -> None:
    args = cli._parse_args(["wizard"])

    assert args.command == "wizard"


def test_parse_args_accepts_update_command() -> None:
    args = cli._parse_args(["update"])

    assert args.command == "update"


def test_update_command_runs_pipx_install(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/pipx")

    def fake_run(cmd: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    cli.main(["update"])
    assert calls == [
        [
            "/usr/local/bin/pipx",
            "install",
            "--force",
            "git+https://github.com/Tresnanda/screenshot-to-json.git",
        ]
    ]


def test_parse_args_accepts_config_subcommands() -> None:
    show = cli._parse_args(["config", "show"])
    assert show.command == "config"
    assert show.config_action == "show"

    set_provider = cli._parse_args(
        [
            "config",
            "set-provider",
            "--provider",
            "openrouter",
            "--model",
            "openai/gpt-4o",
        ]
    )
    assert set_provider.config_action == "set-provider"
    assert set_provider.provider == "openrouter"


def test_config_show_reads_saved_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys,
) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text('provider = "openrouter"\nmodel = "openai/gpt-4o"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "config_path", lambda: config_file)

    cli.main(["config", "show"])

    out = capsys.readouterr().out
    assert "provider: openrouter" in out
    assert "model: openai/gpt-4o" in out


def test_config_set_provider_saves_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr(cli, "config_path", lambda: config_file)

    cli.main(["config", "set-provider", "--provider", "gemini"])

    text = config_file.read_text(encoding="utf-8")
    assert 'provider = "gemini"' in text
    assert 'model = "gemini-3.5-flash"' in text


def test_build_wizard_args_for_table_file_output() -> None:
    args = cli.build_wizard_args(
        {
            "acquisition": "file",
            "file": "receipt.png",
            "mode": "table",
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
            "output": "result.json",
            "copy": True,
        }
    )

    assert args == [
        "table",
        "receipt.png",
        "--provider",
        "anthropic",
        "--model",
        "claude-sonnet-4-20250514",
        "--output",
        "result.json",
        "--copy",
    ]


def test_main_opens_wizard_for_bare_interactive_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"wizard": False}

    class Tty:
        def isatty(self) -> bool:
            return True

    def fake_wizard() -> None:
        called["wizard"] = True

    monkeypatch.setattr(cli.sys, "stdin", Tty())
    monkeypatch.setattr(cli.sys, "stdout", Tty())
    monkeypatch.setattr(cli, "run_wizard", fake_wizard)

    cli.main([])

    assert called["wizard"] is True
