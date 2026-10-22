// mod/common.js — what every piece of the local-delegate mod shares (SDD claude-plugin-and-mods,
// batch F2-mod-core; interface fixed in plan.md, wave 3).
//
// REQ-016: the mod reads exactly one secret, `LOCAL_DELEGATE_WEB_TOKEN`, never writes it anywhere
// (no log, no status, no heartbeat) and talks only to the daemon on 127.0.0.1. Every helper here
// answers `null` instead of throwing, so a piece that loses the daemon, `$.process.run` or the
// data folder degrades instead of failing its hook.
//
// How a piece uses it, as the engine's validator allows (measured, F2-mod-core evidence): it
// imports the helpers by name from './common.js' and calls them inside its hooks with that hook's
// `$` (`await daemonFetch($, '/api/stats')`), or builds `engineCommon($)` there and hands that
// object to its own top-level functions.
//
// `$` may be handed only to a function declared at the top of the same file (2.1.292 never
// follows it across an import), never to a method (`common.token($)` is refused): so these are
// top-level functions, and `scripts/build_mod.py` pastes this file and the pieces into one
// `register.js`, dropping the imports. The options and the texts are set once by `register.js`
// through `setup`.
//
// The module only declares at load, so loading it cannot throw.

// The only environment variables the mod reads. `test_mod_static.py` holds every `$.env.get` of
// the mod to this list: the token is the one secret; the others locate the plugin's data folder
// (T0: `CLAUDE_PLUGIN_DATA` does not reach the mod) and say who started the session.
export const TOKEN_VARIABLE = 'LOCAL_DELEGATE_WEB_TOKEN'

// The daemon's own default (`config.WEB_PORT`). The mod cannot read `LOCAL_DELEGATE_WEB_PORT`
// without widening REQ-016, so a daemon on another port is out of the mod's reach.
export const DAEMON_HOST = '127.0.0.1'
export const DAEMON_PORT = 9393

// `<plugin>-<marketplace>`: the folder Claude Code gives the plugin's hooks as `CLAUDE_PLUGIN_DATA`.
export const DATA_FOLDER = 'local-delegate-local-delegate'

const LANGUAGES = ['es', 'en']

// macOS (issue #409): without the variable, the token comes from the Keychain, the same service
// `token_source.py` reads. A Mac app opened from the Dock only has launchd's environment, so
// `$.env.get` comes back empty there. The absolute path: launchd's PATH is minimal. The time limit:
// a locked Keychain can leave `security` waiting on a dialog, and a stuck hook is worse than none.
export const KEYCHAIN_SERVICE = 'local-delegate-web-token'
export const SECURITY_PROGRAM = '/usr/bin/security'
export const KEYCHAIN_TIMEOUT_MS = 3000

// What `setup` stores: the plugin's options, the embedded texts, the plugin's version, the
// `isInteractive` of the session's start, and what the Keychain answered (`undefined` until asked;
// `null`, «nothing», is remembered too, so it is asked once per load).
const STATE = { options: {}, catalogs: {}, version: null, interactive: null, keychain: undefined }

function isText(value) {
  return typeof value === 'string' && value.trim() !== ''
}

/**
 * Called once by `register.js`: the plugin's options and what `build_mod.py` embedded.
 *
 * @param {Record<string, unknown>} options what `register(on, options)` received
 * @param {{ catalogs?: Record<string, Record<string, string>>, version?: string | null }} [extras]
 */
export function setup(options, extras = {}) {
  STATE.options = options || {}
  STATE.catalogs = extras.catalogs || {}
  STATE.version = extras.version || null
  STATE.interactive = null
  STATE.keychain = undefined
}

/**
 * The macOS account to ask the Keychain for, or `null` off macOS.
 *
 * The mod has no platform noun and reads only the variables `test_mod_static.py` allows, so macOS
 * is told by a `HOME` of `/Users/<account>` and no `USERPROFILE` (Windows); `<account>` is the
 * `$USER` the docs store the item under.
 */
async function keychainAccount($) {
  if (isText(await $.env.get('USERPROFILE'))) {
    return null
  }
  const home = await $.env.get('HOME')
  const match = isText(home) ? /^\/Users\/([^/]+)\/?$/.exec(home.trim()) : null
  return match ? match[1] : null
}

