from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_unix_installer_uses_numbered_vision_ai_setup_and_key_entry() -> None:
    text = _read("install.sh")

    assert "Choose vision AI default:" in text
    assert "1) OpenAI API" in text
    assert "2) Gemini API" in text
    assert "3) OpenRouter API" in text
    assert "4) Skip AI setup" in text
    assert "Paste API key now" in text
    assert "save_secret_to_shell_profile" in text
    assert 'provider = "%s"' in text


def test_windows_installer_uses_numbered_vision_ai_setup_and_key_entry() -> None:
    text = _read("install.ps1")

    assert "Choose vision AI default:" in text
    assert "1) OpenAI API" in text
    assert "2) Gemini API" in text
    assert "3) OpenRouter API" in text
    assert "4) Skip AI setup" in text
    assert "Paste API key now" in text
    assert "Save-UserSecret" in text
    assert "provider = `\"$Provider`\"" in text
