#!/usr/bin/env python3
"""Capturas del panel de B4: español e inglés, claro y oscuro, con los datos de ejemplo del README.

Sirve `web/metrics.py` del árbol en un puerto propio (9499), con el backend apuntando a un puerto
cerrado y el directorio de logs en una carpeta temporal: no toca el daemon ni el backend reales.
Los `/api/*` los sustituyen los datos deterministas de `scripts/dev/capture_dashboard.py`
(`SEED_AND_MOCK`), salvo `/api/status`, que es el real del árbol en el idioma pedido.

Uso (desde la raíz del árbol, con el grupo `ui`):

    uv run python .sdd/changes/english-names-bilingual-output/evidence/B4/capture_screens.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent / "screenshots"
PORT = 9499


def _capture_module():
    spec = importlib.util.spec_from_file_location(
        "capture_dashboard", ROOT / "scripts" / "dev" / "capture_dashboard.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dead_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(log_dir: Path) -> uvicorn.Server:
    from local_delegate import config
    from local_delegate.web import metrics

    config.LOG_DIR = log_dir
    config.USAGE_LOG = log_dir / "usage.jsonl"
    config.BASE_URL = f"http://127.0.0.1:{_dead_port()}/v1"
    server = uvicorn.Server(
        uvicorn.Config(metrics.app, host="127.0.0.1", port=PORT, log_level="error")
    )
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError("el panel no levantó")


async def _shoot(capture, url: str) -> list[Path]:
    from playwright.async_api import async_playwright

    shots = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for locale, lang in (("es-ES", "es"), ("en-US", "en")):
            for theme in ("dark", "light"):
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 1400},
                    locale=locale,
                    timezone_id="America/Havana",
                )
                page = await context.new_page()
                await page.add_init_script(
                    f"try{{localStorage.setItem('ld-theme','{theme}')}}catch(e){{}}"
                )
                await page.goto(url, wait_until="networkidle")
                await page.evaluate(capture.SEED_AND_MOCK, capture._package_tables())
                await page.evaluate(capture.REFRESH)
                assert await page.evaluate("() => document.documentElement.lang") == lang
                path = OUT / f"panel-{lang}-{theme}.png"
                await page.screenshot(path=str(path), full_page=True)
                shots.append(path)
                # La cabecera con el selector, a tamaño real.
                path = OUT / f"header-{lang}-{theme}.png"
                await page.locator("header.topbar").screenshot(path=str(path))
                shots.append(path)
                # El diálogo de información del coste: la prosa vive aquí, no en la tarjeta.
                await page.click("#costInfo")
                await page.wait_for_function("() => document.getElementById('infoDlg').open")
                path = OUT / f"dialog-cost-{lang}-{theme}.png"
                await page.locator("#infoDlg").screenshot(path=str(path))
                shots.append(path)
                await context.close()
        await browser.close()
    return shots


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    capture = _capture_module()
    with tempfile.TemporaryDirectory() as tmp:
        server = _serve(Path(tmp))
        try:
            shots = asyncio.run(_shoot(capture, f"http://127.0.0.1:{PORT}/"))
        finally:
            server.should_exit = True
    for shot in shots:
        print(shot.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
