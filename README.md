# ss2json

Capture a screen region or image file and extract structured JSON with a vision-capable AI model.

`ss2json` is a macOS CLI for quick visual data extraction. Use it to turn screenshots of tables, forms, code snippets, dashboards, invoices, or other structured UI into JSON that can be piped into `jq`, saved to a file, or passed into another workflow.

## Highlights

- Interactive macOS region capture through `screencapture`.
- Existing image analysis with `--file`.
- Existing image analysis works cross-platform; only capture and clipboard modes require macOS.
- Reads image bytes from stdin with `--file -`.
- Clipboard image support with optional `pngpaste`.
- Prompt presets for tables, code, forms, and general structured data.
- Custom prompts for domain-specific extraction.
- Writes JSON directly to files with `--output`.
- Emits compact one-line JSON with `--compact`.
- Explicit OpenAI, Anthropic, and OpenAI-compatible endpoint support.
- PNG, JPEG, WebP, and GIF MIME detection for API payloads.
- JSON-shaped error output for scripts and pipelines.

## Requirements

- macOS 12 or newer for interactive capture.
- Python 3.10 or newer.
- An API key for OpenAI, Anthropic, or an OpenAI-compatible vision endpoint.
- Optional: `pngpaste` for reliable clipboard image support.

```bash
brew install pngpaste
```

## Installation

macOS/Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Tresnanda/screenshot-to-json/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/Tresnanda/screenshot-to-json/main/install.ps1 | iex
```

For unattended installs, pass `--yes`:

```bash
curl -fsSL https://raw.githubusercontent.com/Tresnanda/screenshot-to-json/main/install.sh | bash -s -- --yes
```

The installer uses `pipx`, checks capture/clipboard tools where relevant, and offers a simple numbered vision AI setup. You can choose OpenAI, Gemini, OpenRouter, or skip AI setup. If you paste an API key during install, it is saved to your user shell environment; the app config stores only provider/model defaults. The installer then offers to launch `ss2json wizard`.

Manual install:

```bash
pipx install .
```

For local development:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick Start

Set an API key:

```bash
export OPENAI_API_KEY="sk-..."
```

Select a screen region and print JSON:

```bash
ss2json
```

On an interactive terminal, the bare command opens a guided command builder for source selection, extraction mode, detected provider/model, and output destination. The guide shows the generated command before running it:

```bash
ss2json
ss2json wizard
```

To skip the guide and immediately start region capture, use:

```bash
ss2json --no-wizard
```

Analyze an existing image:

```bash
ss2json ~/Desktop/dashboard.png
```

Analyze image bytes from stdin:

```bash
cat ~/Desktop/dashboard.png | ss2json -
```

Extract table-shaped data:

```bash
ss2json table report.png
```

Use a custom extraction prompt:

```bash
ss2json --prompt "extract product names, prices, and ratings as an array"
```

Copy the JSON output to the clipboard:

```bash
ss2json --copy
```

Write output directly to a file:

```bash
ss2json receipt.jpg --out receipt.json
```

Print compact JSON for shell pipelines:

```bash
ss2json receipt.jpg --compact | jq .
```

## Modes

| Mode | Intended output |
| --- | --- |
| `general` | A JSON representation of visible structured information. |
| `table` | A JSON array of row objects. |
| `code` | An array of code blocks with `language` and `code` keys. |
| `form` | A JSON object mapping field labels to visible values. |

Mode presets guide the model, but they do not guarantee perfect extraction. For high-value workflows, validate the output before using it downstream.

## Provider Configuration

OpenAI is used when `OPENAI_API_KEY` is set, when `--api-key` is passed, or when a custom OpenAI-compatible `--api-base` is provided:

```bash
ss2json --api-key "$OPENAI_API_KEY" --model gpt-4o
```

`ss2json` can also auto-detect vision-capable OpenAI-compatible keys such as `GEMINI_API_KEY`, `GOOGLE_API_KEY`, and `OPENROUTER_API_KEY`. Text-only providers such as Groq, Mistral, Together, Perplexity, and xAI may be reported by the installer but are not chosen automatically for screenshots unless you pass a compatible vision model and endpoint.

Save a default provider and model:

```bash
ss2json config
ss2json config set-provider --provider gemini --model gemini-3.5-flash
ss2json config show
```

Defaults live at `$XDG_CONFIG_HOME/ss2json/config.toml` or `~/.config/ss2json/config.toml` on macOS/Linux, and `%APPDATA%\ss2json\config.toml` on Windows. The file stores only `provider`, `base_url`, `model`, and optional `harness`; API keys stay in environment variables or `--api-key`.

Resolution priority is:

1. CLI flags such as `--api-key`, `--provider`, `--api-base`, and `--model`.
2. Saved defaults from `ss2json config`.
3. Detected environment variables.
4. Built-in OpenAI-compatible defaults.

Reset saved defaults:

```bash
ss2json config reset
```

Anthropic is used when only `ANTHROPIC_API_KEY` is available:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
ss2json --model claude-sonnet-4-20250514
```