/** The token stored in the macOS Keychain, or `null`; asked once per load, with a time limit. */
async function keychainToken($) {
  if (STATE.keychain !== undefined) {
    return STATE.keychain
  }
  let found = null
  try {
    const account = await keychainAccount($)
    if (account !== null) {
      const argv = [SECURITY_PROGRAM, 'find-generic-password', '-a', account, '-s', KEYCHAIN_SERVICE, '-w']
      const done = await $.process.run(argv, { timeoutMs: KEYCHAIN_TIMEOUT_MS })
      if (done && done.exitCode === 0 && isText(done.stdout)) {
        found = done.stdout.trim()
      }
    }
  } catch {
    found = null
  }
  STATE.keychain = found
  return found
}

/**
 * The daemon token, or `null`. Never logged: callers put it in a header and nowhere else.
 *
 * The variable first; without it, on macOS, the Keychain (the same order as `token_source.py`).
 */
export async function token($) {
  try {
    const value = await $.env.get('LOCAL_DELEGATE_WEB_TOKEN')
    if (isText(value)) {
      return value.trim()
    }
  } catch {
    // An engine without the variable noun: the Keychain is still worth asking.
  }
  return keychainToken($)
}

/**
 * `$.http.fetch` to the daemon on loopback, with the token as `Bearer`.
 *
 * `path` is a path of the daemon (`/api/stats`), never a URL: anything that would leave
 * `127.0.0.1:<port>` is refused before any request. Resolves `{ status, ok, text, json }` (`json`
 * is `null` when the body is not JSON) for any HTTP status, and `null` when the request is refused
 * or does not complete.
 */
export async function daemonFetch($, path, init = {}) {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) {
    return null
  }
  let url
  try {
    url = new URL(`http://${DAEMON_HOST}:${DAEMON_PORT}${path}`)
  } catch {
    return null
  }
  if (url.protocol !== 'http:' || url.hostname !== DAEMON_HOST || url.port !== String(DAEMON_PORT)) {
    return null
  }
  try {
    const secret = await token($)
    const headers = { ...(init.headers || {}) }
    if (secret) {
      headers.Authorization = `Bearer ${secret}`
    }
    const response = await $.http.fetch(url.href, { ...init, headers })
    let json = null
    try {
      json = JSON.parse(response.text)
    } catch {
      json = null
    }
    return { status: response.status, ok: response.ok, text: response.text, json }
  } catch {
    return null
  }
}

/** The language of the output: the `language` option (`es` or `en`), `es` otherwise. */
export function language() {
  return LANGUAGES.includes(STATE.options.language) ? STATE.options.language : 'es'
}

/**
 * The text of `key` in the output language, with each `{name}` replaced by `vars.name`.
 *
 * Falls back to the other language, then to the key itself: a missing text shows its key instead
 * of an empty line. The texts are `mod/i18n/<lang>.json`, embedded by `build_mod.py`.
 */
export function t(key, vars = {}) {
  const lang = language()
  const other = LANGUAGES.find(candidate => candidate !== lang)
  const text = (STATE.catalogs[lang] || {})[key] ?? (STATE.catalogs[other] || {})[key] ?? key
  return String(text).replace(/\{([A-Za-z0-9_]+)\}/g, (whole, name) =>
    Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : whole,
  )
}

/**
 * Runs `<ld_bin> <args…>` with `$.process.run`: `ld_bin` is the interpreter of the `uv tool`
 * environment, so `['-I', '-m', 'local_delegate', 'hook', 'classify']` runs the CLI and
 * `['-I', '-c', '…']` a line of Python.
 *
 * `null` when `ld_bin` is not set, `$.process.run` is not there (outside the CLI, under a test) or
 * is refused, or the command cannot start or overruns; otherwise `{ exitCode, stdout, stderr }`,
 * whatever the exit code.
 */
export async function runLd($, args, stdin, timeoutMs) {
  const ldBin = STATE.options.ld_bin
  if (!isText(ldBin) || !Array.isArray(args)) {
    return null
  }
  const init = {}
  if (typeof stdin === 'string') {
    init.stdin = stdin
  }
  if (typeof timeoutMs === 'number') {
    init.timeoutMs = timeoutMs
  }
  try {
    const done = await $.process.run([ldBin, ...args.map(String)], init)
    return { exitCode: done.exitCode, stdout: done.stdout, stderr: done.stderr }
  } catch {
    return null
  }
}

/**
 * The absolute path of `name` inside the plugin's data folder, or `null`.
 *
 * Derived as `<CLAUDE_CONFIG_DIR or ~/.claude>/plugins/data/local-delegate-local-delegate`, the
 * folder the hooks get as `CLAUDE_PLUGIN_DATA` (T0). `name` is relative and never climbs out.
 */
