<!-- mcp-name: io.github.ZahiriNatZuke/local-delegate -->

# local-delegate

**Delegate mechanical text→text tasks to a local LLM and save your Claude subscription quota.**
An MCP server (stdio) that acts as a **generic** client for any OpenAI-compatible endpoint —
llama-swap, Ollama, LM Studio, vLLM.

[![PyPI](https://img.shields.io/pypi/v/local-delegate-mcp.svg)](https://pypi.org/project/local-delegate-mcp/)
[![CI](https://github.com/ZahiriNatZuke/local-delegate/actions/workflows/ci.yml/badge.svg)](https://github.com/ZahiriNatZuke/local-delegate/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)

## Demo

![local-delegate savings dashboard](https://raw.githubusercontent.com/ZahiriNatZuke/local-delegate/main/docs/assets/dashboard.png)

*Built-in dashboard (sample data): local backend status (loaded models, in-flight delegations, MCP tools), system RAM/VRAM with per-process breakdown, context tokens saved, savings by tool and model, and paginated recent activity. Served at `http://127.0.0.1:9393`.*

## Why?

When Claude needs to summarize a huge log, classify, extract fields, or generate boilerplate,
it spends your subscription quota on **mechanical** work. `local-delegate` exposes these tasks as
MCP tools that run on a **local** LLM: pass `path` instead of `text` and the file is read
**server-side**, so the large content **never enters Claude's context**. Only the short result
comes back — quota you didn't spend.

## Quick Start

With [`uv`](https://docs.astral.sh/uv/) there's nothing to install: `uvx` downloads and runs the package in isolation.

Add it to your MCP config (Claude Desktop / Claude Code):

```json
{
  "mcpServers": {
    "local-delegate": {
      "command": "uvx",
      "args": ["local-delegate-mcp"]
    }
  }
}
```

See full templates in [`examples/`](./examples).

## Requirements

An **OpenAI-compatible endpoint** already running, reachable at `LOCAL_DELEGATE_BASE_URL`
(default `http://127.0.0.1:9292/v1`). Any backend works:

- **llama-swap** — see [Blackwell GPU recipe](./docs/recipes/llama-swap-blackwell.md).
- **Ollama** — `http://127.0.0.1:11434/v1`.
- **LM Studio**, **vLLM**, or any server that speaks the OpenAI API.

The package **does not start** any backend by default (`LOCAL_DELEGATE_AUTOSTART=0`).
Auto-start for llama-swap is opt-in (see config table).

For recommended `llama-server`/`llama-swap` versions and workspace layout, see
[Backend versions & reference workspace](./docs/wiki/Backend-versions.md) (tested suggestion,
not a requirement). `local-delegate doctor` compares your installation against those versions.

## Tools

Passing `path` (instead of `text`) makes the MCP read the file server-side → real quota savings.

| Tool | What it does | Model role (default) |
|---|---|---|
| `local_summarize` | Summarize text or file | mechanical / long (auto) |
| `local_classify` | Return ONE label from a list | mechanical |
| `local_extract` | Extract fields → JSON object (with `response_format` schema) | mechanical / long (auto) |
| `local_boilerplate` | Generate boilerplate code from a spec | code |
| `local_delegate` | Generic text→text escape hatch | mechanical (or the one you pass) |
| `local_lint_summary` | Summarize lint/test/CI output | mechanical / long (auto) |
| `local_commit_msg` | Commit message from a diff | code |
| `local_translate` | Translate text or file | mechanical / long (auto) |
| `local_explain_code` | Explain code in prose | code |
| `local_describe_image` | Describe an image or answer a question about it (image→text) | vision |
| `local_status` | Read-only diagnostics: backend, catalog, log, VRAM, system RAM | — (doesn't call the chat backend) |

Local models do **not** use tool-calling: the server builds the prompt + guardrails, POSTs to the
endpoint, and returns **text only**.

## Configuration

Everything via environment variables; nothing hardcoded. The default model IDs are just that —
swap them for your backend's.

| Variable | Default | Description |
|---|---|---|
| `LOCAL_DELEGATE_BASE_URL` | `http://127.0.0.1:9292/v1` | OpenAI-compatible endpoint |
| `LOCAL_DELEGATE_API_KEY` | *(empty)* | Bearer token, if your endpoint requires it |
| `LOCAL_DELEGATE_TIMEOUT` | `180` | HTTP timeout (seconds) |
| `LOCAL_DELEGATE_LOG_DIR` | *(user data dir)* | Directory for month-rotated `usage-YYYYMM.jsonl` |
| `LOCAL_DELEGATE_LOG` | *(empty = rotation active)* | If set, explicit `usage.jsonl` path without rotation (compat) |
| `LOCAL_DELEGATE_MODEL_MECHANICAL` | `gemma3-4b` | Model for classify/extract/short summary |
| `LOCAL_DELEGATE_MODEL_LONG` | `llama31-8b` | Model for long documents |
| `LOCAL_DELEGATE_MODEL_CODE` | `qwen25-coder-14b` | Model for code |
| `LOCAL_DELEGATE_MODEL_FAST` | `qwen35-2b` | Ultra-fast / trivial model |
| `LOCAL_DELEGATE_MODEL_VISION` | `qwen3-vl-8b` | Vision model for `local_describe_image` |
| `LOCAL_DELEGATE_MAX_IMAGE_MB` | `8` | Max image size for `local_describe_image` |
| `LOCAL_DELEGATE_LONG_INPUT_CHARS` | `6000` | Threshold mechanical↔long |
| `LOCAL_DELEGATE_JSON_SCHEMA` | `auto` | `response_format` with schema in `local_extract`: `auto`/`on`/`off` |
| `LOCAL_DELEGATE_FEEDBACK` | `1` | Savings line appended to result when `source=path` (`0` disables) |
| `LOCAL_DELEGATE_ALLOWED_DIRS` | *(empty = unrestricted)* | Allowed roots for `path`, `;`-separated |
| `LOCAL_DELEGATE_WEB` | `1` | Embedded metrics web dashboard (`0` to disable) |
| `LOCAL_DELEGATE_WEB_HOST` / `_PORT` | `127.0.0.1` / `9393` | Web host/port |
| `LOCAL_DELEGATE_AUTOSTART` | `0` | Auto-start llama-swap (opt-in) |
| `LOCAL_DELEGATE_REASONING_EFFORT` | *(not set)* | Controls reasoning effort for hybrid reasoning models. Set to `"none"` to suppress think blocks on Qwen3.6/DeepSeek. Valid: `"none"`, `"minimal"`, `"low"`, `"medium"`, `"high"`, `"xhigh"`, `"max"` |
| `LOCAL_DELEGATE_EXTRA_BODY` | *(not set)* | Extra JSON object shallow-merged into each API request payload. For custom params not covered by the vars above |
| `LLAMASWAP_EXE` / `LLAMASWAP_CONFIG` / `LLAMASWAP_LISTEN` | — | Only relevant when `AUTOSTART=1` |

**Language matching**: the server automatically appends a language instruction to the system prompt,
ensuring the model responds in the same language as the input. Chinese input → Chinese output,
Spanish input → Spanish output, English input → English output. `local_translate` and
`local_boilerplate` skip this behavior.

## The Savings Metric

The MCP logs every call in a month-rotated log and serves a **dashboard** at
`http://127.0.0.1:9393`, with a time range selector and visibility of in-flight delegations.
*Context saved* = input characters read server-side (calls with `source=path`) ÷ 4
(or actual backend tokens when available) ≈ tokens that never entered Claude's context.
Details in the [Wiki](./docs/wiki/Home.md).

## Scope / Non-goals

`local-delegate` is deliberately **text/image→text**: it builds the prompt (or multimodal payload),
POSTs to `/chat/completions`, and returns text only. Things it purposely **doesn't** do:

- **Local tool-calling.** Local models don't invoke tools or execute code;
  Claude still handles that. Adding it would turn this package into a parallel orchestrator,
  which is not the goal.
- **Image generation or editing.** `local_describe_image` is image→text only
  (describe, read visible text, answer a specific question); no generating or editing images.
- **Audio.** For transcription use the companion
  [`whisper-transcribe-mcp`](https://github.com/ZahiriNatZuke/whisper-transcribe-mcp) instead
  of trying to handle audio here.
- **Replace the subscription.** The goal is to save quota by delegating bounded mechanical steps,
  not route all work to local models.

## Claude Code Hooks (optional)

Recipe with two hooks that suggest delegating at the right moment without ever blocking the
original tool (`PreToolUse`/`Read` for large files, `PostToolUse`/`Bash` for large lint/test
outputs): [`docs/recipes/claude-code-hooks.md`](./docs/recipes/claude-code-hooks.md).

## llama-swap Groups (optional)

With `pip install "local-delegate-mcp[llamaswap]"` you get two CLIs to manage llama-swap
**groups** (one resident model always loaded + a swap pool) with built-in VRAM **and system RAM**
guardrail (`--ram-gb` is optional: `llama-server` maps the GGUF into RAM even when compute is
100% GPU, so a catalog that fits in VRAM can still exhaust RAM on machines under 32 GB):

```bash
local-delegate check-llamaswap --config config.yaml --vram-gb 16 --ram-gb 32
local-delegate init-llamaswap --config config.yaml --resident gemma3-4b --swap llama31-8b,qwen25-coder-14b --vram-gb 16 --ram-gb 32
```

The package **never** touches your `config.yaml` on its own — these commands only run when you
invoke them. `init-llamaswap` runs the guardrail(s) before writing (doesn't write if it doesn't
fit in VRAM or, if you passed `--ram-gb`, in RAM) and never overwrites without `--force`
(leaving a `.bak`). Full details, `groups` semantics verified against llama-swap source, and
application ritual in [`docs/recipes/llama-swap-groups.md`](./docs/recipes/llama-swap-groups.md).

## Links

- [Wiki](./docs/wiki/Home.md) · [Recipes](./docs/recipes)
- [CONTRIBUTING](./CONTRIBUTING.md) · [CODE OF CONDUCT](./CODE_OF_CONDUCT.md) · [CHANGELOG](./CHANGELOG.md)
- [MIT License](./LICENSE)
