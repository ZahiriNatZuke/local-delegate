#!/usr/bin/env python3
"""Comprueba que el dashboard calcula los rangos en la hora LOCAL del navegador.

El dashboard hacía todo en UTC y, para quien vive en UTC−4, una delegación de las nueve de la
noche caía en el día siguiente: barra equivocada del gráfico y fuera de «Hoy». El arreglo vive
en el JS, así que la única verificación honesta es abrirlo en un navegador con la zona horaria
forzada — que es justo lo que hace este script.

`tests/test_metrics.py` cubre el flanco estático (que no quede ningún `Date.UTC(` en el HTML);
esto cubre el dinámico: qué instante calcula de verdad `computeRange('today')` en cada zona.

Requiere Playwright, que **no** es dependencia del proyecto:

    uv pip install playwright && python -m playwright install chromium

Uso (con el dashboard ya sirviendo):

    LOCAL_DELEGATE_WEB_PORT=9494 uv run python -m local_delegate.web.metrics &
    python scripts/dev/dashboard_timezone_check.py --url http://127.0.0.1:9494/

Para forzar los cuatro estados del indicador sin esperar 30 minutos, se manipula `state` y se
llama a `updateLive()` a mano: eso es lo que hace `--check-live`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

# Zonas elegidas para cubrir los tres casos que importan: offset positivo grande, negativo
# (el del autor) y positivo pequeño — en Madrid «hoy» empieza el día anterior en UTC.
DEFAULT_ZONES = ["Asia/Tokyo", "America/Havana", "Europe/Madrid"]

PROBE = """() => ({
    tz: typeof TZ !== 'undefined' ? TZ : null,
    offset: typeof TZ_OFFSET_TXT !== 'undefined' ? TZ_OFFSET_TXT : null,
    today: computeRange('today'),
    live: document.getElementById('liveTxt')?.textContent ?? null,
})"""

# Los cuatro estados del indicador dependen del paso del tiempo, no de la llegada de datos:
# se falsean el reloj del servidor y el último evento para verlos sin esperar.
LIVE_STATES = """() => {
    const out = [];
    const now = Date.now();
    for (const [label, ago] of [['en curso', 0], ['en vivo', 60e3], ['en reposo', 40*60e3]]) {
        state.lastEventTs = new Date(now - ago).toISOString();
        state.inflight = label === 'en curso' ? [{tool: 'local_translate'}] : [];
        updateLive();
        out.push([label, document.getElementById('liveTxt')?.textContent]);
    }
    state.lastEventTs = null; state.inflight = [];
    updateLive();
    out.push(['sin datos', document.getElementById('liveTxt')?.textContent]);
    return out;
}"""


async def run(url: str, zones: list[str], check_live: bool) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "falta playwright: uv pip install playwright && python -m playwright install chromium",
            file=sys.stderr,
        )
        return 2

    failures = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            for zone in zones:
                context = await browser.new_context(timezone_id=zone)
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle")
                info = await page.evaluate(PROBE)

                start = info["today"]["from"] if isinstance(info["today"], dict) else info["today"]
                print(f"{zone:>16}  offset={info['offset']}  hoy empieza en {start}")
                if info["tz"] != zone:
                    print(f"  ERROR: el dashboard cree estar en {info['tz']}", file=sys.stderr)
                    failures += 1

                if check_live:
                    for label, text in await page.evaluate(LIVE_STATES):
                        print(f"    {label:>10} -> {text}")
                await context.close()
        finally:
            await browser.close()
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9393/")
    parser.add_argument("--zone", action="append", dest="zones", help="repetible")
    parser.add_argument("--check-live", action="store_true", help="fuerza los 4 estados")
    args = parser.parse_args()
    return asyncio.run(run(args.url, args.zones or DEFAULT_ZONES, args.check_live))


if __name__ == "__main__":
    raise SystemExit(main())
