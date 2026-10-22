// Tests of the read piece (REQ-020, REQ-021, REQ-022; SDD claude-plugin-and-mods, F4-read-mod).
// Like `commands.test.ts`, they drive `register` with a fake `$` and a fake `common` (the
// interface of `mod/common.js`), so they depend neither on `common.js` nor on `register.js`.
// `hook classify` and `hook record-read` (batch F4-classifier) are simulated behind `runLd`,
// following the contract fixed in plan.md, wave 5.
import { expect, test } from 'claude-code/testing'
import { onSessionStart, register } from './read.js'

const SESSION = 'sess-read'
const CWD = 'C:/work'
const DATA = 'C:/cfg/plugins/data/local-delegate-local-delegate'
const BIG = 'C:/work/docs/big.md'
const OTHER = 'C:/work/docs/other.md'
const BIG_BYTES = 64 * 1024
// A 100-line file: each range below is a percentage of it.
const HUNDRED_LINES = Array.from({ length: 100 }, (_, i) => `line ${i + 1}`).join('\n') + '\n'

type Classified = Record<string, unknown> | null | 'fail'

type Env = {
  $: any
  common: any
  hooks: any[]
  files: Map<string, string>
  ldRuns: { args: string[]; stdin: any }[]
  mcpCalls: { server: string; tool: string; args: any }[]
  asks: { question: string; options: any }[]
  nexts: any[]
  beats: any[]
  dialog: boolean
  answer: string | null
  session: string
  classify: (input: any) => Classified
  mcpFails: boolean
}

function t(key: string, vars?: Record<string, unknown>) {
  const tail = vars ? ' ' + Object.keys(vars).sort().map(k => `${k}=${String(vars[k])}`).join(' ') : ''
  return `${key}${tail}`
}

function makeEnv(opts: {
  dialog?: boolean
  answer?: string | null
  classify?: (input: any) => Classified
  files?: Record<string, string>
  options?: Record<string, unknown>
  mcpFails?: boolean
  files_map?: Map<string, string>
} = {}): Env {
  const env: Env = {
    $: null,
    common: null,
    hooks: [],
    files: opts.files_map ?? new Map(Object.entries(opts.files ?? { [BIG]: HUNDRED_LINES })),
    ldRuns: [],
    mcpCalls: [],
    asks: [],
    nexts: [],
    beats: [],
    dialog: opts.dialog ?? false,
    answer: opts.answer ?? null,
    session: SESSION,
    classify: opts.classify ?? (() => null),
    mcpFails: opts.mcpFails ?? false,
  }
  env.$ = {
    session: { id: async () => env.session, cwd: async () => CWD },
    fs: {
      read: async (p: string) => {
        if (!env.files.has(p)) throw new Error('missing')
        return env.files.get(p)
      },
      write: async (p: string, text: string) => {
        env.files.set(p, text)
      },
      exists: async (p: string) => env.files.has(p),
    },
    mcp: {
      call: async (server: string, tool: string, args: any) => {
        env.mcpCalls.push({ server, tool, args })
        if (env.mcpFails) throw new Error('MCP down')
        return { content: [{ type: 'text', text: 'SUMMARY OF THE FILE' }], isError: false }
      },
    },
    ui: {
      ask: async (question: string, options: any) => {
        env.asks.push({ question, options })
        if (env.answer === null) throw new Error('dismissed')
        return env.answer
      },
      toast: async () => undefined,
    },
  }
  env.common = {
    t,
    dataPath: async (name: string) => `${DATA}/${name}`,
    hasDialog: () => env.dialog,
    heartbeat: async (fields: any) => {
      env.beats.push(fields)
      return `${DATA}/heartbeats/${env.session}.json`
    },
    runLd: async (args: string[], stdin?: string) => {
      const parsed = typeof stdin === 'string' ? JSON.parse(stdin) : undefined
      env.ldRuns.push({ args, stdin: parsed })
      if (args.includes('--list-tools')) {
        return { exitCode: 0, stdout: JSON.stringify(['Read', 'Bash', 'PowerShell', 'Grep']), stderr: '' }
      }
      if (args.includes('classify')) {
        const answer = env.classify(parsed)
        if (answer === null) return null
        if (answer === 'fail') return { exitCode: 1, stdout: 'not json', stderr: 'boom' }
        return { exitCode: 0, stdout: JSON.stringify(answer), stderr: '' }
      }
      return { exitCode: 0, stdout: '', stderr: '' }
    },
  }
  registerInto(env, opts.options ?? { read_mod_enabled: true })
  return env
}

