// REQ-017 (SDD claude-plugin-and-mods, F3-status and F4-band): what local-delegate is doing in this
// session, in a band of its own above the prompt.
// Run with `claude plugin test <plugin>` after `scripts/build_mod.py` (it builds register.js).
//
// Each test goes through the real plugin: it raises `session.measure` (or a tool call, or the mocked
// clock) on the engine's `$`, and the hooks beneath stand for the engine (`session.id`, `http.fetch`,
// `ui.status`, `ui.invalidate`, `ui.render`). Then a surface draws the `AbovePrompt` band and the test
// reads what the mod put there.
//
// F4-band: each surface has its own design. The terminal draws a bar with a background and a state
// chip (`status_style: bar`, the default) or a dim rule over one plain line (`line`); Claude Desktop
// (any other surface) draws one native row with a round-bordered pill. Neither leaves an empty row:
// the person asked for the band without the air above and below it.
//
// Why a band and not `$.ui.status`: the engine (2.1.308) pins a `$.ui.status` text as a notice with
// no color, and draws every pinned notice as `⚠ <plugin>: <text>` in the theme's `warning` color.
import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

const LD_BIN = 'C:/tools/local-delegate/python.exe'
const TOKEN = 'tok-5e1d-never-in-output'
const SESSION = 'sess-f3'
const PANEL = 'http://localhost:9393'

type Daemon = {
  stats?: () => any
  backend?: () => any
  inflight?: () => any
}

type Seen = {
  statuses: (string | undefined)[]
  fetches: { url: string; auth: unknown }[]
  invalidations: number
  clock: any
}

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

/** One delegation in flight, as `/api/inflight` lists it (`server.inflight_snapshot`). */
function task(tool: string | undefined, elapsed: number, model = 'qwen3-8b') {
  return { id: `${tool}-${elapsed}`, tool, model, source: 'mcp', chars_in: 9000, backend: 'local', elapsed_s: elapsed }
}

function inflight(items: any[] = []) {
  return json({ inflight: items, count: items.length, last_event_ts: null, last_event: null })
}

const UP: Daemon = {
  stats: () => stats(3, 12345, 0.18),
  backend: () => backend(true, [{ model: 'qwen3-8b', state: 'ready' }]),
  inflight: () => inflight(),
}

const BUSY: Daemon = { ...UP, inflight: () => inflight([task('local_summarize', 4.2)]) }

function engine(on: On, variables: Record<string, string>, daemon: () => Daemon): Seen {
  const seen: Seen = { statuses: [], fetches: [], invalidations: 0, clock: mock.clock(on) }
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
  on('ui.invalidate', () => {
    seen.invalidations += 1
    return { value: undefined }
  })
  // Beneath the mod, the engine draws its own band (here, one word) when the mod passes.
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return h(Text, null, 'engine')
  })
  return seen
}

