"""AI provider and local harness detection for screenshot-to-json."""

from __future__ import annotations

from dataclasses import dataclass
from shutil import which as default_which
from typing import Callable, Mapping


@dataclass(frozen=True)
class VisionProviderSpec:
    provider: str
    key_names: tuple[str, ...]
    base_url: str
    text_model: str
    vision_model: str
    vision: bool


@dataclass(frozen=True)
class VisionConnection:
    provider: str
    api_key: str
    base_url: str
    model: str


PROVIDER_SPECS: tuple[VisionProviderSpec, ...] = (
    VisionProviderSpec(
        "openai",
        ("OPENAI_API_KEY",),
        "https://api.openai.com/v1",
        "gpt-4o-mini",
        "gpt-4o",
        True,
    ),
    VisionProviderSpec(
        "gemini",
        ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-2.5-flash",
        "gemini-2.5-flash",
        True,
    ),
    VisionProviderSpec(
        "openrouter",
        ("OPENROUTER_API_KEY",),
        "https://openrouter.ai/api/v1",
        "openai/gpt-4o-mini",
        "openai/gpt-4o",
        True,
    ),
    VisionProviderSpec(
        "groq",
        ("GROQ_API_KEY",),
        "https://api.groq.com/openai/v1",
        "llama-3.3-70b-versatile",
        "",
        False,
    ),
    VisionProviderSpec(
        "mistral",
        ("MISTRAL_API_KEY",),
        "https://api.mistral.ai/v1",
        "mistral-small-latest",
        "",
        False,
    ),
    VisionProviderSpec(
        "together",
        ("TOGETHER_API_KEY",),
        "https://api.together.xyz/v1",
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "",
        False,
    ),
    VisionProviderSpec(
        "perplexity",
        ("PERPLEXITY_API_KEY",),
        "https://api.perplexity.ai",
        "sonar-pro",
        "",
        False,
    ),
    VisionProviderSpec("xai", ("XAI_API_KEY",), "https://api.x.ai/v1", "grok-3-mini", "", False),
)

CLI_HARNESSES = ("openai", "gemini", "ollama", "lms", "gh", "vercel", "aider", "opencode", "codex")
LOCAL_ENDPOINTS = (
    "http://localhost:11434/v1",
    "http://localhost:1234/v1",
    "http://localhost:4000/v1",
)


def mask_secret(value: str) -> str:
    """Return a display-safe representation of a secret."""
    if len(value) < 8:
        return "set"
    return f"{value[:4]}...{value[-4:]}"


def detect_ai_environment(
    env: Mapping[str, str],
    which: Callable[[str], str | None] = default_which,
) -> dict[str, object]:
    """Detect AI keys and local CLI harnesses without making paid API calls."""
    api_keys: list[dict[str, object]] = []
    for spec in PROVIDER_SPECS:
        for key_name in spec.key_names:
            value = env.get(key_name)
            if value:
                api_keys.append(
                    {
                        "name": key_name,
                        "provider": spec.provider,
                        "masked": mask_secret(value),
                        "base_url": spec.base_url,
                        "model": spec.vision_model or spec.text_model,
                        "vision": spec.vision,
                    }
                )
                break

    azure_key = env.get("AZURE_OPENAI_API_KEY")
    if azure_key:
        api_keys.append(
            {
                "name": "AZURE_OPENAI_API_KEY",
                "provider": "azure-openai",
                "masked": mask_secret(azure_key),
                "base_url": env.get("AZURE_OPENAI_ENDPOINT", ""),
                "model": env.get("AZURE_OPENAI_DEPLOYMENT") or env.get("AZURE_OPENAI_MODEL", ""),
                "vision": False,
            }
        )

    return {
        "api_keys": sorted(api_keys, key=lambda item: str(item["name"])),
        "cli_harnesses": sorted(command for command in CLI_HARNESSES if which(command)),
        "local_endpoints": list(LOCAL_ENDPOINTS),
    }


def resolve_vision_connection(
    api_key_arg: str | None,
    api_base_arg: str,
    model_arg: str | None,
    env: Mapping[str, str],
) -> VisionConnection:
    """Resolve an OpenAI-compatible connection that can handle images."""
    default_base = "https://api.openai.com/v1"
    if api_key_arg:
        return VisionConnection(
            provider="custom" if api_base_arg.rstrip("/") != default_base else "openai",
            api_key=api_key_arg,
            base_url=api_base_arg,
            model=model_arg or "gpt-4o",
        )

    if api_base_arg.rstrip("/") != default_base:
        return VisionConnection(
            provider="custom",
            api_key=env.get("OPENAI_API_KEY", ""),
            base_url=api_base_arg,
            model=model_arg or "gpt-4o",
        )

    for spec in PROVIDER_SPECS:
        if not spec.vision:
            continue
        for key_name in spec.key_names:
            value = env.get(key_name)
            if value:
                return VisionConnection(
                    provider=spec.provider,
                    api_key=value,
                    base_url=(
                        env.get("OPENAI_BASE_URL")
                        if spec.provider == "openai"
                        else spec.base_url
                    ),
                    model=model_arg or spec.vision_model,
                )

    return VisionConnection(
        provider="openai",
        api_key="",
        base_url=env.get("OPENAI_BASE_URL") or default_base,
        model=model_arg or "gpt-4o",
    )