function registerInto(env: Env, options: Record<string, unknown>) {
  env.hooks = []
  register((event: string, matcher: any, hook?: any) => {
    if (typeof matcher === 'function') env.hooks.push({ event, matcher: undefined, hook: matcher })
    else env.hooks.push({ event, matcher, hook })
  }, options, env.common)
}

// What the real tool answers when the call goes through.
function realResult(e: any) {
  if (e.tool === 'Read') {
    return {
      result: { type: 'text', file: { filePath: e.file_path, content: 'REAL', numLines: 1, startLine: 1, totalLines: 100 } },
      text: 'REAL',
      ref: 1,
    }
  }
  return { result: { stdout: 'REAL', stderr: '', interrupted: false }, text: 'REAL', ref: 1 }
}

async function call(env: Env, e: any): Promise<any> {
  const entry = env.hooks.find(h => h.event === 'tool.call')
  if (!entry) throw new Error('no tool.call hook')
  return entry.hook(env.$, { tool_use_id: `toolu_${env.nexts.length}`, ...e }, async (seen: any) => {
    env.nexts.push(seen)
    return realResult(seen)
  })
}

function readCls(over: Record<string, unknown> = {}) {
  return {
    kind: 'read',
    path: BIG,
    scope: 'whole',
    bytes: BIG_BYTES,
    range: null,
    via: 'read_whole',
    read_switch: 'on',
    ...over,
  }
}

// Classifies each call by its input, the way `hook classify` would for these cases.
function byInput(input: any): Classified {
  const ti = input.tool_input
  if (input.tool_name === 'Read') {
    const path = ti.file_path
    if (typeof ti.offset === 'number') {
      return readCls({ path, scope: 'range', range: [ti.offset, ti.offset + ti.limit - 1], via: 'read_range' })
    }
    return readCls({ path })
  }
  if (input.tool_name === 'Bash' && /> *big\.md/.test(ti.command)) {
    return { kind: 'write', path: BIG, scope: 'whole', bytes: null, range: null, via: 'shell_redirect', read_switch: 'on' }
  }
  return { kind: 'other', path: null, scope: 'unclassifiable', bytes: null, range: null, via: 'other', read_switch: 'on' }
}

function decisions(env: Env): string[] {
  return env.ldRuns.filter(r => r.args.includes('record-read')).map(r => r.stdin.decision)
}

test('off_by_default', async () => {
  // Unset and false: no hook at all, so nothing can be steered.
  expect(makeEnv({ options: {} }).hooks.filter(h => h.event === 'tool.call')).toHaveLength(0)
  expect(makeEnv({ options: { read_mod_enabled: false } }).hooks.filter(h => h.event === 'tool.call')).toHaveLength(0)
  // Guard: switched on, the hook is there, so the two zeros above are the switch's doing.
  expect(makeEnv({ options: { read_mod_enabled: true } }).hooks.filter(h => h.event === 'tool.call')).toHaveLength(1)
})

test('respects_read_switch_off', async () => {
  for (const state of ['off_file', 'off_variable', 'inactive']) {
    const env = makeEnv({ classify: () => readCls({ read_switch: state }) })
    const out = await call(env, { tool: 'Read', file_path: BIG })
    expect(env.nexts).toHaveLength(1)
    expect(out.result.file.content).toBe('REAL')
    expect(env.mcpCalls).toHaveLength(0)
  }
  // Guard: the same read with the switch on is summarized.
  const on = makeEnv({ classify: () => readCls() })
  await call(on, { tool: 'Read', file_path: BIG })
  expect(on.mcpCalls).toHaveLength(1)
})

test('passes_when_classifier_unavailable', async () => {
  for (const answer of [null, 'fail'] as const) {
    const env = makeEnv({ classify: () => answer })
    const out = await call(env, { tool: 'Read', file_path: BIG })
    expect(env.nexts).toHaveLength(1)
    expect(out.result.file.content).toBe('REAL')
    expect(env.mcpCalls).toHaveLength(0)
    expect(env.asks).toHaveLength(0)
  }
  // The classifier was asked with the contract's input.
  const env = makeEnv({ classify: () => null })
  await call(env, { tool: 'Read', file_path: BIG })
  const asked = env.ldRuns.find(r => r.args.includes('classify') && !r.args.includes('--list-tools'))!
  expect(asked.args).toEqual(['-I', '-m', 'local_delegate', 'hook', 'classify'])
  expect(asked.stdin).toEqual({ tool_name: 'Read', tool_input: { file_path: BIG }, cwd: CWD, session_id: SESSION })
})

