# Simple Installer Wizard Design

## Goal

Make the `ss2json` curl installer easy for first-time users by replacing noisy AI diagnostics with a guided numbered setup.

## User Flow

The installer should:

1. Show a short welcome.
2. Check Python, pipx, and macOS capture helpers when relevant.
3. Show a compact vision AI summary.
4. Offer numbered vision AI defaults:
   - OpenAI API.
   - Gemini API.
   - OpenRouter API.
   - Skip AI setup.
5. If an API choice is missing its key, let the user paste the key now, show the env var command, or skip.
6. Save provider/model defaults in the app config file.
7. Save API keys only to shell/user environment, never to app config.
8. Install with pipx and optionally launch `ss2json wizard`.

## Secret Handling

API keys are written only to shell profiles on macOS/Linux or user-level environment variables on Windows. The app config stores `provider`, `base_url`, and `model` only.

## Non-Interactive Mode

`--yes` keeps installation unattended and skips prompts, API key entry, and wizard launch.

## Testing

Use static installer tests for numbered choices, key entry, provider config writes, and config/secret separation. Use shell syntax checks for `install.sh`.
