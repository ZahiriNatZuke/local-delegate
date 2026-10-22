// mod/read.js — large reads go through the local model (REQ-020, REQ-021, REQ-022; SDD
// claude-plugin-and-mods, batch F4-read-mod; design in plan.md, wave 5).
//
// One `tool.call` hook, only with the `read_mod_enabled` option on (off by default):
//   - a cheap filter drops, by tool name and first token, the calls that cannot read or write a
//     file; the rest go to `local-delegate hook classify` through `common.runLd`. No answer, or a
//     `read_switch` other than `on`, and the call goes through untouched;
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
// writes in `blocks.jsonl`, and the session's heartbeat says `read_mod_active`.
//
// A piece of the mod: `scripts/build_mod.py` pastes it into `register.js`. It only declares at
// load, and every top-level name carries `read`, so it cannot clash with another piece's.

import { engineCommon, toolResultText } from './common.js'

export const READ_SWITCH = 'read_mod_enabled'
// REQ-020: ranges that cover this share of the file's lines count as reading it whole.
export const READ_WHOLE_SHARE = 0.8
// The read hook's lower band (`LD_HOOK_READ_SUGGEST_KB`, 8 KB): below it a read is left alone.
export const READ_MIN_BYTES = 8 * 1024

const READ_SERVER = 'local-delegate'
const READ_SUMMARY_TOOL = 'local_summarize'
const READ_ERROR_PREFIX = '[local-delegate error]'
const READ_CLASSIFY = ['-I', '-m', 'local_delegate', 'hook', 'classify']
const READ_RECORD = ['-I', '-m', 'local_delegate', 'hook', 'record-read']
const READ_CLASSIFY_TIMEOUT_MS = 10000
const READ_RECORD_TIMEOUT_MS = 10000
const READ_SESSION_ID = /^[A-Za-z0-9_-]{1,128}$/
// The tools that write a file by a path argument of their own.
const READ_WRITE_TOOLS = { Edit: 'file_path', Write: 'file_path', NotebookEdit: 'notebook_path' }
const READ_SHELL_TOOLS = ['Bash', 'PowerShell']
// The tools whose result the mod can stand in for with a summary.
const READ_SUMMARIZABLE_TOOLS = ['Read', 'Bash', 'PowerShell']
// What `hook classify --list-tools` would say when it cannot be asked.
const READ_DEFAULT_TOOLS = ['Read', 'Bash', 'PowerShell', 'Grep']
// First tokens of a shell command that neither read nor write a file, as long as the command has
// no redirection, pipe or chaining (`> | ; &`): those go to the classifier whatever they start with.
const READ_HARMLESS_FIRST = [
  'git', 'gh', 'ls', 'dir', 'pwd', 'cd', 'uv', 'pnpm', 'npm', 'npx', 'node', 'pytest', 'ruff',
  'which', 'where', 'whoami', 'date', 'mkdir', 'get-childitem', 'gci', 'test-path', 'get-location',
  'set-location', 'claude', 'local-delegate',
]
const READ_CHAINING = /[>|;&]/
const READ_ENVELOPE_KEYS = ['tool', 'tool_use_id', 'agentId', 'requestMeta', 'consent']

// The module's own memory, which a reload starts over: what each file has had read in this
// session (by path), the guarded files, the tools the classifier knows and whether the heartbeat
// already says the mod is active.
const READ_STATE = {
  enabled: false,
  tools: null,
  files: new Map(),
  guard: new Set(),
  guardSession: null,
  beat: false,
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

/** The cheap filter: whether the call may read or write a file, before asking the classifier. */
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
    if (!READ_CHAINING.test(command)) {
      const first = command.split(/\s+/)[0].replace(/^.*[\\/]/, '').replace(/\.exe$/i, '').toLowerCase()
      if (READ_HARMLESS_FIRST.includes(first)) {
        return false
      }
    }
  }
  return true
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

/** `hook classify`'s answer for this call, or null when it is not there or does not answer. */
async function readClassify(common, e, sessionId, cwd) {
  const stdin = JSON.stringify({ tool_name: e.tool, tool_input: readToolInput(e), cwd, session_id: sessionId })
  try {
    const done = await common.runLd(READ_CLASSIFY, stdin, READ_CLASSIFY_TIMEOUT_MS)
    if (!done || done.exitCode !== 0) {
      return null
    }
    const answer = JSON.parse(done.stdout)
    return answer && typeof answer === 'object' && typeof answer.kind === 'string' ? answer : null
  } catch {
    return null
  }
}