test('buttons_when_dialog', async () => {
  const env = makeEnv({ dialog: true, answer: 'read.ask.summarize', classify: byInput })
  const out = await call(env, { tool: 'Read', file_path: BIG })
  expect(env.asks).toHaveLength(1)
  expect(env.asks[0].options).toEqual(['read.ask.summarize', 'read.ask.whole'])
  expect(env.mcpCalls).toEqual([{ server: 'local-delegate', tool: 'local_summarize', args: { path: BIG } }])
  expect(env.nexts).toHaveLength(0)
  expect(out.deny).toBeUndefined()
  expect(out.result.file.content.includes('SUMMARY OF THE FILE')).toBe(true)
  expect(decisions(env)).toEqual(['summarized'])

  const whole = makeEnv({ dialog: true, answer: 'read.ask.whole', classify: byInput })
  const real = await call(whole, { tool: 'Read', file_path: BIG })
  expect(whole.mcpCalls).toHaveLength(0)
  expect(whole.nexts).toHaveLength(1)
  expect(real.result.file.content).toBe('REAL')
  expect(decisions(whole)).toEqual(['read_whole'])
})

test('auto_summary_without_dialog', async () => {
  const env = makeEnv({ dialog: false, classify: byInput })
  const out = await call(env, { tool: 'Read', file_path: BIG })
  expect(env.asks).toHaveLength(0)
  expect(env.mcpCalls).toEqual([{ server: 'local-delegate', tool: 'local_summarize', args: { path: BIG } }])
  expect(env.nexts).toHaveLength(0)
  expect(out.deny).toBeUndefined()
  expect(out.result.type).toBe('text')
  expect(out.result.file.filePath).toBe(BIG)
  expect(out.result.file.content.includes('SUMMARY OF THE FILE')).toBe(true)
  expect(decisions(env)).toEqual(['auto_summarized'])

  // A subagent has no one to ask either, even in a session with a dialog.
  const sub = makeEnv({ dialog: true, answer: 'read.ask.whole', classify: byInput })
  const subOut = await call(sub, { tool: 'Read', file_path: BIG, agentId: 'agent-1' })
  expect(sub.asks).toHaveLength(0)
  expect(sub.mcpCalls).toHaveLength(1)
  expect(subOut.result.file.content.includes('SUMMARY OF THE FILE')).toBe(true)

  // A shell read gets the summary as the command's output.
  const shell = makeEnv({ classify: () => readCls({ via: 'shell_cat' }) })
  const shellOut = await call(shell, { tool: 'Bash', command: 'cat docs/big.md' })
  expect(shellOut.result.stdout.includes('SUMMARY OF THE FILE')).toBe(true)

  // The summary failing never blocks: the real read goes through.
  const down = makeEnv({ classify: byInput, mcpFails: true })
  const real = await call(down, { tool: 'Read', file_path: BIG })
  expect(down.nexts).toHaveLength(1)
  expect(real.result.file.content).toBe('REAL')
})

test('accumulates_ranges_to_whole', async () => {
  const env = makeEnv({ classify: byInput })
  const range = (offset: number, limit: number) => call(env, { tool: 'Read', file_path: BIG, offset, limit })
  await range(1, 40) // 40 %
  await range(30, 41) // lines 30-70: the union is 70 %, a plain sum would be 81 %
  await range(71, 5) // 75 %
  expect(env.nexts).toHaveLength(3)
  expect(env.mcpCalls).toHaveLength(0)
  const out = await range(76, 5) // 80 %: the threshold, it counts as reading it whole
  expect(env.mcpCalls).toEqual([{ server: 'local-delegate', tool: 'local_summarize', args: { path: BIG } }])
  expect(env.nexts).toHaveLength(3)
  expect(out.result.file.content.includes('SUMMARY OF THE FILE')).toBe(true)
})

