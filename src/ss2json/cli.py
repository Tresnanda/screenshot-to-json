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
import json
import mimetypes
import os
import platform
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Mapping

from rich.console import Console
from rich.status import Status

from ss2json import __version__

# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

_console = Console(stderr=True, highlight=False)


def _err(msg: str) -> None:
    _console.print(f"[red]Error:[/red] {msg}")


def _warn(msg: str) -> None:
    _console.print(f"[yellow]Warning:[/yellow] {msg}")


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
) -> tuple[str, str]:
    """Return provider and model based on CLI args and available environment."""
    if provider_arg:
        provider = provider_arg
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


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ss2json",
        description="Capture a screen region and extract structured JSON via AI vision.",
        epilog=textwrap.dedent("""\
            Examples:
              ss2json                          # Interactive screenshot → JSON
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
        "--output", "-o",
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
        choices=["openai", "anthropic"],
        default=None,
        help="AI provider to use. Defaults from API key environment.",
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
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # ---- macOS guard ----
    if _requires_macos(args.file, args.clipboard) and platform.system() != "Darwin":
        result = {"error": "ss2json only runs on macOS (requires screencapture)."}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(1)

    # ---- Determine provider, model, and API key ----
    provider, model_name = _resolve_provider_and_model(
        provider_arg=args.provider,
        api_key_arg=args.api_key,
        model_arg=args.model,
        env=os.environ,
        api_base=args.api_base,
    )
    api_key = _resolve_api_key(args.api_key, provider, os.environ)
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
                    api_base=args.api_base,
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
