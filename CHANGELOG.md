# Changelog

All notable changes to ss2json are documented here.

## 0.1.0 - 2026-06-01

- Added interactive macOS screenshot capture and existing-image analysis.
- Added clipboard image support through `pngpaste` with a Pillow fallback.
- Added OpenAI, Anthropic, and OpenAI-compatible provider support.
- Added prompt modes for general extraction, tables, code, and forms.
- Added MIME detection for PNG, JPEG, WebP, and GIF images.
- Added `--file -` for stdin image bytes.
- Added `--output` for writing JSON directly to files.
- Added `--compact` for one-line JSON output.
- Added JSON-shaped error output, tests, linting, packaging metadata, and CI.
