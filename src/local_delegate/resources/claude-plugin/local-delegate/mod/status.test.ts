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
  stats?: (url: URL) => any
  backend?: (url: URL) => any
  inflight?: (url: URL) => any
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

function stats(calls: number, net: number, estimate: number | null = null, errors?: number) {
  return json({
    total: errors === undefined ? { calls } : { calls, errors },
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
    return { value: await answer(new URL(e.url)) }
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
    `http://127.0.0.1:9393/api/inflight?session=${SESSION}`,
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

test('bar: failed attempts are not delegations, they go apart (issue #436)', { options: QUIET }, async ($, on) => {
  // The session of the issue: the backend unreachable, 17 attempts logged, 15 of them failed.
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, stats: () => stats(17, 4200, null, 15), backend: () => backend(false) }))
  await $.session.measure(measureInput())
  const { left, texts } = await bar($)
  expect(left).toBe(' ○ CAÍDO  2 delegaciones · 15 fallidas · 4,2k tokens ahorrados')
  expect(texts.find((t: any) => t.text === '15')?.props.bold).toBe(true)
  expect(texts.find((t: any) => t.text === ' fallidas')?.props.dimColor).toBe(true)
})

test('bar: only failures, no delegation yet, says both', { options: QUIET }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, stats: () => stats(1, 0, null, 1), backend: () => backend(false) }))
  await $.session.measure(measureInput())
  expect((await bar($)).left).toBe(' ○ CAÍDO  0 delegaciones · 1 fallida')
})

test('line: failed attempts in English (issue #436)', { options: { ...LINE, language: 'en' } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, stats: () => stats(3, 1500, null, 1) }))
  await $.session.measure(measureInput())
  expect((await line($)).line).toContain('· 2 delegations · 1 failed · 1.5k tokens saved')
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

// --- F4-live-fixes: minutes, progress by chunks and no loose separator ------------------------------

/** One delegation in flight split in chunks, as `/api/inflight` lists it (`chunks`, 1-based `chunk`). */
function chunked(elapsed: number, chunks: number, chunk: number) {
  return { ...task('local_summarize', elapsed), chunks, chunk }
}

test('bar: past a minute the time is in minutes, and a split delegation shows its chunk', { options: QUIET }, async ($, on) => {
  let items: any[] = []
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, inflight: () => inflight(items) }))
  const cases: [any, string][] = [
    // Live 2026-10-23: «196 s», and nothing said it was on chunk 7 of 9.
    [chunked(196.5, 9, 7), 'local_summarize 7/9 · 3 min 16 s'],
    [task('local_summarize', 14.2), 'local_summarize 14 s'],
    [task('local_summarize', 59.9), 'local_summarize 59 s'],
    [task('local_summarize', 60), 'local_summarize 1 min 0 s'],
    // One chunk is no progress to show.
    [chunked(75, 1, 1), 'local_summarize 1 min 15 s'],
  ]
  for (const [item, shown] of cases) {
    items = [item]
    await $.session.measure(measureInput())
    const { left, boxes, texts } = await bar($)
    // (The dot turns with the seconds: only the words are compared.)
    expect(left.slice(3)).toBe(`DELEGANDO  qwen3-8b · ${shown} · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18`)
    expectNoEmptyRows(boxes, texts)
  }
})

test('line: minutes and chunks in English', { options: { ...LINE, language: 'en' } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, inflight: () => inflight([chunked(196.5, 9, 7)]) }))
  await $.session.measure(measureInput())
  const { line: text, boxes, texts } = await line($)
  expect(text).toContain(' · local_summarize 7/9 · 3m 16s · ')
  expectNoEmptyRows(boxes, texts)
  // A narrow band still drops the task before the state (statusFit).
  expect((await line($, band(40))).line).toBe('local-delegate · ◐ qwen3-8b delegating')
})