function band(bodyColumns = 120, hasSurvey = false, surface = 'terminal') {
  return {
    plugin: 'local-delegate',
    component: 'AbovePrompt',
    requestId: 'above-prompt',
    surface,
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

const desktop = (columns = 160) => band(columns, false, 'desktop')

/** Every element the band drew, in order, with its type, its text and its props. */
async function drawnAll($: any, props = band()) {
  const ui = await $.ui.mount(props)
  const pick = async (type: string) =>
    (await ui.findAll({ type })).map((n: any) => ({ type, text: n.text as string, props: n.props }))
  const texts = await pick('Text')
  const boxes = await pick('Box')
  const links = await pick('Link')
  await ui.unmount()
  return { texts, boxes, links }
}

/** The terminal bar: its own Box, the chip, the left side read as one string and the right side. */
async function bar($: any, props = band()) {
  const { texts, boxes } = await drawnAll($, props)
  const outer = boxes[0]
  const left = boxes[1]
  const chip = texts[0]
  const right = texts.find((t: any) => /^(lecturas|reads):/.test(t.text))
  return { outer, left: left?.text ?? texts.map((t: any) => t.text).join(''), chip, right, texts, boxes }
}

/** The terminal line: the rule (dim, or `undefined`), the line read as one string and its Texts. */
async function line($: any, props = band()) {
  const { texts, boxes } = await drawnAll($, props)
  const rule = /^─+$/.test(texts[0]?.text ?? '') ? texts[0] : undefined
  const rest = rule ? texts.slice(1) : texts
  return { rule, line: rest.map((t: any) => t.text).join(''), texts: rest, boxes }
}

/**
 * Guard against the air the person asked to drop: no Box keeps a margin or padding above or below,
 * and no Text is a blank row.
 */
function expectNoEmptyRows(boxes: any[], texts: any[]) {
  for (const box of boxes) {
    for (const key of ['marginTop', 'marginBottom', 'marginY', 'paddingTop', 'paddingBottom', 'paddingY', 'margin', 'padding']) {
      expect([undefined, 0]).toContain(box.props[key])
    }
  }
  // A joint of one space is a Text of its own; an empty Text would be a row of nothing.
  expect(texts.every((t: any) => t.text !== '')).toBe(true)
}

function colorOf(texts: { text: string; props: any }[], glyph: string) {
  return texts.find(t => t.text.includes(glyph))?.props.color
}

const QUIET = { ld_bin: LD_BIN, read_mod_enabled: false }
const LINE = { ld_bin: LD_BIN, read_mod_enabled: false, status_style: 'line' }

// --- terminal, bar (the default) ------------------------------------------------------------------

test('bar: one row with a background and a state chip, never the quota nor a warning', { options: QUIET }, async ($, on) => {
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput(42.4))
  const { outer, left, chip, texts, boxes } = await bar($)
  expect(outer.props).toMatchObject({
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: 'userMessageBackground',
    paddingX: 1,
  })
  expect(chip.text).toBe(' ● LISTO ')
  expect(chip.props).toMatchObject({ inverse: true, bold: true, color: 'success' })
  expect(left).toBe(' ● LISTO  qwen3-8b · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
  // Two tones: the model and the labels dim, the figures bold.
  expect(texts.find((t: any) => t.text === 'qwen3-8b')?.props.dimColor).toBe(true)
  expect(texts.find((t: any) => t.text === '3')?.props.bold).toBe(true)
  expect(texts.find((t: any) => t.text === ' delegaciones')?.props.dimColor).toBe(true)
  // No rule and no empty row: the bar's own background sets it apart from the chat.
  expect(texts.some((t: any) => /^─+$/.test(t.text))).toBe(false)
  expectNoEmptyRows(boxes, texts)
  expect(left.includes('42')).toBe(false)
  expect(texts.some((t: any) => t.text.includes('⚠') || t.text.includes('◆'))).toBe(false)
  expect(seen.statuses).toEqual([])
  expect(seen.fetches.map(f => f.url).sort()).toEqual([
    'http://127.0.0.1:9393/api/backend?lang=es',
    'http://127.0.0.1:9393/api/inflight',
    `http://127.0.0.1:9393/api/stats?session=${SESSION}&lang=es`,
  ])
  expect(seen.fetches.every(f => f.auth === `Bearer ${TOKEN}`)).toBe(true)
  expect(texts.some((t: any) => t.text.includes(TOKEN))).toBe(false)
})

test('bar: the chip says each state in its color', { options: QUIET }, async ($, on) => {
  let daemon: Daemon = BUSY
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => daemon)
  const cases: [Daemon, string, Record<string, unknown>][] = [
    [BUSY, ' ◐ DELEGANDO ', { color: 'warning' }],
    [{ ...UP, backend: () => backend(false) }, ' ○ CAÍDO ', { color: 'error' }],
    [{ stats: UP.stats, inflight: UP.inflight }, ' ◌ SIN DATOS ', { dimColor: true }],
    [{}, ' ○ SIN SERVICIO ', { color: 'error' }],
  ]
  for (const [answers, text, props] of cases) {
    daemon = answers
    await $.session.measure(measureInput())
    const { chip, boxes, texts } = await bar($)
    expect(chip.text).toBe(text)
    expect(chip.props).toMatchObject({ inverse: true, bold: true, ...props })
    expectNoEmptyRows(boxes, texts)
  }
})

test('bar: delegating shows the tool and how long it has run', { options: QUIET }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => BUSY)
  await $.session.measure(measureInput())
  const { left } = await bar($)
  expect(left).toBe(' ◐ DELEGANDO  qwen3-8b · local_summarize 4 s · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
})

