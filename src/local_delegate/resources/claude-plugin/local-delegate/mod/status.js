// mod/status.js — what local-delegate is doing in this session, in a band above the prompt (REQ-017;
// SDD claude-plugin-and-mods, batch F3-status).
//
// On each `session.measure` (after every main-thread turn) the piece asks the daemon three things
// and keeps the answer for the band:
//   - `/api/stats?session=<id>`: this session's delegations (`total.calls`), the context they saved
//     (`tokens_context_net`, the panel's KPI) and, when `recompute-cost` left its figures, what that
//     is worth at API prices (`cost.figure.estimate`).
//   - `/api/backend`: whether the local backend answers and which model it has mounted.
//   - `/api/inflight`: whether it is working on a delegation right now.
// The band draws `◆ local-delegate · ● <model> · 3 delegaciones · 12,3k tok ahorrados ≈ $0,18`, the
// dot green, amber or red as the backend is ready, busy or down, and drops the least important
// parts first when the band is narrow. A dim `─` rule as wide as the band goes above that line, so
// the band does not read as the last line of the chat, and one empty row between them balances the
// row the engine keeps under the band (its notices on the right), so the line sits centred between
// the rule and the prompt's own line. The Claude quota is NOT here: the person's own status line
// shows it.
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

import { daemonFetch, language, readModOn, t, token } from './common.js'

export const STATUS_SWITCH = 'status_enabled'

const STATUS_SESSION_ID = /^[A-Za-z0-9_-]{1,128}$/
const STATUS_MODEL_WIDTH = 28
const STATUS_SEPARATOR = ' · '
const STATUS_RULE = '─'

// The glyphs carry the state on their own, for a terminal without color.
const STATUS_GLYPH = { mark: '◆', ready: '●', busy: '◐', down: '○' }

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

/** The mounted model's name, cut to a few characters, or `null`. */
function statusModel(backend) {
  const running = backend && Array.isArray(backend.running) ? backend.running : []
  const entry = running.find(item => item && item.state === 'ready') || running[0]
  const name = entry && typeof entry.model === 'string' ? entry.model.trim() : ''
  if (!name) {
    return null
  }
  return name.length > STATUS_MODEL_WIDTH ? `${name.slice(0, STATUS_MODEL_WIDTH - 1)}…` : name
}

/**
 * What the band shows, from the daemon's three answers (each a parsed body or `null`).
 *
 * `{ daemon: 'down' }` when the stats are not there; otherwise the figures and the backend's state
 * (`null` when `/api/backend` did not answer).
 */
export function statusSnapshot(stats, backend, inflight) {
  const net = stats ? statusNumber(stats.tokens_context_net) : null
  if (net === null) {
    return { daemon: 'down' }
  }
  const calls = statusNumber(stats.total && stats.total.calls) ?? 0
  const figure = stats.cost && stats.cost.figure
  const cost = figure ? statusNumber(figure.estimate) : null
  let state = null
  if (backend && typeof backend.available === 'boolean') {
    if (!backend.available) {
      state = 'down'
    } else {
      state = inflight && statusNumber(inflight.count) > 0 ? 'busy' : 'ready'
    }
  }
  return { daemon: 'up', calls, net, cost, backend: state, model: statusModel(backend) }
}

/**
 * The parts of the band in order, each `{ text, color?, joint, rank }`: `joint` goes before it
 * (`' · '` or `' '`), `rank` says which go first when the band is narrow (higher goes first).
 */
