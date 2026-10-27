"""Una línea hostil en el log no corre en el panel: prueba en un navegador real (2026-10-23).

La revisión de seguridad del 2026-10-23 encadenó dos fallos: `record-read` dejaba a cualquier web
añadir una línea a cualquier `.jsonl` (también al log de uso del mes), y el panel pintaba en
`innerHTML` el `tool`, el `model` o el `source` de esa línea sin escapar. Aquí el log de uso trae una
delegación con `<img onerror>` en cada campo de texto que pinta la tabla de actividad y la última
delegación, y se abre el panel con Chromium:

- **sin la CSP** (`bypass_csp`): lo que se prueba es el escape. El texto sale literal y nada corre;
- **con la CSP**: el panel funciona (sus propios scripts pasan, sin violaciones) y nada corre.

Los dos, en tema claro y oscuro. La guarda estática que cuenta las plantillas está en
`test_panel_escaping.py`.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from typing import Self

import pytest
import uvicorn

from local_delegate import config
from local_delegate.web import metrics

pytest.importorskip("playwright.sync_api", reason="Playwright no está instalado (grupo `ui`)")

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

# Puerto fijo propio, y en el mismo grupo de xdist que los demás tests de navegador.
pytestmark = pytest.mark.xdist_group("dashboard_ui")
PORT = 9511


def _payload(field: str) -> str:
    """Lo que intenta correr cada campo: si corre, deja su nombre en `window.__xss`."""
    return f"<img src=x onerror=\"(window.__xss=window.__xss||[]).push('{field}')\">{field}"


HOSTILE_FIELDS = ("tool", "model", "source", "model_requested", "backend", "chunks")


class _Server:
    def __init__(self, port: int) -> None:
        self._server = uvicorn.Server(
            uvicorn.Config(metrics.app, host="127.0.0.1", port=port, log_level="error")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self.url = f"http://127.0.0.1:{port}/"

    def __enter__(self) -> Self:
        self._thread.start()
        for _ in range(200):
            if self._server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("el panel no llegó a levantar")

    def __exit__(self, *_exc) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


@pytest.fixture(autouse=True)
def backend_down(request, monkeypatch):
    """El backend es el servidor que corta cada conexión de la suite, no el llama-swap real."""
    from conftest import CUT_DAEMON

    port = request.node.stash[CUT_DAEMON].port
    monkeypatch.setattr(config, "BASE_URL", f"http://127.0.0.1:{port}/v1")


@pytest.fixture
def hostile_panel(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    now = datetime.now(UTC)
    event = {
        "ts": now.isoformat(timespec="seconds"),
        "chars_in": 1000,
        "chars_out": 100,
        "latency_ms": 10,
        "ok": True,
        "tokens_in": 250,
        "routing": "fallback",
        **{field: _payload(field) for field in HOSTILE_FIELDS},
    }
    log = tmp_path / f"usage-{now:%Y%m}.jsonl"
    log.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
    metrics._FILE_CACHE.clear()
    with _Server(PORT) as server:
        yield server.url


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("with_policy", [False, True], ids=["escape-only", "with-csp"])
def test_a_hostile_log_line_is_text_not_code(hostile_panel, theme, with_policy):
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f"no hay navegador de Playwright instalado: {exc}")
        try:
            # Sin la CSP, Playwright la ignora (`bypass_csp`): queda solo el escape.
            options = {"bypass_csp": not with_policy, "color_scheme": theme}
            context = browser.new_context(**options)
            page = context.new_page()
            page.add_init_script(
                "window.__csp=[];document.addEventListener('securitypolicyviolation',"
                "e=>window.__csp.push(e.violatedDirective+' '+e.blockedURI+' '+e.sample));"
            )
            page.goto(hostile_panel)
            # El panel corrió: la fila de la delegación hostil y «la última» están pintadas.
            page.wait_for_selector("#activity tr[data-i]", timeout=15000)
            page.wait_for_function(
                "document.getElementById('inflightBody').textContent.includes('onerror')",
                timeout=15000,
            )
            page.wait_for_timeout(500)  # una imagen rota dispara `onerror` enseguida

            assert page.evaluate("window.__xss || []") == []
            row = page.text_content("#activity tr[data-i]")
            for field in ("tool", "model", "source", "model_requested", "chunks"):
                assert _payload(field) in row, (field, row)
            last = page.text_content("#inflightBody")
            assert _payload("tool") in last and _payload("model") in last, last
            assert page.locator("#activity img, #inflightBody img").count() == 0
            if with_policy:
                # Los scripts del propio panel pasan: ni una violación al cargar y pintar.
                assert page.evaluate("window.__csp") == []
                # Control: un manejador inline inyectado a mano lo bloquea la CSP.
                page.evaluate(
                    "document.body.insertAdjacentHTML('beforeend',"
                    "'<img src=x onerror=\"window.__probe=1\">')"
                )
                page.wait_for_timeout(500)
                assert page.evaluate("window.__probe === undefined")
                assert any("script-src" in v for v in page.evaluate("window.__csp"))
        finally:
            browser.close()
