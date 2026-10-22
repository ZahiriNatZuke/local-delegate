// REQ-016 (SDD claude-plugin-and-mods, F2-mod-core): what `mod/common.js` promises.
// Run with `claude plugin test <plugin>` after `scripts/build_mod.py` (it builds register.js).
//
// The helpers take a hook's `$`. A test holds the engine's `$`, not a plugin's, and an inline
// plugin is written to its own folder (it cannot reach `common.js`), so the helpers get a `$` made
// here with only the nouns each case needs: a noun that is missing throws when called, as
// `$.process.run` does where it is not available. The heartbeat goes through the real plugin.
import { expect, mock, test } from 'claude-code/testing'
import { daemonFetch, dataPath, engineCommon, hasDialog, runLd, setup, t, token } from './common.js'
import * as commonModule from './common.js'

const LD_BIN = 'C:/tools/local-delegate/python.exe'
const TOKEN = 'tok-7f3a-never-in-output'
const OPTIONS = { options: { ld_bin: LD_BIN } } as const

function fakeEngine(variables: Record<string, string>, nouns: Record<string, unknown> = {}) {
  return { env: { get: async (name: string) => variables[name] }, ...nouns }
}

test('runLd_null_without_process_run', OPTIONS, async () => {
  setup({ ld_bin: LD_BIN }, {})
  // No `process` noun: the call throws, and runLd answers null instead.
  expect(await runLd(fakeEngine({}), ['--version'])).toBe(null)
  // A `process.run` that rejects (vetoed, cannot start, overran) is null too.
  const refused = fakeEngine({}, { process: { run: async () => Promise.reject(new Error('denied')) } })
  expect(await runLd(refused, ['--version'])).toBe(null)
  // Without `ld_bin` there is nothing to run.
  setup({}, {})
  const seen: unknown[] = []
  const works = fakeEngine({}, { process: { run: async (argv: unknown) => (seen.push(argv), { exitCode: 0 }) } })
  expect(await runLd(works, ['--version'])).toBe(null)
  expect(seen).toEqual([])
})

test('runLd runs ld_bin with the arguments given when process.run answers', OPTIONS, async () => {
  setup({ ld_bin: LD_BIN }, {})
  const seen: unknown[] = []
  const engine = fakeEngine(
    {},
    {
      process: {
        run: async (argv: unknown, init: unknown) => {
          seen.push([argv, init])
          return { exitCode: 3, stdout: 'out', stderr: 'err', isStdoutTruncated: false, isStderrTruncated: false }
        },
      },
    },
  )
  const args = ['-I', '-m', 'local_delegate', 'hook', 'classify']
  expect(await runLd(engine, args, '{}', 5000)).toEqual({ exitCode: 3, stdout: 'out', stderr: 'err' })
  expect(seen).toEqual([[[LD_BIN, ...args], { stdin: '{}', timeoutMs: 5000 }]])
})

test('engineCommon binds the helpers to one $, as the plan names them', OPTIONS, async () => {
  setup({ ld_bin: LD_BIN, language: 'en' }, { catalogs: { en: { k: 'hi {who}' } } })
  const seen: unknown[] = []
  const engine = fakeEngine(
    { CLAUDE_CONFIG_DIR: 'D:/cfg' },
    { process: { run: async (argv: unknown) => (seen.push(argv), { exitCode: 0, stdout: '', stderr: '' }) } },
  )
  const common = engineCommon(engine)
  expect(await common.dataPath('tmp/x.diff')).toBe('D:/cfg/plugins/data/local-delegate-local-delegate/tmp/x.diff')
  expect(await common.runLd(['-I', '-c', ''])).toEqual({ exitCode: 0, stdout: '', stderr: '' })
  expect(seen).toEqual([[LD_BIN, '-I', '-c', '']])
  expect(common.t('k', { who: 'you' })).toBe('hi you')
  expect(await common.token()).toBe(null)
  expect(await common.daemonFetch('http://evil.example/')).toBe(null)
})

// Issue #409 (macos-keychain): on macOS, without the variable, the token comes from the Keychain
// through `/usr/bin/security`, as `token_source` does. `security` here is a fake `process.run`.
const MAC_HOME = { HOME: '/Users/ana' }
const KEYCHAIN_ARGV = ['/usr/bin/security', 'find-generic-password', '-a', 'ana', '-s', 'local-delegate-web-token', '-w']

function keychainEngine(variables: Record<string, string>, answer: () => Promise<unknown>) {
  const seen: unknown[] = []
  const engine = fakeEngine(variables, {
    process: { run: async (argv: unknown, init: unknown) => (seen.push([argv, init]), answer()) },
  })
  return { engine, seen }
}

