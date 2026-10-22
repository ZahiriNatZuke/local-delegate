// Tests of the slash commands piece (REQ-014). They drive `register` with a fake `$` and a fake
// `common` (the interface fixed in the plan for `mod/common.js`), so they depend neither on the
// real `common.js` nor on the generated `register.js`. The `$` and `on` of the kit are not used:
// nothing here loads the plugin.
import { expect, test } from 'claude-code/testing'
import { register } from './commands.js'

const DATA = 'C:\\cfg\\plugins\\data\\local-delegate-local-delegate'
const REMOVE_MARK = 'os.remove'

type Env = {
  $: any
  common: any
  hooks: any[]
  files: Map<string, string>
  runs: any[]
  mcpCalls: any[]
  ldRuns: any[]
  registered: any[]
}

function makeT(language: string) {
  return (key: string, vars?: Record<string, unknown>) => {
    const tail = vars
      ? ' ' + Object.keys(vars).sort().map((k) => `${k}=${String(vars[k])}`).join(' ')
      : ''
    return `[${language}] ${key}${tail}`
  }
}

function makeEnv(opts: {
  cwd?: string
  language?: string
  process?: boolean
  procImpl?: (argv: string[], init: any) => any
  mcpImpl?: (tool: string, args: any, env: Env) => any
  files?: Record<string, string>
  runLd?: boolean
} = {}): Env {
  const cwd = opts.cwd ?? 'C:\\work'
  const language = opts.language ?? 'es'
  const env: Env = {
    $: null,
    common: null,
    hooks: [],
    files: new Map(Object.entries(opts.files ?? {})),
    runs: [],
    mcpCalls: [],
    ldRuns: [],
    registered: [],
  }
  const $: any = {
    session: { cwd: async () => cwd },
    fs: {
      write: async (p: string, text: string) => {
        env.files.set(p, text)
      },
      exists: async (p: string) => env.files.has(p),
      stat: async (p: string) => {
        if (!env.files.has(p)) throw new Error('missing')
        return { kind: 'file', size: env.files.get(p)!.length, mtimeMs: 0, isLink: false }
      },
    },
    mcp: {
      call: async (server: string, tool: string, args: any) => {
        env.mcpCalls.push({ server, tool, args, seen: args && env.files.get(args.path) })
        const impl = opts.mcpImpl ?? (() => ({ content: [{ type: 'text', text: 'SUMMARY' }], isError: false }))
        return impl(tool, args, env)
      },
    },
    command: {
      register: async (spec: any) => {
        env.registered.push(spec)
        return { command: spec.name }
      },
    },
  }
  if (opts.process !== false) {
    $.process = {
      run: async (argv: string[], init: any) => {
        env.runs.push({ argv, init })
        const impl = opts.procImpl ?? (() => ({ exitCode: 0, stdout: 'out', stderr: '', isStdoutTruncated: false, isStderrTruncated: false }))
        return impl(argv, init)
      },
    }
  } else {
    // Not available on this surface, or blocked by policy: the call rejects.
    $.process = {
      run: async () => {
        throw new Error('process.run is not available')
      },
    }
  }
  env.$ = $
  env.common = {
    t: makeT(language),
    dataPath: (name: string) => `${DATA}\\${name.replace(/\//g, '\\')}`,
    runLd: async (args: string[], stdin?: string) => {
      env.ldRuns.push({ args, stdin })
      // `runLd` goes through `$.process.run`: without it, or with a broken interpreter, null.
      if (opts.runLd === false || opts.process === false) return null
      const script = args.find((a) => a.includes(REMOVE_MARK))
      if (script) env.files.delete(args[args.length - 1])
      return { exitCode: 0, stdout: '', stderr: '' }
    },
  }
  register((event: string, matcher: any, hook?: any) => {
    if (typeof matcher === 'function') env.hooks.push({ event, matcher: undefined, hook: matcher })
    else env.hooks.push({ event, matcher, hook })
  }, { language, commands_enabled: true }, env.common)
  return env
}

async function run(env: Env, command: string, args: string): Promise<any> {
  const entry = env.hooks.find((h) => h.event === 'command.run' && h.matcher?.command === command)
  if (!entry) throw new Error(`no command.run hook for ${command}`)
  const next = () => {
    throw new Error('the command must answer for itself, without next')
  }
  return entry.hook(env.$, { command, args, origin: { kind: 'composer' }, presentation: {} }, next)
}

function tempFiles(env: Env): string[] {
  return [...env.files.keys()].filter((p) => p.startsWith(DATA))
}

const DIFF = 'diff --git a/x b/x\n+API_KEY=sk-secret\n'

