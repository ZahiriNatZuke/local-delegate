// REQ-017 (SDD claude-plugin-and-mods, F3-status): what local-delegate is doing in this session, in a
// band of its own above the prompt.
// Run with `claude plugin test <plugin>` after `scripts/build_mod.py` (it builds register.js).
//
// Each test goes through the real plugin: it raises `session.measure` on the engine's `$`, and the
// hooks beneath stand for the engine (`session.id`, `http.fetch`, `ui.status`, `ui.render`). Then a
// surface draws the `AbovePrompt` band and the test reads what the mod put there.
//
// Why a band and not `$.ui.status`: the engine (2.1.308) pins a `$.ui.status` text as a notice with
// no color, and draws every pinned notice as `⚠ <plugin>: <text>` in the theme's `warning` color.
// The entry looked like an alarm. The band takes a tree, so the mod chooses its own colors.
import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

const LD_BIN = 'C:/tools/local-delegate/python.exe'
const TOKEN = 'tok-5e1d-never-in-output'
const SESSION = 'sess-f3'

type Daemon = {
  stats?: () => any
  backend?: () => any
  inflight?: () => any
}

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

function json(body: unknown, status = 200) {
  return { status, ok: status >= 200 && status < 300, headers: {}, text: JSON.stringify(body) }
}

function stats(calls: number, net: number, estimate: number | null = null) {
  return json({
    total: { calls },
    tokens_context_net: net,
    cost: { figure: estimate === null ? null : { low_bound: estimate / 2, estimate } },
  })
}

function backend(available: boolean, running: { model: string; state: string }[] = []) {
  return json({ available, running, running_ok: available, models: [] })
}

function inflight(count: number) {
  return json({ inflight: [], count })
}

const UP: Daemon = {
  stats: () => stats(3, 12345, 0.18),
  backend: () => backend(true, [{ model: 'qwen3-8b', state: 'ready' }]),
  inflight: () => inflight(0),
}

function engine(on: On, variables: Record<string, string>, daemon: () => Daemon): Seen {
  const seen: Seen = { statuses: [], fetches: [] }
  mock.env(on, variables)
  // The engine's own answer to a measurement: it echoes what changed.
  on('session.measure', (_$, e) => ({ changed: e.changed }))
  on('session.id', () => ({ value: SESSION }))
  on('http.fetch', async (_$, e) => {
    seen.fetches.push({ url: e.url, auth: e.init?.headers?.Authorization })
    const path = new URL(e.url).pathname
    const answer = daemon()[path.replace('/api/', '') as keyof Daemon]
    if (!answer) {
      throw new Error('ECONNREFUSED')
    }
    return { value: await answer() }
  })
  on('ui.status', (_$, e) => {
    seen.statuses.push(e.text)
    return { value: undefined }
  })
  // Beneath the mod, the engine draws its own band (here, one word) when the mod passes.
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return h(Text, null, 'engine')
  })
  return seen
}

function band(bodyColumns = 120, hasSurvey = false) {
  return {
    plugin: 'local-delegate',
    component: 'AbovePrompt',
    requestId: 'above-prompt',
    surface: 'terminal',
    props: {
      hasSurvey,
      isWorking: false,
      maxRows: 10,
      bodyColumns,
      scroll: { offset: 0, bodyRows: 9 },
      view: {},
    },
  } as any
}

/** What the band shows, read as one line, and each Text as `{ text, color }`. */
async function drawn($: any, props = band()) {
  const ui = await $.ui.mount(props)
  const texts = (await ui.findAll({ type: 'Text' })).map((t: any) => ({ text: t.text, color: t.props.color }))
  await ui.unmount()
  return { line: texts.map((t: any) => t.text).join(''), texts }
}

function colorOf(texts: { text: string; color: unknown }[], glyph: string) {
  return texts.find(t => t.text.includes(glyph))?.color
}

test('shows backend, delegations and savings, never the quota nor a warning', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput(42.4))
  const { line, texts } = await drawn($)
  expect(line).toBe('◆ local-delegate · ● qwen3-8b · 3 delegaciones · 12,3k tok ahorrados ≈ $0,18')
  expect(colorOf(texts, '●')).toBe('success')
  // The quota belongs to the person's own status line; the mod repeats none of it.
  expect(line.includes('42')).toBe(false)
  expect(line.includes('⚠')).toBe(false)
  // The `$.ui.status` entry is gone: the engine draws it with a warning sign.
  expect(seen.statuses).toEqual([])
  // This session's figures and the backend, asked of the daemon on loopback with the token.
  expect(seen.fetches.map(f => f.url).sort()).toEqual([
    'http://127.0.0.1:9393/api/backend?lang=es',
    'http://127.0.0.1:9393/api/inflight',
    `http://127.0.0.1:9393/api/stats?session=${SESSION}&lang=es`,
  ])
  expect(seen.fetches.every(f => f.auth === `Bearer ${TOKEN}`)).toBe(true)
  expect(line.includes(TOKEN)).toBe(false)
})