test('bar: a daemon that does not answer leaves the chip alone', { options: { ld_bin: LD_BIN, read_mod_enabled: true } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({}))
  await $.session.measure(measureInput())
  const { texts } = await bar($)
  expect(texts.map((t: any) => t.text)).toEqual([' ○ SIN SERVICIO '])
})

test('bar: in English with the language option', { options: { ld_bin: LD_BIN, language: 'en', read_mod_enabled: true } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, stats: () => stats(1, 1500000, 2.5) }))
  await $.session.measure(measureInput(7))
  const { left, right } = await bar($)
  expect(left).toBe(' ● READY  qwen3-8b · 1 delegation · 1.5M tokens saved ≈ $2.50')
  expect(right?.text).toBe('reads: auto-summary')
})

test('bar: the read mode on the right, dim', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput())
  const { right } = await bar($)
  expect(right?.text).toBe('lecturas: resume solo')
  expect(right?.props.dimColor).toBe(true)
})

test('bar: a narrow band drops the least important parts first', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput())
  // 2 cells of padding, the left side and, on the right, one cell of gap and the read mode.
  expect((await bar($, band(92))).right?.text).toBe('lecturas: resume solo')
  const narrow = await bar($, band(60))
  expect(narrow.left).toBe(' ● LISTO  qwen3-8b · 3 delegaciones')
  expect(narrow.right).toBeUndefined()
  expect((await bar($, band(24))).left).toBe(' ● LISTO  qwen3-8b')
})

// --- terminal, line --------------------------------------------------------------------------------

test('line: a dim rule over one line, with no empty row between them', { options: { ...LINE, read_mod_enabled: true } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput())
  for (const columns of [120, 60, 36]) {
    const { rule, boxes, texts } = await line($, band(columns))
    expect(rule).toMatchObject({ text: '─'.repeat(columns), props: { dimColor: true } })
    expectNoEmptyRows(boxes, texts)
    // Two rows and no more: the column holds the rule and the line's own row.
    expect(boxes[0].props.flexDirection).toBe('column')
    expect(boxes.filter((b: any) => b.props.flexDirection === 'row')).toHaveLength(1)
  }
  const { line: text, texts } = await line($)
  expect(text).toBe('local-delegate · ● qwen3-8b listo · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18 · lecturas: resume solo')
  expect(colorOf(texts, '●')).toBe('success')
  // Color only on the dot: the words stay in the normal tone, the name and the labels dim.
  expect(texts.find((t: any) => t.text === ' qwen3-8b listo')?.props.color).toBeUndefined()
  expect(texts.find((t: any) => t.text === 'local-delegate')?.props.dimColor).toBe(true)
})

test('line: each state', { options: LINE }, async ($, on) => {
  let daemon: Daemon = UP
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => daemon)
  const cases: [Daemon, string, string, unknown][] = [
    [{ ...UP, backend: () => backend(true, []) }, '· ● modelo local listo ·', '●', 'success'],
    [BUSY, '· ◐ qwen3-8b delegando · local_summarize 4 s ·', '◐', 'warning'],
    [{ ...UP, backend: () => backend(false) }, '· ○ modelo local caído ·', '○ modelo local caído', 'error'],
  ]
  for (const [answers, part, glyph, color] of cases) {
    daemon = answers
    await $.session.measure(measureInput())
    const { line: text, texts } = await line($)
    expect(text).toContain(part)
    expect(colorOf(texts, glyph)).toBe(color)
  }
  daemon = { stats: UP.stats, inflight: UP.inflight }
  await $.session.measure(measureInput())
  const nodata = await line($)
  expect(nodata.line).toContain('· ◌ modelo local sin datos ·')
  expect(nodata.texts.find((t: any) => t.text.includes('◌'))?.props.dimColor).toBe(true)
  daemon = {}
  await $.session.measure(measureInput())
  const gone = await line($)
  expect(gone.line).toBe('local-delegate · ○ servicio local sin respuesta')
  expect(colorOf(gone.texts, '○')).toBe('error')
})

