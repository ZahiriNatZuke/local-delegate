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

Full details and the tool catalog in the `local-delegation` skill; backend diagnostics
with `local_status`; savings dashboard at `http://127.0.0.1:9393`.
