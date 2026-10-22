// REQ-013 (SDD claude-plugin-and-mods, F2-mod-core): the pinned tools leave ToolSearch.
// Run with `claude plugin test <plugin>` after `scripts/build_mod.py` (it builds register.js).
import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'

const LD_BIN = 'C:/tools/local-delegate/python.exe'
const PROVIDER = { plugin: 'mcp:local-delegate', tier: 'user' } as const

function describeAs(name: string) {
  return { tool: name, description: `${name} does things`, isDeferred: true, provider: PROVIDER } as const
}

// Beneath the plugin, this hook stands for the engine: every MCP tool waits behind ToolSearch.
function engineDefers(on: On) {
  on('tool.describe', (_$, e) => ({
    description: e.description,
    isDeferred: true,
  }))
}

test('the four default tools are pinned, the rest stay deferred', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engineDefers(on)
  for (const name of ['local_summarize', 'local_extract', 'local_lint_summary', 'local_commit_msg']) {
    const described = await $.tool.describe(describeAs(`mcp__local-delegate__${name}`))
    expect(described.isDeferred).toBe(false)
    expect(described.description).toBe(`mcp__local-delegate__${name} does things`)
  }
  // Control: a tool of ours that is not in the list keeps the engine's placement.
  const other = await $.tool.describe(describeAs('mcp__local-delegate__local_translate'))
  expect(other.isDeferred).toBe(true)
})

test('an empty list turns the piece off', { options: { ld_bin: LD_BIN, pinned_tools: [] } }, async ($, on) => {
  engineDefers(on)
  const described = await $.tool.describe(describeAs('mcp__local-delegate__local_summarize'))
  expect(described.isDeferred).toBe(true)
})

test(
  'a tool of another server is never pinned, even if listed',
  { options: { ld_bin: LD_BIN, pinned_tools: ['mcp__github__get_file_contents', 'local_translate', 'Read'] } },
  async ($, on) => {
    engineDefers(on)
    const foreign = await $.tool.describe(describeAs('mcp__github__get_file_contents'))
    expect(foreign.isDeferred).toBe(true)
    // Guard: the same list did pin the valid entry, so the test reached the piece.
    const ours = await $.tool.describe(describeAs('mcp__local-delegate__local_translate'))
    expect(ours.isDeferred).toBe(false)
    const summarize = await $.tool.describe(describeAs('mcp__local-delegate__local_summarize'))
    expect(summarize.isDeferred).toBe(true)
  },
)