test('line: several in flight show the oldest and how many more', { options: LINE }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({
    ...UP,
    inflight: () => inflight([task('local_extract', 2.1), task('mcp__local-delegate__local_summarize', 10.4)]),
  }))
  await $.session.measure(measureInput())
  expect((await line($)).line).toContain('· ◑ qwen3-8b delegando · local_summarize 10 s +1 ·')
})

test('line: an empty session says so instead of a zero', { options: LINE }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, stats: () => stats(0, 0) }))
  await $.session.measure(measureInput(4))
  const { line: text, texts } = await line($)
  expect(text).toBe('local-delegate · ● qwen3-8b listo · sin delegaciones aún')
  expect(texts.find((t: any) => t.text.includes('sin delegaciones'))?.props.dimColor).toBe(true)
})

test('line: a narrow band drops the least important parts first', { options: { ...LINE, read_mod_enabled: true } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput())
  expect((await line($, band(60))).line).toBe('local-delegate · ● qwen3-8b listo · 3 delegaciones')
  expect((await line($, band(40))).line).toBe('local-delegate · ● qwen3-8b listo')
})

test('a style outside the options is the bar', { options: { ...QUIET, status_style: 'neon' } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput())
  expect((await bar($)).chip.text).toBe(' ● LISTO ')
})

// --- the read mode, from hasDialog --------------------------------------------------------------

test('the read mode follows whether a person is at the prompt', { options: { ld_bin: LD_BIN, status_style: 'line' } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  on('session.start', (_$, e) => ({ cwd: e.cwd }) as any)
  await $.session.start({ cwd: 'D:/work', surface: 'terminal', isInteractive: true } as any)
  await $.session.measure(measureInput())
  expect((await line($)).line.endsWith(' · lecturas: pregunta')).toBe(true)
  expect((await drawnAll($, desktop())).texts.some((t: any) => t.text === 'Lecturas: pregunta')).toBe(true)
  await $.session.start({ cwd: 'D:/work', surface: 'terminal', isInteractive: false } as any)
  await $.session.measure(measureInput(1))
  expect((await line($)).line.endsWith(' · lecturas: resume solo')).toBe(true)
})

test('no read mode when the mod does not steer the reads', { options: { ...LINE, read_mod_enabled: false } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput())
  expect((await line($)).line.includes('lecturas')).toBe(false)
})

// --- Claude Desktop ----------------------------------------------------------------------------------

test('desktop: one native row with a pill, a link to the panel and the read mode on the right', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput())
  const { texts, boxes, links } = await drawnAll($, desktop())
  expect(boxes[0].props).toMatchObject({ flexDirection: 'row', justifyContent: 'space-between' })
  expectNoEmptyRows(boxes, texts)
  expect(texts.some((t: any) => /^─+$/.test(t.text))).toBe(false)
  // The validator takes `localhost` alone, never 127.0.0.1.
  expect(links.map((l: any) => l.props.href)).toEqual([PANEL])
  expect(links[0].text.endsWith('local-delegate')).toBe(true)
  const name = texts.find((t: any) => t.text === 'local-delegate')
  expect(name?.props).toMatchObject({ dimColor: true, size: 'footnote' })
  const pill = boxes.find((b: any) => b.props.borderStyle === 'round')
  expect(pill?.props).toMatchObject({ borderColor: 'success', paddingX: 'xs' })
  expect(pill?.text).toBe('● Listo')
  expect(colorOf(texts, '●')).toBe('success')
  expect(texts.find((t: any) => t.text === 'qwen3-8b')?.props.dimColor).toBe(true)
  expect(texts.find((t: any) => t.text === '3')?.props).toMatchObject({ weight: 'semibold', tabular: true })
  expect(texts.find((t: any) => t.text === '12,3k')?.props).toMatchObject({ weight: 'semibold', tabular: true })
  expect(texts.find((t: any) => t.text === 'tokens ahorrados')?.props.dimColor).toBe(true)
  const reads = texts[texts.length - 1]
  expect(reads.text).toBe('Lecturas: resume solo')
  expect(reads.props).toMatchObject({ size: 'caption', dimColor: true })
})