test('splits_windows_args', async () => {
  const env = makeEnv({ cwd: 'C:\\work' })
  await run(env, 'local-lint', String.raw`tool "a b" c\d "e\"f" "g""h" x\\"y z" 'q r'`)
  expect(env.runs).toHaveLength(1)
  expect(env.runs[0].argv).toEqual(['tool', 'a b', 'c\\d', 'e"f', 'g"h', 'x\\y z', "'q", "r'"])
  expect(env.runs[0].init.timeoutMs).toBe(30000)
})

test('splits_posix_args', async () => {
  const env = makeEnv({ cwd: '/home/u/repo' })
  await run(env, 'local-lint', String.raw`tool 'a b' "c \"d\" \$e" f\ g 'h"i' "j'k" 'x\y'`)
  expect(env.runs).toHaveLength(1)
  expect(env.runs[0].argv).toEqual(['tool', 'a b', 'c "d" $e', 'f g', 'h"i', "j'k", 'x\\y'])
  expect(env.runs[0].init.timeoutMs).toBe(30000)
})

test('posix_unclosed_quote_is_refused', async () => {
  const env = makeEnv({ cwd: '/home/u/repo' })
  const r = await run(env, 'local-lint', `tool 'open`)
  expect(env.runs).toHaveLength(0)
  expect(r.text).toBe('[es] commands.lint.bad_quotes')
})

test('lint_without_process_run_accepts_only_file', async () => {
  const env = makeEnv({ process: false, files: { 'C:\\work\\out.log': 'E501 line too long' } })
  const refused = await run(env, 'local-lint', 'ruff check .')
  expect(refused.text).toBe('[es] commands.lint.file_only arg=ruff check .')
  expect(env.mcpCalls).toHaveLength(0)

  const ok = await run(env, 'local-lint', 'out.log')
  expect(env.mcpCalls).toHaveLength(1)
  expect(env.mcpCalls[0]).toMatchObject({
    server: 'local-delegate',
    tool: 'local_lint_summary',
    args: { path: 'C:\\work\\out.log' },
  })
  expect(ok.text).toContain('SUMMARY')
})

test('lint_file_is_summarized_without_running_it', async () => {
  const env = makeEnv({ files: { 'C:\\work\\out.log': 'x' } })
  await run(env, 'local-lint', '"out.log"')
  expect(env.runs).toHaveLength(0)
  expect(env.mcpCalls[0].args.path).toBe('C:\\work\\out.log')
})

test('lint_command_output_goes_to_a_file_then_is_removed', async () => {
  const env = makeEnv({
    procImpl: () => ({ exitCode: 1, stdout: 'a.py:1: E501', stderr: 'warn', isStdoutTruncated: false, isStderrTruncated: false }),
  })
  const r = await run(env, 'local-lint', 'ruff check .')
  expect(env.mcpCalls).toHaveLength(1)
  expect(env.mcpCalls[0].tool).toBe('local_lint_summary')
  expect(env.mcpCalls[0].args.path.startsWith(DATA)).toBe(true)
  expect(env.mcpCalls[0].seen).toContain('a.py:1: E501')
  expect(env.mcpCalls[0].seen).toContain('warn')
  expect(tempFiles(env)).toEqual([])
  expect(r.text).toContain('SUMMARY')
})

test('lint_command_that_cannot_run_says_why', async () => {
  const env = makeEnv({
    procImpl: () => {
      throw new Error('still running after 30000 ms')
    },
  })
  const r = await run(env, 'local-lint', 'slow-tool')
  expect(r.text).toBe('[es] commands.lint.run_failed command=slow-tool detail=still running after 30000 ms')
  expect(env.mcpCalls).toHaveLength(0)
  expect(tempFiles(env)).toEqual([])
})

test('commit_only_shows_message', async () => {
  const env = makeEnv({
    procImpl: () => ({ exitCode: 0, stdout: DIFF, stderr: '', isStdoutTruncated: false, isStderrTruncated: false }),
    mcpImpl: () => ({ content: [{ type: 'text', text: 'feat: add key' }], isError: false }),
  })
  const r = await run(env, 'local-commit', '')
  expect(env.runs.map((x) => x.argv)).toEqual([['git', 'diff', '--cached']])
  expect(env.mcpCalls).toHaveLength(1)
  expect(env.mcpCalls[0]).toMatchObject({ server: 'local-delegate', tool: 'local_commit_msg' })
  expect(Object.keys(env.mcpCalls[0].args)).toEqual(['path'])
  expect(env.mcpCalls[0].seen).toBe(DIFF)
  expect(r.text).toBe('[es] commands.commit.header\n\nfeat: add key')
})

test('commit_with_nothing_staged_calls_nothing', async () => {
  const env = makeEnv({
    procImpl: () => ({ exitCode: 0, stdout: '  \n', stderr: '', isStdoutTruncated: false, isStderrTruncated: false }),
  })
  const r = await run(env, 'local-commit', '')
  expect(r.text).toBe('[es] commands.commit.no_changes')
  expect(env.mcpCalls).toHaveLength(0)
})

