// mod/status.js — the session's quota and savings in the status line (REQ-017; SDD
// claude-plugin-and-mods, batch F3-status).
//
// On each `session.measure` (after every main-thread turn, and when a rate-limit window moves a
// whole point) the piece writes one short entry with `$.ui.status`:
//   - the quota: `percentUsed` of the `five_hour` window that the engine hands the event. It is the
//     subscription's own figure for the window the session runs in; the piece computes nothing.
//   - the savings: `tokens_context_net` of `/api/stats?session=<id>`, the panel's KPI (gross saved
//     minus what the tools returned) counted only over this session's delegations.
// No daemon, no token, or an answer that is not the stats: the entry is cleared, never an error.
// Switched off by the `status_enabled` option (`register.js` does not call `register` then).
//
// A piece of the mod: `scripts/build_mod.py` pastes it into `register.js`, which calls its
// `register` inside its own `try`. It only declares at load, so loading it cannot throw. Its
// top-level names carry `status`, so they cannot clash with another piece's.

import { daemonFetch, language, t, token } from './common.js'

export const STATUS_SWITCH = 'status_enabled'
// The rate-limit window shown: the five-hour one, the window a working session spends.
export const STATUS_QUOTA_WINDOW = 'five_hour'

const STATUS_SESSION_ID = /^[A-Za-z0-9_-]{1,128}$/

/** `percentUsed` of the five-hour window, rounded to a whole point, or `null`. */
export function statusQuota(rateLimits) {
  if (!Array.isArray(rateLimits)) {
    return null
  }
  const window = rateLimits.find(limit => limit && limit.kind === STATUS_QUOTA_WINDOW)
  if (!window || typeof window.percentUsed !== 'number' || !Number.isFinite(window.percentUsed)) {
    return null
  }
  return Math.round(window.percentUsed)
}

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

/**
 * The text of the entry for this measurement, or `undefined` to clear it.
 *
 * `undefined` without the token (no request is made), without a session id, or when the daemon
 * does not answer the stats with a 2xx and a number.
 */
export async function statusText($, e) {
  if ((await token($)) === null) {
    return undefined
  }
  let sessionId
  try {
    sessionId = String(await $.session.id())
  } catch {
    return undefined
  }
  if (!STATUS_SESSION_ID.test(sessionId)) {
    return undefined
  }
  const lang = language()
  const answer = await daemonFetch($, `/api/stats?session=${encodeURIComponent(sessionId)}&lang=${lang}`)
  if (!answer || !answer.ok || !answer.json) {
    return undefined
  }
  const net = answer.json.tokens_context_net
  if (typeof net !== 'number' || !Number.isFinite(net)) {
    return undefined
  }
  const saved = statusTokens(net, lang)
  const quota = statusQuota(e && e.rateLimits)
  return quota === null ? t('status.saved_only', { saved }) : t('status.line', { quota, saved })
}

/** Registers the `session.measure` hook that keeps the entry up to date. */
export function register(on, options) {
  if (options[STATUS_SWITCH] === false) {
    return
  }
  on('session.measure', async ($, e, next) => {
    const measured = await next(e)
    try {
      await $.ui.status(await statusText($, e))
    } catch {
      // The status line is a courtesy: a failure here must never reach the measurement.
    }
    return measured
  })
}
