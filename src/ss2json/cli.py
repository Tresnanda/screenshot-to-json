"""
ss2json.cli — macOS screenshot-to-JSON via AI vision.

Usage:
    ss2json                          # Interactive: select screen region
    ss2json --file screenshot.png    # Analyze existing image
    ss2json --prompt "custom prompt" # Custom extraction prompt
    ss2json --mode table             # Hint AI to format as table (JSON array)
    ss2json --mode code              # Extract code blocks
    ss2json --mode form              # Extract form fields and values
    ss2json --file -                 # Read image bytes from stdin
    ss2json --output result.json     # Write JSON to a file
    ss2json --compact                # Emit one-line JSON
    ss2json --copy                   # Also copy result to clipboard
    ss2json --clipboard              # Take from clipboard image
    ss2json --api-key sk-...         # API key (or set OPENAI_API_KEY / ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import argparse
import base64
import importlib.metadata
import json
import mimetypes
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.status import Status

from ss2json import __version__
from ss2json.ai_env import PROVIDER_SPECS, detect_ai_environment, resolve_vision_connection
from ss2json.config import AIConfig, config_path, load_config, reset_config, save_config

# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

_console = Console(stderr=True, highlight=False)

APP_NAME = "ss2json"
DIST_NAME = "ss2json"
REPO_URL = "https://github.com/Tresnanda/screenshot-to-json.git"
REPO_SPEC = f"git+{REPO_URL}"
MIN_PYTHON = (3, 10)


@dataclass
class UpdateCheck:
    available: bool
    current_commit: str | None = None
    latest_commit: str | None = None


def _err(msg: str) -> None:
    _console.print(f"[red]Error:[/red] {msg}")


def _warn(msg: str) -> None:
    _console.print(f"[yellow]Warning:[/yellow] {msg}")


# ---------------------------------------------------------------------------
# Self update
# ---------------------------------------------------------------------------


def _pipx_binary() -> str | None:
    pipx = shutil.which("pipx")
    if pipx:
        return pipx
    local_pipx = Path.home() / ".local" / "bin" / "pipx"
    if local_pipx.exists():
        return str(local_pipx)
    return None


def _is_app_pipx_python(path: str) -> bool:
    normalized = str(Path(path)).replace("\\", "/")
    return f"/pipx/venvs/{DIST_NAME}/" in normalized


def _python_version_ok(path: str) -> bool:
    code = (
        "import sys; "
        f"raise SystemExit(0 if sys.version_info >= {MIN_PYTHON!r} else 1)"
    )
    try:
        completed = subprocess.run(
            [path, "-c", code],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return completed.returncode == 0


def _host_python() -> str | None:
    for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3", "python"):
        candidate = shutil.which(name)
        if candidate and not _is_app_pipx_python(candidate) and _python_version_ok(candidate):
            return candidate
    if not _is_app_pipx_python(sys.executable) and _python_version_ok(sys.executable):
        return sys.executable
    return None


def _pipx_update_command() -> list[str]:
    python = _host_python()
    if not python:
        return []
    pipx = _pipx_binary()
    if pipx:
        return [pipx, "install", "--python", python, "--force", REPO_SPEC]
    return [python, "-m", "pipx", "install", "--python", python, "--force", REPO_SPEC]


def _bootstrap_pipx(python: str) -> None:
    print("pipx was not available; installing pipx and retrying...")
    subprocess.run([python, "-m", "pip", "install", "--user", "pipx"], check=True)
    subprocess.run([python, "-m", "pipx", "ensurepath"], check=True)


def run_update() -> None:
    """Install the latest ss2json from GitHub via pipx."""
    print(f"Updating {APP_NAME} from GitHub...")
    command = _pipx_update_command()
    if not command:
        _err("Update failed: could not find a usable Python or pipx.")
        sys.exit(1)
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        if len(command) >= 3 and command[1:3] == ["-m", "pipx"]:
            try:
                _bootstrap_pipx(command[0])
                subprocess.run(command, check=True)
            except subprocess.CalledProcessError as retry_exc:
                _err(f"Update failed with exit code {retry_exc.returncode}.")
                sys.exit(retry_exc.returncode or 1)
        else:
            _err(f"Update failed with exit code {exc.returncode}.")
            sys.exit(exc.returncode or 1)
    print(f"{APP_NAME} updated. Run `{APP_NAME}` again to use the latest version.")


def _installed_git_commit() -> str | None:
    try:
        distribution = importlib.metadata.distribution(DIST_NAME)
    except importlib.metadata.PackageNotFoundError:
        return None

    for file in distribution.files or []:
        if str(file).endswith("direct_url.json"):
            try:
                data = json.loads(distribution.locate_file(file).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            commit = data.get("vcs_info", {}).get("commit_id")
            return commit if isinstance(commit, str) else None
    return None


def _latest_git_commit(timeout: float = 3.0) -> str | None:
    git = shutil.which("git")
    if not git:
        return None
    try:
        result = subprocess.run(
            [git, "ls-remote", REPO_URL, "HEAD"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    fields = result.stdout.strip().split()
    return fields[0] if fields else None


def check_for_update() -> UpdateCheck:
    """Best-effort update check for pipx installs from GitHub."""
    if os.environ.get("SS2JSON_SKIP_UPDATE_CHECK"):
        return UpdateCheck(available=False)
    current_commit = _installed_git_commit()
    latest_commit = _latest_git_commit()
    if not current_commit or not latest_commit:
        return UpdateCheck(False, current_commit, latest_commit)
    return UpdateCheck(current_commit != latest_commit, current_commit, latest_commit)


def prompt_for_update_if_available() -> bool:
    """Prompt in interactive flows. Return True when an update was attempted."""
    check = check_for_update()
    if not check.available:
        return False
    if Confirm.ask(f"New {APP_NAME} update found. Update now?", default=False):
        run_update()
        return True
    return False


# ---------------------------------------------------------------------------
# Image capture
# ---------------------------------------------------------------------------


def _capture_screenshot_interactive() -> Path:
    """Run ``screencapture -i`` and return the path to the saved PNG."""
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    path = Path(tmp.name)
    # -i: interactive selection  -p: "play sound"  -x: no sound
    result = subprocess.run(
        ["screencapture", "-i", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"screencapture failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("Screenshot was cancelled or produced an empty image.")
    return path


def _get_clipboard_image() -> Path:
    """Read image from clipboard via ``pngpaste`` and return a temp PNG path."""
    # First try pngpaste
    pngpaste = _which("pngpaste")
    if pngpaste is not None:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        path = Path(tmp.name)
        result = subprocess.run(
            [pngpaste, str(path)], capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"pngpaste failed (exit {result.returncode}): {result.stderr.strip()}\n"
                "Install it with: brew install pngpaste"
            )
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError("Clipboard does not contain an image.")
        return path

    # Fallback: PIL clipboard reader (macOS only via NSImage)
    _warn("pngpaste not found — falling back to PIL clipboard reader (may be unreliable)")
    try:
        from PIL import ImageGrab
        img = ImageGrab.grabclipboard()
        if img is None:
            raise RuntimeError("Clipboard does not contain an image.")
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        path = Path(tmp.name)
        img.save(path, "PNG")
        return path
    except Exception as exc:
        raise RuntimeError(
            f"Clipboard image grab failed: {exc}\n"
            "Install pngpaste: brew install pngpaste"
        ) from exc


def _read_stdin_image() -> Path:
    """Read image bytes from stdin and return a temp PNG path."""
    data = sys.stdin.buffer.read()
    if not data:
        raise RuntimeError("No image bytes were provided on stdin.")

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    try:
        tmp.write(data)
        return Path(tmp.name)
    finally:
        tmp.close()


def _which(name: str) -> str | None:
    """Return full path of *name* or None."""
    return os.path.expanduser(
        subprocess.run(["which", name], capture_output=True, text=True).stdout.strip()
    ) or None


# ---------------------------------------------------------------------------
# Image → base64
# ---------------------------------------------------------------------------


def _image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


# ---------------------------------------------------------------------------
# AI Vision API
# ---------------------------------------------------------------------------

SYSTEM_PROMPTS = {
    "table": textwrap.dedent("""\
        You extract structured data from images. When the image contains
        tabular data (spreadsheets, price lists, schedules, etc.), return a
        JSON array of objects where each object represents one row with
        column names as keys. Use the most natural column names you can infer.
        If the image does not contain a table, return an error object:
        {"error": "No table detected in the image."}
        """),
    "code": textwrap.dedent("""\
        You extract code from images. When the image contains code snippets,
        return a JSON array of objects with keys "language" and "code".
        If multiple code blocks exist, include all of them. If no code is
        found, return: {"error": "No code detected in the image."}
        """),
    "form": textwrap.dedent("""\
        You extract form fields and values from images. Return a JSON object
        where each key is the field label and each value is the filled-in
        value (or null/empty string if blank). If no form fields are detected,
        return: {"error": "No form fields detected in the image."}
        """),
    "general": textwrap.dedent("""\
        You extract structured data from images. Return a JSON representation
        of the information visible in the image. Use arrays for lists/tables,
        objects for key-value pairs, and strings for text. The output must be
        valid JSON. If the image is blank or unreadable, return:
        {"error": "Could not extract data from the image."}
        """),
}


def _build_user_prompt(custom: str | None, mode: str) -> str:
    if custom:
        return custom
    mode_labels = {
        "table": "Extract all data from this image as a JSON array of row-objects.",
        "code": "Extract all code from this image as a JSON array of {language, code} objects.",
        "form": "Extract all form fields and values from this image as a JSON object.",
        "general": "Extract all structured data from this image as valid JSON.",
    }
    return mode_labels.get(mode, mode_labels["general"])


def _parse_json_content(content: str) -> dict[str, Any] | list[Any]:
    """Parse model content as JSON, including fenced JSON code blocks."""
    content_stripped = content.strip()
    if content_stripped.startswith("```"):
        start = content_stripped.find("\n", content_stripped.index("```"))
        end = content_stripped.rfind("```")
        if start != -1 and end != -1:
            content_stripped = content_stripped[start:end].strip()

    try:
        return json.loads(content_stripped)
    except json.JSONDecodeError:
        return {
            "result": content_stripped,
            "_warning": "Response was not valid JSON; returned as text",
        }


def _resolve_provider_and_model(
    provider_arg: str | None,
    api_key_arg: str | None,
    model_arg: str | None,
    env: Mapping[str, str],
    api_base: str,
    config: AIConfig | None = None,
) -> tuple[str, str]:
    """Return provider and model based on CLI args and available environment."""
    if provider_arg:
        provider = provider_arg
    elif config and config.provider:
        provider = config.provider
    elif config and config.harness:
        provider = config.harness
    else:
        has_openai_key = bool(env.get("OPENAI_API_KEY"))
        has_anthropic_key = bool(env.get("ANTHROPIC_API_KEY"))
        uses_custom_openai_base = api_base.rstrip("/") != "https://api.openai.com/v1"

        if api_key_arg or has_openai_key or uses_custom_openai_base:
            provider = "openai"
        elif has_anthropic_key:
            provider = "anthropic"
        else:
            provider = "openai"

    if model_arg:
        return provider, model_arg
    if config and config.model:
        return provider, config.model

    if provider == "anthropic":
        return provider, "claude-sonnet-4-20250514"
    return provider, "gpt-4o"


def _resolve_api_key(
    api_key_arg: str | None,
    provider: str,
    env: Mapping[str, str],
) -> str | None:
    """Resolve API key using explicit CLI value first, then provider-specific env."""
    if api_key_arg:
        return api_key_arg
    if provider == "anthropic":
        return env.get("ANTHROPIC_API_KEY")
    return env.get("OPENAI_API_KEY")


def _resolve_openai_compatible_config(
    provider_arg: str | None,
    api_key_arg: str | None,
    model_arg: str | None,
    api_base_arg: str,
    env: Mapping[str, str],
    config: AIConfig | None = None,
) -> tuple[str, str, str | None, str]:
    """Resolve provider, model, key, and base URL for the current run."""
    provider, model = _resolve_provider_and_model(
        provider_arg=provider_arg,
        api_key_arg=api_key_arg,
        model_arg=model_arg,
        env=env,
        api_base=api_base_arg,
        config=config,
    )
    if provider == "anthropic":
        return provider, model, _resolve_api_key(api_key_arg, provider, env), api_base_arg

    connection = resolve_vision_connection(
        api_key_arg=api_key_arg,
        api_base_arg=api_base_arg,
        model_arg=model_arg,
        env=env,
        config=config,
        provider_arg=provider_arg,
    )
    return "openai", connection.model, connection.api_key, connection.base_url


def _detect_mime_type(path: str | Path) -> str:
    """Return a supported image MIME type for API payloads."""
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        return guessed
    return "image/png"


def _requires_macos(file_path: str | None, clipboard: bool) -> bool:
    """Return True when the requested acquisition mode needs macOS tools."""
    return file_path is None or clipboard


def _call_vision_api(
    image_b64: str,
    mime_type: str,
    api_key: str,
    api_base: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """Call an OpenAI-compatible vision API and return the parsed JSON response."""
    import httpx

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_b64}",
                            "detail": "high",
                        },
                    },
                    {
                        "type": "text",
                        "text": user_prompt,
                    },
                ],
            },
        ],
        "max_tokens": 4096,
        "temperature": 0.1,
    }

    url = f"{api_base.rstrip('/')}/chat/completions"

    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"API error {response.status_code}: {response.text}"
            )
        data = response.json()

    return _parse_json_content(data["choices"][0]["message"]["content"])


# ---------------------------------------------------------------------------
# Anthropic API
# ---------------------------------------------------------------------------


def _call_anthropic_api(
    image_b64: str,
    mime_type: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """Call Anthropic Messages API and return parsed JSON."""
    import httpx

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.1,
        "system": system_prompt,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": user_prompt,
                    },
                ],
            }
        ],
    }

    url = "https://api.anthropic.com/v1/messages"

    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"Anthropic API error {response.status_code}: {response.text}"
            )
        data = response.json()

    return _parse_json_content(data["content"][0]["text"])


# ---------------------------------------------------------------------------
# Clipboard copy
# ---------------------------------------------------------------------------


def _copy_to_clipboard(text: str) -> None:
    """Copy *text* to the macOS pasteboard."""
    subprocess.run(
        ["pbcopy"],
        input=text.encode("utf-8"),
        check=True,
    )


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def _format_json_output(result: dict[str, Any] | list[Any], compact: bool) -> str:
    """Serialize API results as pretty or compact JSON with a trailing newline."""
    if compact:
        return json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
    return json.dumps(result, indent=2, ensure_ascii=False) + "\n"


def build_wizard_args(answers: Mapping[str, object]) -> list[str]:
    """Build deterministic ss2json arguments from wizard answers."""
    args: list[str] = []
    mode = str(answers.get("mode") or "general")
    if mode != "general":
        args.append(mode)

    acquisition = str(answers.get("acquisition") or "screenshot")
    if acquisition == "file" and answers.get("file"):
        args.append(str(answers["file"]))
    elif acquisition == "clipboard":
        args.append("--clipboard")
    elif acquisition == "stdin":
        args.append("-")

    provider = answers.get("provider")
    if provider:
        args.extend(["--provider", str(provider)])
    model = answers.get("model")
    if model:
        args.extend(["--model", str(model)])
    output = answers.get("output")
    if output:
        args.extend(["--output", str(output)])
    if answers.get("copy"):
        args.append("--copy")
    return args


def _choice(message: str, choices: list[str], default: str) -> str:
    return Prompt.ask(message, choices=choices, default=default)


def _format_command(args: list[str]) -> str:
    return "ss2json " + " ".join(shlex.quote(item) for item in args)


def _provider_defaults(provider: str) -> tuple[str, str]:
    for spec in PROVIDER_SPECS:
        if spec.provider == provider:
            return spec.base_url, spec.vision_model or spec.text_model
    if provider == "custom":
        return "https://api.openai.com/v1", "gpt-4o"
    if provider == "anthropic":
        return "", "claude-sonnet-4-20250514"
    raise ValueError(f"Unknown provider: {provider}")


def _print_config(config: AIConfig, path: Path) -> None:
    print(f"path: {path}")
    for field in ("provider", "base_url", "model", "harness"):
        value = getattr(config, field)
        if value:
            print(f"{field}: {value}")


def run_config_command(args: argparse.Namespace) -> None:
    """Show, reset, or update saved AI defaults."""
    path = config_path()
    action = args.config_action or "interactive"
    if action == "show":
        config = load_config(path)
        if config is None:
            print(f"No config found at {path}")
        else:
            _print_config(config, path)
        return

    if action == "reset":
        if reset_config(path):
            print(f"Removed config: {path}")
        else:
            print(f"No config found at {path}")
        return

    if action == "set-provider":
        provider = args.provider
        if not provider:
            provider = _choice(
                "Provider",
                [spec.provider for spec in PROVIDER_SPECS if spec.vision]
                + ["custom", "anthropic"],
                "openai",
            )
        default_base_url, default_model = _provider_defaults(provider)
        if provider == "custom" and not args.api_base:
            default_base_url = Prompt.ask("OpenAI-compatible base URL", default=default_base_url)
        config = AIConfig(
            provider=provider,
            base_url=(
                args.api_base
                if args.api_base != "https://api.openai.com/v1"
                else default_base_url
            ),
            model=args.model or default_model,
        )
        written = save_config(path, config)
        print(f"Saved AI defaults to {written}")
        return

    if action == "set-cli":
        harness = args.harness or _choice("CLI harness", ["ollama", "lms"], "ollama")
        default_model = "llama3.2-vision" if harness == "ollama" else "local-vision-model"
        default_base_url = "http://localhost:11434/v1" if harness == "ollama" else "http://localhost:1234/v1"
        config = AIConfig(
            harness=harness,
            base_url=(
                args.api_base
                if args.api_base != "https://api.openai.com/v1"
                else default_base_url
            ),
            model=args.model or default_model,
        )
        written = save_config(path, config)
        print(f"Saved AI defaults to {written}")
        return

    if action == "interactive":
        mode = _choice("Default type", ["provider", "cli"], "provider")
        args.config_action = "set-cli" if mode == "cli" else "set-provider"
        run_config_command(args)
        return

    _err(f"Unknown config action: {action}")
    sys.exit(2)


def run_wizard() -> None:
    """Interactive command builder for ss2json."""
    ai_report = detect_ai_environment(os.environ)
    provider, model = _resolve_provider_and_model(
        provider_arg=None,
        api_key_arg=None,
        model_arg=None,
        env=os.environ,
        api_base="https://api.openai.com/v1",
        config=load_config(),
    )
    acquisition = _choice(
        "Image source",
        ["screenshot", "file", "clipboard", "stdin"],
        "screenshot",
    )
    answers: dict[str, object] = {
        "acquisition": acquisition,
        "mode": _choice("Extraction mode", ["general", "table", "code", "form"], "general"),
    }
    if acquisition == "file":
        answers["file"] = Prompt.ask("Image file")
    if Confirm.ask(f"Use detected provider '{provider}' with model '{model}'", default=True):
        answers["provider"] = provider
        answers["model"] = model
    else:
        answers["provider"] = _choice(
            "Provider",
            [spec.provider for spec in PROVIDER_SPECS if spec.vision] + ["anthropic"],
            provider,
        )
        answers["model"] = Prompt.ask("Model", default=model)

    output = Prompt.ask("Output file (blank for stdout)", default="")
    if output:
        answers["output"] = output
    answers["copy"] = Confirm.ask("Copy JSON to clipboard", default=False)
    if ai_report["cli_harnesses"]:
        print("Detected AI CLIs: " + ", ".join(ai_report["cli_harnesses"]))

    args = build_wizard_args(answers)
    print(f"\nGenerated command:\n  {_format_command(args)}\n")
    if Confirm.ask("Run it now", default=True):
        main(args)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ss2json",
        description="Capture a screen region and extract structured JSON via AI vision.",
        epilog=textwrap.dedent("""\
            Examples:
              ss2json                          # Guided command builder
              ss2json wizard                   # Build the right command interactively
              ss2json config                   # Choose saved AI defaults
              ss2json config show              # Show saved AI defaults
              ss2json update                   # Update ss2json from GitHub
              ss2json --no-wizard              # Interactive screenshot → JSON
              ss2json report.png                # Analyze existing image
              ss2json table report.png          # Extract table data as JSON array
              ss2json -                         # Analyze image bytes from stdin
              ss2json --file report.png         # Analyze existing image
              cat report.png | ss2json --file -  # Analyze image bytes from stdin
              ss2json --mode table              # Extract table data as JSON array
              ss2json --prompt "extract prices" # Custom instruction
              ss2json --output result.json       # Write JSON to a file
              ss2json --compact                  # One-line JSON for shell pipelines
              ss2json --copy                    # Also copy JSON to clipboard
              ss2json --clipboard               # Use clipboard image

            Post-install:
              brew install pngpaste   # Required for --clipboard mode
            """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ss2json v{__version__}",
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        metavar="PATH",
        help="Analyze an existing image file instead of taking a screenshot. Use '-' for stdin.",
    )
    parser.add_argument(
        "--prompt", "-p",
        type=str,
        default=None,
        help="Custom extraction prompt (default: auto-generated from --mode)",
    )
    parser.add_argument(
        "--mode", "-m",
        type=str,
        choices=["table", "code", "form", "general"],
        default="general",
        help=(
            "Hints to the AI how to format output. "
            "'table' → JSON array of row-objects, "
            "'code' → [{language, code}, ...], "
            "'form' → {field: value, ...}, "
            "'general' → auto-detect (default)"
        ),
    )
    parser.add_argument(
        "--copy", "-c",
        action="store_true",
        default=False,
        help="Also copy the resulting JSON to the clipboard",
    )
    parser.add_argument(
        "--output", "--out", "-o",
        type=str,
        default=None,
        help="Write JSON output to a file instead of stdout",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        default=False,
        help="Emit compact one-line JSON",
    )
    parser.add_argument(
        "--clipboard", "-C",
        action="store_true",
        default=False,
        help="Read image from clipboard instead of taking a screenshot",
    )
    parser.add_argument(
        "--api-key", "-k",
        type=str,
        default=None,
        help="API key (overrides OPENAI_API_KEY / ANTHROPIC_API_KEY env vars)",
    )
    parser.add_argument(
        "--provider",
        choices=[
            "openai",
            "anthropic",
            "gemini",
            "openrouter",
            "groq",
            "mistral",
            "together",
            "perplexity",
            "xai",
            "custom",
        ],
        default=None,
        help="AI provider to use. Defaults from API key environment.",
    )
    parser.add_argument(
        "--harness",
        type=str,
        default=None,
        help="CLI harness name for config set-cli, such as ollama or lms",
    )
    parser.add_argument(
        "--api-base",
        type=str,
        default="https://api.openai.com/v1",
        help="OpenAI-compatible API base URL (default: https://api.openai.com/v1)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=(
            "Vision model to use. Defaults to gpt-4o for OpenAI or "
            "claude-sonnet-4-20250514 for Anthropic."
        ),
    )
    parser.add_argument(
        "--no-wizard",
        action="store_true",
        default=False,
        help="Capture immediately instead of opening the interactive guide",
    )
    parser.add_argument(
        "tokens",
        nargs="*",
        help=(
            "Optional command, mode, and image path, e.g. 'wizard', 'config show', "
            "'update', 'table receipt.png', or '-'"
        ),
    )
    return parser


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments and friendly positional shortcuts."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    tokens = list(args.tokens)
    modes = {"table", "code", "form", "general"}
    args.command = None

    if tokens and tokens[0] == "wizard":
        args.command = "wizard"
        tokens.pop(0)
        if tokens:
            parser.error("wizard does not accept extra arguments")

    if tokens and tokens[0] == "update":
        args.command = "update"
        tokens.pop(0)
        if tokens:
            parser.error("update does not accept extra arguments")

    if tokens and tokens[0] == "config":
        args.command = "config"
        tokens.pop(0)
        args.config_action = tokens.pop(0) if tokens else "interactive"
        if tokens:
            parser.error("config accepts at most one action")
    else:
        args.config_action = None

    if tokens and tokens[0] in modes:
        args.mode = tokens.pop(0)

    if tokens:
        if len(tokens) > 1:
            parser.error("expected at most one image path")
        if args.file:
            parser.error("provide an image path either positionally or with --file, not both")
        args.file = tokens[0]

    del args.tokens
    return args


def main(argv: list[str] | None = None) -> None:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = _parse_args(argv)

    if args.command == "update":
        run_update()
        return

    if args.command == "wizard" or (
        not raw_argv
        and not args.no_wizard
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    ):
        if prompt_for_update_if_available():
            return
        run_wizard()
        return

    if args.command == "config":
        run_config_command(args)
        return

    # ---- macOS guard ----
    if _requires_macos(args.file, args.clipboard) and platform.system() != "Darwin":
        result = {"error": "ss2json only runs on macOS (requires screencapture)."}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(1)

    # ---- Determine provider, model, API key, and API base ----
    try:
        user_config = load_config()
    except ValueError as exc:
        result = {"error": f"Invalid AI config: {exc}"}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(1)
    provider, model_name, api_key, api_base = _resolve_openai_compatible_config(
        provider_arg=args.provider,
        api_key_arg=args.api_key,
        model_arg=args.model,
        env=os.environ,
        api_base_arg=args.api_base,
        config=user_config,
    )
    if not api_key:
        result = {
            "error": (
                f"No API key found for provider '{provider}'. Set the matching "
                "environment variable or pass --api-key."
            )
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(1)

    # ---- Image acquisition ----
    image_path: Path | None = None
    delete_image_path = False

    try:
        if args.file:
            if args.file == "-":
                image_path = _read_stdin_image()
                delete_image_path = True
            else:
                image_path = Path(args.file)
                if not image_path.exists():
                    raise RuntimeError(f"File not found: {image_path}")
                if image_path.stat().st_size == 0:
                    raise RuntimeError(f"File is empty: {image_path}")
        elif args.clipboard:
            with Status("[bold green]Reading image from clipboard…", console=_console):
                image_path = _get_clipboard_image()
                delete_image_path = True
        else:
            with Status("[bold green]Select a screen region to capture…", console=_console):
                image_path = _capture_screenshot_interactive()
                delete_image_path = True

        # ---- Encode image ----
        with Status("[bold green]Encoding image…", console=_console):
            image_b64 = _image_to_base64(image_path)
            mime_type = _detect_mime_type(image_path)

        # ---- Build prompts ----
        system_prompt = SYSTEM_PROMPTS.get(args.mode, SYSTEM_PROMPTS["general"])
        user_prompt = _build_user_prompt(args.prompt, args.mode)

        # ---- Call API ----
        status_text = f"[bold green]Analyzing with {model_name}…"
        with Status(status_text, console=_console):
            if provider == "anthropic":
                result = _call_anthropic_api(
                    image_b64=image_b64,
                    mime_type=mime_type,
                    api_key=api_key,
                    model=model_name,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
            else:
                result = _call_vision_api(
                    image_b64=image_b64,
                    mime_type=mime_type,
                    api_key=api_key,
                    api_base=api_base,
                    model=model_name,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )

    except RuntimeError as exc:
        result = {"error": str(exc)}
    except Exception as exc:
        result = {"error": f"Unexpected error: {exc}"}
    finally:
        # Clean up temp images
        if image_path and image_path.exists() and delete_image_path:
            try:
                image_path.unlink(missing_ok=True)
            except Exception:
                pass

    # ---- Output JSON ----
    json_output = _format_json_output(result, compact=args.compact)
    if args.output:
        Path(args.output).write_text(json_output, encoding="utf-8")
    else:
        print(json_output, end="")

    if args.copy:
        try:
            _copy_to_clipboard(json_output)
            _console.print("[green]✓[/green] Copied to clipboard")
        except Exception as exc:
            _warn(f"Clipboard copy failed: {exc}")

    # Exit with non-zero if there was an error
    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