test('bar: without a model the chip is followed by the next part, with no loose separator', { options: QUIET }, async ($, on) => {
  let daemon: Daemon = { ...UP, backend: () => backend(true, []) }
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => daemon)
  await $.session.measure(measureInput())
  let drawn = await bar($)
  expect(drawn.left).toBe(' ● LISTO  3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
  expectNoEmptyRows(drawn.boxes, drawn.texts)
  // The same while delegating with no model named, and in a narrow band.
  daemon = { ...UP, backend: () => backend(true, []), inflight: () => inflight([task('local_summarize', 4.2, '')]) }
  await $.session.measure(measureInput())
  drawn = await bar($)
  expect(drawn.left).toBe(' ◐ DELEGANDO  local_summarize 4 s · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
  expect((await bar($, band(40))).left).toBe(' ◐ DELEGANDO  local_summarize 4 s')
  // Guard: with a model the separators between present parts stay.
  daemon = UP
  await $.session.measure(measureInput())
  expect((await bar($)).left).toBe(' ● LISTO  qwen3-8b · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
})

test('line: without a model nothing is left loose either', { options: LINE }, async ($, on) => {
  // Guard (the line already joined only present parts): the same case as the bar's.
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, backend: () => backend(true, []) }))
  await $.session.measure(measureInput())
  expect((await line($)).line).toBe('local-delegate · ● modelo local listo · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
  expect((await line($, band(60))).line).toBe('local-delegate · ● modelo local listo · 3 delegaciones')
})

// --- Claude Desktop (F4-live-fixes, design v2) ---------------------------------------------------------
//
// Live 2026-10-23, «visualmente es terrible»: the round-bordered pill looked like a button and
// made the card grow, and the panel link sat off the baseline. Now one line of text in two tones,
// like the app's own (`Opus 5.5 Medio`): the left side is a single Text with inline Texts inside.

// F4-desktop-spacing (live 2026-10-23, «en desktop hay textos que quedan muy juntos»): Desktop
// separates with an en space (U+2002) on each side of the `·` and binds the dot to its word with a
// no-break space (U+00A0). `plain` reads them back as plain spaces, so the content checks below
// stay readable; the spacing has a test of its own.
const DESKTOP_SEPARATOR = ' · '

function plain(text: string) {
  return text.replaceAll(DESKTOP_SEPARATOR, ' · ').replaceAll(' ', ' ')
}

/** The Desktop band: its Boxes, its Texts, its Links, the left line (the outer Text) and the right. */
async function desk($: any, columns = 160) {
  const { texts, boxes, links } = await drawnAll($, desktop(columns))
  const left = texts[0] && { ...texts[0], raw: texts[0].text as string, text: plain(texts[0].text) }
  const right = texts.find((t: any) => /^(Lecturas|Reads):/.test(t.text))
  return { texts, boxes, links, left, right }
}

function expectPlainDesktop(drawn: { texts: any[]; boxes: any[]; links: any[] }) {
  // No pill, no background, no link, no gap and no typography props (the minimum CLI refuses
  // `size`; `bold` would become a weight the app's own line does not use).
  expect(drawn.links).toHaveLength(0)
  expect(drawn.boxes).toHaveLength(1)
  for (const box of drawn.boxes) {
    for (const key of ['borderStyle', 'borderColor', 'backgroundColor', 'gap', 'paddingX']) {
      expect(box.props[key]).toBeUndefined()
    }
  }
  for (const text of drawn.texts) {
    for (const key of ['size', 'weight', 'mono', 'tabular', 'bold']) {
      expect(text.props[key]).toBeUndefined()
    }
  }
  expectNoEmptyRows(drawn.boxes, drawn.texts)
}

function span(texts: any[], text: string) {
  return texts.slice(1).find((t: any) => plain(t.text) === text)
}