You can also choose a provider explicitly:

```bash
ss2json --provider anthropic --file receipt.jpg
```

OpenAI-compatible local or hosted endpoints are supported:

```bash
ss2json \
  --api-base http://localhost:11434/v1 \
  --api-key local-key \
  --model llama3.2-vision
```

## CLI Reference

```text
usage: ss2json [-h] [--version] [--file PATH] [--prompt PROMPT]
               [--mode {table,code,form,general}] [--copy] [--output OUTPUT]
               [--compact] [--clipboard] [--api-key API_KEY]
               [--provider PROVIDER] [--harness HARNESS]
               [--api-base API_BASE] [--model MODEL] [--no-wizard]
               [command|mode] [image]

options:
  command|mode               Optional command or shortcut: wizard, config,
                             table, code, form, or general.
  image                      Optional image path. Use "-" for stdin.
  --file PATH, -f PATH       Analyze an existing image instead of capturing one.
                             Use "-" for stdin.
  --prompt TEXT, -p TEXT     Custom extraction instruction.
  --mode MODE, -m MODE       Output hint: table, code, form, or general.
  --copy, -c                 Copy JSON output to the macOS clipboard.
  --output PATH, --out PATH, -o PATH
                             Write JSON output to a file instead of stdout.
  --compact                  Emit compact one-line JSON.
  --clipboard, -C            Read an image from the clipboard.
  --api-key KEY, -k KEY      API key override.
  --provider PROVIDER        Provider override: openai, anthropic, gemini,
                             openrouter, groq, mistral, together, perplexity,
                             xai, or custom.
  --harness NAME             CLI harness for config set-cli, such as ollama or lms.
  --api-base URL             OpenAI-compatible API base URL.
  --model NAME               Vision model override.
  --no-wizard                Capture immediately instead of opening the guide.
  --version                  Print the installed version.
```

## Output

Successful extraction prints JSON to stdout:

```json
[
  {
    "Product": "Widget A",
    "Price": "$19.99",
    "Stock": 42
  }
]
```

Errors also print JSON, which keeps shell pipelines predictable:

```json
{
  "error": "File not found: missing.png"
}
```

## Examples

Extract a visible pricing table and inspect product names:

```bash
ss2json --mode table | jq '.[].Product'
```

Extract visible code blocks:

```bash
ss2json code screenshot.png
```

Extract chart values with a custom schema:

```bash
ss2json \
  --file chart.png \
  --prompt "Extract the chart as {labels: string[], values: number[]}"
```

## Limitations

- Interactive capture and clipboard mode are macOS-only. Existing image files can be analyzed on any supported Python platform.
- AI extraction can be wrong, incomplete, or overconfident. Validate important results.
- Screenshots containing private data are sent to the configured model provider.
- Clipboard mode is most reliable with `pngpaste` installed.
- Large or dense screenshots may require a stronger model or a more specific prompt.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```

## License

MIT. See [LICENSE](LICENSE).