export function statusParts(snapshot, options, lang) {
  const parts = [{ text: STATUS_GLYPH.mark, color: 'suggestion', joint: '', rank: 0 }]
  parts.push({ text: ` ${t('status.name')}`, joint: '', rank: 0 })
  if (snapshot.daemon === 'down') {
    parts.push({ text: `${STATUS_GLYPH.down} ${t('status.daemon_down')}`, color: 'error', joint: STATUS_SEPARATOR, rank: 0 })
    return parts
  }
  if (snapshot.backend === 'down') {
    parts.push({ text: `${STATUS_GLYPH.down} ${t('status.backend_down')}`, color: 'error', joint: STATUS_SEPARATOR, rank: 0 })
  } else if (snapshot.backend === 'busy') {
    const text = snapshot.model ? t('status.backend_busy_model', { model: snapshot.model }) : t('status.backend_busy')
    parts.push({ text: `${STATUS_GLYPH.busy} ${text}`, color: 'warning', joint: STATUS_SEPARATOR, rank: 0 })
  } else if (snapshot.backend === 'ready') {
    parts.push({
      text: `${STATUS_GLYPH.ready} ${snapshot.model || t('status.backend_ready')}`,
      color: 'success',
      joint: STATUS_SEPARATOR,
      rank: 0,
    })
  }
  if (snapshot.calls <= 0) {
    parts.push({ text: t('status.empty'), color: 'subtle', joint: STATUS_SEPARATOR, rank: 1 })
  } else {
    const calls = snapshot.calls === 1 ? t('status.calls_one') : t('status.calls', { n: snapshot.calls })
    parts.push({ text: calls, joint: STATUS_SEPARATOR, rank: 1 })
    parts.push({ text: t('status.saved', { saved: statusTokens(snapshot.net, lang) }), joint: STATUS_SEPARATOR, rank: 2 })
    if (snapshot.cost !== null && snapshot.cost >= 0.005) {
      parts.push({ text: `≈ ${statusMoney(snapshot.cost, lang)}`, color: 'subtle', joint: ' ', rank: 3 })
    }
  }
  if (readModOn(options)) {
    parts.push({ text: t('status.read_mod'), color: 'subtle', joint: STATUS_SEPARATOR, rank: 4 })
  }
  return parts
}

/** The parts that fit in `columns` cells, dropping the highest ranks first (rank 0 always stays). */
export function statusFit(parts, columns) {
  let kept = parts
  const width = list => list.reduce((sum, part) => sum + part.joint.length + part.text.length, 0)
  while (width(kept) > columns) {
    const rank = Math.max(...kept.map(part => part.rank))
    if (rank === 0) {
      break
    }
    kept = kept.filter(part => part.rank !== rank)
  }
  return kept
}

/**
 * The band's tree for these parts: a dim rule as wide as the band, then one row of Texts with the
 * joints dim, one empty row between them. The rule sets the band apart from the last line of the
 * chat, the way the engine's own `─` lines frame the prompt; the empty row matches the engine's row
 * under the band (its notices on the right), so the line has the same air above and below.
 */
function statusTree($, e, parts, columns) {
  const { Box, Text } = $.ui.resolve(e)
  const children = []
  for (const part of parts) {
    if (part.joint) {
      children.push(h(Text, { dimColor: true, wrap: 'truncate-end' }, part.joint))
    }
    const props = { wrap: 'truncate-end' }
    if (part.color) {
      props.color = part.color
    }
    children.push(h(Text, props, part.text))
  }
  const rule = h(Text, { dimColor: true, wrap: 'truncate-end' }, STATUS_RULE.repeat(Math.max(1, columns)))
  return h(Box, { flexDirection: 'column' }, rule, h(Box, { flexDirection: 'row', marginTop: 1 }, ...children))
}

/** What the daemon says for this session, or `null` (no token, no session id): no band. */
async function statusRead($) {
  if ((await token($)) === null) {
    return null
  }
  let sessionId
  try {
    sessionId = String(await $.session.id())
  } catch {
    return null
  }
  if (!STATUS_SESSION_ID.test(sessionId)) {
    return null
  }
  const lang = language()
  const [stats, backend, inflight] = await Promise.all([
    daemonFetch($, `/api/stats?session=${encodeURIComponent(sessionId)}&lang=${lang}`),
    daemonFetch($, `/api/backend?lang=${lang}`),
    daemonFetch($, '/api/inflight'),
  ])
  const body = answer => (answer && answer.ok && answer.json ? answer.json : null)
  return statusSnapshot(body(stats), body(backend), body(inflight))
}

/** Registers the measurement that refreshes the band and the hook that draws it. */
export function register(on, options) {
  if (options[STATUS_SWITCH] === false) {
    return
  }
  // The last snapshot; a reload starts empty and the next measurement fills it.
  const view = { snapshot: null }
  on('session.measure', async ($, e, next) => {
    const measured = await next(e)
    try {
      const snapshot = await statusRead($)
      if (JSON.stringify(snapshot) !== JSON.stringify(view.snapshot)) {
        view.snapshot = snapshot
        await $.ui.invalidate('ui.render')
      }
    } catch {
      // The band is a courtesy: a failure here must never reach the measurement.
    }
    return measured
  })
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (view.snapshot === null || e.props.hasSurvey) {
      return next(e)
    }
    const parts = statusParts(view.snapshot, options, language())
    const columns = e.props.bodyColumns
    return statusTree($, e, statusFit(parts, columns), columns)
  })
}