test('unclassifiable_only_warns', async () => {
  const env = makeEnv({
    dialog: true,
    answer: 'read.ask.summarize',
    classify: () => readCls({ scope: 'unclassifiable', via: 'shell_grep', range: null }),
  })
  const out = await call(env, { tool: 'Bash', command: 'grep -n foo docs/big.md | sort' })
  expect(env.nexts).toHaveLength(1)
  expect(out.deny).toBeUndefined()
  expect(out.result.stdout).toBe('REAL')
  expect(env.asks).toHaveLength(0)
  expect(env.mcpCalls).toHaveLength(0)
  expect((out.context ?? []).some((line: string) => line.startsWith('read.warn.large'))).toBe(true)
  expect(decisions(env)).toEqual(['warned'])
})

test('blocks_write_after_summary', async () => {
  const env = makeEnv({ classify: byInput })
  // Control: before any summary, a write goes through.
  await call(env, { tool: 'Write', file_path: BIG, content: 'x' })
  expect(env.nexts).toHaveLength(1)
  await call(env, { tool: 'Read', file_path: BIG })
  expect(env.mcpCalls).toHaveLength(1)
  const before = env.nexts.length
  for (const e of [
    { tool: 'Write', file_path: BIG, content: 'x' },
    { tool: 'Edit', file_path: 'C:\\work\\docs\\big.md', old_string: 'a', new_string: 'b' },
    { tool: 'NotebookEdit', notebook_path: BIG, new_source: 'x' },
    { tool: 'Bash', command: 'echo x > big.md' },
  ]) {
    const out = await call(env, e)
    expect(typeof out.deny).toBe('string')
    expect(out.deny.startsWith('read.guard.refused')).toBe(true)
  }
  expect(env.nexts).toHaveLength(before)
  // Another file is not guarded.
  await call(env, { tool: 'Write', file_path: OTHER, content: 'x' })
  expect(env.nexts).toHaveLength(before + 1)
})

test('allows_write_after_real_read', async () => {
  const env = makeEnv({ classify: byInput })
  await call(env, { tool: 'Read', file_path: BIG })
  expect(env.mcpCalls).toHaveLength(1)
  const refused = await call(env, { tool: 'Write', file_path: BIG, content: 'x' })
  expect(typeof refused.deny).toBe('string')
  // A real read, by ranges below the threshold, lifts the guard.
  const real = await call(env, { tool: 'Read', file_path: BIG, offset: 1, limit: 10 })
  expect(real.result.file.content).toBe('REAL')
  const out = await call(env, { tool: 'Write', file_path: BIG, content: 'x' })
  expect(out.deny).toBeUndefined()
  expect(env.nexts.at(-1).tool).toBe('Write')
})

test('guard_survives_resume', async () => {
  const env = makeEnv({ classify: byInput })
  await call(env, { tool: 'Read', file_path: BIG })
  expect(env.mcpCalls).toHaveLength(1)
  expect(env.files.has(`${DATA}/read-guard/${SESSION}.json`)).toBe(true)
  // `--resume`: the module loads again (its variables start over) and the session starts again.
  registerInto(env, { read_mod_enabled: true })
  await onSessionStart(env.$, { cwd: CWD, isInteractive: false }, env.common)
  const out = await call(env, { tool: 'Write', file_path: BIG, content: 'x' })
  expect(typeof out.deny).toBe('string')
  expect(out.deny.startsWith('read.guard.refused')).toBe(true)
  // Per session: another session never goes by this one's list.
  env.session = 'sess-other'
  registerInto(env, { read_mod_enabled: true })
  await onSessionStart(env.$, { cwd: CWD, isInteractive: false }, env.common)
  const other = await call(env, { tool: 'Write', file_path: BIG, content: 'x' })
  expect(other.deny).toBeUndefined()
})

test('heartbeat_says_read_mod_active', async () => {
  const env = makeEnv({ classify: byInput })
  env.files.set(`${DATA}/heartbeats/${SESSION}.json`, JSON.stringify({ session_id: SESSION, pieces: { read: 'on' } }))
  await call(env, { tool: 'Read', file_path: BIG })
  await call(env, { tool: 'Read', file_path: BIG })
  // Once per load, keeping the pieces `register.js` wrote.
  expect(env.beats).toEqual([{ pieces: { read: 'on' }, read_mod_active: true }])
})