test('token comes from the macOS Keychain when the variable is missing, asked once', OPTIONS, async () => {
  setup({}, {})
  const { engine, seen } = keychainEngine(MAC_HOME, async () => ({ exitCode: 0, stdout: `${TOKEN}\n`, stderr: '' }))
  expect(await token(engine)).toBe(TOKEN)
  expect(await token(engine)).toBe(TOKEN)
  expect(seen).toEqual([[KEYCHAIN_ARGV, { timeoutMs: 3000 }]])
})

test('the variable wins over the Keychain, which is then not asked', OPTIONS, async () => {
  setup({}, {})
  const { engine, seen } = keychainEngine({ ...MAC_HOME, LOCAL_DELEGATE_WEB_TOKEN: 'from-env' }, async () => ({
    exitCode: 0,
    stdout: TOKEN,
    stderr: '',
  }))
  expect(await token(engine)).toBe('from-env')
  expect(seen).toEqual([])
})

test('a Keychain that fails, is empty or overruns is no token, and is not asked again', OPTIONS, async () => {
  const answers: (() => Promise<unknown>)[] = [
    async () => ({ exitCode: 44, stdout: '', stderr: 'item not found' }),
    async () => ({ exitCode: 0, stdout: '  \n', stderr: '' }),
    async () => Promise.reject(new Error('timed out')),
  ]
  for (const answer of answers) {
    setup({}, {})
    const { engine, seen } = keychainEngine(MAC_HOME, answer)
    expect(await token(engine)).toBe(null)
    expect(await token(engine)).toBe(null)
    expect(seen.length).toBe(1)
  }
})

test('outside macOS the Keychain is never asked', OPTIONS, async () => {
  for (const variables of [{ USERPROFILE: 'C:\\Users\\ana', HOME: '/Users/ana' }, { HOME: '/home/ana' }, {}]) {
    setup({}, {})
    const { engine, seen } = keychainEngine(variables, async () => ({ exitCode: 0, stdout: TOKEN, stderr: '' }))
    expect(await token(engine)).toBe(null)
    expect(seen).toEqual([])
  }
})

test('daemonFetch_rejects_non_loopback', OPTIONS, async () => {
  const calls: { url: string; auth: unknown }[] = []
  const engine = fakeEngine(
    { LOCAL_DELEGATE_WEB_TOKEN: TOKEN },
    {
      http: {
        fetch: async (url: string, init: { headers?: Record<string, string> }) => {
          calls.push({ url, auth: init.headers?.Authorization })
          return { status: 200, ok: true, headers: {}, text: '{"n":1}' }
        },
      },
    },
  )
  expect(await daemonFetch(engine, 'http://evil.example/api/stats')).toBe(null)
  expect(await daemonFetch(engine, '//evil.example/api/stats')).toBe(null)
  expect(await daemonFetch(engine, 'api/stats')).toBe(null)
  expect(await daemonFetch(engine, '@evil.example/x')).toBe(null)
  expect(calls).toEqual([])
  // Guard: the same helper does reach the daemon when the path is its own.
  expect(await daemonFetch(engine, '/api/stats')).toEqual({ status: 200, ok: true, text: '{"n":1}', json: { n: 1 } })
  expect(calls).toEqual([{ url: 'http://127.0.0.1:9393/api/stats', auth: `Bearer ${TOKEN}` }])
})

test('daemonFetch answers null when the daemon does not answer', OPTIONS, async () => {
  const down = fakeEngine({}, { http: { fetch: async () => Promise.reject(new Error('ECONNREFUSED')) } })
  expect(await daemonFetch(down, '/api/stats')).toBe(null)
  // No token: no Authorization header at all, never an empty one.
  const headers: unknown[] = []
  const open = fakeEngine(
    {},
    {
      http: {
        fetch: async (_url: string, init: { headers?: Record<string, string> }) => {
          headers.push(init.headers)
          return { status: 401, ok: false, headers: {}, text: 'no' }
        },
      },
    },
  )
  expect(await daemonFetch(open, '/api/stats')).toEqual({ status: 401, ok: false, text: 'no', json: null })
  expect(headers).toEqual([{}])
})

test('dataPath stays inside the plugin data folder', OPTIONS, async () => {
  const engine = fakeEngine({ CLAUDE_CONFIG_DIR: 'D:/cfg/' })
  expect(await dataPath(engine, 'heartbeats/s1.json')).toBe(
    'D:/cfg/plugins/data/local-delegate-local-delegate/heartbeats/s1.json',
  )
  expect(await dataPath(engine, '../escape.json')).toBe(null)
  expect(await dataPath(engine, 'heartbeats/../../x')).toBe(null)
  expect(await dataPath(engine, '/etc/passwd')).toBe(null)
  expect(await dataPath(engine, 'C:/x.json')).toBe(null)
  expect(await dataPath(engine, 'a\\b')).toBe(null)
  // Without CLAUDE_CONFIG_DIR, the profile's `.claude`, as Claude Code does.
  expect(await dataPath(fakeEngine({ USERPROFILE: 'C:\\Users\\me\\' }), 'x.json')).toBe(
    'C:\\Users\\me/.claude/plugins/data/local-delegate-local-delegate/x.json',
  )
  expect(await dataPath(fakeEngine({ HOME: '/home/me' }), 'x.json')).toBe(
    '/home/me/.claude/plugins/data/local-delegate-local-delegate/x.json',
  )
  expect(await dataPath(fakeEngine({}), 'x.json')).toBe(null)
})

