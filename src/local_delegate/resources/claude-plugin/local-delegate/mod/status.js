// mod/status.js — what local-delegate is doing in this session, in a band above the prompt (REQ-017;
// SDD claude-plugin-and-mods, batches F3-status and F4-band).
//
// The piece asks the daemon three things and keeps the answer for the band:
//   - `/api/stats?session=<id>`: this session's delegations (`total.calls`), the context they saved
//     (`tokens_context_net`, the panel's KPI) and, when `recompute-cost` left its figures, what that
//     is worth at API prices (`cost.figure.estimate`).
//   - `/api/backend`: whether the local backend answers and which model it has mounted (or is still
//     loading: a `running` entry whose state is not `ready`).
//   - `/api/inflight`: the delegations running right now, each with its tool and `elapsed_s`.
//
// When it asks (F4-band, live refresh):
//   - after each `session.measure` (every main-thread turn) and when a call to a local-delegate tool
//     answers: the three of them;
//   - on a `$.clock.every` timer, `/api/backend` and `/api/inflight` alone (plain HTTP to the daemon,
//     never a process): every second while a delegation runs or the backend is loading a model, so
//     the band shows the mounted model and the tool at work as they happen, not when the turn ends;
//     every 30 seconds otherwise, which catches what this session does not cause (the backend going
//     down, a model unloaded by its TTL, another session's delegation) for two loopback requests.
//     A call to a local-delegate tool switches to the quick pace at once. The band is redrawn only
//     when the answer changed, the session's figures are asked again when the last delegation ends,
//     and the timer stops at `session.end` (and with the module, on a reload).
//
// How it looks depends on the surface (`e.surface`):
//   - terminal, `status_style: bar` (the default): one row with the theme's message background, a
//     state chip in inverse video (` ● LISTO `, ` ◐ DELEGANDO `, ` ○ CAÍDO `, ` ◌ SIN DATOS `,
//     ` ○ SIN SERVICIO `), the model dim, the tool at work, the figures bold with dim labels, and the
//     read mode dim on the right. No empty row above or below: the background sets it apart.
//   - terminal, `status_style: line`: a dim `─` rule as wide as the band over one plain line,
//     `local-delegate · ● qwen3-8b listo · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18 ·
//     lecturas: pregunta`, color only on the dot (all of it red when the backend is down). The rule
//     stays because a line without a background would read as the last line of the chat.
//   - any other surface (Claude Desktop): one native row, the name a dim link to the panel, a
//     round-bordered pill with the dot and the state, the model dim, the tool in mono, the figures
//     semibold and tabular, and the read mode as a caption on the right.
// The read mode follows `hasDialog()`: with a person at the prompt the read mod asks before it
// summarizes («lecturas: pregunta»), without one it summarizes on its own («lecturas: resume solo»).
// While delegating the dot turns (◐◓◑◒) with the seconds the oldest call has run, so the turn costs
// no redraw of its own. When the band is narrow the least important parts go first. The Claude
// quota is NOT here: the person's own status line shows it.
//
// Why a band (`ui.render` on `AbovePrompt`) and not `$.ui.status`: `$.ui.status(text)` takes text
// alone, and the engine (2.1.308) pins it as a notice with no color, drawn like every pinned notice
// as `⚠ <plugin>: <text>` in the theme's `warning` color. The band takes a tree whose colors are
// theme keys, so it follows the person's light or dark theme.
//
// No token: nothing is asked and the band is left to the engine. A daemon that does not answer the
// stats: the band says so. Switched off by the `status_enabled` option (`register.js` does not call
// `register` then).
//
// A piece of the mod: `scripts/build_mod.py` pastes it into `register.js`, which calls its
// `register` inside its own `try`. It only declares at load, so loading it cannot throw. Its
// top-level names carry `status`, so they cannot clash with another piece's.

import { daemonFetch, hasDialog, language, readModOn, t, token } from './common.js'

export const STATUS_SWITCH = 'status_enabled'
export const STATUS_STYLE = 'status_style'

const STATUS_SESSION_ID = /^[A-Za-z0-9_-]{1,128}$/
const STATUS_MODEL_WIDTH = 28
const STATUS_SEPARATOR = ' · '
const STATUS_RULE = '─'
const STATUS_TOOL_PREFIX = 'mcp__local-delegate__'
const STATUS_TOOL = /^mcp__local-delegate__/
// The daemon's panel. The engine's validator takes `http:` links to `localhost` alone, never to
// 127.0.0.1 (where the daemon listens): the live test checks that the panel answers there.
const STATUS_PANEL = 'http://localhost:9393'
const STATUS_HOT_MS = 1000
const STATUS_COLD_MS = 30000