test('desktop: each state in the pill', { options: QUIET }, async ($, on) => {
  let daemon: Daemon = UP
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => daemon)
  daemon = BUSY
  await $.session.measure(measureInput())
  let drawn = await drawnAll($, desktop())
  let pill = drawn.boxes.find((b: any) => b.props.borderStyle === 'round')
  expect(pill?.props.borderColor).toBe('warning')
  expect(pill?.text).toBe('◐ Delegando')
  // The tool in mono after the pill, and how long it has run.
  expect(drawn.texts.find((t: any) => t.text === 'local_summarize')?.props.mono).toBe(true)
  expect(drawn.texts.some((t: any) => t.text === '4 s')).toBe(true)

  daemon = { ...UP, backend: () => backend(false) }
  await $.session.measure(measureInput())
  drawn = await drawnAll($, desktop())
  pill = drawn.boxes.find((b: any) => b.props.borderStyle === 'round')
  expect(pill?.props.borderColor).toBe('error')
  expect(pill?.text).toBe('○ Modelo local caído')
  expect(drawn.texts.find((t: any) => t.text.includes('Modelo local caído'))?.props.color).toBe('error')

  daemon = { stats: UP.stats, inflight: UP.inflight }
  await $.session.measure(measureInput())
  drawn = await drawnAll($, desktop())
  pill = drawn.boxes.find((b: any) => b.props.borderStyle === 'round')
  expect(pill?.props.borderDimColor).toBe(true)
  expect(pill?.text).toBe('◌ Sin datos')

  daemon = {}
  await $.session.measure(measureInput())
  drawn = await drawnAll($, desktop())
  pill = drawn.boxes.find((b: any) => b.props.borderStyle === 'round')
  expect(pill?.text).toBe('○ Servicio local sin respuesta')
  expect(drawn.texts.map((t: any) => t.text)).toEqual(['local-delegate', '○', ' Servicio local sin respuesta'])
})

test('desktop: an empty session says so instead of the figures', { options: QUIET }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, stats: () => stats(0, 0) }))
  await $.session.measure(measureInput())
  const { texts } = await drawnAll($, desktop())
  expect(texts.find((t: any) => t.text === 'Sin delegaciones aún')?.props.dimColor).toBe(true)
  expect(texts.some((t: any) => t.text === '0')).toBe(false)
})

// --- live refresh -------------------------------------------------------------------------------------

function since(seen: Seen, from: number) {
  return seen.fetches.slice(from).map(f => new URL(f.url).pathname).sort()
}

test('while delegating, the clock rereads inflight and backend every second', { options: LINE }, async ($, on) => {
  let daemon: Daemon = BUSY
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => daemon)
  await $.session.measure(measureInput())
  expect((await line($)).line).toContain('◐ qwen3-8b delegando · local_summarize 4 s')
  daemon = { ...BUSY, inflight: () => inflight([task('local_summarize', 5.3)]) }
  const before = seen.fetches.length
  await seen.clock.advance(1000)
  // Only the two quick answers: the session's figures do not change while the call runs.
  expect(since(seen, before)).toEqual(['/api/backend', '/api/inflight'])
  // The seconds moved, and the dot turned with them.
  expect((await line($)).line).toContain('◓ qwen3-8b delegando · local_summarize 5 s')
})

test('the clock redraws the band only when something changed', { options: LINE }, async ($, on) => {
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => BUSY)
  await $.session.measure(measureInput())
  const drawnBefore = seen.invalidations
  const fetchedBefore = seen.fetches.length
  await seen.clock.advance(1000)
  // Asked again, the same answer: no redraw.
  expect(seen.fetches.length).toBe(fetchedBefore + 2)
  expect(seen.invalidations).toBe(drawnBefore)
})

test('a model the backend shows while it loads reaches the band before the turn ends', { options: LINE }, async ($, on) => {
  let daemon: Daemon = { ...UP, backend: () => backend(true, [{ model: 'gemma-4b', state: 'starting' }]) }
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => daemon)
  await $.session.measure(measureInput())
  daemon = { ...UP, backend: () => backend(true, [{ model: 'gemma-4b', state: 'ready' }]) }
  const drawnBefore = seen.invalidations
  await seen.clock.advance(1000)
  expect(seen.invalidations).toBe(drawnBefore + 1)
  expect((await line($)).line).toContain('● gemma-4b listo')
})

