// REQ-017 (SDD claude-plugin-and-mods, F3-status): the session's quota and savings in the status line.
// Run with `claude plugin test <plugin>` after `scripts/build_mod.py` (it builds register.js).
//
// Each test goes through the real plugin: it raises `session.measure` on the engine's `$`, and the
// hooks beneath stand for the engine (`session.id`, `http.fetch`, `ui.status`).
import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

const LD_BIN = 'C:/tools/local-delegate/python.exe'
const TOKEN = 'tok-5e1d-never-in-output'
const SESSION = 'sess-f3'

type Seen = { statuses: (string | undefined)[]; fetches: { url: string; auth: unknown }[] }

function measureInput(percentUsed?: number) {
  return {
    context: { window: 200000, tokens: 50000, percent: 25 },
    rateLimits:
      percentUsed === undefined
        ? []
        : [
            { kind: 'five_hour', percentUsed },
            { kind: 'seven_day', percentUsed: 80 },
          ],
    changed: ['context', 'rateLimits'],
  } as any
}

function engine(on: On, variables: Record<string, string>, daemon: () => Promise<any> | any): Seen {
  const seen: Seen = { statuses: [], fetches: [] }
  mock.env(on, variables)
  // The engine's own answer to a measurement: it echoes what changed.
  on('session.measure', (_$, e) => ({ changed: e.changed }))
  on('session.id', () => ({ value: SESSION }))
  on('http.fetch', async (_$, e) => {
    seen.fetches.push({ url: e.url, auth: e.init?.headers?.Authorization })
    return { value: await daemon() }
  })
  on('ui.status', (_$, e) => {
    seen.statuses.push(e.text)
    return { value: undefined }
  })
  return seen
}

function stats(net: number) {
  return { status: 200, ok: true, headers: {}, text: JSON.stringify({ tokens_context_net: net, total: { calls: 3 } }) }
}

test('shows_quota_and_savings', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => stats(12345))
  await $.session.measure(measureInput(42.4))
  expect(seen.statuses).toEqual(['LD · cuota 5h 42% · ahorro 12,3k tok'])
  // The savings are those of THIS session, asked of the daemon on loopback with the token.
  expect(seen.fetches).toEqual([
    { url: `http://127.0.0.1:9393/api/stats?session=${SESSION}&lang=es`, auth: `Bearer ${TOKEN}` },
  ])
  // Without a five-hour window (off a subscription), only the savings.
  await $.session.measure(measureInput())
  expect(seen.statuses[1]).toBe('LD · ahorro 12,3k tok')
  expect(seen.statuses.join(' ').includes(TOKEN)).toBe(false)
})

test('shows the entry in English with the language option', { options: { ld_bin: LD_BIN, language: 'en' } }, async ($, on) => {
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => stats(1500000))
  await $.session.measure(measureInput(7))
  expect(seen.statuses).toEqual(['LD · 5h quota 7% · saved 1.5M tok'])
})

test('hides_when_daemon_down', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  let up = true
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => {
    if (!up) {
      throw new Error('ECONNREFUSED')
    }
    return stats(850)
  })
  // Guard: with the daemon up the entry is there, so the clearing below is the daemon's doing.
  await $.session.measure(measureInput(10))
  expect(seen.statuses).toEqual(['LD · cuota 5h 10% · ahorro 850 tok'])
  up = false
  await $.session.measure(measureInput(11))
  expect(seen.statuses).toEqual(['LD · cuota 5h 10% · ahorro 850 tok', undefined])
})

test('hides when the daemon refuses or answers something else', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  const answers = [
    { status: 401, ok: false, headers: {}, text: '{"detail":"no"}' },
    { status: 200, ok: true, headers: {}, text: '<html>' },
    { status: 200, ok: true, headers: {}, text: '{"total":{}}' },
  ]
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => answers.shift())
  for (let i = 0; i < 3; i++) {
    await $.session.measure(measureInput(5))
  }
  expect(seen.fetches.length).toBe(3)
  expect(seen.statuses).toEqual([undefined, undefined, undefined])
})

test('hides_without_token', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  const seen = engine(on, {}, () => stats(999))
  await $.session.measure(measureInput(50))
  expect(seen.statuses).toEqual([undefined])
  // No token, no request at all.
  expect(seen.fetches).toEqual([])
})

test('off_by_userconfig', { options: { ld_bin: LD_BIN, status_enabled: false } }, async ($, on) => {
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => stats(999))
  await $.session.measure(measureInput(50))
  expect(seen.statuses).toEqual([])
  expect(seen.fetches).toEqual([])
})