// The glyphs carry the state on their own, for a terminal without color.
const STATUS_GLYPH = { ready: '●', down: '○', none: '◌' }
const STATUS_SPIN = ['◐', '◓', '◑', '◒']
const STATUS_COLOR = { ready: 'success', busy: 'warning', down: 'error' }

/** A token count in a few characters: `850`, `12.3k`, `456k`, `1.2M` (`,` as the decimal in es). */
export function statusTokens(value, lang) {
  const sign = value < 0 ? '-' : ''
  const size = Math.abs(Math.round(value))
  let text
  if (size < 1000) {
    text = String(size)
  } else if (size < 100000) {
    text = `${(size / 1000).toFixed(1)}k`
  } else if (size < 1000000) {
    text = `${Math.round(size / 1000)}k`
  } else {
    text = `${(size / 1000000).toFixed(1)}M`
  }
  text = text.replace(/\.0(?=[kM])/, '')
  return sign + (lang === 'es' ? text.replace('.', ',') : text)
}

/** Dollars with two decimals: `$0.18`, `$0,18` in es. */
export function statusMoney(value, lang) {
  const text = value.toFixed(2)
  return `$${lang === 'es' ? text.replace('.', ',') : text}`
}

function statusNumber(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function statusCut(name) {
  return name.length > STATUS_MODEL_WIDTH ? `${name.slice(0, STATUS_MODEL_WIDTH - 1)}…` : name
}

/** The mounted model's name, cut to a few characters, or `null`. */
function statusModelName(running) {
  const entry = running.find(item => item && item.state === 'ready') || running[0]
  const name = entry && typeof entry.model === 'string' ? entry.model.trim() : ''
  return name ? statusCut(name) : null
}

/** The oldest delegation in flight as `{ tool, seconds, more, model }`, or `null`. */
function statusTask(list) {
  const items = list.filter(item => item && typeof item === 'object')
  if (items.length === 0) {
    return null
  }
  const oldest = items.reduce((a, b) => ((statusNumber(b.elapsed_s) ?? 0) > (statusNumber(a.elapsed_s) ?? 0) ? b : a))
  const raw = typeof oldest.tool === 'string' ? oldest.tool.trim() : ''
  const tool = raw.startsWith(STATUS_TOOL_PREFIX) ? raw.slice(STATUS_TOOL_PREFIX.length) : raw
  const model = typeof oldest.model === 'string' && oldest.model.trim() ? statusCut(oldest.model.trim()) : null
  return {
    tool: tool || null,
    seconds: Math.max(0, Math.floor(statusNumber(oldest.elapsed_s) ?? 0)),
    more: items.length - 1,
    model,
  }
}

/**
 * What the band shows, from the daemon's three answers (each a parsed body or `null`).
 *
 * `{ daemon: 'down' }` when the stats are not there; otherwise the figures, the backend's state
 * (`ready`, `busy`, `down`, or `null` when `/api/backend` did not answer), the model, whether the
 * backend is still loading one, and the oldest delegation in flight.
 */
export function statusSnapshot(stats, backend, inflight) {
  const net = stats ? statusNumber(stats.tokens_context_net) : null
  if (net === null) {
    return { daemon: 'down' }
  }
  const calls = statusNumber(stats.total && stats.total.calls) ?? 0
  const figure = stats.cost && stats.cost.figure
  const cost = figure ? statusNumber(figure.estimate) : null
  const running = backend && Array.isArray(backend.running) ? backend.running : []
  const list = inflight && Array.isArray(inflight.inflight) ? inflight.inflight : []
  const count = inflight ? statusNumber(inflight.count) ?? list.length : 0
  let state = null
  let task = null
  if (backend && typeof backend.available === 'boolean') {
    if (!backend.available) {
      state = 'down'
    } else if (count > 0) {
      state = 'busy'
      task = statusTask(list) || { tool: null, seconds: 0, more: Math.max(0, count - 1), model: null }
    } else {
      state = 'ready'
    }
  }
  const loading = running.some(item => item && typeof item.state === 'string' && item.state !== 'ready')
  const model = statusModelName(running) || (task && task.model) || null
  return { daemon: 'up', calls, net, cost, backend: state, model, loading, task }
}

/** `asks`, `auto`, or `null` when the mod does not steer the reads. */
function statusReadMode(options) {
  if (!readModOn(options)) {
    return null
  }
  return hasDialog() ? 'asks' : 'auto'
}

/** The dot: the turning one while delegating (one step per second the oldest call has run). */
function statusGlyph(snapshot) {
  if (snapshot.daemon === 'down' || snapshot.backend === 'down') {
    return STATUS_GLYPH.down
  }
  if (snapshot.backend === 'busy') {
    return STATUS_SPIN[(snapshot.task ? snapshot.task.seconds : 0) % STATUS_SPIN.length]
  }
  return snapshot.backend === 'ready' ? STATUS_GLYPH.ready : STATUS_GLYPH.none
}

// A part is `{ joint, rank, pieces }`: `joint` goes before it (dim), each piece is
// `{ text, color?, dim?, bold?, ... }`, and `rank` says which parts go first when the band is
// narrow (higher goes first; rank 0 always stays).
function statusPart(rank, joint, ...pieces) {
  return { rank, joint, pieces }
}

function statusTaskPieces(task) {
  const pieces = []
  if (task.tool) {
    pieces.push({ text: task.tool })
  }
  const seconds = t('status.seconds', { n: task.seconds })
  pieces.push({ text: task.tool ? ` ${seconds}` : seconds, dim: true })
  if (task.more > 0) {
    pieces.push({ text: ` ${t('status.more', { n: task.more })}`, dim: true })
  }
  return pieces
}

/** The figures as parts: `3 delegaciones · 12,3k tokens ahorrados ≈ $0,18`, or the empty note. */
function statusFigures(snapshot, lang, joint) {
  if (snapshot.calls <= 0) {
    return [{ ...statusPart(2, joint, { text: t('status.empty'), dim: true }), kind: 'empty' }]
  }
  const label = snapshot.calls === 1 ? t('status.calls_label_one') : t('status.calls_label')
  const parts = [
    { ...statusPart(2, joint, { text: String(snapshot.calls), bold: true }, { text: ` ${label}`, dim: true }), kind: 'calls' },
    statusPart(
      3,
      STATUS_SEPARATOR,
      { text: statusTokens(snapshot.net, lang), bold: true },
      { text: ` ${t('status.saved_label')}`, dim: true },
    ),
  ]
  if (snapshot.cost !== null && snapshot.cost >= 0.005) {
    parts.push({ ...statusPart(4, ' ', { text: `≈ ${statusMoney(snapshot.cost, lang)}`, dim: true }), kind: 'cost' })
  }
  return parts
}

/** The terminal line's parts (`status_style: line`). */
export function statusLineParts(snapshot, options, lang) {
  const parts = [statusPart(0, '', { text: t('status.name'), dim: true })]
  const glyph = statusGlyph(snapshot)
  if (snapshot.daemon === 'down') {
    parts.push(statusPart(0, STATUS_SEPARATOR, { text: `${glyph} ${t('status.daemon_down')}`, color: 'error' }))
    return parts
  }
  if (snapshot.backend === 'down') {
    parts.push(statusPart(0, STATUS_SEPARATOR, { text: `${glyph} ${t('status.down')}`, color: 'error' }))
  } else if (snapshot.backend === null) {
    parts.push(statusPart(0, STATUS_SEPARATOR, { text: `${glyph} ${t('status.no_data')}`, dim: true }))
  } else {
    const busy = snapshot.backend === 'busy'
    const words = snapshot.model
      ? t(busy ? 'status.busy_model' : 'status.ready_model', { model: snapshot.model })
      : t(busy ? 'status.busy' : 'status.ready')
    parts.push(statusPart(0, STATUS_SEPARATOR, { text: glyph, color: STATUS_COLOR[snapshot.backend] }, { text: ` ${words}` }))
    if (busy && snapshot.task) {
      parts.push(statusPart(1, STATUS_SEPARATOR, ...statusTaskPieces(snapshot.task)))
    }
  }
  parts.push(...statusFigures(snapshot, lang, STATUS_SEPARATOR))
  const mode = statusReadMode(options)
  if (mode) {
    parts.push(statusPart(5, STATUS_SEPARATOR, { text: t(`status.reads_${mode}`), dim: true }))
  }
  return parts
}

/** The chip of the bar: its text and its props. */
function statusChip(snapshot) {
  const glyph = statusGlyph(snapshot)
  if (snapshot.daemon === 'down') {
    return { text: ` ${glyph} ${t('status.chip_daemon_down')} `, color: 'error' }
  }
  if (snapshot.backend === null) {
    return { text: ` ${glyph} ${t('status.chip_no_data')} `, dim: true }
  }
  return { text: ` ${glyph} ${t(`status.chip_${snapshot.backend}`)} `, color: STATUS_COLOR[snapshot.backend] }
}

/** The bar's left parts (`status_style: bar`) and its read mode, for the right side. */
export function statusBarParts(snapshot, options, lang) {
  const parts = [statusPart(0, '', { ...statusChip(snapshot), inverse: true, bold: true })]
  if (snapshot.daemon === 'down') {
    return { parts, right: null }
  }
  if (snapshot.model && snapshot.backend !== 'down') {
    parts.push({ ...statusPart(1, ' ', { text: snapshot.model, dim: true }), kind: 'model' })
  }
  if (snapshot.backend === 'busy' && snapshot.task) {
    parts.push({ ...statusPart(1, STATUS_SEPARATOR, ...statusTaskPieces(snapshot.task)), kind: 'task' })
  }
  parts.push(...statusFigures(snapshot, lang, STATUS_SEPARATOR))
  const mode = statusReadMode(options)
  const right = mode ? statusPart(5, ' ', { text: t(`status.reads_${mode}`), dim: true }) : null
  return { parts, right }
}

function statusWidth(list) {
  return list.reduce((sum, part) => sum + part.joint.length + part.pieces.reduce((n, piece) => n + piece.text.length, 0), 0)
}

/**
 * The parts that fit in `columns` cells, dropping the highest ranks first (rank 0 always stays).
 * `extra` counts the cells the tree adds around them (padding).
 */
export function statusFit(parts, columns, extra = 0) {
  let kept = parts
  while (statusWidth(kept) + extra > columns) {
    const rank = Math.max(...kept.map(part => part.rank))
    if (rank === 0) {
      break
    }
    kept = kept.filter(part => part.rank !== rank)
  }
  return kept
}

function statusTextProps(piece) {
  const props = { wrap: 'truncate-end' }
  for (const key of ['color', 'bold', 'inverse']) {
    if (piece[key] !== undefined) {
      props[key] = piece[key]
    }
  }
  if (piece.dim) {
    props.dimColor = true
  }
  return props
}

/** The Texts of these parts in a row: each joint dim, each piece with its own props. */
function statusTexts(Text, parts) {
  const children = []
  for (const part of parts) {
    if (part.joint) {
      children.push(h(Text, { dimColor: true, wrap: 'truncate-end' }, part.joint))
    }
    for (const piece of part.pieces) {
      children.push(h(Text, statusTextProps(piece), piece.text))
    }
  }
  return children
}

/** Terminal, `line`: a dim rule over the line, and no empty row between them. */
function statusLineTree($, e, snapshot, options, columns) {
  const { Box, Text } = $.ui.resolve(e)
  const parts = statusFit(statusLineParts(snapshot, options, language()), columns)
  const rule = h(Text, { dimColor: true, wrap: 'truncate-end' }, STATUS_RULE.repeat(Math.max(1, columns)))
  return h(Box, { flexDirection: 'column' }, rule, h(Box, { flexDirection: 'row' }, ...statusTexts(Text, parts)))
}

/** Terminal, `bar`: one row with the message background, the chip and figures left, reads right. */
function statusBarTree($, e, snapshot, options, columns) {
  const { Box, Text } = $.ui.resolve(e)
  const { parts, right } = statusBarParts(snapshot, options, language())
  // The right side fits like any other part (its joint is the gap); 2 cells of padding.
  const kept = statusFit(right ? [...parts, right] : parts, columns, 2)
  const keptRight = right && kept.includes(right) ? right : null
  const left = h(Box, { flexDirection: 'row', flexShrink: 1 }, ...statusTexts(Text, kept.filter(part => part !== right)))
  const children = [left]
  if (keptRight) {
    children.push(h(Text, statusTextProps(keptRight.pieces[0]), keptRight.pieces[0].text))
  }
  return h(
    Box,
    {
      flexDirection: 'row',
      justifyContent: 'space-between',
      backgroundColor: 'userMessageBackground',
      paddingX: 1,
      width: '100%',
    },
    ...children,
  )
}

/** Desktop and the other remote surfaces: one native row with a pill. */
function statusDesktopTree($, e, snapshot, options, columns) {
  const { Box, Text, Link } = $.ui.resolve(e)
  // Spacing by step names where the surface takes them (desktop, mobile), in cells elsewhere.
  const named = e.surface === 'desktop' || e.surface === 'mobile'
  const gap = named ? 'sm' : 1
  const small = named ? 'xs' : 1
  const lang = language()
  const note = { size: 'footnote', wrap: 'truncate-end' }
  const glyph = statusGlyph(snapshot)
  let word
  let color
  if (snapshot.daemon === 'down') {
    word = t('status.pill_daemon_down')
    color = 'error'
  } else if (snapshot.backend === null) {
    word = t('status.pill_no_data')
    color = null
  } else {
    word = t(`status.pill_${snapshot.backend}`)
    color = STATUS_COLOR[snapshot.backend]
  }
  const pillProps = { flexDirection: 'row', borderStyle: 'round', paddingX: small }
  const dotProps = { ...note }
  const wordProps = { ...note, weight: 'medium' }
  if (color) {
    pillProps.borderColor = color
    dotProps.color = color
    if (color === 'error') {
      wordProps.color = color
    }
  } else {
    pillProps.borderDimColor = true
    dotProps.dimColor = true
    wordProps.dimColor = true
  }
  const name = h(Link, { href: STATUS_PANEL }, h(Text, { ...note, weight: 'medium', dimColor: true }, t('status.name')))
  const pill = h(Box, pillProps, h(Text, dotProps, glyph), h(Text, wordProps, ` ${word}`))
  const left = [name, pill]
  let right = null
  if (snapshot.daemon !== 'down') {
    // The same parts as the terminal decide what fits; each becomes its own element here.
    const { parts, right: reads } = statusBarParts(snapshot, options, lang)
    const kept = statusFit(reads ? [...parts.slice(1), reads] : parts.slice(1), columns, 4 + word.length + t('status.name').length)
    for (const part of kept) {
      if (part === reads) {
        right = h(Text, { size: 'caption', dimColor: true, wrap: 'truncate-end' }, t(`status.reads_${statusReadMode(options)}_title`))
        continue
      }
      left.push(...statusDesktopPart(Box, Text, part, note, small))
    }
  }
  const row = h(Box, { flexDirection: 'row', alignItems: 'center', gap, flexShrink: 1 }, ...left)
  return h(Box, { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', width: '100%' }, row, ...(right ? [right] : []))
}

/** One part of the bar as Desktop elements: the model, the tool at work, or a figure. */
function statusDesktopPart(Box, Text, part, note, small) {
  if (part.kind === 'model') {
    return [h(Text, { ...note, dimColor: true }, part.pieces[0].text)]
  }
  if (part.kind === 'task') {
    // The tool at work: its name in mono, then how long it has run (and how many more), dim.
    const out = []
    const rest = []
    for (const piece of part.pieces) {
      if (piece.dim) {
        rest.push(piece.text.trim())
      } else {
        out.push(h(Text, { ...note, mono: true }, piece.text))
      }
    }
    out.push(h(Text, { ...note, dimColor: true, tabular: true }, rest.join(' ')))
    return out
  }
  if (part.kind === 'empty') {
    return [h(Text, { ...note, dimColor: true }, t('status.empty_title'))]
  }
  if (part.kind === 'cost') {
    return [h(Text, { ...note, dimColor: true, tabular: true }, part.pieces[0].text)]
  }
  // A figure: the number semibold and tabular, its label dim (`delegaciones ·` before the next one).
  const label = part.kind === 'calls' ? `${part.pieces[1].text.trim()}${STATUS_SEPARATOR.trimEnd()}` : part.pieces[1].text.trim()
  const children = [
    h(Text, { ...note, weight: 'semibold', tabular: true }, part.pieces[0].text),
    h(Text, { ...note, dimColor: true }, label),
  ]
  return [h(Box, { flexDirection: 'row', gap: small }, ...children)]
}

/** The session id the stats are asked for, or `null` (no token, no valid id): no band. */
async function statusSession($) {
  if ((await token($)) === null) {
    return null
  }
  let sessionId
  try {
    sessionId = String(await $.session.id())
  } catch {
    return null
  }
  return STATUS_SESSION_ID.test(sessionId) ? sessionId : null
}

function statusBody(answer) {
  return answer && answer.ok && answer.json ? answer.json : null
}

/**
 * Asks the daemon and keeps the answer in `view`: the three answers when `full`, else the backend
 * and the inflight list alone, with the stats it kept. `false` without a token or a session id.
 */
async function statusRead($, view, full) {
  const sessionId = await statusSession($)
  if (sessionId === null) {
    return false
  }
  const lang = language()
  const asks = [daemonFetch($, `/api/backend?lang=${lang}`), daemonFetch($, '/api/inflight')]
  if (full) {
    asks.push(daemonFetch($, `/api/stats?session=${encodeURIComponent(sessionId)}&lang=${lang}`))
  }
  const [backend, inflight, stats] = await Promise.all(asks)
  view.backend = statusBody(backend)
  view.inflight = statusBody(inflight)
  if (full) {
    view.stats = statusBody(stats)
  }
  return true
}

/** Redraws the band if the snapshot changed, and sets the timer's pace for it. */
async function statusApply($, view) {
  const snapshot = statusSnapshot(view.stats, view.backend, view.inflight)
  if (JSON.stringify(snapshot) !== JSON.stringify(view.snapshot)) {
    view.snapshot = snapshot
    await $.ui.invalidate('ui.render')
  }
  const hot = snapshot.backend === 'busy' || snapshot.loading === true
  statusArm($, view, hot ? STATUS_HOT_MS : STATUS_COLD_MS)
}

/** Asks everything (after a turn, after a call to a local-delegate tool). */
async function statusRefresh($, view) {
  if (await statusRead($, view, true)) {
    await statusApply($, view)
  } else {
    statusStop(view)
  }
}

/** One beat of the timer: the quick answers, and the stats too when the last delegation ended. */
async function statusTick($, view) {
  if (view.polling || view.stopped) {
    return
  }
  view.polling = true
  try {
    const wasBusy = view.snapshot !== null && view.snapshot.backend === 'busy'
    if (!(await statusRead($, view, false))) {
      statusStop(view)
      return
    }
    const quiet = !view.inflight || !(statusNumber(view.inflight.count) > 0)
    // Both quick answers missing means the daemon itself is gone: ask the stats to know it.
    if ((wasBusy && quiet) || (view.backend === null && view.inflight === null)) {
      await statusRead($, view, true)
    }
    await statusApply($, view)
  } catch {
    // The band is a courtesy: a failed beat waits for the next one.
  } finally {
    view.polling = false
  }
}

/** Runs the timer at `period`, replacing one at another pace. */
function statusArm($, view, period) {
  if (view.stopped || (view.timer && view.period === period)) {
    return
  }
  statusCancel(view)
  view.period = period
  view.timer = $.clock.every(period, () => statusTick($, view))
}

function statusCancel(view) {
  if (view.timer) {
    try {
      view.timer.cancel()
    } catch {
      // A timer the engine already dropped.
    }
  }
  view.timer = null
  view.period = 0
}

function statusStop(view) {
  statusCancel(view)
}

/** Registers the refreshes, the timer's end and the hook that draws the band. */
export function register(on, options) {
  if (options[STATUS_SWITCH] === false) {
    return
  }
  // The last answers and snapshot; a reload starts empty and the next measurement fills it.
  const view = {
    snapshot: null,
    stats: null,
    backend: null,
    inflight: null,
    timer: null,
    period: 0,
    polling: false,
    stopped: false,
  }
  on('session.measure', async ($, e, next) => {
    const measured = await next(e)
    try {
      await statusRefresh($, view)
    } catch {
      // The band is a courtesy: a failure here must never reach the measurement.
    }
    return measured
  })
  on('tool.call', { tool: STATUS_TOOL }, async ($, e, next) => {
    // A delegation starts: the quick pace now, not at the next beat of the slow one.
    if (view.snapshot !== null) {
      try {
        statusArm($, view, STATUS_HOT_MS)
      } catch {
        // Never in the way of the call.
      }
    }
    const result = await next(e)
    try {
      await statusRefresh($, view)
    } catch {
      // Never in the way of the call.
    }
    return result
  })
  on('session.end', async ($, e, next) => {
    view.stopped = true
    statusStop(view)
    return next(e)
  })
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (view.snapshot === null || e.props.hasSurvey) {
      return next(e)
    }
    const columns = e.props.bodyColumns
    if (e.surface !== 'terminal') {
      return statusDesktopTree($, e, view.snapshot, options, columns)
    }
    if (options[STATUS_STYLE] === 'line') {
      return statusLineTree($, e, view.snapshot, options, columns)
    }
    return statusBarTree($, e, view.snapshot, options, columns)
  })
}