test('with nothing in flight, the clock asks every 30 seconds', { options: LINE }, async ($, on) => {
  let daemon: Daemon = UP
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => daemon)
  await $.session.measure(measureInput())
  const before = seen.fetches.length
  await seen.clock.advance(1000)
  expect(seen.fetches.length).toBe(before)
  daemon = { ...UP, backend: () => backend(true, []) }
  await seen.clock.advance(29000)
  expect(since(seen, before)).toEqual(['/api/backend', '/api/inflight'])
  expect((await line($)).line).toContain('● modelo local listo')
})

test('when the last delegation ends, the clock rereads the session figures too', { options: LINE }, async ($, on) => {
  let daemon: Daemon = BUSY
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => daemon)
  await $.session.measure(measureInput())
  daemon = { ...UP, stats: () => stats(4, 20000, 0.25) }
  const before = seen.fetches.length
  await seen.clock.advance(1000)
  expect(since(seen, before)).toContain(`/api/stats`)
  expect((await line($)).line).toBe('local-delegate · ● qwen3-8b listo · 4 delegaciones · 20k tokens ahorrados ≈ $0,25')
})

test('a call to a local-delegate tool turns the quick refresh on at once', { options: LINE }, async ($, on) => {
  let daemon: Daemon = UP
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => daemon)
  // Beneath the mod, the tool takes a second and a half to answer.
  on('tool.call', async () => {
    await seen.clock.sleep(1500)
    return { result: 'ok' } as any
  })
  await $.session.measure(measureInput())
  daemon = BUSY
  const call = $.tool.call({ tool: 'mcp__local-delegate__local_summarize', path: 'D:/big.log' } as any)
  await seen.clock.advance(1000)
  expect((await line($)).line).toContain('◐ qwen3-8b delegando · local_summarize 4 s')
  daemon = { ...UP, stats: () => stats(4, 20000, 0.25) }
  await seen.clock.advance(1000)
  await call
  // Once the call answers, the session's figures come at once.
  expect((await line($)).line).toContain('● qwen3-8b listo · 4 delegaciones')
})

test('the timer stops when the session ends', { options: LINE }, async ($, on) => {
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => BUSY)
  on('session.end', (_$, e) => ({ sessionId: e.sessionId }) as any)
  await $.session.measure(measureInput())
  // Guard: the quick refresh runs before the end.
  let before = seen.fetches.length
  await seen.clock.advance(1000)
  expect(seen.fetches.length).toBe(before + 2)
  await $.session.end({ reason: 'exit', sessionId: SESSION } as any)
  before = seen.fetches.length
  await seen.clock.advance(60000)
  expect(seen.fetches.length).toBe(before)
})

// --- what did not change --------------------------------------------------------------------------

test('a refusal or a body that is not the stats reads as a daemon that does not answer', { options: LINE }, async ($, on) => {
  const answers = [json({ detail: 'no' }, 401), { status: 200, ok: true, headers: {}, text: '<html>' }, json({ total: {} })]
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, stats: () => answers.shift() }))
  for (let i = 0; i < 3; i++) {
    await $.session.measure(measureInput(5))
    expect((await line($)).line).toBe('local-delegate · ○ servicio local sin respuesta')
  }
})

test('yields the band to a survey', { options: QUIET }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput())
  for (const surface of ['terminal', 'desktop']) {
    const { texts } = await drawnAll($, band(120, true, surface))
    expect(texts.map((t: any) => t.text)).toEqual(['engine'])
  }
})

test('draws nothing and asks nothing without the token', { options: QUIET }, async ($, on) => {
  const seen = engine(on, {}, () => UP)
  await $.session.measure(measureInput(50))
  await seen.clock.advance(60000)
  expect((await drawnAll($)).texts.map((t: any) => t.text)).toEqual(['engine'])
  expect(seen.fetches).toEqual([])
})

test('off_by_userconfig', { options: { ld_bin: LD_BIN, status_enabled: false } }, async ($, on) => {
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput(50))
  await seen.clock.advance(60000)
  expect((await drawnAll($)).texts.map((t: any) => t.text)).toEqual(['engine'])
  expect(seen.statuses).toEqual([])
  expect(seen.fetches).toEqual([])
})
