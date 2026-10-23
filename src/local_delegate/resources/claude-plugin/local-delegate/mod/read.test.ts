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
const CODE = 'C:/work/src/big.py'
// What `local_summarize` really answers through `$.mcp.call`: FastMCP wraps the `str` it returns
// in `{ "result": … }`, as structured content and as the text block's JSON (seen live with -p).
const SUMMARY = '## Intro\nSUMMARY OF THE FILE'
function summaryResult(text: string = SUMMARY, over: Record<string, unknown> = {}) {
  return { content: [{ type: 'text', text: JSON.stringify({ result: text }) }], structuredContent: { result: text }, isError: false, ...over }
}
// A 100-line file: each range below is a percentage of it.
const HUNDRED_LINES = Array.from({ length: 100 }, (_, i) => `line ${i + 1}`).join('\n') + '\n'

type Classified = Record<string, unknown> | null | 'fail'

// What `hook classify --config` answers (`read_classifier.prefilter_config`): the mod's prefilter
// takes all of it from Python. The tests use these values unless they pass their own.
const CONFIG = {
  tools: ['Bash', 'Edit', 'Grep', 'MultiEdit', 'NotebookEdit', 'PowerShell', 'Read', 'Write', 'mcp__*'],
  prose_extensions: ['.markdown', '.md', '.rst', '.txt'],
  min_bytes: 8192,
  harmless_first: ['cd', 'date', 'echo', 'git', 'ls', 'printf', 'pwd'],
}
const CLASSIFY_ARGS = ['-I', '-m', 'local_delegate.hook', 'classify']
const RECORD_ARGS = ['-I', '-m', 'local_delegate.hook', 'record-read']

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
  mcpResult: any
  sizes: Map<string, number>
  config: any
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
  mcpResult?: any
  sizes?: Record<string, number>
  config?: any
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
    mcpResult: opts.mcpResult ?? summaryResult(),
    // What `$.fs.stat` says of each file: the files the classifier calls large are large on disk.
    sizes: new Map(Object.entries(opts.sizes ?? { [BIG]: BIG_BYTES, [OTHER]: BIG_BYTES, [CODE]: BIG_BYTES })),
    config: opts.config === undefined ? CONFIG : opts.config,
  }
  // `$.fs.stat` takes either slash and either case of the drive.
  const lookup = (p: string) => [...env.files.keys()].find(k => k.toLowerCase() === p.replace(/\\/g, '/').toLowerCase())
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
      stat: async (p: string) => {
        const key = lookup(p)
        if (key === undefined) throw new Error('ENOENT')
        return { kind: 'file', size: env.sizes.get(key) ?? env.files.get(key)!.length, mtimeMs: 0, isLink: false }
      },
    },
    mcp: {
      call: async (server: string, tool: string, args: any) => {
        env.mcpCalls.push({ server, tool, args })
        if (env.mcpFails) throw new Error('MCP down')
        return env.mcpResult
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
      if (args.includes('--config')) {
        if (env.config === null) return null
        return { exitCode: 0, stdout: typeof env.config === 'string' ? env.config : JSON.stringify(env.config), stderr: '' }
      }
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
    summarizable: true,
    ...over,
  }
}

// Classifies each call by its input, the way `hook classify` would for these cases.
function byInput(input: any): Classified {
  const ti = input.tool_input
  if (input.tool_name === 'Read') {
    const path = ti.file_path
    // `hook classify` says which band the file is in: only large prose can be summarized.
    const summarizable = path.endsWith('.md')
    if (typeof ti.offset === 'number') {
      return readCls({ path, summarizable, scope: 'range', range: [ti.offset, ti.offset + ti.limit - 1], via: 'read_range' })
    }
    return readCls({ path, summarizable })
  }
  if (input.tool_name === 'Bash' && /> *big\.md/.test(ti.command)) {
    return { kind: 'write', path: BIG, scope: 'whole', bytes: null, range: null, via: 'shell_redirect', read_switch: 'on' }
  }
  return { kind: 'other', path: null, scope: 'unclassifiable', bytes: null, range: null, via: 'other', read_switch: 'on' }
}

function decisions(env: Env): string[] {
  return env.ldRuns.filter(r => r.args.includes('record-read')).map(r => r.stdin.decision)
}

