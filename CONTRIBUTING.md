# Contributing to ss2json

Thanks for helping improve ss2json. The project aims to be a small, dependable CLI for turning screenshots and image files into structured JSON.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Before Opening a Pull Request

Run:

```bash
ruff check .
pytest
python -m build
python -m twine check dist/*
```

If you build locally, remove generated `build/`, `dist/`, and `*.egg-info` directories before committing.

## Contribution Guidelines

- Add tests for provider resolution, prompt handling, image acquisition, output formatting, and CLI behavior changes.
- Keep all error responses JSON-shaped so scripts can parse failures.
- Preserve cross-platform existing-file mode. macOS should only be required for screenshot capture and clipboard image acquisition.
- Avoid logging image data, API keys, or provider response payloads that may contain private information.
- Document new CLI flags and examples in `README.md`.

## Reporting Bugs

Please include:

- The command you ran.
- Whether you used screenshot, clipboard, existing-file, or stdin mode.
- The provider and model, without API keys.
- The expected JSON shape and the actual output.
- Your Python version and operating system.
