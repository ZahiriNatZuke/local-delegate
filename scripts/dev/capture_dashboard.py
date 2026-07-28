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

El README avisa de que son «datos de ejemplo». Mantener ese pie es parte del trato.

Requiere Playwright, que **no** es dependencia del proyecto:

    uv pip install playwright && uv run python -m playwright install chromium

Uso (con el dashboard sirviendo, por ejemplo el daemon en :9393):

    uv run python scripts/dev/capture_dashboard.py
    uv run python scripts/dev/capture_dashboard.py --url http://127.0.0.1:9494/ --out /tmp/d.png
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]

# Datos de ejemplo. La semilla fija hace la captura reproducible; los nombres de archivo y el
# host remoto son inventados a propósito para no filtrar nada de la máquina real.
SEED_AND_MOCK = """() => {
  const TOOLS = ['local_summarize','local_translate','local_extract','local_classify',
    'local_lint_summary','local_boilerplate','local_commit_msg','local_explain_code',
    'local_describe_image','local_delegate'];
  const MODELS = {local_summarize:'llama31-8b',local_translate:'llama31-8b',
    local_extract:'gemma3-4b',local_classify:'qwen35-2b',local_lint_summary:'gemma3-4b',
    local_boilerplate:'qwen25-coder-14b',local_commit_msg:'qwen25-coder-14b',
    local_explain_code:'qwen25-coder-14b',local_describe_image:'qwen3-vl-8b',
    local_delegate:'gemma3-4b'};
  let seed = 20260728;
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;

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
      });
    }
  }
  events.sort((a, b) => a.ts.localeCompare(b.ts));

  const MOCKS = {
    '/api/events': {meta: {chars_per_token: 4, log_dir: 'D:\\\\datos\\\\local-delegate',
      count: events.length, files_read: ['usage-202607.jsonl'],
      range_from: events[0].ts, range_to: events[events.length - 1].ts}, events},
    // Un modelo procesando (sale en inflight), otro montado en reposo, el resto frío.
    '/api/backend': {available: true, running: [{model: 'llama31-8b'}, {model: 'qwen25-coder-14b'}],
      origin: 'local', host: '127.0.0.1:9292',
      models: [{id:'gemma3-4b',status:'unloaded'},{id:'llama31-8b',status:'loaded'},
        {id:'qwen25-coder-14b',status:'loaded'},{id:'qwen35-2b',status:'unloaded'},
        {id:'qwen3-vl-8b',status:'unloaded'}]},
    // Una traducción por chunks a media faena: es lo que enseña el progreso `trozo 9/14`.
    '/api/inflight': {inflight: [{id: '4242:7', tool: 'local_translate', model: 'llama31-8b',
      source: 'path', chars_in: 39110, backend: 'local', elapsed_s: 13.4, chunks: 14, chunk: 9}],
      count: 1, last_event_ts: new Date(now.getTime() - 4000).toISOString(),
      now: now.toISOString()},
    '/api/system': {ram: {used_gb: 18.4, total_gb: 31.1, free_gb: 12.7, pct: 59},
      vram: {used_mb: 11890, total_mb: 16311, pct: 72.9, gpu_util_pct: 68},
      processes: [{pid: 4242, name: 'llama-server.exe', ram_mb: 7640, vram_mb: 8420, self: false},
        {pid: 4310, name: 'llama-server.exe', ram_mb: 3180, vram_mb: 3470, self: false},
        {pid: 9001, name: 'pythonw.exe', ram_mb: 44, vram_mb: null, self: true}]},
    '/api/backend/stats': {available: true, stats: {requests: 1284,
      avg_tokens_per_second: 61.4, avg_time_to_first_token_ms: 214, total_tokens: 486320}},
  };

  const real = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = String(typeof input === 'string' ? input : input.url);
    for (const [key, body] of Object.entries(MOCKS)) {
      if (url.includes(key)) {
        return Promise.resolve(new Response(JSON.stringify(body),
          {status: 200, headers: {'Content-Type': 'application/json'}}));
      }
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
  fetchStatus(); pollSystem();
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
            total = await page.evaluate(SEED_AND_MOCK)
            info = await page.evaluate(REFRESH)
            if info["canvas"] < 6 or not info["filas"]:
                print(f"el panel no se pobló como se esperaba: {info}", file=sys.stderr)
                return 1
            out.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(out), full_page=True)
            print(f"{out} — {total} eventos, indicador «{info['live']}», {info['canvas']} gráficos")
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
