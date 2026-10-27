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
  // The daemon (F4-classify-daemon): how it answers, what it was asked, and the clock the mod reads.
  daemon: Daemon
  daemonCalls: { path: string; init: any; body: any }[]
  vars: Record<string, string>
  now: number
  sleeps: number[]
  // F4-read-fixes: what `$.ui.log` got, whether a dialog was shown, and whether `$.process.run`
  // refuses to start once it was (the live 0.41.0 symptom: no dialog decision ever reached the log).
  logs: { message: string; opts: any }[]
  asked: boolean
  refuseProcessAfterAsk: boolean
  recordStatus: number | null | 'slow'
  // F4-live-fixes: the lines that reached the telemetry file, by either road, written the way
  // `hook_common.already_recorded` keeps them (an `id` already written is not written again), and
  // the daemon's record answers still to come (`recordStatus: 'slow'`).
  telemetry: { decision: string; id: unknown }[]
  slowRecords: (() => void)[]
}

// `up` answers like `hook classify`; the rest are the ways the daemon can fail the mod.
type Daemon = 'none' | 'up' | 'down' | 'hang' | '401' | '404' | 'invalid' | 'notoken'

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
  daemon?: Daemon
  vars?: Record<string, string> | null
  refuseProcessAfterAsk?: boolean
  recordStatus?: number | null | 'slow'
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
    daemon: opts.daemon ?? 'none',
    daemonCalls: [],
    vars: opts.vars === null ? (null as any) : opts.vars ?? VARS,
    now: 1_000_000,
    sleeps: [],
    logs: [],
    asked: false,
    refuseProcessAfterAsk: opts.refuseProcessAfterAsk ?? false,
    recordStatus: opts.recordStatus === undefined ? 204 : opts.recordStatus,
    telemetry: [],
    slowRecords: [],
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
        env.asked = true
        if (env.answer === null) throw new Error('dismissed')
        return env.answer
      },
      toast: async () => undefined,
      log: async (message: string, opts: any) => {
        env.logs.push({ message, opts })
      },
    },
    // `$.env.get`: the variables of the Claude Code process (`vars: null`, an engine without it).
    env: {
      get: async (name: string) => {
        if (env.vars === null) throw new Error('no env noun')
        return env.vars[name]
      },
    },
    // A daemon that hangs never answers; the mod's own time limit is a `$.clock.sleep`.
    clock: {
      now: async () => env.now,
      sleep: async (ms: number) => {
        env.sleeps.push(ms)
      },
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
    token: async () => (env.daemon === 'notoken' ? null : 'tok'),
    daemonFetch: env.daemon === 'none' ? undefined : (path: string, init: any) => daemonAnswer(env, path, init),
    runLd: async (args: string[], stdin?: string) => {
      // `common.runLd` resolves null when `$.process.run` is refused.
      if (env.refuseProcessAfterAsk && env.asked) return null
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
      if (args.includes('record-read')) writeTelemetry(env, parsed)
      return { exitCode: 0, stdout: '', stderr: '' }
    },
  }
  registerInto(env, opts.options ?? { read_mod_enabled: true })
  return env
}

// The variables the test process "has": what `hook_entry.CLASSIFY_ENV` names, plus one it does not.
const VARS: Record<string, string> = {
  LD_HOOK_READ_ENABLED: '1',
  LD_HOOK_READ_BLOCK: '1',
  LD_HOOK_READ_SUGGEST_KB: '4',
  LOCAL_DELEGATE_LOG_DIR: 'C:/data/ld',
  USERPROFILE: 'C:/Users/me',
  PATH: 'C:/bin',
}

