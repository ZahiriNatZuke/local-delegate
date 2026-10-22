// mod/pinned-tools.js — the local-delegate tools the model sees without ToolSearch (REQ-013;
// SDD claude-plugin-and-mods, batch F2-mod-core).
//
// An MCP tool waits behind ToolSearch until the model asks for it by name, and the measurements
// say it rarely does. `tool.describe` answering `isDeferred: false` puts the schema of each
// pinned tool in the prompt's own list (~500 tokens each). The list is the `pinned_tools` option:
// the four of the spec by default, and an empty list turns the piece off. Only
// `mcp__local-delegate__*` tools are accepted: this piece never moves another server's tools.
//
// A piece of the mod: `scripts/build_mod.py` pastes it into `register.js`, which calls its
// `register` inside its own `try`. It needs nothing from `common.js` and only declares at load, so
// loading it cannot throw. Its top-level names carry `pinned`, so they cannot clash with another
// piece's.

export const PINNED_SWITCH = 'pinned_tools'
export const PINNED_TOOL_PREFIX = 'mcp__local-delegate__'
export const DEFAULT_PINNED = ['local_summarize', 'local_extract', 'local_lint_summary', 'local_commit_msg']

const PINNED_SHORT_NAME = /^local_[a-z0-9_]+$/
const PINNED_FULL_NAME = /^mcp__local-delegate__local_[a-z0-9_]+$/

/**
 * The full tool names to pin, from the option's value.
 *
 * A short name (`local_summarize`) gets the server's prefix; a full one is kept only when it is
 * a local-delegate tool; anything else is dropped. Unset (no value at all) means the default list;
 * an empty list means none.
 */
export function pinnedTools(value) {
  let names
  if (value === undefined || value === null) {
    names = DEFAULT_PINNED
  } else if (Array.isArray(value)) {
    names = value
  } else if (typeof value === 'string') {
    names = value.split(',')
  } else {
    names = []
  }
  const tools = []
  for (const raw of names) {
    if (typeof raw !== 'string') {
      continue
    }
    const name = raw.trim()
    const tool = PINNED_SHORT_NAME.test(name) ? `${PINNED_TOOL_PREFIX}${name}` : name
    if (PINNED_FULL_NAME.test(tool) && !tools.includes(tool)) {
      tools.push(tool)
    }
  }
  return tools
}

/** Registers the `tool.describe` hook; nothing when the list is empty. */
export function register(on, options) {
  const tools = pinnedTools(options[PINNED_SWITCH])
  if (tools.length === 0) {
    return
  }
  on('tool.describe', { tool: tools }, async ($, e, next) => {
    const described = await next(e)
    return { ...described, isDeferred: false }
  })
}