test('desktop: one line of text in two tones, the read mode dim on the right', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput())
  const drawn = await desk($)
  expectPlainDesktop(drawn)
  expect(drawn.boxes[0].props).toMatchObject({ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' })
  // The left side is ONE Text, the spaces and the `·` inside it.
  expect(drawn.left.text).toBe('local-delegate · ● Listo · qwen3-8b · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
  expect(drawn.right?.text).toBe('Lecturas: resume solo')
  expect(drawn.right?.props.dimColor).toBe(true)
  // Two tones: the data normal, everything else dim; color only on the dot.
  expect(span(drawn.texts, '●')?.props.color).toBe('success')
  expect(span(drawn.texts, ' Listo')?.props.dimColor).toBeUndefined()
  expect(span(drawn.texts, ' Listo')?.props.color).toBeUndefined()
  expect(span(drawn.texts, '3')?.props.dimColor).toBeUndefined()
  expect(span(drawn.texts, '12,3k')?.props.dimColor).toBeUndefined()
  for (const dim of ['local-delegate', 'qwen3-8b', ' delegaciones', ' tokens ahorrados', '≈ $0,18']) {
    expect(span(drawn.texts, dim)?.props.dimColor).toBe(true)
  }
})

test('desktop: each state', { options: QUIET }, async ($, on) => {
  let daemon: Daemon = UP
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => daemon)

  daemon = { ...UP, inflight: () => inflight([chunked(196.5, 9, 7), task('local_extract', 3)]) }
  await $.session.measure(measureInput())
  let drawn = await desk($)
  expectPlainDesktop(drawn)
  // (The dot turns with the seconds: 196 s is ◐.)
  expect(drawn.left.text).toBe('local-delegate · ◐ Delegando local_summarize 7/9 · 3 min 16 s +1 más · qwen3-8b · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
  expect(span(drawn.texts, '◐')?.props.color).toBe('warning')
  expect(span(drawn.texts, 'local_summarize')?.props.dimColor).toBeUndefined()
  expect(span(drawn.texts, ' 7/9')?.props.dimColor).toBeUndefined()
  // The dot already says it is at work: the verb goes dim, so the tool (the datum) stands out.
  expect(span(drawn.texts, ' Delegando')?.props.dimColor).toBe(true)
  expect(span(drawn.texts, ' · 3 min 16 s')?.props.dimColor).toBe(true)
  expect(span(drawn.texts, ' +1 más')?.props.dimColor).toBe(true)

  daemon = { ...UP, backend: () => backend(false) }
  await $.session.measure(measureInput())
  drawn = await desk($)
  expectPlainDesktop(drawn)
  expect(drawn.left.text.startsWith('local-delegate · ○ Modelo local caído · 3 delegaciones')).toBe(true)
  expect(span(drawn.texts, '○')?.props.color).toBe('error')
  expect(span(drawn.texts, ' Modelo local caído')?.props.color).toBe('error')

  // Issue #436 on Desktop: the failed attempts apart from the delegations, no bold.
  daemon = { ...UP, stats: () => stats(17, 4200, null, 15), backend: () => backend(false) }
  await $.session.measure(measureInput())
  drawn = await desk($)
  expectPlainDesktop(drawn)
  expect(drawn.left.text).toBe('local-delegate · ○ Modelo local caído · 2 delegaciones · 15 fallidas · 4,2k tokens ahorrados')

  daemon = { stats: UP.stats, inflight: UP.inflight }
  await $.session.measure(measureInput())
  drawn = await desk($)
  expectPlainDesktop(drawn)
  expect(drawn.left.text.startsWith('local-delegate · ◌ Sin datos del modelo · 3 delegaciones')).toBe(true)
  expect(span(drawn.texts, '◌')?.props.dimColor).toBe(true)
  expect(span(drawn.texts, ' Sin datos del modelo')?.props.dimColor).toBe(true)

  daemon = {}
  await $.session.measure(measureInput())
  drawn = await desk($)
  expectPlainDesktop(drawn)
  expect(drawn.left.text).toBe('local-delegate · ○ Servicio local sin respuesta')
  expect(span(drawn.texts, ' Servicio local sin respuesta')?.props.color).toBe('error')
  // Without the service there is no right side.
  expect(drawn.texts).toHaveLength(5)
})

test('desktop: an empty session says so instead of a zero', { options: QUIET }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, stats: () => stats(0, 0) }))
  await $.session.measure(measureInput())
  const drawn = await desk($)
  expect(drawn.left.text).toBe('local-delegate · ● Listo · qwen3-8b · sin delegaciones aún')
  expect(span(drawn.texts, 'sin delegaciones aún')?.props.dimColor).toBe(true)
  expect(drawn.texts.some((t: any) => t.text === '0')).toBe(false)
})

