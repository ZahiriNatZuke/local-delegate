// Slash commands that run without a model turn (REQ-014): `/local-summarize <path>`,
// `/local-commit` and `/local-lint <file|command>`. Each answers its own `command.run` with the
// local model's output as `{ text }`; the output row stays in the transcript, so the next turn
// reads it. Every text for the person comes from `common.t` (catalogs in `mod/i18n`).
//
// The engine only lets `$` reach functions declared at the top of the file, so the helpers are
// top-level and take `common` as an argument: `engineCommon($)` builds it inside each hook (a
// test passes its own double as `register`'s third argument instead). Every name but `register`
// carries the `commands` prefix and cannot clash with another piece's.

import { engineCommon } from './common.js'

const COMMANDS_SERVER = 'local-delegate'
const COMMANDS_ERROR_PREFIX = '[local-delegate error]'
const COMMANDS_RUN_TIMEOUT_MS = 30000
// Deletes the file named by the last argument; a missing file is not an error. `$.fs` has no
// delete, so it goes through the interpreter of the uv tool environment (`common.runLd`).
const COMMANDS_REMOVE_SCRIPT =
  'import os, sys\ntry:\n    os.remove(sys.argv[1])\nexcept FileNotFoundError:\n    pass'

function commandsIsWindowsPath(p) {
  return /^[A-Za-z]:[\\/]/.test(p) || p.startsWith('\\\\')
}

function commandsUnquote(s) {
  const v = s.trim()
  if (v.length >= 2 && (v[0] === '"' || v[0] === "'") && v.at(-1) === v[0]) return v.slice(1, -1)
  return v
}