test('commit_without_process_run_says_so', async () => {
  const env = makeEnv({ process: false })
  const r = await run(env, 'local-commit', '')
  expect(r.text).toBe('[es] commands.commit.no_process')
})

test('commit_temp_file_removed', async () => {
  const outcomes: Record<string, (tool: string, args: any, env: Env) => any> = {
    ok: () => ({ content: [{ type: 'text', text: 'msg' }], isError: false }),
    tool_error: () => ({ content: [{ type: 'text', text: '[local-delegate error] boom' }], isError: true }),
    rejected: () => {
      throw new Error('server disconnected')
    },
  }
  for (const [name, impl] of Object.entries(outcomes)) {
    const env = makeEnv({
      procImpl: () => ({ exitCode: 0, stdout: DIFF, stderr: '', isStdoutTruncated: false, isStderrTruncated: false }),
      mcpImpl: impl,
    })
    await run(env, 'local-commit', '')
    expect(env.mcpCalls[0].seen, name).toBe(DIFF)
    expect(tempFiles(env), name).toEqual([])
    const removal = env.ldRuns.find((x) => x.args.some((a: string) => a.includes(REMOVE_MARK)))
    expect(removal?.args.at(-1), name).toBe(env.mcpCalls[0].args.path)
  }

  // Without a way to delete it (`runLd` gives null), the file is at least emptied.
  const env = makeEnv({
    runLd: false,
    procImpl: () => ({ exitCode: 0, stdout: DIFF, stderr: '', isStdoutTruncated: false, isStderrTruncated: false }),
    mcpImpl: outcomes.rejected,
  })
  await run(env, 'local-commit', '')
  for (const p of tempFiles(env)) expect(env.files.get(p)).toBe('')
})

test('daemon_down_clear_error', async () => {
  const down = makeEnv({
    files: { 'C:\\work\\big.md': 'x' },
    mcpImpl: () => {
      throw new Error('MCP server "local-delegate" is not connected')
    },
  })
  const r = await run(down, 'local-summarize', 'big.md')
  expect(r.text).toBe('[es] commands.error.mcp_down detail=MCP server "local-delegate" is not connected')
  expect(r.exitCode).toBe(1)

  const backend = makeEnv({
    files: { 'C:\\work\\big.md': 'x' },
    mcpImpl: () => ({ content: [{ type: 'text', text: '[local-delegate error] backend not responding' }], isError: true }),
  })
  const r2 = await run(backend, 'local-summarize', 'big.md')
  expect(r2.text).toBe('[es] commands.error.tool_failed detail=backend not responding')
  expect(r2.exitCode).toBe(1)
})

test('summarize_calls_local_summarize_with_absolute_path', async () => {
  const env = makeEnv({ files: { 'C:\\work\\docs\\a.md': 'x' } })
  const r = await run(env, 'local-summarize', 'docs\\a.md')
  expect(env.mcpCalls).toEqual([
    { server: 'local-delegate', tool: 'local_summarize', args: { path: 'C:\\work\\docs\\a.md' }, seen: 'x' },
  ])
  expect(r.text).toBe('SUMMARY')
  expect(env.runs).toHaveLength(0)
})

test('summarize_missing_file_and_usage', async () => {
  const env = makeEnv()
  expect((await run(env, 'local-summarize', '')).text).toBe('[es] commands.summarize.usage')
  expect((await run(env, 'local-summarize', 'nope.md')).text).toBe('[es] commands.summarize.missing path=C:\\work\\nope.md')
  expect((await run(env, 'local-lint', '  ')).text).toBe('[es] commands.lint.usage')
  expect(env.mcpCalls).toHaveLength(0)
})

test('texts_follow_language', async () => {
  for (const language of ['es', 'en']) {
    const env = makeEnv({ language, process: false })
    await env.hooks.find((h) => h.event === 'session.start').hook(env.$, { cwd: 'C:\\work' }, async () => ({}))
    expect(env.registered.map((c) => c.name)).toEqual(['local-summarize', 'local-commit', 'local-lint'])
    for (const spec of env.registered) expect(spec.description).toStartWith(`[${language}] commands.`)
    expect((await run(env, 'local-commit', '')).text).toBe(`[${language}] commands.commit.no_process`)
    expect((await run(env, 'local-lint', 'x y')).text).toBe(`[${language}] commands.lint.file_only arg=x y`)
  }
})

test('switch_off_registers_nothing', async () => {
  const hooks: any[] = []
  register((...a: any[]) => hooks.push(a), { commands_enabled: false }, makeEnv().common)
  expect(hooks).toHaveLength(0)
})