test('t falls back to the other language, then to the key, and fills its variables', OPTIONS, async () => {
  setup({ language: 'en' }, { catalogs: { es: { 'a.only_es': 'solo {n}' }, en: { 'a.both': '{n} files of {who}' } } })
  expect(t('a.both', { n: 3, who: 'you' })).toBe('3 files of you')
  expect(t('a.only_es', { n: 1 })).toBe('solo 1')
  expect(t('a.missing')).toBe('a.missing')
  expect(t('a.both', { n: 1 })).toBe('1 files of {who}')
  setup({ language: 'fr' }, { catalogs: { es: { k: 'es' }, en: { k: 'en' } } })
  expect(t('k')).toBe('es')
})

test('hasDialog follows isInteractive of session.start', OPTIONS, async () => {
  setup({}, {})
  expect(hasDialog({})).toBe(false)
  expect(hasDialog({ isInteractive: true })).toBe(true)
  expect(hasDialog({ tool: 'Read' })).toBe(true)
  expect(hasDialog({ isInteractive: false })).toBe(false)
})

test('the heartbeat is written per session, with the pieces and never the token', OPTIONS, async ($, on) => {
  // `/cfg` is absolute on every OS (a drive-letter path is relative on Linux and macOS).
  mock.env(on, { CLAUDE_CONFIG_DIR: '/cfg', LOCAL_DELEGATE_WEB_TOKEN: TOKEN })
  const writes: { path: string; text: string }[] = []
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'sess-1' }))
  on('fs.write', (_$, e) => {
    writes.push({ path: e.path, text: e.text })
    return { value: undefined }
  })
  await $.session.start({ cwd: 'D:/work', surface: null, isInteractive: false })
  expect(writes.length).toBe(1)
  // The engine hands the path resolved, in the platform's own separators (`C:\cfg\…` on Windows).
  const written = writes[0].path.split('\\').join('/')
  expect(written.endsWith('/cfg/plugins/data/local-delegate-local-delegate/heartbeats/sess-1.json')).toBe(true)
  expect(written.includes('/claude-plugin/')).toBe(false)
  const beat = JSON.parse(writes[0].text)
  expect(beat.session_id).toBe('sess-1')
  expect(beat.pieces['pinned-tools']).toBe('on')
  // F2-commands' piece loads beside it, and its start ran inside its own `try`.
  expect(beat.pieces.commands).toBe('on')
  expect(beat.dialog).toBe(false)
  // Nothing answers `process.run` beneath: the heartbeat says so instead of failing.
  expect(beat.process_run).toBe(false)
  expect(beat.read_mod_enabled).toBe(false)
  expect(typeof beat.version).toBe('string')
  expect(writes[0].text.includes(TOKEN)).toBe(false)
})

test(
  'a piece switched off is recorded off in the heartbeat',
  { options: { ld_bin: LD_BIN, pinned_tools: [] } },
  async ($, on) => {
    mock.env(on, { CLAUDE_CONFIG_DIR: '/cfg' })
    const writes: string[] = []
    on('session.start', (_$, e) => ({ cwd: e.cwd }))
    on('session.id', () => ({ value: 'sess-2' }))
    on('fs.write', (_$, e) => {
      writes.push(e.text)
      return { value: undefined }
    })
    await $.session.start({ cwd: 'D:/work', surface: 'terminal', isInteractive: true })
    const beat = JSON.parse(writes[0])
    expect(beat.pieces['pinned-tools']).toBe('off')
    expect(beat.dialog).toBe(true)
  },
)

test('toolResultText unwraps the FastMCP `{ result }` of a tool that returns str', OPTIONS, async () => {
  const unwrap = (commonModule as any).toolResultText
  expect(typeof unwrap).toBe('function')
  const text = 'Line one.\nLine two.'
  const block = { type: 'text', text: JSON.stringify({ result: text }) }
  // structuredContent first, then the text block's JSON, then the text blocks as they come
  expect(unwrap({ content: [block], structuredContent: { result: ` ${text} ` } })).toBe(text)
  expect(unwrap({ content: [block] })).toBe(text)
  expect(unwrap({ content: [{ type: 'text', text: 'plain' }, { type: 'image' }, { type: 'text', text: 'more' }] })).toBe('plain\nmore')
  expect(unwrap({ content: [{ type: 'text', text: '{"a": 1}' }] })).toBe('{"a": 1}')
  expect(unwrap({ content: [{ type: 'text', text: '{not json' }] })).toBe('{not json')
  expect(unwrap(null)).toBe('')
  expect(unwrap({})).toBe('')
})
