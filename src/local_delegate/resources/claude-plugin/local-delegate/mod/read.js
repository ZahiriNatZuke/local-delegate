// mod/read.js — large reads go through the local model (REQ-020, REQ-021, REQ-022; SDD
// claude-plugin-and-mods, batch F4-read-mod; design in plan.md, wave 5).
//
// One `tool.call` hook, only with the `read_mod_enabled` option on (on by default since 0.41):
//   - a prefilter drops, without starting a process, the calls that cannot lead to a decision: a
//     tool or a harmless first word that cannot read or write a file, and a call that names no
//     prose file, no guarded file and no large file. Its data (tools, prose extensions, threshold,
//     harmless first words) comes from Python, once per load, with `hook classify --config`
//     (F4-read-mod-perf: each `classify` is a process, and F4-live measured +724 ms per `Bash`).
//     The rest go to `hook classify`: first the daemon's copy (`POST /api/hook/classify`, with the
//     classifier's variables, F4-classify-daemon), else the process through `common.runLd`. No answer, or a `read_switch` other
//     than `on`, and the call goes through untouched;
//   - a read the classifier is sure of (`whole`, or ranges that add up to 80 % of the file's
//     lines, the threshold fixed in evidence/F4-read-paths.md) of large prose (`summarizable`,
//     the band the read hook blocks, decided in Python by `hook classify`) is summarized by `local_summarize`, and the summary is the tool's result: with a dialog the
//     person picks «summarize with the local model / read it whole»; without one (`-p`, a
//     subagent) the mod summarizes by itself (REQ-021 v3: delegating cannot hang on the model
//     following a suggestion). A summary that fails lets the real read through: the mod never
//     blocks without giving content;
//   - a large read that is not prose (code, config, data) always goes through, and is logged;
//   - a read it is not sure of (`unclassifiable`) goes through, with a note to the model;
//   - after a summary, `Edit`, `Write`, `NotebookEdit` and recognizable shell writes on that file
//     are refused until a real read of it (REQ-022). The list is kept per session in the data
//     folder, so it survives `--resume`.
// Each decision is logged with `local-delegate hook record-read`, the same line the read hook
// writes in `blocks.jsonl`, and the session's heartbeat says `read_mod_active`. The line goes first
// to the daemon (`POST /api/hook/record-read`, F4-read-fixes), else through the process: in 0.41.0
// it only went through the process, and no decision taken in the dialog ever reached the log. A
// line neither road takes leaves a trace (`$.ui.log` to debug, `hook-failures.jsonl`) and is tried
// again at the start of the next tool call. Each decision carries one `id`, made here once and sent
// on every road (F4-live-fixes), and `record-read` drops an id already in the log: in the live test
// of 2026-10-23 the daemon wrote the line after the mod's limit, the mod called it lost and the
// retry wrote it again. A daemon that runs out of time is not a lost line either: the line waits
// for the next tool call (no process racing the daemon, no trace), and only if that try fails too
// is it traced.
//
// A piece of the mod: `scripts/build_mod.py` pastes it into `register.js`. It only declares at
// load, and every top-level name carries `read`, so it cannot clash with another piece's.

import { engineCommon, readModOn, toolResultText } from './common.js'

// REQ-020: ranges that cover this share of the file's lines count as reading it whole.
export const READ_WHOLE_SHARE = 0.8
// The read hook's lower band (`LD_HOOK_READ_SUGGEST_KB`, 8 KB): below it a read is left alone.
// `hook classify --config` sends the real one (`min_bytes`); this is only for a package that does
// not answer it.
export const READ_MIN_BYTES = 8 * 1024
// Issue #472: in the main thread a range of a short file is never summarized, whatever the session
// read of it before. Short is both: at most this many lines AND under this size (a file of few but
// very long lines is still worth summarizing).
export const READ_SHORT_LINES = 200
export const READ_SHORT_BYTES = 32 * 1024