test('on_by_default', async () => {
  // F4-live passed: unset (a value never saved is the manifest's `"default": true`) and true
  // register the hook.
  expect(makeEnv({ options: {} }).hooks.filter(h => h.event === 'tool.call')).toHaveLength(1)
  expect(makeEnv({ options: { read_mod_enabled: true } }).hooks.filter(h => h.event === 'tool.call')).toHaveLength(1)
  // Guard: switched off, as a boolean or as the text an option may arrive as, there is no hook,
  // so the ones above are the switch's doing.
  expect(makeEnv({ options: { read_mod_enabled: false } }).hooks.filter(h => h.event === 'tool.call')).toHaveLength(0)
  expect(makeEnv({ options: { read_mod_enabled: 'false' } }).hooks.filter(h => h.event === 'tool.call')).toHaveLength(0)
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
  const asked = env.ldRuns.find(r => r.args.includes('classify') && !r.args.includes('--config'))!
  expect(asked.args).toEqual(CLASSIFY_ARGS)
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

test('session_start_says_read_mod_active', async () => {
  // REQ-023: the heartbeat `register.js` writes at the session's start carries what this resolves,
  // so the read hooks step aside from the first read; the first read then writes no second beat.
  const env = makeEnv({ classify: byInput })
  registerInto(env, { read_mod_enabled: true })
  const said = await onSessionStart(env.$, { cwd: CWD, isInteractive: false }, env.common)
  expect(said).toEqual({ read_mod_active: true })
  await call(env, { tool: 'Read', file_path: BIG })
  expect(env.beats).toEqual([])
  // Control: switched off, it says nothing.
  const off = makeEnv({ classify: byInput })
  registerInto(off, { read_mod_enabled: false })
  expect(await onSessionStart(off.$, { cwd: CWD, isInteractive: false }, off.common)).toBeUndefined()
})

test('summary_is_the_clean_text', async () => {
  // Structured content and the text block's JSON both carry `{ result }`: the model gets the text.
  for (const result of [summaryResult(), { content: summaryResult().content, isError: false }]) {
    const env = makeEnv({ classify: byInput, mcpResult: result })
    const out = await call(env, { tool: 'Read', file_path: BIG })
    const content: string = out.result.file.content
    expect(content.includes('{"result"')).toBe(false)
    expect(content.endsWith(`\n\n${SUMMARY}`)).toBe(true)
    // Real line breaks, not the JSON escape `\n`.
    expect(content.includes('\\n')).toBe(false)
    expect(out.result.file.numLines).toBe(content.split('\n').length)
  }
  // A plain text block (no JSON) is still taken as it comes.
  const plain = makeEnv({ classify: byInput, mcpResult: { content: [{ type: 'text', text: 'PLAIN SUMMARY' }], isError: false } })
  const out = await call(plain, { tool: 'Read', file_path: BIG })
  expect(out.result.file.content.endsWith('\n\nPLAIN SUMMARY')).toBe(true)
})

test('tool_error_lets_the_read_through', async () => {
  for (const result of [
    summaryResult('the backend is down', { isError: true }),
    summaryResult('[local-delegate error] backend unreachable'),
    { content: [{ type: 'text', text: '[local-delegate error] backend unreachable' }], isError: false },
    summaryResult(''),
  ]) {
    const env = makeEnv({ classify: byInput, mcpResult: result })
    const out = await call(env, { tool: 'Read', file_path: BIG })
    expect(env.mcpCalls).toHaveLength(1)
    expect(env.nexts).toHaveLength(1)
    expect(out.result.file.content).toBe('REAL')
    expect(decisions(env)).toEqual(['summary_failed'])
  }
})

test('large_code_passes_without_summary', async () => {
  // A subagent about to program needs the literal code: no summary, with or without a dialog.
  for (const dialog of [false, true]) {
    const env = makeEnv({ dialog, answer: 'read.ask.summarize', classify: byInput, files: { [CODE]: HUNDRED_LINES } })
    const out = await call(env, { tool: 'Read', file_path: CODE })
    expect(env.asks).toHaveLength(0)
    expect(env.mcpCalls).toHaveLength(0)
    expect(env.nexts).toHaveLength(1)
    expect(out.result.file.content).toBe('REAL')
    expect(decisions(env)).toEqual(['not_prose'])
  }
  // Read by ranges, past 80 % and to the end: every range is the real code.
  const env = makeEnv({ classify: byInput, files: { [CODE]: HUNDRED_LINES } })
  for (const offset of [1, 41, 81]) {
    const out = await call(env, { tool: 'Read', file_path: CODE, offset, limit: 40 })
    expect(out.result.file.content).toBe('REAL')
  }
  expect(env.mcpCalls).toHaveLength(0)
  // A shell dump of code goes through too.
  const shell = makeEnv({ classify: () => readCls({ path: CODE, via: 'shell_cat', summarizable: false }) })
  const shellOut = await call(shell, { tool: 'Bash', command: 'cat src/big.py' })
  expect(shellOut.result.stdout).toBe('REAL')
  expect(shell.mcpCalls).toHaveLength(0)
  // Guard: the same calls on large prose are summarized, so the zeros above are the band's doing.
  const prose = makeEnv({ classify: byInput })
  await call(prose, { tool: 'Read', file_path: BIG })
  expect(prose.mcpCalls).toHaveLength(1)
})

test('large_prose_is_summarized_without_dialog', async () => {
  const env = makeEnv({ dialog: false, classify: byInput })
  const out = await call(env, { tool: 'Read', file_path: BIG })
  expect(env.nexts).toHaveLength(0)
  expect(out.result.file.content.includes('SUMMARY OF THE FILE')).toBe(true)
  expect(decisions(env)).toEqual(['auto_summarized'])
  // A classifier without the band (an older one) is not trusted to summarize: the read passes.
  const old = makeEnv({ classify: () => { const c: any = readCls(); delete c.summarizable; return c } })
  const real = await call(old, { tool: 'Read', file_path: BIG })
  expect(old.mcpCalls).toHaveLength(0)
  expect(real.result.file.content).toBe('REAL')
})

// --- The cost per call (F4-read-mod-perf, evidence/F4-live.md) -------------------------------------

function classifyRuns(env: Env) {
  return env.ldRuns.filter(r => r.args.includes('classify') && !r.args.includes('--config') && !r.args.includes('--list-tools'))
}
function configRuns(env: Env) {
  return env.ldRuns.filter(r => r.args.includes('--config'))
}
// The F4-live script: five small reads that the old filter let through, five calls it already
// dropped, and `echo`, which went to the classifier because it was not in the harmless list.
const SMALL = 'C:/work/LICENSE'
const IGNORE = 'C:/work/.gitignore'
const F4_LIVE_SCRIPT = [
  'cat LICENSE', 'head -5 .gitignore', 'sed -n 1,5p LICENSE', 'cat .gitignore', 'head -n 3 LICENSE',
  'git status --short', 'pwd', 'ls', 'git log -1 --oneline', 'date', 'echo hi',
]

test('runs_the_light_path', async () => {
  // `local_delegate.hook`, never `-m local_delegate hook` (entrypoint, then server, then the MCP SDK).
  const env = makeEnv({ classify: byInput })
  await onSessionStart(env.$, { cwd: CWD, isInteractive: false }, env.common)
  await call(env, { tool: 'Read', file_path: BIG })
  expect(configRuns(env).map(r => r.args)).toEqual([[...CLASSIFY_ARGS, '--config']])
  expect(classifyRuns(env).map(r => r.args)).toEqual([CLASSIFY_ARGS])
  const records = env.ldRuns.filter(r => r.args.includes('record-read'))
  expect(records.length).toBe(1)
  expect(records[0].args).toEqual(RECORD_ARGS)
})

test('prefilter_spares_the_f4_live_script', async () => {
  const files = { [BIG]: HUNDRED_LINES, [OTHER]: HUNDRED_LINES, [SMALL]: 'MIT\n', [IGNORE]: 'node_modules\n' }
  const env = makeEnv({ classify: byInput, files })
  await onSessionStart(env.$, { cwd: CWD, isInteractive: false }, env.common)
  for (const command of F4_LIVE_SCRIPT) {
    const out = await call(env, { tool: 'Bash', command })
    expect(out.result.stdout).toBe('REAL')
  }
  // No call in the script names prose or a large file: not one process.
  expect(classifyRuns(env)).toHaveLength(0)
  expect(env.nexts).toHaveLength(F4_LIVE_SCRIPT.length)
  // Guard: a shell read of a large `.md` still reaches the classifier.
  await call(env, { tool: 'Bash', command: 'cat docs/big.md' })
  expect(classifyRuns(env)).toHaveLength(1)
  expect(classifyRuns(env)[0].stdin.tool_input).toEqual({ command: 'cat docs/big.md' })
  // So does a `Read` of one.
  await call(env, { tool: 'Read', file_path: OTHER })
  expect(classifyRuns(env)).toHaveLength(2)
})

test('prefilter_drops_small_non_prose_reads', async () => {
  const files = { [SMALL]: 'MIT\n', 'C:/work/src/small.py': 'x = 1\n', [CODE]: HUNDRED_LINES }
  const env = makeEnv({ classify: byInput, files, sizes: { [CODE]: BIG_BYTES } })
  await call(env, { tool: 'Read', file_path: 'C:/work/src/small.py' })
  await call(env, { tool: 'Bash', command: 'cat src/small.py' })
  await call(env, { tool: 'Read', file_path: 'C:/work/missing.json' })
  await call(env, { tool: 'Grep', pattern: 'foo' })
  expect(classifyRuns(env)).toHaveLength(0)
  // A large file that is not prose still goes to the classifier: its read is logged (`not_prose`).
  await call(env, { tool: 'Read', file_path: CODE })
  await call(env, { tool: 'Bash', command: 'cat src/big.py' })
  expect(classifyRuns(env)).toHaveLength(2)
  expect(decisions(env)[0]).toBe('not_prose')
})

test('prefilter_takes_its_data_from_python', async () => {
  // Another prose list, threshold and harmless list from `--config`: the mod follows them.
  const config = { ...CONFIG, prose_extensions: ['.prose'], min_bytes: 1 << 30, harmless_first: ['cat'] }
  const files = { [BIG]: HUNDRED_LINES, 'C:/work/notes.prose': 'x\n' }
  const env = makeEnv({ classify: byInput, files, config })
  await onSessionStart(env.$, { cwd: CWD, isInteractive: false }, env.common)
  await call(env, { tool: 'Read', file_path: BIG })
  expect(classifyRuns(env)).toHaveLength(0)
  await call(env, { tool: 'Read', file_path: 'C:/work/notes.prose' })
  expect(classifyRuns(env)).toHaveLength(1)
  // `cat` is harmless here, `echo` is not.
  await call(env, { tool: 'Bash', command: 'cat notes.prose' })
  expect(classifyRuns(env)).toHaveLength(1)
  await call(env, { tool: 'Bash', command: 'echo notes.prose' })
  expect(classifyRuns(env)).toHaveLength(2)
  // The tool list comes from Python too: a tool it does not name is never classified.
  const narrow = makeEnv({ classify: byInput, config: { ...CONFIG, tools: ['Bash'] } })
  await onSessionStart(narrow.$, { cwd: CWD, isInteractive: false }, narrow.common)
  await call(narrow, { tool: 'Read', file_path: BIG })
  expect(classifyRuns(narrow)).toHaveLength(0)
})

test('echo_is_harmless_unless_it_writes', async () => {
  const env = makeEnv({ classify: byInput })
  await call(env, { tool: 'Bash', command: 'echo docs/big.md' })
  expect(classifyRuns(env)).toHaveLength(0)
  // A redirection can write: it goes to the classifier, and the guard can refuse it.
  await call(env, { tool: 'Bash', command: 'echo x > big.md' })
  expect(classifyRuns(env)).toHaveLength(1)
})

test('guarded_file_reaches_the_classifier', async () => {
  // A guarded file named without a prose extension the list knows (a list saved under another
  // config): the call still goes to the classifier, which sees the write.
  const LOG = 'c:/work/out/report.log'
  const env = makeEnv({
    classify: (input: any) =>
      /report\.log/.test(input.tool_input.command ?? '')
        ? { kind: 'write', path: 'C:/work/out/report.log', scope: 'unclassifiable', bytes: null, range: null, via: 'shell_redirect', read_switch: 'on' }
        : byInput(input),
  })
  env.files.set(`${DATA}/read-guard/${SESSION}.json`, JSON.stringify({ session_id: SESSION, paths: [LOG] }))
  await call(env, { tool: 'Bash', command: 'git log > out/other.log' })
  expect(classifyRuns(env)).toHaveLength(0)
  const out = await call(env, { tool: 'Bash', command: 'printf x > out/report.log' })
  expect(classifyRuns(env)).toHaveLength(1)
  expect(typeof out.deny).toBe('string')
})

test('config_is_asked_once', async () => {
  const env = makeEnv({ classify: byInput })
  await onSessionStart(env.$, { cwd: CWD, isInteractive: false }, env.common)
  for (let i = 0; i < 5; i++) await call(env, { tool: 'Bash', command: 'cat docs/big.md' })
  expect(configRuns(env)).toHaveLength(1)
  // A reload mid-session has no `session.start`: the first call that may need it asks, once.
  registerInto(env, { read_mod_enabled: true })
  for (let i = 0; i < 3; i++) await call(env, { tool: 'Bash', command: 'cat docs/other.md' })
  expect(configRuns(env)).toHaveLength(2)
})

test('without_config_every_candidate_is_classified', async () => {
  // A package that does not answer `--config` (or answers something else): the old filter, and the
  // classifier decides; nothing is dropped on a guess.
  for (const config of [null, 'not json', JSON.stringify({ kind: 'other' })]) {
    const files = { [SMALL]: 'MIT\n' }
    const env = makeEnv({ classify: byInput, files, config })
    await onSessionStart(env.$, { cwd: CWD, isInteractive: false }, env.common)
    await call(env, { tool: 'Bash', command: 'cat LICENSE' })
    await call(env, { tool: 'Read', file_path: BIG })
    expect(classifyRuns(env)).toHaveLength(2)
  }
})