// What the daemon answers to `POST /api/hook/classify[-config]`, like `common.daemonFetch` resolves.
async function daemonAnswer(env: Env, path: string, init: any) {
  const body = init && typeof init.body === 'string' ? JSON.parse(init.body) : undefined
  env.daemonCalls.push({ path, init, body })
  const ok = (text: string) => ({ status: 200, ok: true, text, json: JSON.parse(text) })
  switch (env.daemon) {
    case 'down':
      return null
    case 'hang':
      return new Promise(() => undefined)
    case '401':
      return { status: 401, ok: false, text: '{"detail":"no"}', json: { detail: 'no' } }
    case '404':
      return { status: 404, ok: false, text: '{"detail":"Not Found"}', json: { detail: 'Not Found' } }
    case 'invalid':
      return { status: 200, ok: true, text: '<html>', json: null }
  }
  if (path === '/api/hook/classify-config') {
    return ok(typeof env.config === 'string' ? env.config : JSON.stringify(env.config))
  }
  if (path === '/api/hook/record-read') {
    // `'slow'`: the daemon takes longer than the mod's limit, and writes the line when it answers.
    if (env.recordStatus === 'slow') {
      return new Promise(resolve => {
        env.slowRecords.push(() => {
          writeTelemetry(env, body.payload)
          resolve({ status: 204, ok: true, text: '', json: null })
        })
      })
    }
    // `null`: the request does not complete (refused, or no daemon).
    if (env.recordStatus === null) return null
    if (env.recordStatus < 300) writeTelemetry(env, body.payload)
    return { status: env.recordStatus, ok: env.recordStatus < 300, text: '', json: null }
  }
  if (path === '/api/hook/classify') {
    const answer = env.classify(body.payload)
    return answer === null || answer === 'fail' ? { status: 500, ok: false, text: '', json: null } : ok(JSON.stringify(answer))
  }
  return { status: 404, ok: false, text: '', json: null }
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

// A `record-read` line reaching the file, as `record_decision` writes it (F4-live-fixes): one whose
// valid `id` is already there is dropped.
function writeTelemetry(env: Env, entry: any) {
  const id = entry && typeof entry.id === 'string' && /^[0-9a-f]{12}$/.test(entry.id) ? entry.id : null
  if (id !== null && env.telemetry.some(line => line.id === id)) return
  env.telemetry.push({ decision: entry.decision, id: entry.id })
}

function decisions(env: Env): string[] {
  return env.ldRuns.filter(r => r.args.includes('record-read')).map(r => r.stdin.decision)
}

// The decisions the daemon took (`POST /api/hook/record-read`, F4-read-fixes).
function daemonDecisions(env: Env): string[] {
  return env.daemonCalls.filter(c => c.path === '/api/hook/record-read').map(c => c.body.payload.decision)
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

test('subagent_large_file_gets_locate_then_range_note', async () => {
  // Issue #443: inside a subagent a large file read whole, code included, still goes through, and
  // the note says to locate the lines with a `local_*` tool and read only that range.
  const notes = (out: any) => (out.context ?? []).filter((line: string) => line.startsWith('read.'))
  const sub = makeEnv({ dialog: true, answer: 'read.ask.summarize', classify: byInput, files: { [CODE]: HUNDRED_LINES } })
  const subOut = await call(sub, { tool: 'Read', file_path: CODE, agentId: 'agent-1' })
  expect(sub.nexts).toHaveLength(1)
  expect(subOut.result.file.content).toBe('REAL')
  expect(sub.asks).toHaveLength(0)
  expect(sub.mcpCalls).toHaveLength(0)
  expect(notes(subOut)).toEqual([`read.warn.subagent kb=64 path=${CODE}`])
  expect(decisions(sub)).toEqual(['not_prose'])
  // A range is already the pattern: no note.
  const rangeOut = await call(sub, { tool: 'Read', file_path: CODE, offset: 1, limit: 40, agentId: 'agent-1' })
  expect(notes(rangeOut)).toEqual([])
  // The main thread keeps its behavior: the same whole read of code passes with no note.
  for (const dialog of [false, true]) {
    const main = makeEnv({ dialog, classify: byInput, files: { [CODE]: HUNDRED_LINES } })
    const mainOut = await call(main, { tool: 'Read', file_path: CODE })
    expect(mainOut.result.file.content).toBe('REAL')
    expect(notes(mainOut)).toEqual([])
  }
  // An unclassifiable read in a subagent: the subagent note instead of «if a summary is enough».
  const warn = makeEnv({ classify: () => readCls({ scope: 'unclassifiable', via: 'shell_grep', range: null }) })
  const warnOut = await call(warn, { tool: 'Bash', command: 'grep -n foo docs/big.md | sort', agentId: 'agent-1' })
  expect(warnOut.result.stdout).toBe('REAL')
  expect(notes(warnOut)).toEqual([`read.warn.subagent kb=64 path=${BIG}`])
  expect(decisions(warn)).toEqual(['warned'])
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

// --- The daemon's classifier (F4-classify-daemon) -------------------------------------------------

function daemonPaths(env: Env): string[] {
  return env.daemonCalls.map(c => c.path)
}

test('classifies_through_the_daemon', async () => {
  const env = makeEnv({ classify: byInput, daemon: 'up' })
  await onSessionStart(env.$, { cwd: CWD, isInteractive: false }, env.common)
  const out = await call(env, { tool: 'Read', file_path: BIG })
  // Not one process for `classify` or `--config`: the daemon answered both.
  expect(classifyRuns(env)).toHaveLength(0)
  expect(configRuns(env)).toHaveLength(0)
  // The decision went to the daemon too (F4-read-fixes).
  expect(daemonPaths(env)).toEqual(['/api/hook/classify-config', '/api/hook/classify', '/api/hook/record-read'])
  // Same answer, same decision as through the process.
  expect(out.result.file.content.includes('SUMMARY OF THE FILE')).toBe(true)
  expect(daemonDecisions(env)).toEqual(['auto_summarized'])
  expect(decisions(env)).toEqual([])
  // The request: a POST with the hook's input and the client's classifier variables, and only those.
  const ask = env.daemonCalls[1]
  expect(ask.init.method).toBe('POST')
  expect(ask.body.payload).toEqual({ tool_name: 'Read', tool_input: { file_path: BIG }, cwd: CWD, session_id: SESSION })
  const { PATH, ...sent } = VARS
  expect(PATH).toBe('C:/bin')
  expect(ask.body.env).toEqual(sent)
  expect(env.daemonCalls[0].body.env).toEqual(sent)
  // With a time limit on each request.
  expect(env.sleeps.length).toBeGreaterThan(0)
  expect(env.sleeps.every(ms => ms <= 1000)).toBe(true)
})

test('daemon_config_feeds_the_prefilter', async () => {
  const env = makeEnv({ classify: byInput, daemon: 'up', config: { ...CONFIG, min_bytes: 70 * 1024 } })
  await onSessionStart(env.$, { cwd: CWD, isInteractive: false }, env.common)
  // 64 KB of code is under the daemon's 70 KB: dropped without asking anyone.
  await call(env, { tool: 'Bash', command: 'cat src/big.py' })
  expect(configRuns(env)).toHaveLength(0)
  expect(daemonPaths(env)).toEqual(['/api/hook/classify-config'])
  expect(classifyRuns(env)).toHaveLength(0)
})

for (const failure of ['down', 'hang', '401', '404', 'invalid', 'notoken'] as Daemon[]) {
  test(`falls_back_to_the_process_when_daemon_${failure}`, async () => {
    const env = makeEnv({ classify: byInput, daemon: failure })
    await onSessionStart(env.$, { cwd: CWD, isInteractive: false }, env.common)
    const out = await call(env, { tool: 'Read', file_path: BIG })
    // The call is not lost: the process classified it and the read was summarized as before.
    expect(configRuns(env)).toHaveLength(1)
    expect(classifyRuns(env)).toHaveLength(1)
    expect(out.result.file.content.includes('SUMMARY OF THE FILE')).toBe(true)
    expect(decisions(env)).toEqual(['auto_summarized'])
    // Guard: the daemon was the first thing tried (without a token it is not even asked).
    expect(env.daemonCalls.length).toBe(failure === 'notoken' ? 0 : 1)
  })
}

test('falls_back_when_the_variables_cannot_be_read', async () => {
  // Without the variables the daemon would classify with the wrong switch: the process, not a guess.
  const env = makeEnv({ classify: byInput, daemon: 'up', vars: null })
  await call(env, { tool: 'Read', file_path: BIG })
  expect(env.daemonCalls).toHaveLength(0)
  expect(classifyRuns(env)).toHaveLength(1)
})

test('remembers_a_daemon_failure_for_a_while', async () => {
  const env = makeEnv({ classify: byInput, daemon: 'hang' })
  await onSessionStart(env.$, { cwd: CWD, isInteractive: false }, env.common)
  for (let i = 0; i < 4; i++) await call(env, { tool: 'Read', file_path: BIG })
  // One timeout paid (the config), then straight to the process.
  expect(env.daemonCalls).toHaveLength(1)
  expect(classifyRuns(env)).toHaveLength(4)
  // Some time later it is worth asking again, and a daemon back up is used.
  env.now += 10 * 60 * 1000
  env.daemon = 'up'
  await call(env, { tool: 'Read', file_path: BIG })
  expect(daemonPaths(env)).toEqual(['/api/hook/classify-config', '/api/hook/classify', '/api/hook/record-read'])
  expect(classifyRuns(env)).toHaveLength(4)
})

// --- F4-read-fixes: the dialog's decisions reach the log, and the summary says the real rule -------

// The variables the record route needs on top of the classifier's (`hook_entry.RECORD_ENV`).
const RECORD_VARS: Record<string, string> = {
  ...VARS,
  LD_HOOK_TELEMETRY_LOG: 'C:/Users/me/.claude/hooks/telemetry.jsonl',
  LD_HOOK_ENABLED: '1',
}
const FAILURES = 'C:/data/ld/hook-failures.jsonl'

test('dialog_decisions_are_recorded_by_the_daemon_when_the_process_is_refused', async () => {
  // Live 0.41.0: after `$.ui.ask`, the `record-read` process never wrote its line. With the daemon
  // up, each of the three dialog decisions still reaches the log, by HTTP.
  for (const [answer, decision] of [
    ['read.ask.summarize', 'summarized'],
    ['read.ask.whole', 'read_whole'],
    [null, 'dismissed'],
  ] as const) {
    const env = makeEnv({ dialog: true, answer, classify: byInput, daemon: 'up', vars: RECORD_VARS, refuseProcessAfterAsk: true })
    await call(env, { tool: 'Read', file_path: BIG })
    expect(env.asks).toHaveLength(1)
    expect(daemonDecisions(env)).toEqual([decision])
    const sent = env.daemonCalls.find(c => c.path === '/api/hook/record-read')!
    expect(sent.init.method).toBe('POST')
    expect(sent.body.payload).toMatchObject({ path: BIG, via: 'read_whole', session_id: SESSION, decision })
    // The route gets what `record-read` reads: the destination and the experiment's switch too.
    expect(sent.body.env).toEqual({
      LD_HOOK_READ_ENABLED: '1',
      LD_HOOK_READ_BLOCK: '1',
      LD_HOOK_READ_SUGGEST_KB: '4',
      LOCAL_DELEGATE_LOG_DIR: 'C:/data/ld',
      USERPROFILE: 'C:/Users/me',
      LD_HOOK_TELEMETRY_LOG: 'C:/Users/me/.claude/hooks/telemetry.jsonl',
      LD_HOOK_ENABLED: '1',
    })
    // Recorded once: the process is not asked again after the daemon took the line.
    expect(decisions(env)).toEqual([])
    expect(env.logs).toHaveLength(0)
  }
})

test('the_process_is_the_fallback_when_the_daemon_does_not_record', async () => {
  for (const status of [404, 401, 500, null]) {
    const env = makeEnv({ dialog: true, answer: 'read.ask.summarize', classify: byInput, daemon: 'up', vars: RECORD_VARS, recordStatus: status })
    await call(env, { tool: 'Read', file_path: BIG })
    expect(daemonDecisions(env)).toEqual(['summarized'])
    expect(decisions(env)).toEqual(['summarized'])
    expect(env.logs).toHaveLength(0)
  }
})

test('a_lost_decision_leaves_a_trace_and_is_retried', async () => {
  const env = makeEnv({
    dialog: true,
    answer: 'read.ask.summarize',
    classify: byInput,
    daemon: 'up',
    vars: RECORD_VARS,
    refuseProcessAfterAsk: true,
    recordStatus: null,
  })
  const out = await call(env, { tool: 'Read', file_path: BIG })
  // The read itself is not touched: the summary arrives.
  expect(out.result.file.content.includes('SUMMARY OF THE FILE')).toBe(true)
  // A debug line, without the file's content or its path.
  expect(env.logs).toHaveLength(1)
  expect(env.logs[0].opts).toEqual({ to: 'debug' })
  expect(env.logs[0].message.includes('summarized')).toBe(true)
  expect(env.logs[0].message.includes('SUMMARY')).toBe(false)
  expect(env.logs[0].message.includes('big.md')).toBe(false)
  // And a line in the hooks' failure log, the shape `hook_entry._log_failure` writes.
  const failures = (env.files.get(FAILURES) ?? '').trim().split('\n').filter(Boolean).map(line => JSON.parse(line))
  expect(failures).toHaveLength(1)
  expect(failures[0]).toMatchObject({ hook: 'record-read', error: 'ModRecordLost', decision: 'summarized' })
  expect(typeof failures[0].ts).toBe('string')
  expect(JSON.stringify(failures[0]).includes('big.md')).toBe(false)

  // The next tool call, with no dialog before it, records the lost line first.
  env.recordStatus = 204
  await call(env, { tool: 'Bash', command: 'git status' })
  expect(daemonDecisions(env)).toEqual(['summarized', 'summarized'])
  // Once recorded, it is not sent again.
  await call(env, { tool: 'Bash', command: 'git status' })
  expect(daemonDecisions(env)).toEqual(['summarized', 'summarized'])
})

test('the_failure_log_is_capped', async () => {
  const env = makeEnv({
    dialog: true,
    answer: 'read.ask.whole',
    classify: byInput,
    daemon: 'up',
    vars: RECORD_VARS,
    refuseProcessAfterAsk: true,
    recordStatus: null,
  })
  env.files.set(FAILURES, 'x')
  env.sizes.set(FAILURES, 300 * 1024)
  await call(env, { tool: 'Read', file_path: BIG })
  expect(env.files.get(FAILURES)).toBe('x')
  expect(env.logs).toHaveLength(1)
})

// --- F4-live-fixes: one decision, one line ----------------------------------------------------------

function failureLines(env: Env): any[] {
  return (env.files.get(FAILURES) ?? '').trim().split('\n').filter(Boolean).map(line => JSON.parse(line))
}

function recordIds(env: Env): unknown[] {
  return [
    ...env.daemonCalls.filter(c => c.path === '/api/hook/record-read').map(c => c.body.payload.id),
    ...env.ldRuns.filter(r => r.args.includes('record-read')).map(r => r.stdin.id),
  ]
}

for (const refuse of [true, false]) {
  test(`a_daemon_slower_than_its_limit_that_writes_leaves_one_line_${refuse ? 'process_refused' : 'process_up'}`, async () => {
    // Live 2026-10-23: the daemon answered after the mod's 1 s limit but wrote the line; the mod
    // called it lost (6 ms after the line was there) and the next tool call wrote it again.
    const env = makeEnv({
      dialog: true,
      answer: 'read.ask.summarize',
      classify: byInput,
      daemon: 'up',
      vars: RECORD_VARS,
      refuseProcessAfterAsk: refuse,
      recordStatus: 'slow',
    })
    const out = await call(env, { tool: 'Read', file_path: BIG })
    expect(out.result.file.content.includes('SUMMARY OF THE FILE')).toBe(true)
    // Guard: the daemon's limit did run out (the answer is still to come).
    expect(env.slowRecords).toHaveLength(1)
    // A late answer is not a lost line: no trace, and no second writer racing the daemon.
    expect(env.logs).toHaveLength(0)
    expect(failureLines(env)).toHaveLength(0)
    expect(decisions(env)).toEqual([])
    // The daemon writes after all; the next call tries once more, with the same id.
    env.slowRecords.splice(0).forEach(write => write())
    env.recordStatus = 204
    await call(env, { tool: 'Bash', command: 'git status' })
    expect(daemonDecisions(env)).toEqual(['summarized', 'summarized'])
    expect(env.telemetry).toEqual([{ decision: 'summarized', id: env.telemetry[0].id }])
    expect(env.logs).toHaveLength(0)
    expect(failureLines(env)).toHaveLength(0)
    // And it is not sent a third time.
    await call(env, { tool: 'Bash', command: 'git status' })
    expect(daemonDecisions(env)).toHaveLength(2)
  })
}

test('every_road_carries_the_same_id', async () => {
  // Daemon down, process refused: lost, then retried by the daemon. Daemon down, process up: the
  // process takes it. Each decision has one id, on every road, and two decisions two ids.
  const lost = makeEnv({ dialog: true, answer: 'read.ask.summarize', classify: byInput, daemon: 'up', vars: RECORD_VARS, refuseProcessAfterAsk: true, recordStatus: null })
  await call(lost, { tool: 'Read', file_path: BIG })
  lost.recordStatus = 204
  await call(lost, { tool: 'Bash', command: 'git status' })
  const ids = recordIds(lost)
  expect(ids).toHaveLength(2)
  expect(String(ids[0])).toMatch(/^[0-9a-f]{12}$/)
  expect(ids[1]).toBe(ids[0])
  expect(lost.telemetry).toHaveLength(1)

  const viaProcess = makeEnv({ dialog: true, answer: 'read.ask.whole', classify: byInput, daemon: 'up', vars: RECORD_VARS, recordStatus: null })
  await call(viaProcess, { tool: 'Read', file_path: BIG })
  await call(viaProcess, { tool: 'Read', file_path: OTHER })
  const both = recordIds(viaProcess)
  // daemon then process, for each of the two reads
  expect(both).toHaveLength(4)
  expect(both[0]).toMatch(/^[0-9a-f]{12}$/)
  expect(new Set(both).size).toBe(2)
})

test('a_late_daemon_that_never_writes_is_traced_at_the_retry', async () => {
  // The daemon is late twice and the process is refused: the line may really be lost, so the trace
  // is written then (once), not left out.
  const env = makeEnv({ dialog: true, answer: 'read.ask.summarize', classify: byInput, daemon: 'up', vars: RECORD_VARS, refuseProcessAfterAsk: true, recordStatus: 'slow' })
  await call(env, { tool: 'Read', file_path: BIG })
  expect(failureLines(env)).toHaveLength(0)
  await call(env, { tool: 'Bash', command: 'git status' })
  expect(failureLines(env)).toHaveLength(1)
  expect(failureLines(env)[0]).toMatchObject({ hook: 'record-read', error: 'ModRecordLost', decision: 'summarized' })
  expect(env.telemetry).toHaveLength(0)
  await call(env, { tool: 'Bash', command: 'git status' })
  expect(failureLines(env)).toHaveLength(1)
})

test('the_summary_says_how_much_can_be_read_literally', async () => {
  const env = makeEnv({ classify: byInput })
  const out = await call(env, { tool: 'Read', file_path: BIG })
  const text: string = out.result.file.content
  // 100 lines: under 80 % is up to 79 of them.
  expect(text.startsWith(`read.summary.header_budget lines=79 path=${BIG} total=100`)).toBe(true)
})

test('a_range_summary_says_it_was_the_accumulated_share', async () => {
  const env = makeEnv({ classify: byInput })
  const range = (offset: number, limit: number) => call(env, { tool: 'Read', file_path: BIG, offset, limit })
  await range(1, 50)
  const out = await range(51, 40) // lines 51-90: with the first 50, 90 % of the file
  expect(env.mcpCalls).toHaveLength(1)
  const text: string = out.result.file.content
  expect(text.startsWith(`read.summary.header_ranges left=29 lines=79 path=${BIG} pct=90 read=50 total=100`)).toBe(true)
  // A range small enough still goes through literally after the summary.
  const next = await range(91, 5)
  expect(next.result.file.content).toBe('REAL')
})