test('desktop: a narrow band drops the least important parts first, and leaves no loose separator', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => UP)
  await $.session.measure(measureInput())
  // The head (`local-delegate · ● Listo`, 18.5 cells in Desktop's letter) always stays; then the
  // model, the calls, ...
  const narrow = await desk($, 45)
  expect(narrow.left.text).toBe('local-delegate · ● Listo · qwen3-8b · 3 delegaciones')
  expect(narrow.right).toBeUndefined()
  expectPlainDesktop(narrow)
  expect((await desk($, 20)).left.text).toBe('local-delegate · ● Listo')
})

test('desktop: the separators are wide spaces that do not collapse, never plain ones', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, inflight: () => inflight([chunked(107, 9, 4)]) }))
  await $.session.measure(measureInput())
  const drawn = await desk($)
  // No ` · ` with plain spaces anywhere in Desktop's line, not even inside the task's own time.
  expect(drawn.left.raw.includes(' · ')).toBe(false)
  expect(drawn.left.raw.includes(' ·')).toBe(false)
  expect(drawn.left.raw.includes('· ')).toBe(false)
  expect(drawn.left.raw.split(DESKTOP_SEPARATOR)).toHaveLength(6)
  // The dot is bound to its word with a no-break space: they never part.
  expect(drawn.left.raw).toContain(' Delegando')
  expect(drawn.left.text).toBe('local-delegate · ◒ Delegando local_summarize 4/9 · 1 min 47 s · qwen3-8b · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
})

// Live 2026-10-23: while delegating, Desktop lost the figures and the read mode with half the card
// empty. `bodyColumns` counts cells of the app's monospace font, and its proportional letter takes
// about three quarters of one (measured on the capture: ~6.1 px a character, cells of 8 to 9.8 px).
function screenshotDaemon(): Daemon {
  return {
    stats: () => stats(32, 446000, 0.12),
    backend: () => backend(true, [{ model: 'gemma4-26b-a4b', state: 'ready' }]),
    inflight: () => inflight([{ ...chunked(107, 9, 4), model: 'gemma4-26b-a4b' }]),
  }
}

test('desktop: delegating in a band of about 100 cells keeps the figures', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, screenshotDaemon)
  await $.session.measure(measureInput())
  const drawn = await desk($, 100)
  expect(drawn.left.text).toBe('local-delegate · ◒ Delegando local_summarize 4/9 · 1 min 47 s · gemma4-26b-a4b · 32 delegaciones · 446k tokens ahorrados ≈ $0,12')
  // At the narrow end of what the capture allows (96 cells), the cost goes before the figures.
  expect((await desk($, 96)).left.text).toContain('· 32 delegaciones · 446k tokens ahorrados')
  expectPlainDesktop(drawn)
})

test('desktop: with room for it, the read mode stays on the right while delegating', { options: { ld_bin: LD_BIN } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, screenshotDaemon)
  await $.session.measure(measureInput())
  const drawn = await desk($, 120)
  expect(drawn.left.text).toContain('· 32 delegaciones · 446k tokens ahorrados ≈ $0,12')
  expect(drawn.right?.text).toBe('Lecturas: resume solo')
  // Still one row: one Box, the left one Text, the right one Text.
  expect(drawn.boxes).toHaveLength(1)
  expect(drawn.boxes[0].props.flexDirection).toBe('row')
})

test('desktop: in English', { options: { ld_bin: LD_BIN, language: 'en' } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, inflight: () => inflight([chunked(75, 3, 2), task('local_extract', 3)]) }))
  await $.session.measure(measureInput())
  const drawn = await desk($)
  expect(drawn.left.text.slice(19)).toBe('Delegating local_summarize 2/3 · 1m 15s +1 more · qwen3-8b · 3 delegations · 12.3k tokens saved ≈ $0.18')
  expect(drawn.right?.text).toBe('Reads: auto-summary')
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

// --- several sessions at once (issue #442) ------------------------------------------------------------
//
// With two sessions open, a delegation of one turned every band to ` ◐ DELEGANDO ` with its tool,
// its time and its chunks. Now the mod asks `/api/inflight?session=<id>` and the daemon marks each
// entry `mine`: only the session that asked for it sees it at work; the others see the backend in
// use by another session, and nothing of that call.