const READ_SERVER = 'local-delegate'
const READ_SUMMARY_TOOL = 'local_summarize'
const READ_ERROR_PREFIX = '[local-delegate error]'
// `local_delegate.hook`, never `-m local_delegate hook`: that road goes through `entrypoint`, which
// imports the server and the MCP SDK (654 ms of imports, evidence/F4-live.md). `test_read_classifier`
// runs these very arguments and fails if they load `local_delegate.server` or `mcp`.
const READ_CLASSIFY = ['-I', '-m', 'local_delegate.hook', 'classify']
const READ_RECORD = ['-I', '-m', 'local_delegate.hook', 'record-read']
const READ_CONFIG_FLAG = '--config'
const READ_CLASSIFY_TIMEOUT_MS = 10000
const READ_RECORD_TIMEOUT_MS = 10000
// The daemon's copy of the same two answers (F4-classify-daemon): `hook_entry.classify_text` and
// `config_text` behind the panel's token, ~120 ms cheaper per question than a process on Windows.
// Any failure (no token, no daemon, the time limit, 401, a daemon without the route, an answer
// that is not the contract) falls back to the process, and the session leaves the daemon alone
// for `READ_DAEMON_RETRY_MS` so a dead daemon costs the time limit once, not on every call.
const READ_DAEMON_CLASSIFY = '/api/hook/classify'
const READ_DAEMON_CONFIG = '/api/hook/classify-config'
const READ_DAEMON_TIMEOUT_MS = 300
const READ_DAEMON_RETRY_MS = 5 * 60 * 1000
// The daemon's copy of `hook record-read` (F4-read-fixes): the same `hook_entry.record_read`, with
// the variables it reads (`hook_entry.RECORD_ENV`: the classifier's plus these two). Answers 204.
const READ_DAEMON_RECORD = '/api/hook/record-read'
const READ_DAEMON_RECORD_TIMEOUT_MS = 1000
// What `readWithin` resolves when the time limit runs out first: the request may still complete.
const READ_TIMED_OUT = Symbol('timed out')
// The hooks' failure log (`hook_entry.FAILURE_LOG`, capped at `FAILURE_LOG_MAX_BYTES`), in the
// package's data folder: where a decision that reached neither the daemon nor the process is noted.
const READ_FAILURE_LOG = 'hook-failures.jsonl'
const READ_FAILURE_LOG_MAX_BYTES = 256 * 1024
const READ_FAILURE_ERROR = 'ModRecordLost'
// Lost lines kept for one more try at the next tool call; beyond this many the oldest go.
const READ_PENDING_MAX = 20
const READ_SESSION_ID = /^[A-Za-z0-9_-]{1,128}$/
// The tools that write a file by a path argument of their own.
const READ_WRITE_TOOLS = { Edit: 'file_path', Write: 'file_path', NotebookEdit: 'notebook_path' }
const READ_SHELL_TOOLS = ['Bash', 'PowerShell']
// The tools whose result the mod can stand in for with a summary.
const READ_SUMMARIZABLE_TOOLS = ['Read', 'Bash', 'PowerShell']
// The tools to look at when `hook classify --config` cannot be asked: then every call of these
// goes to the classifier, which decides (nothing is dropped on a guess).
const READ_DEFAULT_TOOLS = ['Read', 'Bash', 'PowerShell', 'Grep']
// A harmless first word (`harmless_first`, from Python) only counts without redirection, pipe or
// chaining (`> | ; &`): those go on to the prefilter whatever they start with.
const READ_CHAINING = /[>|;&]/
// The input keys that name a file for the size check (`Read`, `Grep`).
const READ_PATH_KEYS = ['file_path', 'path']
// Shell words looked at for the size check: at most this many, so a long command stays cheap.
const READ_MAX_STATS = 8
const READ_ENVELOPE_KEYS = ['tool', 'tool_use_id', 'agentId', 'requestMeta', 'consent']

// The module's own memory, which a reload starts over: what each file has had read in this
// session (by path), the guarded files, the tools the classifier knows and whether the heartbeat
// already says the mod is active.
const READ_STATE = {
  enabled: false,
  tools: null,
  config: null,
  configAsked: false,
  files: new Map(),
  guard: new Set(),
  guardSession: null,
  beat: false,
  // The classifier's variables, read once per load (`undefined` until then, `null` if unreadable),
  // and until when the daemon is not asked after a failure.
  vars: undefined,
  daemonDownUntil: 0,
  // `record-read`'s own variables (`undefined` until read), until when the daemon's record route is
  // not asked after it answered that it cannot take the line, and the lines still to record.
  recordVars: undefined,
  recordDownUntil: 0,
  pending: [],
}

function readText(value) {
  return typeof value === 'string' && value.trim() !== ''
}

/** A path compared as the same file: absolute, forward slashes, a Windows drive in lower case. */
export function readNormalize(path, cwd) {
  if (!readText(path)) {
    return null
  }
  let p = path.trim().replace(/\\/g, '/')
  const absolute = p.startsWith('/') || /^[A-Za-z]:\//.test(p)
  if (!absolute && readText(cwd)) {
    p = `${cwd.replace(/\\/g, '/').replace(/\/+$/, '')}/${p.replace(/^\.\//, '')}`
  }
  if (/^[A-Za-z]:\//.test(p)) {
    p = p.toLowerCase()
  }
  return p
}

/** The `{ start, end }` of a classifier's `range` (1-based lines, `end` null to the end), or null. */
export function readRange(range) {
  let start = null
  let end = null
  if (Array.isArray(range)) {
    start = range[0]
    end = range[1]
  } else if (range && typeof range === 'object') {
    start = range.start ?? range.first ?? null
    end = range.end ?? range.last ?? null
  }
  if (typeof start !== 'number' || !Number.isFinite(start)) {
    return null
  }
  const last = typeof end === 'number' && Number.isFinite(end) ? Math.floor(end) : null
  return { start: Math.max(1, Math.floor(start)), end: last }
}

/** The share of `total` lines that `ranges` cover, counting each line once. */
export function readCoverage(ranges, total) {
  if (!(total > 0)) {
    return 0
  }
  const spans = ranges
    .map(r => [Math.max(1, r.start), Math.min(total, r.end === null ? total : r.end)])
    .filter(([a, b]) => b >= a)
    .sort((x, y) => x[0] - y[0])
  let covered = 0
  let reach = 0
  for (const [a, b] of spans) {
    const from = Math.max(a, reach + 1)
    if (b >= from) {
      covered += b - from + 1
      reach = b
    }
  }
  return covered / total
}

function readFileEntry(key) {
  let entry = READ_STATE.files.get(key)
  if (!entry) {
    entry = { ranges: [], vias: {}, total: null, whole: false }
    READ_STATE.files.set(key, entry)
  }
  return entry
}

/** The first word of a shell command, without its folder or `.exe`, in lower case. */
function readFirstWord(command) {
  return command.split(/\s+/)[0].replace(/^.*[\\/]/, '').replace(/\.exe$/i, '').toLowerCase()
}

/** The quick filter, no file system: whether the tool and the first word may read or write a file. */
function readMayTouchFile(e) {
  const tools = READ_STATE.tools || READ_DEFAULT_TOOLS
  if (!tools.includes(e.tool)) {
    return false
  }
  if (READ_SHELL_TOOLS.includes(e.tool)) {
    const command = typeof e.command === 'string' ? e.command.trim() : ''
    if (command === '') {
      return false
    }
    const harmless = READ_STATE.config ? READ_STATE.config.harmless : []
    if (!READ_CHAINING.test(command) && harmless.includes(readFirstWord(command))) {
      return false
    }
  }
  return true
}

