#!/usr/bin/env python3
"""Regenera `docs/assets/dashboard.png`, la captura del dashboard que enseña el README.

La captura tiene que lucir el panel **completo** —todos los gráficos con datos, un modelo
montado y procesando, otro montado en reposo, VRAM ocupada de verdad— y eso no se consigue
esperando a que tu log real tenga la forma adecuada. Se interceptan las respuestas de `/api/*`
con datos de ejemplo **deterministas**, así que:

- la imagen es reproducible: la misma semilla da la misma captura;
- **no se publica tu actividad real** (rutas de archivos, nombres de proyectos, horarios);
- `/api/status` se deja pasar sin tocar, para que la versión, el catálogo de modelos y el
  número de tools que aparecen sean los de verdad.

Que la segunda promesa se cumpla **no depende de acordarse**: `tests/test_captura.py` compara los
`/api/*` que la página pide con las claves de `MOCKS`, y un endpoint nuevo sin interceptar rompe el
test. Se añadió después de descubrir que `/api/hooks` y `/api/stats` llevaban tiempo escapándose y
publicando el log real de quien capturaba.

El README avisa de que son «datos de ejemplo». Mantener ese pie es parte del trato.

Junto al PNG se escribe un **manifiesto** (`dashboard.json`) con la versión que sirvió el
dashboard capturado y el hash de la imagen. `tests/test_captura.py` lo compara con
`pyproject.toml`, así que una captura que se quede vieja deja de pasar en silencio: durante 20 de
las 25 releases del proyecto nadie la regeneró, y la 0.16.0 se publicó con el badge diciendo
`v0.15.0`.

Requiere Playwright, que **no** es dependencia del proyecto:

    uv pip install playwright && uv run python -m playwright install chromium

**Captura contra el repo, no contra el daemon instalado.** El daemon sirve la versión que tenga
instalada, que tras un bump ya no es la del árbol, y `/api/status` se deja pasar sin mockear. Ojo:
`local-delegate serve --port 9494` **no** vale para esto —es singleton y el lock lo tiene el
daemon del 9393—, hay que montar solo la app de métricas:

    uv run python -c "import uvicorn; from local_delegate.web import metrics; \
uvicorn.run(metrics.app, host='127.0.0.1', port=9494)"
    uv run python scripts/dev/capture_dashboard.py --url http://127.0.0.1:9494/

Si se captura contra el daemon igualmente, no se cuela nada: el manifiesto registra la versión
vieja —la que la imagen enseña de verdad— y el test sigue fallando.

Códigos de salida:

    0  captura y manifiesto escritos
    1  el panel no se pobló como se esperaba
    2  falta Playwright
    3  el dashboard no dice qué versión sirve
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parents[2]

MANIFIESTO_ACERCA_DE = [
    "Manifiesto de la captura del README. Es la FUENTE DE VERDAD de con qué versión se generó.",
    "Lo escribe `scripts/dev/capture_dashboard.py` al capturar, NUNCA a mano y nunca el bump de",
    "versión: si lo actualizara quien sube la versión, el check se cumpliría sin que nadie",
    "regenerara la imagen, que es justo lo que se quiere evitar.",
    "La versión es la que sirvió el dashboard capturado (`/api/status`), no la de pyproject.toml:",
    "así, capturar contra el daemon instalado en vez de contra el repo deja constancia en vez de",
    "colar un badge viejo.",
    "Lo comprueba `tests/test_captura.py`. Procedimiento: docs/wiki/Publishing.md.",
]


def _version_del_dashboard(url: str) -> str:
    """Versión que sirve el dashboard que se va a capturar, leída de `/api/status`.

    Se lee **antes** de capturar y a propósito: si no se puede, el script falla sin haber tocado
    ni el PNG ni el manifiesto. Un manifiesto con la versión vacía sería un manifiesto que miente,
    que es exactamente lo que este vigilante existe para impedir.
    """
    endpoint = url.rstrip("/") + "/api/status"
    with urllib.request.urlopen(endpoint, timeout=5) as resp:
        datos = json.load(resp)
    version = datos.get("version")
    if not version:
        raise RuntimeError(f"{endpoint} no declara `version`: {sorted(datos)}")
    return str(version)


def _escribir_manifiesto(png: Path, version: str) -> Path:
    """Deja junto al PNG el manifiesto que lo describe. Devuelve su ruta."""
    blob = png.read_bytes()
    destino = png.with_suffix(".json")
    destino.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "_acerca_de": MANIFIESTO_ACERCA_DE,
                "file": png.name,
                "version": version,
                "sha256": hashlib.sha256(blob).hexdigest(),
                "bytes": len(blob),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destino


# Datos de ejemplo. La semilla fija hace la captura reproducible; los nombres de archivo y el
# host remoto son inventados a propósito para no filtrar nada de la máquina real.
SEED_AND_MOCK = """({DENSIDAD, PRECIOS_CONSULTADO}) => {
  const TOOLS = ['local_summarize','local_translate','local_extract','local_classify',
    'local_lint_summary','local_boilerplate','local_commit_msg','local_explain_code',
    'local_describe_image','local_delegate'];
  const MODELS = {local_summarize:'gemma4-26b-a4b',local_translate:'gemma4-26b-a4b',
    local_extract:'gemma3-4b',local_classify:'qwen35-2b',local_lint_summary:'gemma3-4b',
    local_boilerplate:'qwen36-35b-a3b',local_commit_msg:'qwen36-35b-a3b',
    local_explain_code:'qwen36-35b-a3b',local_describe_image:'gemma4-12b',
    local_delegate:'gemma3-4b'};
  let seed = 20260728;
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;

  // `/api/events` entrega las filas ya fundidas y con la densidad resuelta (`resolver_densidad`
  // en Python); el JS del panel solo divide. Sin `densidad`, `tokensClaude` da 0 y las series por
  // día saldrían planas. Esta es una resolución de juguete para los datos de ejemplo —familia
  // `nueva`, clase por la tool o por la extensión `.md`— con los valores de la tabla del paquete.
  const DENS = DENSIDAD.familias.nueva;
  const CLASE_TOOL = {local_lint_summary: 'log', local_commit_msg: 'diff',
    local_explain_code: 'codigo'};
  const celda = (columna, clase) => {
    if (DENS[columna][clase]) return [DENS[columna][clase], 'medida'];
    return [DENS.sin_numerar[clase], 'sin_numerar'];
  };
  const densidadDe = (tool, porPath) => {
    if (tool === 'local_describe_image') return {text: null, returned: null, output: null};
    const clase = CLASE_TOOL[tool] || 'prosa';
    const devuelta = tool === 'local_extract' ? 'estructurado'
      : (tool === 'local_boilerplate' ? 'codigo' : 'prosa');
    return {
      text: porPath ? celda('formato_read', clase) : [DENS.sin_numerar[clase], 'medida'],
      returned: [DENS.sin_numerar[devuelta], 'medida'],
      output: [DENS.sin_numerar[tool === 'local_boilerplate' ? 'codigo' : 'prosa'], 'medida'],
    };
  };
  const aTokens = (cantidad, c) => (c ? Math.floor(cantidad * 100 / c[0]) : 0);

  const now = new Date();
  const events = [];
  for (let d = 11; d >= 0; d--) {
    const perDay = 24 + Math.floor(rnd() * 20);
    for (let i = 0; i < perDay; i++) {
      const tool = TOOLS[Math.floor(rnd() * TOOLS.length)];
      const ts = new Date(now.getTime() - d * 864e5 + (9 + rnd() * 11) * 36e5);
      const path = rnd() > 0.28;
      const remote = rnd() > 0.72;
      const chars = path ? 4000 + Math.floor(rnd() * 46000) : 300 + Math.floor(rnd() * 2500);
      const chunks = chars > 20000 ? 2 + Math.floor(rnd() * 12) : 1;
      events.push({
        ts: ts.toISOString(), tool, model: MODELS[tool],
        source: path ? 'path' : 'inline',
        chars_in: chars, chars_out: 200 + Math.floor(rnd() * 1200),
        latency_ms: 600 + Math.floor(rnd() * 9000),
        ok: rnd() > 0.03,
        backend: remote ? 'remote' : 'local',
        backend_host: remote ? 'pc.tailnet.ts.net:9292' : '127.0.0.1:9292',
        v: '0.11.0', finish_reason: 'stop',
        tokens_in: Math.floor(chars / 4), tokens_out: 120 + Math.floor(rnd() * 400),
        raw_len: chars, ...(chunks > 1 ? {chunks} : {}),
        ...(path ? {path: 'D:\\\\docs\\\\informe-' + (i % 7) + '.md'} : {}),
        familia: 'nueva', densidad: densidadDe(tool, path),
      });
    }
  }
  // Espera frente a lentitud (T14): unos eventos locales llevan la inferencia y la espera por
  // separado, y uno de cada nueve, la marca «lento». Se derivan de los campos que ya hay, sin
  // gastar `rnd()`: la serie de ejemplo sigue siendo la misma de antes.
  events.forEach((e, i) => {
    if (e.backend !== 'local' || !e.ok || i % 3) return;
    const slow = i % 9 === 0;
    e.inference_ms = Math.round(e.latency_ms * (slow ? 0.9 : 0.7));
    e.wait_ms = e.latency_ms - e.inference_ms;
    e.tok_s = slow ? 15.2 : 41.3;
    e.prefill_tok_s = 1850.4;
    if (slow) Object.assign(e, {pace_rel: 0.37, slow: true, free_ram_mb: 7680});
  });
  events.sort((a, b) => a.ts.localeCompare(b.ts));

  // Los cuatro KPIs grandes NO se calculan sobre `events`: el panel los pide a `/api/stats`,
  // porque `/api/events` viene topado y sumar ahí subestimaría. Así que este mock no es opcional
  // —sin él la cabecera del panel enseña el log real de quien captura— y tampoco puede llevar
  // números a mano: se derivan de los mismos eventos de ejemplo, con las reglas de
  // `_accounting()`. Cuando no cuadraban, la imagen se contradecía a sí misma: el pie decía
  // «390 eventos» y el KPI de al lado «120 delegaciones».
  const stats = events.reduce((a, e) => {
    const chunks = e.chunks || 1;
    // `chars_in` de local_describe_image son BYTES, no caracteres. Una imagen sale entera del
    // neto (no hay forma de saber sus tokens de Claude) y se cuenta aparte, en «Imágenes».
    const imagen = e.tool === 'local_describe_image';
    a.calls += 1;
    a.backend_calls += chunks;
    a.tokens_in += e.tokens_in;
    a.tokens_out += e.tokens_out;
    // Un fallo (`ok` exactamente false) no ahorra ni devuelve nada: solo cuenta como error y
    // con los tokens que gastó el backend.
    if (e.ok === false) { a.errors += 1; return a; }
    if (imagen) {
      if (e.source === 'path') {
        a.img_n += 1; a.img_bytes += e.chars_in;
        if (e.tokens_in > 0) a.img_devueltos += e.chars_out;
      }
      return a;
    }
    // Solo `source: 'path'` ahorra contexto: si el input viajó inline, ya pasó por Claude.
    if (e.source === 'path') {
      a.saved += aTokens(e.chars_in, e.densidad.text);
      // Lo que la tool devolvió al contexto se resta: el KPI enseña el NETO.
      if (e.chars_in > 0) a.returned += aTokens(e.chars_out, e.densidad.returned);
    }
    return a;
  }, {calls: 0, backend_calls: 0, tokens_in: 0, tokens_out: 0, saved: 0, returned: 0,
      errors: 0, img_n: 0, img_bytes: 0, img_devueltos: 0});

  // Coste equivalente y cuota de ejemplo. Salen de correr `valoracion.bloque_coste` y
  // `cuota.estado` de verdad sobre un log y un `coste-agregados.json` sintéticos (sin datos de
  // nadie): así la forma es la que sirve `/api/stats` y las cifras cuadran entre sí (la cifra es
  // la suma del desglose, la barra suma las valoradas). La cuota sale «sin calibrar», que es lo
  // que verá casi todo el mundo: nunca se enseña un % sin calibración.
  const COSTE = {cifra: {cota_baja: 6.87, estimacion: 27.4}, motivo: null, eventos: 98,
    T: 1241362,
    barra: {excluido: 22, al_momento: 94, por_relleno: 0, pendiente: 4, supuesto: 0,
      valoradas: 98, con_modelo_supuesto: 4,
      excluidas_por_motivo: {'no es Claude': 15, pruebas: 7}, plazo_dias: 30},
    respaldo: {modelo: 'claude-opus-5-5', nombre: 'Opus 5.5', hilo: 'subagent',
      invalido: false, variable: 'LOCAL_DELEGATE_COSTE_RESPALDO'},
    n_origen: {relleno: 0, agregado: 0, declarado: 98}, n_declarado: {main: 127, subagent: 40},
    densidad: {origen: {medida: 74, sin_numerar: 24, conservadora: 0}, familias: {nueva: 98},
      familia_supuesta: 0, densidad_de_la_familia: 0},
    sin_precio: {n: 0, ids: []},
    fuera_de_la_base: {imagenes: stats.img_n, salida_a_fichero: 0},
    desglose: [
      {modelo: 'claude-opus-5', nombre: 'Opus 5', hilo: 'main', esfuerzo: 'high', casos: 17,
       T: 191044, cota_baja: 1.91, estimacion: 14.04},
      {modelo: 'claude-opus-5-5', nombre: 'Opus 5.5', hilo: 'subagent', esfuerzo: 'high',
       casos: 69, T: 880897, cota_baja: 4.4, estimacion: 11.45},
      {modelo: 'claude-sonnet-5-5', nombre: 'Sonnet 5.5', hilo: 'subagent', esfuerzo: 'medium',
       casos: 8, T: 117678, cota_baja: 0.29, estimacion: 1.24},
      {modelo: 'claude-opus-5-5', nombre: 'Opus 5.5', hilo: 'subagent', esfuerzo: 'sin dato',
       casos: 4, T: 51743, cota_baja: 0.26, estimacion: 0.67},
    ],
    tabla: {consultado: PRECIOS_CONSULTADO,
      fuente: 'https://platform.claude.com/docs/en/about-claude/pricing'},
    comando: 'local-delegate recalcular-coste'};
  const CUOTA = {
    five_hour: {deriva: false, puntos: 1, estado: 'sin calibrar',
      motivo: 'faltan 2 puntos del statusline', puntos_rechazo: 1,
      descartes: {contaminado: 1, delta_pequeno: 2}, reinicio: null},
    seven_day: {deriva: false, puntos: 0, estado: 'sin calibrar',
      motivo: 'faltan 3 puntos del statusline', puntos_rechazo: 0,
      descartes: {delta_pequeno: 3}, reinicio: null},
    hay_agregados: true, comando: 'local-delegate recalcular-coste'};

  const MOCKS = {
    '/api/events': {meta: {chars_per_token: 4, log_dir: 'D:\\\\datos\\\\local-delegate',
      count: events.length, excluded_tests: 0, tests_in_range: 0, files_read: ['usage-202607.jsonl'],
      range_from: events[0].ts, range_to: events[events.length - 1].ts}, events},
    // Un modelo procesando (sale en inflight), otro montado en reposo, el resto frío. Sin
    // `running_ok: true` las filas caerían en «montado»/«frío» (backend que no es llama-swap) y la
    // captura no enseñaría «procesando»; `causa`, `etiqueta` y `detalle` van a null cuando está
    // conectado, como los devuelve el daemon.
    '/api/backend': {available: true, running: [{model: 'gemma4-26b-a4b', state: 'ready'},
      {model: 'qwen36-35b-a3b', state: 'ready'}], running_ok: true, models_stale: false,
      causa: null, etiqueta: null, detalle: null,
      origin: 'local', host: '127.0.0.1:9292',
      models: [{id:'gemma3-4b',status:'unloaded'},{id:'gemma4-26b-a4b',status:'loaded'},
        {id:'qwen36-35b-a3b',status:'loaded'},{id:'qwen35-2b',status:'unloaded'},
        {id:'gemma4-12b',status:'unloaded'}]},
    // Una traducción por chunks a media faena: es lo que enseña el progreso `trozo 9/14`.
    '/api/inflight': {inflight: [{id: '4242:7', tool: 'local_translate', model: 'gemma4-26b-a4b',
      source: 'path', chars_in: 39110, backend: 'local', elapsed_s: 13.4, chunks: 14, chunk: 9}],
      count: 1, last_event_ts: new Date(now.getTime() - 4000).toISOString(),
      now: now.toISOString()},
    '/api/system': {ram: {used_gb: 18.4, total_gb: 31.1, free_gb: 12.7, pct: 59},
      vram: {used_mb: 11890, total_mb: 16311, pct: 72.9, gpu_util_pct: 68},
      processes: [{pid: 4242, name: 'llama-server.exe', ram_mb: 7640, vram_mb: 8420, self: false},
        {pid: 4310, name: 'llama-server.exe', ram_mb: 3180, vram_mb: 3470, self: false},
        {pid: 9001, name: 'pythonw.exe', ram_mb: 44, vram_mb: null, self: true}],
      // Cómputo local en Windows: sin la nota de cómputo remoto ni los textos de otra plataforma.
      platform: 'win32', origin: 'local', host: '127.0.0.1:9292'},
    // La forma la impone renderBackendStats: histogramas con p50/p95 y totales. Con otras
    // claves el panel se pinta con guiones o cae al "sin datos", que es lo que enseñaba la
    // captura anterior aunque el mock dijera available:true.
    '/api/backend/stats': {available: true, stats: {
      total_requests: 1284,
      gen_histogram: {p50: 61.4, p95: 48.2},
      prompt_histogram: {p50: 1840.5, p95: 1210.7},
      total_input_tokens: 486320, total_output_tokens: 138940, total_cache_tokens: 214880}},
    // Los eventos de ejemplo siempre traen `tokens_in`/`tokens_out`, así que no hay ninguno
    // estimado: `estimated_events: 0` es la consecuencia, no una simplificación.
    '/api/stats': {total: {calls: stats.calls, backend_calls: stats.backend_calls,
      errors: stats.errors, tokens_in: stats.tokens_in, tokens_out: stats.tokens_out,
      saved: stats.saved, returned: stats.returned, net: stats.saved - stats.returned,
      estimated_events: 0},
      // El KPI «Contexto conservado» es el NETO (`tokens_context_net`) y su pista dice el bruto
      // y el devuelto: sin estas dos claves la captura lo enseñaría a 0.
      tokens_context_saved: stats.saved, tokens_returned: stats.returned,
      // Interruptor «Pruebas» (test-windows-out-of-metrics): el mock casa por pathname, así que
      // responde igual con `include_tests=1`; sin pruebas ni ventanas abiertas en el ejemplo.
      excluded_tests: 0, tests_in_range: 0, open_test_windows: [],
      tokens_context_net: stats.saved - stats.returned, tokens_generated_local: stats.tokens_out,
      tokens_local_input: stats.tokens_in, backend_calls: stats.backend_calls,
      estimated_events: 0, by_tool: [], by_model: [], by_backend: [],
      // La tarjeta «Quién delegó» lee de aquí. Los nombres son los de clientes MCP reales pero
      // los conteos son inventados, igual que el resto del mock: lo que la imagen no puede
      // enseñar es de quién son las delegaciones de quien regenera la captura. La columna de
      // ahorro lee `tokens_net` (sin ella saldría «–»).
      by_client: [
        {client: 'claude-code', calls: 74, backend_calls: 96,
         tokens_saved: 88240, tokens_net: 81520, tokens_in: 101300, tokens_generated: 6120},
        {client: 'codex-mcp-client', calls: 31, backend_calls: 38,
         tokens_saved: 24880, tokens_net: 22950, tokens_in: 29010, tokens_generated: 2410},
        {client: 'desconocido', calls: 15, backend_calls: 18,
         tokens_saved: 7180, tokens_net: 6640, tokens_in: 8640, tokens_generated: 690},
      ],
      // Las tres tarjetas de coste-api-y-cuota se esconden si falta su clave: sin ellas la
      // captura saldría como antes. «Imágenes» se deriva de los mismos eventos de ejemplo.
      coste: COSTE, cuota: CUOTA,
      imagenes: {n: stats.img_n, bytes: stats.img_bytes, chars_devueltos: stats.img_devueltos},
      densidad_tabla: DENSIDAD},
    // La tarjeta de hooks lee de aquí, y este mock **no es cosmético**: `/api/hooks` se quedó
    // fuera de la lista y el endpoint llegaba al servidor real, así que la captura publicaba la
    // telemetría de quien la regeneraba —conteos por categoría de su propia sesión— justo lo que
    // la cabecera de este script promete que no pasa. Con `LD_HOOK_TELEMETRY_LOG` sin definir la
    // tarjeta se esconde y el fallo no se veía: dependía del entorno de quien capturaba.
    //
    // `total`, `suggested` y `rate` se derivan de las filas en vez de escribirse a mano: si la
    // cabecera dijera un número y la tabla sumara otro, la imagen enseñaría un panel que el
    // dashboard real nunca puede pintar.
    '/api/hooks': (() => {
      const cats = [
        {category: 'bash', suggested: 148, total: 604},
        {category: 'lint', suggested: 96, total: 96},
        {category: 'sin categoría', suggested: 0, total: 214},
        {category: 'summarize', suggested: 72, total: 80},
        {category: 'read', suggested: 41, total: 130},
        {category: 'extract', suggested: 18, total: 22},
      ];
      const total = cats.reduce((a, c) => a + c.total, 0);
      const suggested = cats.reduce((a, c) => a + c.suggested, 0);
      const motivos = [
        {motivo: 'codigo', total: 52},
        {motivo: 'aviso', total: 41},
        {motivo: 'acotada', total: 24},
        {motivo: 'pequeno', total: 13},
      ];
      return {enabled: true, log: 'D:\\\\datos\\\\local-delegate\\\\hooks.jsonl', exists: true,
        total, suggested, rate: suggested / total,
        by_category: cats, by_event: [], by_day: [],
        // La puntería del hook de lectura. Su total es el de la categoría 'read' —130— y los
        // avisos son sus 'suggested' —41—, no números sueltos: un panel cuyas dos tablas no
        // cuadran es un panel que el dashboard real nunca puede pintar.
        read_total: motivos.reduce((a, m) => a + m.total, 0),
        by_motivo: motivos,
        by_ext: [{ext: '.ts', total: 48}, {ext: '.md', total: 39},
                 {ext: '.py', total: 22}, {ext: 'sin extension', total: 21}]};
    })(),
  };

  const real = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = String(typeof input === 'string' ? input : input.url);
    // Se compara el pathname EXACTO, no `includes`: '/api/backend/stats' contiene
    // '/api/backend', así que un match por substring devolvía el mock del panel de modelos
    // al panel de rendimiento, y este se pintaba como "sin datos".
    const path = new URL(url, location.origin).pathname;
    if (Object.prototype.hasOwnProperty.call(MOCKS, path)) {
      return Promise.resolve(new Response(JSON.stringify(MOCKS[path]),
        {status: 200, headers: {'Content-Type': 'application/json'}}));
    }
    return real(input, init);  // /api/status pasa: versión, catálogo y tools son los reales
  };

  // Sin animaciones. El screenshot por CDP espera a que la página quede quieta, y un gráfico
  // animándose o un badge parpadeando lo dejan colgado hasta el timeout.
  if (window.Chart) { Chart.defaults.animation = false; Chart.defaults.animations = false; }
  const style = document.createElement('style');
  style.textContent = '*,*::before,*::after{animation:none!important;transition:none!important}';
  document.head.appendChild(style);
  return events.length;
}"""

# `pollInflight` es asíncrona: si se lanza sin esperarla, `updateLive()` repinta con el estado
# anterior y el indicador sale «EN REPOSO» en vez de enseñar la delegación en curso. Se espera
# a que resuelva y se repinta al final, ya con todo cargado.
REFRESH = """async () => {
  // Los datos de ejemplo cubren 12 días: con el rango en «Hoy» el selector diría una cosa y
  // el gráfico enseñaría otra.
  const sel = document.getElementById('range');
  if (sel) { sel.value = '30'; sel.dispatchEvent(new Event('change')); }
  // fetchStatus va con await: pinta el panel de backend y, en un segundo fetch, el de
  // rendimiento. Sin esperarla el screenshot puede salir con ese panel todavía vacío.
  await fetchStatus();
  pollSystem();
  await fetchData();
  await pollInflight();
  await new Promise(r => setTimeout(r, 1000));
  await pollInflight();
  updateLive();
  return {
    live: document.getElementById('liveTxt')?.textContent,
    canvas: [...document.querySelectorAll('canvas')].length,
    filas: document.querySelectorAll('tbody tr').length,
  };
}"""


def _tablas_del_paquete() -> dict:
    """La tabla de densidad y la fecha de la de precios, leídas del paquete (no son datos de nadie).

    Se leen del fichero en vez de copiarlas al mock para que la captura no se quede con unos
    valores que el vigilante de precios o una medida nueva ya cambiaron.
    """
    datos = ROOT / "src" / "local_delegate" / "resources" / "datos"
    densidad = json.loads((datos / "densidad.json").read_text(encoding="utf-8"))
    precios = json.loads((datos / "precios.json").read_text(encoding="utf-8"))
    return {
        "DENSIDAD": {k: v for k, v in densidad.items() if not k.startswith("_")},
        "PRECIOS_CONSULTADO": precios.get("consultado"),
    }


async def run(url: str, out: Path, width: int, timezone: str) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "falta playwright: uv pip install playwright && "
            "uv run python -m playwright install chromium",
            file=sys.stderr,
        )
        return 2

    # Antes de abrir el navegador: si el dashboard no dice qué versión sirve, no hay captura que
    # valga. Fallar aquí deja el PNG y el manifiesto anteriores intactos.
    try:
        version = _version_del_dashboard(url)
    except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
        print(f"no se pudo leer la versión de {url}: {exc}", file=sys.stderr)
        return 3

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            # La zona se fija: si no, el pie de la captura acaba anunciando la zona de quien
            # la generó y la imagen deja de ser reproducible.
            context = await browser.new_context(
                viewport={"width": width, "height": 1400}, timezone_id=timezone
            )
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle")
            total = await page.evaluate(SEED_AND_MOCK, _tablas_del_paquete())
            info = await page.evaluate(REFRESH)
            # Cinco gráficos: el hero, el de ahorro en el tiempo y los tres donuts/barras.
            if info["canvas"] < 5 or not info["filas"]:
                print(f"el panel no se pobló como se esperaba: {info}", file=sys.stderr)
                return 1
            out.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(out), full_page=True)
            print(f"{out} — {total} eventos, indicador «{info['live']}», {info['canvas']} gráficos")
            manifiesto = _escribir_manifiesto(out, version)
            print(f"{manifiesto} — versión {version}, la que sirvió el dashboard capturado")
        finally:
            await browser.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9393/")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "assets" / "dashboard.png")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--timezone", default="America/Havana", help="zona del pie de página")
    args = parser.parse_args()
    return asyncio.run(run(args.url, args.out, args.width, args.timezone))


if __name__ == "__main__":
    raise SystemExit(main())