const OTHER = 'sess-other'

/**
 * `/api/inflight?session=<id>` as the daemon answers it: each entry `mine` only when the session
 * that started it is the one asking now (an entry without a session is nobody's), and `mine_count`.
 */
function bySession(items: { session?: string; item: any }[]) {
  return (url: URL) => {
    const asking = url.searchParams.get('session')
    const list = items.map(({ session, item }) => ({ ...item, mine: asking !== null && session === asking }))
    const mine = list.filter(entry => entry.mine).length
    return json({ inflight: list, count: list.length, mine_count: mine, last_event_ts: null, last_event: null })
  }
}

const OTHERS_ONLY: Daemon = { ...UP, inflight: bySession([{ session: OTHER, item: chunked(196.5, 9, 7) }]) }
const BOTH: Daemon = {
  ...UP,
  inflight: bySession([
    { session: OTHER, item: chunked(196.5, 9, 7) },
    { session: SESSION, item: task('local_extract', 3) },
  ]),
}

test('several sessions: only its own delegation is at work in a band, never another session\'s', { options: QUIET }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => BOTH)
  await $.session.measure(measureInput())
  const { left, chip } = await bar($)
  // Its own call (3 s, ◒), not the other session's older one (local_summarize 7/9, 3 min 16 s), and no `+1`.
  expect(chip.text).toBe(' ◒ DELEGANDO ')
  expect(left).toBe(' ◒ DELEGANDO  qwen3-8b · local_extract 3 s · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
})

test('several sessions: another session\'s delegation is only «in use», in each surface', { options: QUIET }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => OTHERS_ONLY)
  await $.session.measure(measureInput())

  const drawnBar = await bar($)
  expect(drawnBar.chip.text).toBe(' ● LISTO ')
  expect(drawnBar.chip.props).toMatchObject({ inverse: true, bold: true, color: 'success' })
  expect(drawnBar.left).toBe(' ● LISTO  qwen3-8b · en uso por otra sesión · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
  expect(drawnBar.texts.find((t: any) => t.text === 'en uso por otra sesión')?.props.dimColor).toBe(true)
  expectNoEmptyRows(drawnBar.boxes, drawnBar.texts)

  const drawn = await desk($)
  expectPlainDesktop(drawn)
  expect(drawn.left.text).toBe('local-delegate · ● Listo · en uso por otra sesión · qwen3-8b · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
  expect(span(drawn.texts, '●')?.props.color).toBe('success')
  expect(span(drawn.texts, 'en uso por otra sesión')?.props.dimColor).toBe(true)
  // Desktop's separators stay wide there too.
  expect(drawn.left.raw.includes(' · ')).toBe(false)

  for (const text of [drawnBar.left, drawn.left.text]) {
    expect(text).not.toContain('DELEGANDO')
    expect(text).not.toContain('Delegando')
    expect(text).not.toContain('local_summarize')
    expect(text).not.toContain('7/9')
    expect(text).not.toContain('min')
  }
})

test('several sessions: the line, and in English', { options: { ...LINE, language: 'en' } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => OTHERS_ONLY)
  await $.session.measure(measureInput())
  expect((await line($)).line).toBe('local-delegate · ● qwen3-8b ready · in use by another session · 3 delegations · 12.3k tokens saved ≈ $0.18')
  expect((await desk($)).left.text).toBe('local-delegate · ● Ready · in use by another session · qwen3-8b · 3 delegations · 12.3k tokens saved ≈ $0.18')
})

test('several sessions: the bar in English', { options: { ...QUIET, language: 'en' } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => OTHERS_ONLY)
  await $.session.measure(measureInput())
  expect((await bar($)).left).toBe(' ● READY  qwen3-8b · in use by another session · 3 delegations · 12.3k tokens saved ≈ $0.18')
})

test('several sessions: in Spanish, the line too', { options: LINE }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => OTHERS_ONLY)
  await $.session.measure(measureInput())
  expect((await line($)).line).toBe('local-delegate · ● qwen3-8b listo · en uso por otra sesión · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
})