/** The words of a call that may name a file: the shell command's words, or the string arguments. */
function readWords(e) {
  if (READ_SHELL_TOOLS.includes(e.tool)) {
    return (typeof e.command === 'string' ? e.command : '')
      .split(/[\s|;&<>()]+/)
      .map(word => word.replace(/^['"`]+|['"`,]+$/g, ''))
      .filter(word => word !== '' && !word.startsWith('-'))
  }
  return Object.values(readToolInput(e)).filter(readText)
}

/** Whether a word names a file with one of the prose extensions (`docs/a.md:12` too). */
function readNamesProse(word, prose) {
  const lower = word.toLowerCase()
  return prose.some(ext => lower.endsWith(ext) || lower.includes(`${ext}:`))
}

/** Whether a word names a guarded file: the file's name, without case, ends the word. */
function readNamesGuarded(word) {
  const lower = word.replace(/\\/g, '/').toLowerCase()
  for (const key of READ_STATE.guard) {
    const name = key.slice(key.lastIndexOf('/') + 1).toLowerCase()
    if (name !== '' && lower.endsWith(name)) {
      return true
    }
  }
  return false
}

/** Whether one of these words is a file of at least `min_bytes` (`$.fs.stat`, no process). */
async function readNamesLargeFile($, words, cwd) {
  const candidates = words.filter(word => /[./\\]/.test(word) && !/[*?$`]/.test(word)).slice(0, READ_MAX_STATS)
  for (const word of candidates) {
    const absolute = word.startsWith('/') || /^[A-Za-z]:[\\/]/.test(word)
    const path = absolute || !readText(cwd) ? word : `${cwd.replace(/[\\/]+$/, '')}/${word}`
    try {
      const stat = await $.fs.stat(path)
      if (stat && stat.kind === 'file' && typeof stat.size === 'number' && stat.size >= READ_STATE.config.minBytes) {
        return true
      }
    } catch (error) {
      if (error instanceof TypeError) {
        // An engine without `$.fs.stat`: the classifier decides, as before the prefilter.
        return true
      }
      // not a file there: nothing to read
    }
  }
  return false
}

/**
 * The prefilter, after the quick one: whether the call can end in a decision, so it is worth a
 * process. Only prose is summarized, accumulated and guarded, so a call that names neither a prose
 * file nor a guarded one cannot be steered; a large file of another kind is still classified, so
 * its read is logged (`not_prose`, `warned`). Without Python's data, every candidate goes on.
 */
async function readWorthClassifying($, e, cwd) {
  const config = READ_STATE.config
  if (!config) {
    return true
  }
  const words = readWords(e)
  if (words.some(word => readNamesProse(word, config.prose) || readNamesGuarded(word))) {
    return true
  }
  const paths = READ_SHELL_TOOLS.includes(e.tool) ? words : READ_PATH_KEYS.map(key => e[key]).filter(readText)
  return readNamesLargeFile($, paths, cwd)
}

/** The tool's arguments as the classifier takes them: the envelope's own keys left out. */
function readToolInput(e) {
  const input = {}
  for (const [key, value] of Object.entries(e)) {
    if (!READ_ENVELOPE_KEYS.includes(key)) {
      input[key] = value
    }
  }
  return input
}

async function readSessionId($) {
  try {
    const id = String(await $.session.id())
    return READ_SESSION_ID.test(id) ? id : null
  } catch {
    return null
  }
}

async function readCwd($) {
  try {
    return await $.session.cwd()
  } catch {
    return null
  }
}

/**
 * The variables `hook classify` reads (`hook_entry.CLASSIFY_ENV`, which `test_mod_static.py` holds
 * this list to), as this session's process has them: the daemon has its own environment, not
 * Claude Code's, and classifies with these instead. Read once per load; `null` when the engine
 * cannot read them, and then the daemon is not asked (it would decide with the wrong switch).
 */
async function readClassifierVars($) {
  if (READ_STATE.vars !== undefined) {
    return READ_STATE.vars
  }
  const vars = {}
  const put = (name, value) => {
    if (typeof value === 'string' && value !== '') {
      vars[name] = value
    }
  }
  try {
    put('LD_HOOK_READ_ENABLED', await $.env.get('LD_HOOK_READ_ENABLED'))
    put('LD_HOOK_READ_BLOCK', await $.env.get('LD_HOOK_READ_BLOCK'))
    put('LD_HOOK_READ_SWITCH_FILE', await $.env.get('LD_HOOK_READ_SWITCH_FILE'))
    put('LD_HOOK_READ_SUGGEST_KB', await $.env.get('LD_HOOK_READ_SUGGEST_KB'))
    put('LOCAL_DELEGATE_LOG_DIR', await $.env.get('LOCAL_DELEGATE_LOG_DIR'))
    put('LOCALAPPDATA', await $.env.get('LOCALAPPDATA'))
    put('XDG_DATA_HOME', await $.env.get('XDG_DATA_HOME'))
    put('USERPROFILE', await $.env.get('USERPROFILE'))
    put('HOME', await $.env.get('HOME'))
    READ_STATE.vars = vars
  } catch {
    READ_STATE.vars = null
  }
  return READ_STATE.vars
}

async function readNow($) {
  try {
    return await $.clock.now()
  } catch {
    return Date.now()
  }
}

/**
 * `promise`, or `null` once `ms` have gone by (`$.clock.sleep`: the module has no timers). The wait
 * is called off as soon as `promise` settles, so it does not outlive the hook.
 */
async function readWithin($, promise, ms) {
  const stop = typeof AbortController === 'function' ? new AbortController() : null
  let late
  try {
    late = $.clock.sleep(ms, stop ? { signal: stop.signal } : undefined).then(
      () => READ_TIMED_OUT,
      () => null,
    )
  } catch {
    return promise
  }
  try {
    return await Promise.race([promise, late])
  } finally {
    if (stop) {
      stop.abort()
    }
  }
}

/**
 * Asks the daemon `path` with `body` plus this session's classifier variables, and hands its text to
 * `parse`. Resolves what `parse` makes of it, or `null` (and the daemon is left alone for a while)
 * on any failure: then the caller asks the process, as before. Never logs the body.
 */
async function readAskDaemon($, common, path, body, parse) {
  if (typeof common.daemonFetch !== 'function') {
    return null
  }
  const now = await readNow($)
  if (now < READ_STATE.daemonDownUntil) {
    return null
  }
  let answer = null
  try {
    const vars = await readClassifierVars($)
    if (vars && typeof common.token === 'function' && (await common.token())) {
      const init = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...body, env: vars }),
      }
      const done = await readWithin($, common.daemonFetch(path, init), READ_DAEMON_TIMEOUT_MS)
      if (done && done.status === 200 && readText(done.text)) {
        answer = parse(done.text)
      }
    }
  } catch {
    answer = null
  }
  if (answer === null) {
    READ_STATE.daemonDownUntil = now + READ_DAEMON_RETRY_MS
  }
  return answer
}

/** `hook classify`'s answer, checked, or null when it is not that shape. */
function readParseClassified(text) {
  try {
    const answer = JSON.parse(text)
    return answer && typeof answer === 'object' && typeof answer.kind === 'string' ? answer : null
  } catch {
    return null
  }
}

/** `hook classify`'s answer for this call (the daemon, else the process), or null. */
async function readClassify($, common, e, sessionId, cwd) {
  const input = { tool_name: e.tool, tool_input: readToolInput(e), cwd, session_id: sessionId }
  const fromDaemon = await readAskDaemon($, common, READ_DAEMON_CLASSIFY, { payload: input }, readParseClassified)
  if (fromDaemon) {
    return fromDaemon
  }
  try {
    const done = await common.runLd(READ_CLASSIFY, JSON.stringify(input), READ_CLASSIFY_TIMEOUT_MS)
    if (!done || done.exitCode !== 0) {
      return null
    }
    return readParseClassified(done.stdout)
  } catch {
    return null
  }
}

/**
 * The variables `hook record-read` reads besides the classifier's (`hook_entry.RECORD_ENV`, which
 * `test_mod_static.py` holds this list and `readClassifierVars` to): where the line goes and the
 * experiment's switch. Read once per load; `null` when the engine cannot read them.
 */
async function readRecordVars($) {
  if (READ_STATE.recordVars !== undefined) {
    return READ_STATE.recordVars
  }
  const vars = {}
  const put = (name, value) => {
    if (typeof value === 'string' && value !== '') {
      vars[name] = value
    }
  }
  try {
    put('LD_HOOK_TELEMETRY_LOG', await $.env.get('LD_HOOK_TELEMETRY_LOG'))
    put('LD_HOOK_ENABLED', await $.env.get('LD_HOOK_ENABLED'))
    READ_STATE.recordVars = vars
  } catch {
    READ_STATE.recordVars = null
  }
  return READ_STATE.recordVars
}

/**
 * The line to the daemon's `record-read`: `'taken'` when it took it (204), `'late'` when the time
 * limit ran out first (the daemon may still write it), `'no'` otherwise. An answer that says it
 * cannot (401, 403, 404: a token it does not take, an older daemon without the route) leaves the
 * route alone for a while; a request that does not complete does not, so the next try asks again.
 */
async function readRecordByDaemon($, common, entry) {
  if (typeof common.daemonFetch !== 'function') {
    return 'no'
  }
  const now = await readNow($)
  // Nor while the classifier's daemon is being left alone: a dead daemon costs its time limit once.
  if (now < READ_STATE.recordDownUntil || now < READ_STATE.daemonDownUntil) {
    return 'no'
  }
  try {
    const vars = await readClassifierVars($)
    const extra = await readRecordVars($)
    if (!vars || !extra || typeof common.token !== 'function' || !(await common.token())) {
      return 'no'
    }
    const init = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payload: entry, env: { ...vars, ...extra } }),
    }
    const done = await readWithin($, common.daemonFetch(READ_DAEMON_RECORD, init), READ_DAEMON_RECORD_TIMEOUT_MS)
    if (done === READ_TIMED_OUT) {
      return 'late'
    }
    if (done && (done.status === 204 || done.status === 200)) {
      return 'taken'
    }
    if (done && [401, 403, 404].includes(done.status)) {
      READ_STATE.recordDownUntil = now + READ_DAEMON_RETRY_MS
    }
  } catch {
    // the process is next
  }
  return 'no'
}

/**
 * One try at recording `item.entry`: the daemon, else the process. `'taken'` when one of them took
 * it, `'lost'` when neither did, `'late'` when the daemon ran out of time on the line's first late
 * try: then the process is not started (it would race the daemon's write), and the line waits for
 * the next tool call.
 */
async function readRecordOnce($, common, item) {
  const byDaemon = await readRecordByDaemon($, common, item.entry)
  if (byDaemon === 'taken') {
    return 'taken'
  }
  if (byDaemon === 'late' && !item.late) {
    item.late = true
    return 'late'
  }
  try {
    const done = await common.runLd(READ_RECORD, JSON.stringify(item.entry), READ_RECORD_TIMEOUT_MS)
    if (done && done.exitCode === 0) {
      return 'taken'
    }
    return 'lost'
  } catch {
    return 'lost'
  }
}

/** The `id` of one decision's line: 12 hex digits, the shape `hook_common.new_id` makes and
 * `hook_common.mod_record_id` takes. */
function readRecordId() {
  const bytes = new Uint8Array(6)
  try {
    globalThis.crypto.getRandomValues(bytes)
  } catch {
    for (let i = 0; i < bytes.length; i++) {
      bytes[i] = Math.floor(Math.random() * 256)
    }
  }
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}

/**
 * The package's data folder (`LOG_DIR`), as `hook_common.log_dir` finds it, from the variables the
 * classifier already reads: `LOCAL_DELEGATE_LOG_DIR`; on Windows (a `USERPROFILE`) `LOCALAPPDATA`;
 * on macOS (a `HOME` of `/Users/<account>`) `Library/Application Support`; else `XDG_DATA_HOME` or
 * `~/.local/share`. `null` when none of them is there.
 */
function readLogDir(vars) {
  const pick = name => (vars && readText(vars[name]) ? vars[name].trim().replace(/[\\/]+$/, '') : null)
  const explicit = pick('LOCAL_DELEGATE_LOG_DIR')
  if (explicit) {
    return explicit
  }
  const profile = pick('USERPROFILE')
  if (profile) {
    return `${pick('LOCALAPPDATA') || `${profile}/AppData/Local`}/local-delegate`
  }
  const home = pick('HOME')
  if (home && /^\/Users\/[^/]+$/.test(home)) {
    return `${home}/Library/Application Support/local-delegate`
  }
  const xdg = pick('XDG_DATA_HOME')
  if (xdg) {
    return `${xdg}/local-delegate`
  }
  return home ? `${home}/.local/share/local-delegate` : null
}

/**
 * The trace of a line neither road took: a debug line and one in the hooks' failure log, the shape
 * `hook_entry._log_failure` writes (time, hook, type of failure) plus the decision's name. Neither
 * carries the file's path or content. Best effort: a trace that fails is not retried.
 */
async function readRecordLost($, entry) {
  const decision = String(entry.decision)
  try {
    await $.ui.log(`local-delegate: record-read lost (decision=${decision}, via=${String(entry.via)})`, { to: 'debug' })
  } catch {
    // no debug log here: the failure log below still counts
  }
  try {
    const dir = readLogDir(await readClassifierVars($))
    if (!dir) {
      return
    }
    const path = `${dir}/${READ_FAILURE_LOG}`
    let before = ''
    try {
      const stat = await $.fs.stat(path)
      if (stat && typeof stat.size === 'number' && stat.size > READ_FAILURE_LOG_MAX_BYTES) {
        return
      }
      before = await $.fs.read(path)
    } catch {
      before = ''
    }
    const line = JSON.stringify({ ts: new Date().toISOString(), hook: 'record-read', error: READ_FAILURE_ERROR, decision })
    const head = typeof before === 'string' && before !== '' && !before.endsWith('\n') ? `${before}\n` : before || ''
    await $.fs.write(path, `${head}${line}\n`)
  } catch {
    // the debug line is all that is left
  }
}

/**
 * Logs a decision with `hook record-read`: the daemon, else the process. Best effort, like all
 * telemetry, and never in the read's way; a line neither takes leaves a trace and waits for the
 * next tool call.
 *
 * Why not record before the dialog: the decision does not exist until the person answers it. So a
 * road the engine refuses right after `$.ui.ask` (the live 0.41.0 symptom, cause not yet seen) is
 * covered three ways: a second road (HTTP), the trace, and the retry from a hook no dialog precedes.
 */
async function readRecord($, common, classified, decision, sessionId) {
  const entry = { ...classified, decision, session_id: sessionId, id: readRecordId() }
  const item = { entry, late: false, traced: false }
  const done = await readRecordOnce($, common, item)
  if (done === 'taken') {
    return
  }
  if (done === 'lost') {
    await readRecordLost($, entry)
    item.traced = true
  }
  readKeepPending(item)
}

function readKeepPending(item) {
  READ_STATE.pending.push(item)
  if (READ_STATE.pending.length > READ_PENDING_MAX) {
    READ_STATE.pending.shift()
  }
}

/**
 * The lines lost (or left waiting by a late daemon) in an earlier call, tried once more with the
 * same `id`, so a line the daemon wrote late is not written twice. One that fails again is dropped,
 * with its trace written now if it had none; one the daemon is late on for the first time waits
 * once more.
 */
async function readFlushPending($, common) {
  const items = READ_STATE.pending
  READ_STATE.pending = []
  for (const item of items) {
    const done = await readRecordOnce($, common, item)
    if (done === 'late') {
      readKeepPending(item)
    } else if (done === 'lost' && !item.traced) {
      await readRecordLost($, item.entry)
    }
  }
}

/** `hook classify --config`'s answer, checked, or null when it is not there or not that shape. */
function readParseConfig(stdout) {
  let parsed
  try {
    parsed = JSON.parse(stdout)
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== 'object') {
    return null
  }
  const list = value => (Array.isArray(value) ? value.filter(readText).map(v => v.trim()) : null)
  const tools = list(parsed.tools)
  const prose = list(parsed.prose_extensions)
  const harmless = list(parsed.harmless_first)
  const minBytes = parsed.min_bytes
  if (!tools || tools.length === 0 || !prose || !harmless || typeof minBytes !== 'number' || !(minBytes >= 0)) {
    return null
  }
  return {
    tools,
    prose: prose.map(ext => ext.toLowerCase()),
    harmless: harmless.map(word => word.toLowerCase()),
    minBytes,
  }
}

/** Asks Python once per load for the prefilter's data (the daemon, else the process); later calls
 * reuse it (or its absence). */
async function readLoadConfig($, common) {
  if (READ_STATE.configAsked) {
    return
  }
  READ_STATE.configAsked = true
  try {
    let config = await readAskDaemon($, common, READ_DAEMON_CONFIG, {}, readParseConfig)
    if (!config) {
      const done = await common.runLd([...READ_CLASSIFY, READ_CONFIG_FLAG], undefined, READ_CLASSIFY_TIMEOUT_MS)
      config = done && done.exitCode === 0 && readText(done.stdout) ? readParseConfig(done.stdout) : null
    }
    if (config) {
      READ_STATE.config = config
      READ_STATE.tools = config.tools
    }
  } catch {
    // no data: every candidate goes to the classifier, as before the prefilter
  }
}

async function readGuardPath(common, sessionId) {
  try {
    return await common.dataPath(`read-guard/${sessionId}.json`)
  } catch {
    return null
  }
}

/** Loads this session's guarded files once (a reload or `--resume` starts the module over). */
async function readLoadGuard($, common, sessionId) {
  if (!sessionId || READ_STATE.guardSession === sessionId) {
    return
  }
  READ_STATE.guard = new Set()
  READ_STATE.guardSession = sessionId
  const path = await readGuardPath(common, sessionId)
  if (!path) {
    return
  }
  try {
    const saved = JSON.parse(await $.fs.read(path))
    if (saved && saved.session_id === sessionId && Array.isArray(saved.paths)) {
      for (const p of saved.paths) {
        if (readText(p)) {
          READ_STATE.guard.add(p)
        }
      }
    }
  } catch {
    // no list yet, or unreadable: nothing guarded
  }
}

async function readSaveGuard($, common, sessionId) {
  const path = sessionId ? await readGuardPath(common, sessionId) : null
  if (!path) {
    return
  }
  try {
    const text = JSON.stringify({ session_id: sessionId, paths: [...READ_STATE.guard] }, null, 2)
    await $.fs.write(path, `${text}\n`)
  } catch {
    // the guard still holds in memory for this load
  }
}

/** Says once per load, in this session's heartbeat, that the read mod is active (for `doctor`). */
async function readBeat($, common, sessionId) {
  if (READ_STATE.beat || !sessionId) {
    return
  }
  READ_STATE.beat = true
  let pieces
  try {
    const path = await common.dataPath(`heartbeats/${sessionId}.json`)
    const previous = path ? JSON.parse(await $.fs.read(path)) : null
    pieces = previous && previous.pieces
  } catch {
    pieces = undefined
  }
  try {
    await common.heartbeat(pieces ? { pieces, read_mod_active: true } : { read_mod_active: true })
  } catch {
    // the heartbeat is for `doctor`; the read goes on without it
  }
}

/** The file's line count: from an earlier `Read`, else counted here (never shown to the model). */
async function readTotalLines($, entry, path) {
  if (entry.total) {
    return entry.total
  }
  try {
    const text = await $.fs.read(path)
    if (typeof text === 'string') {
      const lines = text.split('\n').length - (text.endsWith('\n') ? 1 : 0)
      entry.total = Math.max(lines, 1)
    }
  } catch {
    entry.total = null
  }
  return entry.total
}

/** What a real read leaves behind: the file is no longer guarded, and its lines count as read. */
async function readNoteRealRead($, common, sessionId, key, classified, ran, countRange = true) {
  if (!ran || ran.deny !== undefined || ran.isError === true) {
    return
  }
  const entry = readFileEntry(key)
  const via = readText(classified.via) ? classified.via : 'unknown'
  entry.vias[via] = (entry.vias[via] || 0) + 1
  const file = ran.result && ran.result.file
  if (file && typeof file.totalLines === 'number' && file.totalLines > 0) {
    entry.total = file.totalLines
  }
  const range = readRange(classified.range)
  if (classified.scope === 'whole') {
    entry.whole = true
  } else if (range && countRange) {
    entry.ranges.push(range)
  }
  if (READ_STATE.guard.delete(key)) {
    await readSaveGuard($, common, sessionId)
  }
}

/** Asks `local_summarize` for the file; the summary's text, or null when it fails. */
async function readSummarize($, path) {
  try {
    const result = await $.mcp.call(READ_SERVER, READ_SUMMARY_TOOL, { path })
    // `common.js` unwraps FastMCP's `{ "result": … }` (shared with the commands).
    const text = toolResultText(result)
    if (!text || (result && result.isError) || text.startsWith(READ_ERROR_PREFIX)) {
      return null
    }
    return text
  } catch {
    return null
  }
}

/** The summary as the result of the tool that was called, in that tool's own shape. */
function readAsResult(e, content) {
  if (e.tool === 'Read') {
    const numLines = content.split('\n').length
    return {
      result: {
        type: 'text',
        file: { filePath: e.file_path, content, numLines, startLine: 1, totalLines: numLines },
      },
    }
  }
  return { result: { stdout: content, stderr: '', interrupted: false } }
}

/** Whether the call comes from a subagent: Claude Code puts its `agentId` in the event. */
function readInSubagent(e) {
  return Boolean(readText(e.agentId))
}

/**
 * The note for a large file read in a subagent (issue #443): locate the lines with a `local_*` tool
 * and read only that range. No «read it if you need exact lines»: a subagent always needs them
 * (to quote `file:line` or to edit), so that exception was a standing permission to read it whole.
 */
function readSubagentNote(common, classified) {
  return common.t('read.warn.subagent', { path: classified.path, kb: Math.round(classified.bytes / 1024) })
}

/** Whether a person can pick here: a session with a dialog, and not inside a subagent. */
function readCanAsk(common, e) {
  if (readInSubagent(e)) {
    return false
  }
  try {
    return common.hasDialog() === true
  } catch {
    return false
  }
}

/** A real read through `next`, logged and noted. */
async function readPass($, common, e, next, ctx, decision) {
  const ran = await next(e)
  if (decision) {
    await readRecord($, common, ctx.classified, decision, ctx.sessionId)
  }
  await readNoteRealRead($, common, ctx.sessionId, ctx.key, ctx.classified, ran, ctx.countRange !== false)
  return ran
}

/** A read to steer: summary (asked, or by itself without a dialog) or the real read. */
async function readSteer($, common, e, next, ctx) {
  const { classified, key, path, sessionId } = ctx
  let decision = 'auto_summarized'
  if (readCanAsk(common, e)) {
    const summarize = common.t('read.ask.summarize')
    const whole = common.t('read.ask.whole')
    let picked = null
    try {
      const kb = Math.round((classified.bytes || 0) / 1024)
      picked = await $.ui.ask(common.t('read.ask.question', { path, kb }), [summarize, whole])
    } catch {
      picked = null
    }
    if (picked !== summarize) {
      // «Read it whole», or the dialog dismissed: the person chose not to summarize.
      return readPass($, common, e, next, ctx, picked === whole ? 'read_whole' : 'dismissed')
    }
    decision = 'summarized'
  }
  const summary = await readSummarize($, path)
  if (summary === null) {
    return readPass($, common, e, next, ctx, 'summary_failed')
  }
  READ_STATE.guard.add(key)
  await readSaveGuard($, common, sessionId)
  await readRecord($, common, classified, decision, sessionId)
  return readAsResult(e, `${await readSummaryHeader($, common, ctx)}\n\n${summary}`)
}

/**
 * How many of a file's `total` lines can be read literally in a session: ranges that reach
 * `READ_WHOLE_SHARE` of them count as reading it whole (REQ-020), so the most is one line short.
 */
export function readLiteralBudget(total) {
  return total > 0 ? Math.max(0, Math.ceil(total * READ_WHOLE_SHARE - 1e-9) - 1) : 0
}

/** Whether a file is short enough that a range of it always passes literally (issue #472). */
export function readShortFile(total, bytes) {
  return total > 0 && total <= READ_SHORT_LINES && typeof bytes === 'number' && bytes < READ_SHORT_BYTES
}

/**
 * The line above a summary: what it is and the real rule for reading the file literally (F4-read-
 * fixes; 0.41.0 said «read it with offset/limit», and a range that took the session's reads of the
 * file to 80 % was summarized again). With the file's line count: how many lines can be read
 * literally; for a range summarized because of what was read before, that it was the share and not
 * the range's size, how many lines were read and how many are left.
 */
async function readSummaryHeader($, common, ctx) {
  const { path, key } = ctx
  const entry = readFileEntry(key)
  const total = await readTotalLines($, entry, path)
  if (!total) {
    return common.t('read.summary.header', { path })
  }
  const lines = readLiteralBudget(total)
  if (typeof ctx.share === 'number') {
    const read = Math.round(readCoverage(entry.ranges, total) * total)
    const pct = Math.floor(ctx.share * 100 + 1e-9)
    const left = Math.max(0, lines - read)
    const header = common.t('read.summary.header_ranges', { path, pct, total, read, left, lines })
    if (!ctx.range) {
      return header
    }
    // Issue #472: which lines did not come literally, and the one way to get them that way.
    const first = Math.min(ctx.range.start, total)
    const last = ctx.range.end === null ? total : Math.max(first, Math.min(ctx.range.end, total))
    const omitted = left > 0
      ? common.t('read.summary.range_omitted', { first, last, left })
      : common.t('read.summary.range_omitted_none', { first, last })
    return `${header} ${omitted}`
  }
  return common.t('read.summary.header_budget', { path, lines, total })
}

/** The write guard of REQ-022: a refusal while `key` was only read summarized, else `null`. */
function readGuardRefusal(common, key, path) {
  return key && READ_STATE.guard.has(key) ? { deny: common.t('read.guard.refused', { path }) } : null
}

/** The whole hook: the write guard first, then the read steering. */
async function readOnToolCall($, common, e, next) {
  if (READ_STATE.pending.length > 0) {
    // A decision lost in an earlier call (F4-read-fixes): this hook has no dialog before it.
    await readFlushPending($, common)
  }
  const writeKey = READ_WRITE_TOOLS[e.tool]
  if (writeKey === undefined) {
    // The tool list and the harmless words come with the config: after a reload it is asked here.
    if (!READ_STATE.configAsked && (READ_STATE.tools || READ_DEFAULT_TOOLS).includes(e.tool)) {
      await readLoadConfig($, common)
    }
    if (!readMayTouchFile(e)) {
      return next(e)
    }
  }
  const sessionId = await readSessionId($)
  await readLoadGuard($, common, sessionId)
  const cwd = await readCwd($)
  if (writeKey !== undefined) {
    return readGuardRefusal(common, readNormalize(e[writeKey], cwd), e[writeKey]) || next(e)
  }
  if (!(await readWorthClassifying($, e, cwd))) {
    return next(e)
  }
  const classified = await readClassify($, common, e, sessionId, cwd)
  if (!classified) {
    return next(e)
  }
  const key = readNormalize(classified.path, cwd)
  if (classified.kind === 'write') {
    return readGuardRefusal(common, key, classified.path) || next(e)
  }
  if (classified.kind !== 'read' || classified.read_switch !== 'on' || !key) {
    return next(e)
  }
  await readBeat($, common, sessionId)
  const minBytes = READ_STATE.config ? READ_STATE.config.minBytes : READ_MIN_BYTES
  const big = typeof classified.bytes === 'number' && classified.bytes >= minBytes
  // The band comes from `hook classify` (the read hook's own constants): only large prose can be
  // summarized. A classifier that does not say so is not trusted to summarize.
  const prose = classified.summarizable === true
  const ctx = { classified, key, path: classified.path, sessionId }
  if (classified.scope === 'unclassifiable' || !READ_SUMMARIZABLE_TOOLS.includes(e.tool)) {
    // Not sure what enters the context, or a tool whose result the mod cannot stand in for: a
    // note and the log, never a block.
    const ran = await next(e)
    if (!big || !ran || ran.deny !== undefined) {
      return ran
    }
    const kb = Math.round(classified.bytes / 1024)
    if (classified.via === 'read_image' || classified.via === 'read_document') {
      // `Read` shows these as an image or pages, not lines: no `local_extract` ranges and no
      // `offset`/`limit` (issue #469). An image `local_describe_image` accepts gets that tool;
      // anything else passes in silence.
      if (classified.describable !== true) {
        return ran
      }
      await readRecord($, common, classified, 'warned', sessionId)
      const image = common.t('read.warn.image', { path: classified.path, kb })
      return { ...ran, context: [...(ran.context || []), image] }
    }
    await readRecord($, common, classified, 'warned', sessionId)
    const note = readInSubagent(e)
      ? readSubagentNote(common, classified)
      : common.t('read.warn.large', { path: classified.path, kb })
    return { ...ran, context: [...(ran.context || []), note] }
  }
  if (!big) {
    return readPass($, common, e, next, ctx, null)
  }
  if (!prose) {
    // Code, config, data: the literal text is what the reader needs (a subagent about to program),
    // so the read always goes through, by ranges too, and is logged. A subagent that read it whole
    // also gets the note to locate first and read the range next time (issue #443); a range is
    // already that, and the main thread keeps its silence.
    const ran = await readPass($, common, e, next, ctx, 'not_prose')
    if (!readInSubagent(e) || classified.scope !== 'whole' || !ran || ran.deny !== undefined) {
      return ran
    }
    return { ...ran, context: [...(ran.context || []), readSubagentNote(common, classified)] }
  }
  if (classified.scope === 'whole') {
    return readSteer($, common, e, next, ctx)
  }
  if (readInSubagent(e)) {
    // A subagent reads a range to quote or edit those very lines (issue #472, as #443): a summary in
    // their place pushed it to dodge the hook through the shell. Literal, and it lifts the write
    // guard like any real read, but its lines stay out of the shared coverage: the 80 % is the main
    // thread's budget, and a subagent that read the file whole by ranges left the main thread
    // summarized on any range and unable to edit (orchestrator → subagent reads → main edits).
    return readPass($, common, e, next, { ...ctx, countRange: false }, null)
  }
  const range = readRange(classified.range)
  const entry = readFileEntry(key)
  const total = range ? await readTotalLines($, entry, classified.path) : null
  if (range && total && range.start > total) {
    // Past the end: `Read` returns no lines, so there is nothing to summarize.
    return readPass($, common, e, next, ctx, null)
  }
  if (readShortFile(total, classified.bytes)) {
    // A short file (issue #472): 80 % of it is a few lines, so the share was reached at once and the
    // summary saved next to nothing.
    return readPass($, common, e, next, ctx, null)
  }
  const covered = range && total ? readCoverage([...entry.ranges, range], total) : 0
  if (!entry.whole && covered >= READ_WHOLE_SHARE) {
    // Not the range's size: what this session has read of the file, this range included (REQ-020).
    return readSteer($, common, e, next, { ...ctx, share: covered, range })
  }
  return readPass($, common, e, next, ctx, null)
}

// At the session's start (and on `--resume`): this session's guarded files and the prefilter's
// data from Python (`hook classify --config`, one process). `register.js` holds the module's only `session.start` hook and calls this one; what it
// resolves goes into the heartbeat `register.js` writes right after, so the session's heartbeat
// says `read_mod_active` from its start and the read hooks step aside from the first read
// (REQ-023, decision 10). A reload mid-session starts the module over without a `session.start`:
// then `readBeat` says it at the first classified read.
export async function onSessionStart($, e, common) {
  if (!READ_STATE.enabled) {
    return undefined
  }
  const c = common || engineCommon($)
  await readLoadGuard($, c, await readSessionId($))
  await readLoadConfig($, c)
  READ_STATE.beat = true
  return { read_mod_active: true }
}

/** Registers the `tool.call` hook, only with `read_mod_enabled` on (on by default: `readModOn`). */
export function register(on, options, common) {
  READ_STATE.enabled = readModOn(options)
  READ_STATE.tools = null
  READ_STATE.config = null
  READ_STATE.configAsked = false
  READ_STATE.files = new Map()
  READ_STATE.guard = new Set()
  READ_STATE.guardSession = null
  READ_STATE.beat = false
  READ_STATE.vars = undefined
  READ_STATE.daemonDownUntil = 0
  READ_STATE.recordVars = undefined
  READ_STATE.recordDownUntil = 0
  READ_STATE.pending = []
  if (!READ_STATE.enabled) {
    return
  }
  on('tool.call', ($, e, next) => readOnToolCall($, common || engineCommon($), e, next))
}
