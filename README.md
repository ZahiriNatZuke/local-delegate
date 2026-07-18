<!-- mcp-name: io.github.ZahiriNatZuke/local-delegate -->

# local-delegate

**把机械性的文本→文本任务委托给本地 LLM，节省 Claude 订阅配额。**
一个 MCP 服务器（stdio），作为**通用**客户端对接任意 OpenAI 兼容端点——llama-swap、Ollama、LM Studio、vLLM。

[![PyPI](https://img.shields.io/pypi/v/local-delegate-mcp.svg)](https://pypi.org/project/local-delegate-mcp/)
[![CI](https://github.com/ZahiriNatZuke/local-delegate/actions/workflows/ci.yml/badge.svg)](https://github.com/ZahiriNatZuke/local-delegate/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)

## Demo

![local-delegate 用量面板](https://raw.githubusercontent.com/ZahiriNatZuke/local-delegate/main/docs/assets/dashboard.png)

*内置仪表盘（示例数据）：本地后端状态（已加载模型、进行中的委托、MCP 工具），系统 RAM/显存及进程占用，节省的上下文 token，按工具和模型分类的节省统计，分页的最近活动。访问 `http://127.0.0.1:9393`。*

## 为什么需要它？

当 Claude 需要总结大量日志、分类、提取字段或生成样板代码时，会消耗订阅配额来完成**机械性**工作。`local-delegate` 将这些任务暴露为 MCP 工具，由**本地** LLM 执行：传入 `path` 而非 `text`，文件在**服务端读取**，大量内容**从不进入 Claude 上下文**。只有简短结果返回——你未消耗的配额。

## 快速安装

使用 [`uv`](https://docs.astral.sh/uv/) 无需安装任何东西：`uvx` 会下载并在隔离环境中运行。

添加到你的 MCP 配置（Claude Desktop / Claude Code）：

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

完整模板见 [`examples/`](./examples)。

## 环境要求

一个已运行、可通过 `LOCAL_DELEGATE_BASE_URL` 访问的 **OpenAI 兼容端点**（默认 `http://127.0.0.1:9292/v1`）。任意后端均可：

- **llama-swap** — 参见 [Blackwell GPU 方案](./docs/recipes/llama-swap-blackwell.md)。
- **Ollama** — `http://127.0.0.1:11434/v1`。
- **LM Studio**、**vLLM**，或任何兼容 OpenAI API 的服务器。

本包默认**不启动**任何后端（`LOCAL_DELEGATE_AUTOSTART=0`）。llama-swap 的自动启动需主动开启（见配置表）。

关于 `llama-server`/`llama-swap` 的推荐版本及工作区布局，参见[后端版本与参考工作区](./docs/wiki/Backend-versions.md)（经验性建议，非强制要求）。`local-delegate doctor` 会将你的安装与推荐版本进行对比。

## 工具

使用 `path`（代替 `text`）可使 MCP 在服务端读取文件 → 实际节省配额。

| 工具 | 功能 | 模型角色（默认） |
|---|---|---|
| `local_summarize` | 总结文本或文件 | 机械型 / 长文本型（自动） |
| `local_classify` | 从列表中返回一个标签 | 机械型 |
| `local_extract` | 提取字段 → JSON 对象（含 `response_format` schema） | 机械型 / 长文本型（自动） |
| `local_boilerplate` | 根据描述生成样板代码 | 代码型 |
| `local_delegate` | 通用文本→文本兜底 | 机械型（或指定模型） |
| `local_lint_summary` | 总结 lint/测试/CI 日志 | 机械型 / 长文本型（自动） |
| `local_commit_msg` | 根据 diff 生成 commit 信息 | 代码型 |
| `local_translate` | 翻译文本或文件 | 机械型 / 长文本型（自动） |
| `local_explain_code` | 用自然语言解释代码 | 代码型 |
| `local_describe_image` | 描述图片或回答关于图片的问题（图片→文本） | 视觉型 |
| `local_status` | 只读诊断：后端、模型目录、日志、显存、系统内存 | —（不调用后端） |

本地模型**不使用**工具调用：服务器构建 prompt + guardrail，POST 到端点，返回**纯文本**。

## 配置

全部通过环境变量配置，无硬编码。默认模型 ID 仅为示例——请按你的后端实际情况替换。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LOCAL_DELEGATE_BASE_URL` | `http://127.0.0.1:9292/v1` | OpenAI 兼容端点 |
| `LOCAL_DELEGATE_API_KEY` | *(空)* | Bearer token（如端点需要） |
| `LOCAL_DELEGATE_TIMEOUT` | `180` | HTTP 超时（秒） |
| `LOCAL_DELEGATE_LOG_DIR` | *(用户数据目录)* | 按月轮转的 `usage-YYYYMM.jsonl` 所在目录 |
| `LOCAL_DELEGATE_LOG` | *(空 = 启用轮转)* | 若设置，则为固定的 `usage.jsonl` 路径（兼容模式） |
| `LOCAL_DELEGATE_MODEL_MECHANICAL` | `gemma3-4b` | 分类/提取/简短总结用模型 |
| `LOCAL_DELEGATE_MODEL_LONG` | `llama31-8b` | 长文档用模型 |
| `LOCAL_DELEGATE_MODEL_CODE` | `qwen25-coder-14b` | 代码用模型 |
| `LOCAL_DELEGATE_MODEL_FAST` | `qwen35-2b` | 极速/简单任务用模型 |
| `LOCAL_DELEGATE_MODEL_VISION` | `qwen3-vl-8b` | `local_describe_image` 视觉模型 |
| `LOCAL_DELEGATE_MAX_IMAGE_MB` | `8` | `local_describe_image` 图片大小上限 |
| `LOCAL_DELEGATE_LONG_INPUT_CHARS` | `6000` | 机械型↔长文本型切换阈值 |
| `LOCAL_DELEGATE_JSON_SCHEMA` | `auto` | `local_extract` 中 `response_format` schema 模式：`auto`/`on`/`off` |
| `LOCAL_DELEGATE_FEEDBACK` | `1` | `source=path` 时在结果末尾追加节省信息（`0` 关闭） |
| `LOCAL_DELEGATE_ALLOWED_DIRS` | *(空 = 不限制)* | `path` 参数的允许根目录，`;` 分隔 |
| `LOCAL_DELEGATE_WEB` | `1` | 内嵌用量仪表盘（`0` 关闭） |
| `LOCAL_DELEGATE_WEB_HOST` / `_PORT` | `127.0.0.1` / `9393` | 仪表盘的主机/端口 |
| `LOCAL_DELEGATE_AUTOSTART` | `0` | llama-swap 自动启动（需主动开启） |
| `LOCAL_DELEGATE_REASONING_EFFORT` | *(不设置)* | 控制混合推理模型的思考量。设为 `"none"` 可在 Qwen3.6/DeepSeek 等模型上禁用思考块。有效值：`"none"`、`"minimal"`、`"low"`、`"medium"`、`"high"`、`"xhigh"`、`"max"` |
| `LOCAL_DELEGATE_EXTRA_BODY` | *(不设置)* | 注入到每次 API 请求 payload 的额外 JSON 对象。用于传递上述变量未覆盖的自定义参数 |
| `LLAMASWAP_EXE` / `LLAMASWAP_CONFIG` / `LLAMASWAP_LISTEN` | — | 仅在 `AUTOSTART=1` 时生效 |

**语言匹配**：服务器自动在 system prompt 中追加语言指令，确保模型使用与输入内容相同的语言回复。中文输入 → 中文输出，西语输入 → 西语输出，英语输入 → 英语输出。`local_translate` 和 `local_boilerplate` 工具不受此行为影响。

## 节省指标

MCP 将每次调用记录在按月轮转的日志中，并在 `http://127.0.0.1:9393` 提供**仪表盘**，支持时间范围选择和进行中委托的实时可见。*上下文节省* = 服务端读取的输入字符数（`source=path` 的调用）÷ 4（或后端提供的实际 token 数）≈ 从未进入 Claude 上下文的 token。详见 [Wiki](./docs/wiki/Home.md)。

## 范围 / 非目标

`local-delegate` 有意限定为**文本/图片→文本**：构建 prompt（或多模态 payload），POST 到 `/chat/completions`，返回纯文本。以下为刻意不做的事情：

- **本地工具调用。** 本地模型不调用工具也不执行代码；这些仍由 Claude 完成。加入此能力会将本包变成一个并行编排器，偏离设计目标。
- **生成或编辑图片。** `local_describe_image` 仅支持图片→文本（描述、读取可见文字、回答具体问题）；不生成也不编辑图片。
- **音频。** 转录请使用配套工具 [`whisper-transcribe-mcp`](https://github.com/ZahiriNatZuke/whisper-transcribe-mcp)，不要在此处理音频。
- **替代订阅。** 目标是通过委托有限的机械步骤来节省配额，而非将全部工作路由到本地模型。

## Claude Code Hooks（可选）

提供两个 hook 方案，在适当时机建议委托而不阻塞原始工具（`PreToolUse`/`Read` 用于大文件，`PostToolUse`/`Bash` 用于大量 lint/测试输出）：[`docs/recipes/claude-code-hooks.md`](./docs/recipes/claude-code-hooks.md)。

## llama-swap Groups（可选）

通过 `pip install "local-delegate-mcp[llamaswap]"` 可使用两个 CLI 来管理 llama-swap 的 **groups**（一个常驻模型始终加载 + 一个轮换池），内置显存**和系统内存** guardrail（`--ram-gb` 可选：即使计算 100% 在 GPU，`llama-server` 也会将 GGUF 映射到 RAM，因此在内存不足 32GB 的机器上，显存放得下的模型目录也可能耗尽内存）：

```bash
local-delegate check-llamaswap --config config.yaml --vram-gb 16 --ram-gb 32
local-delegate init-llamaswap --config config.yaml --resident gemma3-4b --swap llama31-8b,qwen25-coder-14b --vram-gb 16 --ram-gb 32
```

本包**绝不会**自行修改你的 `config.yaml`——这些命令仅当你主动调用时才会运行。`init-llamaswap` 在写入前会运行 guardrail（若不满足显存或指定了 `--ram-gb` 时内存条件，则不写入），且无 `--force` 不会覆盖（会保留 `.bak`）。完整细节、对照 llama-swap 源码验证的 `groups` 语义以及操作流程，见 [`docs/recipes/llama-swap-groups.md`](./docs/recipes/llama-swap-groups.md)。

## 链接

- [Wiki](./docs/wiki/Home.md) · [Recipes](./docs/recipes)
- [CONTRIBUTING](./CONTRIBUTING.md) · [CODE OF CONDUCT](./CODE_OF_CONDUCT.md) · [CHANGELOG](./CHANGELOG.md)
- [MIT 许可证](./LICENSE)