test('several sessions: a delegation of no known session is never taken for its own', { options: QUIET }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, inflight: bySession([{ item: task('local_summarize', 4.2) }]) }))
  await $.session.measure(measureInput())
  expect((await bar($)).left).toBe(' ● LISTO  qwen3-8b · en uso por otra sesión · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18')
})

test('several sessions: when its own call ends while another runs, the figures are reread and the band says «in use»', { options: LINE }, async ($, on) => {
  let daemon: Daemon = BOTH
  const seen = engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => daemon)
  await $.session.measure(measureInput())
  expect((await line($)).line).toContain('delegando · local_extract 3 s')
  daemon = { ...OTHERS_ONLY, stats: () => stats(4, 20000, 0.25) }
  const before = seen.fetches.length
  await seen.clock.advance(1000)
  expect(since(seen, before)).toContain('/api/stats')
  expect((await line($)).line).toBe('local-delegate · ● qwen3-8b listo · en uso por otra sesión · 4 delegaciones · 20k tokens ahorrados ≈ $0,25')
  // While the other session's call runs, the quick pace stays, so the note goes as soon as it ends.
  daemon = { ...UP, stats: () => stats(4, 20000, 0.25), inflight: bySession([]) }
  await seen.clock.advance(1000)
  expect((await line($)).line).toBe('local-delegate · ● qwen3-8b listo · 4 delegaciones · 20k tokens ahorrados ≈ $0,25')
})

// --- Issue #477: the band names the delegation the backend is processing, not the oldest --------------

/** One delegation in flight with its `state` (`running`, `retrying` or `queued`), as daemons from #477 list it. */
function stated(tool: string, elapsed: number, state: string, extra: any = {}) {
  return { ...task(tool, elapsed), state, ...extra }
}

test('line: the one at the backend goes first, even when a queued one is older (issue #477)', { options: LINE }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({
    ...UP,
    inflight: () =>
      inflight([
        stated('local_extract', 250, 'queued'),
        stated('local_summarize', 400, 'retrying', { chunks: 9, chunk: 3, phase: 'retry' }),
        stated('local_translate', 12.4, 'running'),
      ]),
  }))
  await $.session.measure(measureInput())
  expect((await line($)).line).toContain('· local_translate 12 s +2 ·')
})

test('line: with none at the backend, the oldest queued one says it waits (issue #477)', { options: LINE }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({
    ...UP,
    inflight: () => inflight([stated('local_extract', 30, 'queued'), stated('local_summarize', 240, 'queued')]),
  }))
  await $.session.measure(measureInput())
  expect((await line($)).line).toContain('· local_summarize · en cola · 4 min 0 s +1 ·')
})

test('line: a retrying one goes before a queued one, and says so, in English (issue #477)', { options: { ...LINE, language: 'en' } }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({
    ...UP,
    inflight: () =>
      inflight([stated('local_extract', 300, 'queued'), stated('local_summarize', 75, 'retrying', { chunks: 9, chunk: 3, phase: 'retry' })]),
  }))
  await $.session.measure(measureInput())
  expect((await line($)).line).toContain('· local_summarize 3/9 · retrying · 1m 15s +1 ·')
})

test('desktop: a queued delegation says it waits (issue #477)', { options: QUIET }, async ($, on) => {
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({ ...UP, inflight: () => inflight([stated('local_summarize', 240, 'queued')]) }))
  await $.session.measure(measureInput())
  expect((await desk($)).left.text).toContain('local_summarize · en cola · 4 min 0 s')
})

test('several sessions: another machine\'s running delegation never wins over this session\'s queued one (issue #477)', { options: LINE }, async ($, on) => {
  // A delegation from the Mac (over HTTP) has no session of this one: it is never `mine`.
  engine(on, { LOCAL_DELEGATE_WEB_TOKEN: TOKEN }, () => ({
    ...UP,
    inflight: bySession([
      { item: { ...stated('local_extract', 500, 'running'), host: 'mac' } },
      { session: SESSION, item: stated('local_summarize', 240, 'queued') },
    ]),
  }))
  await $.session.measure(measureInput())
  const shown = (await line($)).line
  expect(shown).toContain('· local_summarize · en cola · 4 min 0 s ·')
  expect(shown).not.toContain('local_extract')
})
