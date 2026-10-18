---
name: local-delegation
description: Rule and catalog for delegating mechanical steps (summarize, classify, extract, boilerplate, commit message from a diff, translate text or a file, summarize lint/tests/CI output, explain code, describe an image, check whether the local backend is available) to local models through the local_* tools of the local-delegate MCP, to save subscription quota. Consult it when you are about to summarize/classify/extract from long files or text, generate code boilerplate, describe/read an image, or do a first mechanical pass — before generating it yourself.
---

# Delegation to local models (MCP `local-delegate`)

You have an MCP server (`local-delegate`) that exposes models running on your own GPU
(through llama-swap, Ollama, LM Studio or vLLM) as **text/image→text** tools. Delegating to
them **saves subscription quota**: verbose generation and large inputs (or a whole image)
stay out of your context.

## Golden rule

> **Can I describe the step in ONE sentence with an explicit output format?**
> → **yes** → use a `local_*` tool.
> → **no** (it needs reasoning, architecture, judgment, several sources) → **do it yourself**.

## The biggest saving: `path` instead of `text`

For large files/documents, pass **`path`** (do not read the file yourself first). The
tools that accept `path` **read the file server-side**, so the full content **never enters
your context** — you only get the short result.

## The cost of not delegating

Reading a 100 KB file with `Read` costs ≈ 25,000 tokens of your context. The same task
with `local_summarize(path=…)` costs ≈ 200 tokens (only the summary that comes back).
That difference is what is lost every time a large file is read by hand instead of
delegated.

## Tool catalog

| Tool | When | Key args | Returns |
|---|---|---|---|
| `local_summarize` | Summarize a long text or file | `path` **or** `text`, `max_words`, `focus` (what you want to keep) | Summary (prose) |
| `local_classify` | Label into fixed categories | `text`, `labels[]` | One label |
| `local_extract` | Pull out structured fields | `fields[]`, `path` **or** `text` | JSON |
| `local_boilerplate` | Generate repetitive code | `spec`, `language`, `target` (absolute path), `overwrite?` | Receipt: path and size (the code goes to the file, not to your context) |
| `local_delegate` | Generic text→text escape hatch | `task`, `input`, `output_format`, `model?`, `chunk?` | Text |
| `local_lint_summary` | Summarize lint/tests/CI output | `path` **or** `text`, `max_words` | Summary grouped by file |
| `local_commit_msg` | Commit message from a diff | `diff` **or** `path`, `style?` | Message (always review it) |
| `local_translate` | Translate a text or file | `target_lang`, `text` **or** `path` | Translation |
| `local_explain_code` | Explain what some code does | `code` **or** `path`, `question?` | Explanation (prose) |
| `local_describe_image` | Describe an image or answer a question about it | `path`, `question?` | Description (prose) |
| `local_status` | Read-only diagnostics | — | Backend/catalog/log/VRAM |

The model ids in the catalog (mechanical/long/code/vision) are configurable through
env and can change between machines: check `local_status` to see the active catalog
instead of assuming fixed names. `local_describe_image` is **image→text only**
(describe, read visible text, answer a specific question) — it never generates or edits
images.

## Long documents

`local_translate` (and `local_delegate` with long inputs) split the text at natural
boundaries —Markdown headers, paragraphs— and process each chunk in its own call,
concatenating the outputs in order. A document of 20,000+ characters comes back
**complete**, without the truncated-output warning (`[local-delegate warning: …]`). That
strategy is for transforming the whole text (translate, rewrite, reformat); for reduction
tasks over the whole (count, pick the maximum, a single global summary) use
`local_summarize` or `chunk='off'`.

## When to delegate (examples)
- Summarize a large log/file to know what it contains → `local_summarize(path=…)`.
- Classify an issue/message as bug/feature/question → `local_classify`.
- Extract `{name, error, endpoint}` from a text → `local_extract`.
- Generate the skeleton of a CLI/argparse, a dataclass, a parser → `local_boilerplate(target=…)`,
  which writes it to the file instead of returning the code to you.
- Summarize the output of a long lint/test/build dumped to a file → `local_lint_summary(path=…)`.
- Write the commit message from a `git diff` → `local_commit_msg`.
- Translate a text or file → `local_translate`.
- Explain what a code file does before touching it → `local_explain_code(path=…)`.
- Describe a screenshot or read text from an image → `local_describe_image(path=…)`.
- Check that the local backend is alive before delegating in bulk, or diagnose a
  failure → `local_status`.
- A first mechanical pass before your fine review.

## When NOT to delegate
- Design/architecture, trade-off decisions, broad refactors.
- Multi-source research or chained reasoning.
- Anything where the quality of the result depends on judgment, not on format.
- Critical or subtle code: use it as a draft and **always review it**.

## Notes
- The tools return **text only**; the local model does not use tool-calling.
- If a tool returns `[local-delegate error] …`, the backend did not respond; fall back
  to doing it yourself and say so. Use `local_status` to diagnose why.
- The first call to a model can take a few seconds (swap cold-load).
- The dashboard (`http://127.0.0.1:9393`) shows the accumulated savings, the delegations in
  progress and whether the compute ran on the local backend or on a remote one.
