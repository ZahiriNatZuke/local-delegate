## Delegation to local models (MCP `local-delegate`)

There is an MCP `local-delegate` that exposes local models as `local_*` tools. Delegating to
them saves subscription quota.

**Rule:** if the step fits in ONE sentence with an explicit output format (summarize,
classify, extract fields, boilerplate, translate, commit message from a diff, summarize
lint/tests, explain code, describe an image), **delegate it** to the matching `local_*`
tool. If it needs judgment, architecture, chained reasoning or several sources, **do it
yourself**.

**The real savings are in `path`:** for large files pass `path` instead of reading them
first — the MCP reads them server-side and the content never enters the context.

**Subagents:**
- **When you launch one**, its prompt has as step 1 a concrete delegation (tool, `path` and
  question) and loading the tools with `ToolSearch("select:mcp__local-delegate__local_extract,mcp__local-delegate__local_explain_code")`.
  No «if it helps»: a conditional reads as permission not to delegate.
- **If you are a subagent**, for a large file locate first: ask `local_extract` or
  `local_explain_code` (with `path`; `local_extract` with a field that asks for lines:
  `…_with_lines`, which comes back as `{name, start, end}` computed by program) for the lines
  you need and read only that range with `offset`/`limit`; what comes back in `unlocated`,
  find with `grep -n` (`located` says how they were computed; a type that does not fit comes
  back in `type_mismatch_keys`). Quoting or editing exact lines justifies reading the range, not the
  whole file.
- **Without `ToolSearch` or the `local_*` tools** (an agent whose definition closes the list
  with `tools:`) there is no delegating: whoever launches it delegates first and passes it the
  result, or picks a type that inherits the tools or names `mcp__local-delegate__local_*`. That
  subagent reads by ranges with `offset`/`limit` and says so in its report; the hooks do not
  send it to them.

Full details and the tool catalog in the `local-delegation` skill; backend diagnostics
with `local_status`; savings dashboard at `http://127.0.0.1:9393`.
