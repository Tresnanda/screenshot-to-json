# Changelog

All notable changes to ss2json are documented here.

## Unreleased

- Added positional image paths, so `ss2json receipt.png` works without `--file`.
- Added mode shortcuts such as `ss2json table receipt.png` and `ss2json code screenshot.png`.
- Added `ss2json -` as a shortcut for stdin image bytes.
- Added `--out` as a shorter alias for `--output`.

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