export async function dataPath($, name) {
  if (!isText(name) || name.startsWith('/') || name.includes('\\') || /^[A-Za-z]:/.test(name)) {
    return null
  }
  if (name.split('/').some(part => part === '..' || part === '.' || part === '')) {
    return null
  }
  try {
    let base = await $.env.get('CLAUDE_CONFIG_DIR')
    if (!isText(base)) {
      let home = await $.env.get('USERPROFILE')
      if (!isText(home)) {
        home = await $.env.get('HOME')
      }
      if (!isText(home)) {
        return null
      }
      base = `${home.replace(/[\\/]+$/, '')}/.claude`
    }
    return `${base.replace(/[\\/]+$/, '')}/plugins/data/${DATA_FOLDER}/${name}`
  } catch {
    return null
  }
}

/**
 * Whether a person is at the prompt (T0's signal): `isInteractive` of `session.start`.
 *
 * Given that event, it answers and remembers; given any other, it answers what the session's start
 * said, and `false` before it (a `-p` run, the SDK, a test).
 */
export function hasDialog(e) {
  if (e && typeof e.isInteractive === 'boolean') {
    STATE.interactive = e.isInteractive
  }
  return STATE.interactive === true
}

/** Whether `$.process.run` answers: `<ld_bin> -I -c pass` exits with 0. */
export async function processRunWorks($) {
  const ldBin = STATE.options.ld_bin
  if (!isText(ldBin)) {
    return false
  }
  try {
    const done = await $.process.run([ldBin, '-I', '-c', 'pass'], { timeoutMs: 10000 })
    return done.exitCode === 0
  } catch {
    return false
  }
}

/**
 * The plan's interface as an object bound to one hook's `$`: `token()`, `daemonFetch(path, init)`,
 * `t(key, vars)`, `runLd(args, stdin, timeoutMs)`, `dataPath(name)`, `hasDialog(e)`,
 * `heartbeat(fields)` and `language()`.
 *
 * For a piece that passes `common` around its own top-level functions: it is built inside the
 * hook, `($, e) => work($, engineCommon($), e)`, since the engine hands `$` only to functions
 * named at the top of a file and never to a method. The named exports above are the same helpers.
 */
export function engineCommon($) {
  return {
    token: () => token($),
    daemonFetch: (path, init) => daemonFetch($, path, init),
    t,
    language,
    runLd: (args, stdin, timeoutMs) => runLd($, args, stdin, timeoutMs),
    dataPath: name => dataPath($, name),
    hasDialog,
    heartbeat: fields => heartbeat($, fields),
  }
}

/**
 * The text of a `local-delegate` tool's answer to `$.mcp.call`. FastMCP wraps the `str` a tool
 * returns in `{ "result": … }`, as `structuredContent` and as the text block's JSON; without that
 * wrapper the text blocks are taken as they come (a JSON that is not the wrapper stays as it is).
 * Trimmed; `''` when there is no text. Telling an error or an empty answer apart is the caller's.
 */
export function toolResultText(result) {
  const structured = result && result.structuredContent
  if (structured && typeof structured === 'object' && typeof structured.result === 'string') {
    return structured.result.trim()
  }
  const text = ((result && result.content) || [])
    .filter(block => block && block.type === 'text' && typeof block.text === 'string')
    .map(block => block.text)
    .join('\n')
    .trim()
  if (text.startsWith('{')) {
    try {
      const parsed = JSON.parse(text)
      if (parsed && typeof parsed === 'object' && typeof parsed.result === 'string') {
        return parsed.result.trim()
      }
    } catch {
      // not JSON: a plain text answer
    }
  }
  return text
}

/**
 * Writes this session's heartbeat, `heartbeats/<session_id>.json`, for `doctor` and the read hooks
 * (decision 9). One file per session: a session never goes by another one's heartbeat.
 *
 * Resolves the path written, or `null` when it could not be written. Never carries the token.
 */
export async function heartbeat($, fields = {}) {
  try {
    const sessionId = String(await $.session.id())
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(sessionId)) {
      return null
    }
    const path = await dataPath($, `heartbeats/${sessionId}.json`)
    if (!path) {
      return null
    }
    let entrypoint = null
    try {
      entrypoint = (await $.env.get('CLAUDE_CODE_ENTRYPOINT')) || null
    } catch {
      entrypoint = null
    }
    const beat = {
      session_id: sessionId,
      version: STATE.version,
      entrypoint,
      process_run: await processRunWorks($),
      dialog: STATE.interactive === true,
      read_mod_enabled: STATE.options.read_mod_enabled === true,
      ...fields,
      at: new Date().toISOString(),
    }
    await $.fs.write(path, `${JSON.stringify(beat, null, 2)}\n`)
    return path
  } catch {
    return null
  }
}