function commandsAbsolute(cwd, p) {
  if (commandsIsWindowsPath(p) || p.startsWith('/')) return p
  const windows = commandsIsWindowsPath(cwd)
  const sep = windows ? '\\' : '/'
  const rel = windows ? p.replace(/\//g, '\\') : p
  return cwd.endsWith(sep) ? cwd + rel : cwd + sep + rel
}

function commandsErrorText(err) {
  return String(err?.message ?? err).split('\n')[0]
}

// Windows rules (CommandLineToArgvW / MSVC runtime): 2n backslashes before a quote give n and
// toggle quoting, 2n+1 give n and a literal quote, `""` inside quotes is a literal quote,
// backslashes elsewhere are literal; single quotes mean nothing.
function commandsSplitWindows(line) {
  const args = []
  let cur = ''
  let inQuotes = false
  let started = false
  let i = 0
  while (i < line.length) {
    const c = line[i]
    if (c === '\\') {
      let n = 0
      while (line[i] === '\\') {
        n++
        i++
      }
      if (line[i] === '"') {
        cur += '\\'.repeat(Math.floor(n / 2))
        if (n % 2 === 1) {
          cur += '"'
          i++
        }
      } else {
        cur += '\\'.repeat(n)
      }
      started = true
      continue
    }
    if (c === '"') {
      if (inQuotes && line[i + 1] === '"') {
        cur += '"'
        i += 2
        continue
      }
      inQuotes = !inQuotes
      started = true
      i++
      continue
    }
    if ((c === ' ' || c === '\t') && !inQuotes) {
      if (started) args.push(cur)
      cur = ''
      started = false
      i++
      continue
    }
    cur += c
    started = true
    i++
  }
  if (started) args.push(cur)
  return args
}

// POSIX shell rules: single quotes are literal, double quotes let a backslash escape
// `$`, `` ` ``, `"`, `\` and a newline, a bare backslash escapes the next character. An unclosed
// quote gives null.
function commandsSplitPosix(line) {
  const args = []
  let cur = ''
  let started = false
  let i = 0
  while (i < line.length) {
    const c = line[i]
    if (c === "'") {
      const end = line.indexOf("'", i + 1)
      if (end < 0) return null
      cur += line.slice(i + 1, end)
      started = true
      i = end + 1
      continue
    }
    if (c === '"') {
      i++
      let closed = false
      while (i < line.length) {
        const d = line[i]
        if (d === '"') {
          closed = true
          i++
          break
        }
        if (d === '\\' && i + 1 < line.length && '$`"\\\n'.includes(line[i + 1])) {
          cur += line[i + 1]
          i += 2
          continue
        }
        cur += d
        i++
      }
      if (!closed) return null
      started = true
      continue
    }
    if (c === '\\') {
      if (i + 1 < line.length) cur += line[i + 1]
      started = true
      i += 2
      continue
    }
    if (c === ' ' || c === '\t' || c === '\n') {
      if (started) args.push(cur)
      cur = ''
      started = false
      i++
      continue
    }
    cur += c
    started = true
    i++
  }
  if (started) args.push(cur)
  return args
}

// Asked only after `$.process.run` rejected, to tell «not available here or blocked by policy»
// from «this command could not start»: `common.runLd` gives null when it cannot run at all.
async function commandsCanRun(common) {
  try {
    return (await common.runLd(['-I', '-c', ''])) != null
  } catch {
    return false
  }
}

async function commandsIsFile($, path) {
  try {
    if (!(await $.fs.exists(path))) return false
    const st = await $.fs.stat(path)
    return st?.kind === 'file'
  } catch {
    return false
  }
}

// Calls a local-delegate tool and turns every outcome into the command's answer.
async function commandsCallTool($, common, tool, args) {
  let result
  try {
    result = await $.mcp.call(COMMANDS_SERVER, tool, args)
  } catch (err) {
    return { text: common.t('commands.error.mcp_down', { detail: commandsErrorText(err) }), exitCode: 1 }
  }
  const text = (result?.content ?? [])
    .filter((block) => block?.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
    .trim()
  if (result?.isError || text.startsWith(COMMANDS_ERROR_PREFIX)) {
    const detail = text.startsWith(COMMANDS_ERROR_PREFIX)
      ? text.slice(COMMANDS_ERROR_PREFIX.length).trim()
      : text
    return { text: common.t('commands.error.tool_failed', { detail }), exitCode: 1 }
  }
  if (!text) return { text: common.t('commands.error.empty'), exitCode: 1 }
  return { text }
}

// The temporary file may hold secrets (a staged `.env`, a token in a log): it is emptied first,
// which needs nothing but `$.fs`, and then deleted. Neither step may throw out of a `finally`.
async function commandsDiscard($, common, path) {
  try {
    await $.fs.write(path, '')
  } catch {
    // the delete below still runs
  }
  try {
    await common.runLd(['-I', '-c', COMMANDS_REMOVE_SCRIPT, path])
  } catch {
    // emptied, at least
  }
}

// Writes `text` to a temporary file, hands its path to `tool` and always discards the file.
async function commandsViaTempFile($, common, name, text, tool) {
  const stamp = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  const path = await common.dataPath(`tmp/${stamp}-${name}`)
  try {
    await $.fs.write(path, text)
    return await commandsCallTool($, common, tool, { path })
  } finally {
    await commandsDiscard($, common, path)
  }
}

async function commandsSummarize($, common, e) {
  const arg = commandsUnquote(e.args ?? '')
  if (!arg) return { text: common.t('commands.summarize.usage') }
  const path = commandsAbsolute(await $.session.cwd(), arg)
  if (!(await commandsIsFile($, path))) {
    return { text: common.t('commands.summarize.missing', { path }), exitCode: 1 }
  }
  return commandsCallTool($, common, 'local_summarize', { path })
}

async function commandsCommit($, common) {
  let diff
  try {
    diff = await $.process.run(['git', 'diff', '--cached'], { timeoutMs: COMMANDS_RUN_TIMEOUT_MS })
  } catch (err) {
    if (!(await commandsCanRun(common))) {
      return { text: common.t('commands.commit.no_process'), exitCode: 1 }
    }
    const detail = commandsErrorText(err)
    return { text: common.t('commands.commit.git_failed', { detail }), exitCode: 1 }
  }
  if (diff.exitCode !== 0) {
    const first = (diff.stderr || diff.stdout || '').trim().split('\n')[0]
    const detail = first || `exit ${diff.exitCode}`
    return { text: common.t('commands.commit.git_failed', { detail }), exitCode: 1 }
  }
  if (!diff.stdout.trim()) return { text: common.t('commands.commit.no_changes') }
  const answer = await commandsViaTempFile($, common, 'commit.diff', diff.stdout, 'local_commit_msg')
  if (answer.exitCode) return answer
  // Only shown: the mod never runs `git commit`.
  return { text: `${common.t('commands.commit.header')}\n\n${answer.text}` }
}

async function commandsLint($, common, e) {
  const raw = (e.args ?? '').trim()
  if (!raw) return { text: common.t('commands.lint.usage') }
  const cwd = await $.session.cwd()
  const asFile = commandsAbsolute(cwd, commandsUnquote(raw))
  if (await commandsIsFile($, asFile)) {
    return commandsCallTool($, common, 'local_lint_summary', { path: asFile })
  }
  const argv = commandsIsWindowsPath(cwd) ? commandsSplitWindows(raw) : commandsSplitPosix(raw)
  if (!argv || argv.length === 0) {
    return { text: common.t('commands.lint.bad_quotes'), exitCode: 1 }
  }
  let out
  try {
    out = await $.process.run(argv, { timeoutMs: COMMANDS_RUN_TIMEOUT_MS })
  } catch (err) {
    if (!(await commandsCanRun(common))) {
      return { text: common.t('commands.lint.file_only', { arg: raw }), exitCode: 1 }
    }
    const detail = commandsErrorText(err)
    return { text: common.t('commands.lint.run_failed', { command: raw, detail }), exitCode: 1 }
  }
  const log = `$ ${raw}\n${out.stdout ?? ''}\n${out.stderr ?? ''}\nexit ${out.exitCode}\n`
  return commandsViaTempFile($, common, 'lint.log', log, 'local_lint_summary')
}

// One literal call per name: the engine then knows each `command.run` hook below answers a
// command this module registers. A refused name does not take the others down.
async function commandsRegisterAll($, common) {
  try {
    await $.command.register({
      name: 'local-summarize',
      description: common.t('commands.summarize.description'),
      argumentHint: common.t('commands.summarize.hint'),
    })
  } catch {
    // refused: the other two still register
  }
  try {
    await $.command.register({
      name: 'local-commit',
      description: common.t('commands.commit.description'),
    })
  } catch {
    // refused: the other two still register
  }
  try {
    await $.command.register({
      name: 'local-lint',
      description: common.t('commands.lint.description'),
      argumentHint: common.t('commands.lint.hint'),
    })
  } catch {
    // refused: the other two still register
  }
}

// At the session's start the commands are registered. `register.js` holds the module's only
// `session.start` hook (the engine refuses two without a matcher) and calls this one.
export async function onSessionStart($, e, common) {
  await commandsRegisterAll($, common || engineCommon($))
}

export function register(on, options, common) {
  const enabled = options?.commands_enabled
  if (enabled === false || enabled === 'false') return

  on('command.run', { command: 'local-summarize' }, ($, e) => commandsSummarize($, common || engineCommon($), e))
  on('command.run', { command: 'local-commit' }, ($) => commandsCommit($, common || engineCommon($)))
  on('command.run', { command: 'local-lint' }, ($, e) => commandsLint($, common || engineCommon($), e))
}