test('shows the band in English with the language option', { options: { ld_bin: LD_BIN, language: 'en' } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, stats: () => stats(1, 1500000, 2.5) }))
  await $.session.measure(measureInput(7))
  const { line } = await drawn($)
  expect(line).toBe('◆ local-delegate · ● qwen3-8b · 1 delegation · 1.5M tok saved ≈ $2.50')
})

test('an empty session says so instead of a zero', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, stats: () => stats(0, 0) }))
  await $.session.measure(measureInput(4))
  const { line, texts } = await drawn($)
  expect(line).toBe('◆ local-delegate · ● qwen3-8b · sin delegaciones aún')
  expect(line.includes('0 tok')).toBe(false)
  expect(texts.find(t => t.text.includes('sin delegaciones'))?.color).toBe('subtle')
})

test('a backend with nothing mounted is ready, without a model name', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, backend: () => backend(true, []) }))
  await $.session.measure(measureInput())
  const { line } = await drawn($)
  expect(line).toContain('· ● backend listo ·')
})

test('a busy backend shows the half dot in the warning color', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, inflight: () => inflight(2) }))
  await $.session.measure(measureInput())
  const { line, texts } = await drawn($)
  expect(line).toContain('· ◐ qwen3-8b ocupado ·')
  expect(colorOf(texts, '◐')).toBe('warning')
})

test('a backend that is down shows the empty dot in the error color', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, backend: () => backend(false) }))
  await $.session.measure(measureInput())
  const { line, texts } = await drawn($)
  expect(line).toContain('· ○ backend caído ·')
  expect(colorOf(texts, '○')).toBe('error')
})

test('says when the daemon stops answering', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  let up = true
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => (up ? UP : {}))
  // Guard: with the daemon up the band has the figures, so the change below is the daemon's doing.
  await $.session.measure(measureInput(10))
  expect((await drawn($)).line).toContain('3 delegaciones')
  up = false
  await $.session.measure(measureInput(11))
  const { line, texts } = await drawn($)
  expect(line).toBe('◆ local-delegate · ○ daemon sin respuesta')
  expect(colorOf(texts, '○')).toBe('error')
})

test('a refusal or a body that is not the stats reads as a daemon that does not answer', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  const answers = [json({ detail: 'no' }, 401), { status: 200, ok: true, headers: {}, text: '<html>' }, json({ total: {} })]
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, stats: () => answers.shift() }))
  for (let i = 0; i < 3; i++) {
    await $.session.measure(measureInput(5))
    expect((await drawn($)).line).toBe('◆ local-delegate · ○ daemon sin respuesta')
  }
})

test('says when the mod steers the reads', { options: { ld_bin: LD_BIN, read_mod_enabled: true } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput())
  expect((await drawn($)).line).toBe(
    '◆ local-delegate · ● qwen3-8b · 3 delegaciones · 12,3k tok ahorrados ≈ $0,18 · lectura guiada',
  )
})

test('a narrow band drops the least important parts first', { options: { ld_bin: LD_BIN, read_mod_enabled: true } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput())
  expect((await drawn($, band(60))).line).toBe('◆ local-delegate · ● qwen3-8b · 3 delegaciones')
  expect((await drawn($, band(36))).line).toBe('◆ local-delegate · ● qwen3-8b')
})

test('yields the band to a survey', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput())
  expect((await drawn($, band(120, true))).line).toBe('engine')
})

test('draws nothing without the token', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  const seen = engine(on, {}, () => UP)
  await $.session.measure(measureInput(50))
  expect((await drawn($)).line).toBe('engine')
  // No token, no request at all.
  expect(seen.fetches).toEqual([])
})

test('off_by_userconfig', { options: { ld_bin: LD_BIN, status_enabled: false } }, async ($, on) => {
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput(50))
  expect((await drawn($)).line).toBe('engine')
  expect(seen.statuses).toEqual([])
  expect(seen.fetches).toEqual([])
})