/** Logs a decision with `hook record-read`; best effort, like all telemetry. */
async function readRecord(common, classified, decision, sessionId) {
  try {
    const line = JSON.stringify({ ...classified, decision, session_id: sessionId })
    await common.runLd(READ_RECORD, line, READ_RECORD_TIMEOUT_MS)
  } catch {
    // a lost line of telemetry must never reach the read
  }
}

/** The tools `hook classify --list-tools` names (a JSON list, `{ tools }`, or one per line). */
async function readListTools(common) {
  try {
    const done = await common.runLd([...READ_CLASSIFY, '--list-tools'], undefined, READ_CLASSIFY_TIMEOUT_MS)
    if (!done || done.exitCode !== 0 || !readText(done.stdout)) {
      return null
    }
    let names
    try {
      const parsed = JSON.parse(done.stdout)
      names = Array.isArray(parsed) ? parsed : parsed && parsed.tools
    } catch {
      names = done.stdout.split(/\r?\n/)
    }
    if (!Array.isArray(names)) {
      return null
    }
    const tools = names.filter(readText).map(name => name.trim())
    return tools.length > 0 ? tools : null
  } catch {
    return null
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
async function readNoteRealRead($, common, sessionId, key, classified, ran) {
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
  } else if (range) {
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

/** Whether a person can pick here: a session with a dialog, and not inside a subagent. */
function readCanAsk(common, e) {
  if (readText(e.agentId)) {
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
    await readRecord(common, ctx.classified, decision, ctx.sessionId)
  }
  await readNoteRealRead($, common, ctx.sessionId, ctx.key, ctx.classified, ran)
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
  await readRecord(common, classified, decision, sessionId)
  return readAsResult(e, `${common.t('read.summary.header', { path })}\n\n${summary}`)
}

/** The write guard of REQ-022: a refusal while `key` was only read summarized, else `null`. */
function readGuardRefusal(common, key, path) {
  return key && READ_STATE.guard.has(key) ? { deny: common.t('read.guard.refused', { path }) } : null
}

/** The whole hook: the write guard first, then the read steering. */
async function readOnToolCall($, common, e, next) {
  const writeKey = READ_WRITE_TOOLS[e.tool]
  if (writeKey === undefined && !readMayTouchFile(e)) {
    return next(e)
  }
  const sessionId = await readSessionId($)
  await readLoadGuard($, common, sessionId)
  const cwd = await readCwd($)
  if (writeKey !== undefined) {
    return readGuardRefusal(common, readNormalize(e[writeKey], cwd), e[writeKey]) || next(e)
  }
  const classified = await readClassify(common, e, sessionId, cwd)
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
  const big = typeof classified.bytes === 'number' && classified.bytes >= READ_MIN_BYTES
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
    await readRecord(common, classified, 'warned', sessionId)
    const kb = Math.round(classified.bytes / 1024)
    const note = common.t('read.warn.large', { path: classified.path, kb })
    return { ...ran, context: [...(ran.context || []), note] }
  }
  if (!big) {
    return readPass($, common, e, next, ctx, null)
  }
  if (!prose) {
    // Code, config, data: the literal text is what the reader needs (a subagent about to program),
    // so the read always goes through, by ranges too, and is only logged.
    return readPass($, common, e, next, ctx, 'not_prose')
  }
  if (classified.scope === 'whole') {
    return readSteer($, common, e, next, ctx)
  }
  const range = readRange(classified.range)
  const entry = readFileEntry(key)
  const total = range ? await readTotalLines($, entry, classified.path) : null
  const covered = range && total ? readCoverage([...entry.ranges, range], total) : 0
  if (!entry.whole && covered >= READ_WHOLE_SHARE) {
    return readSteer($, common, e, next, ctx)
  }
  return readPass($, common, e, next, ctx, null)
}

// At the session's start (and on `--resume`): this session's guarded files and the classifier's
// tools. `register.js` holds the module's only `session.start` hook and calls this one; what it
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
  const tools = await readListTools(c)
  if (tools) {
    READ_STATE.tools = tools
  }
  READ_STATE.beat = true
  return { read_mod_active: true }
}

/** Registers the `tool.call` hook, only with `read_mod_enabled` on (off by default). */
export function register(on, options, common) {
  READ_STATE.enabled = options?.[READ_SWITCH] === true
  READ_STATE.tools = null
  READ_STATE.files = new Map()
  READ_STATE.guard = new Set()
  READ_STATE.guardSession = null
  READ_STATE.beat = false
  if (!READ_STATE.enabled) {
    return
  }
  on('tool.call', ($, e, next) => readOnToolCall($, common || engineCommon($), e, next))
}
