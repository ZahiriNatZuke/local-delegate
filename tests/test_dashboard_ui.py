"""El panel **interactuado**, en un navegador de verdad.

Es la última capa que le faltaba al dashboard, y las tres se complementan sin solaparse:

- `test_metrics.py` prueba lo que sirve el backend (`/api/events`, `/api/stats`, …).
- `test_dashboard_js.py` **ejecuta con node** las funciones que deciden qué se pide y cómo se
  agrupa (`computeRange`, `localDayKey`, `byDay`, `agg`, `fmtHace`).
- aquí se carga la página entera y se **pulsan los controles**, que es lo único que puede ver un
  fallo de cableado: un `onclick` que no se registró, un id renombrado a medias, un botón que no
  se deshabilita en la última página.

**Qué se prueba y qué no, medido y no supuesto.** El pendiente hablaba de «paginación y filtros de
tool/modelo». Los filtros de tool y modelo **no existen** en el panel: los controles reales son el
selector de rango, el pager, el tema, el auto-refresco y recargar. Así que aquí se cubre lo que hay
y se dice que es lo que hay.

Se salta solo —con motivo visible— donde no haya Playwright o navegador, porque este es el único
módulo de la suite que necesita algo más que Python. En el CI **no** se salta: el job `lint` lo
corre con Chromium instalado, y por eso el módulo lleva un test que grita si se saltó en el sitio
donde no debía saltarse.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Self

import pytest
import uvicorn

from local_delegate import config
from local_delegate.web import metrics

pytest.importorskip("playwright.sync_api", reason="Playwright no está instalado (grupo `ui`)")

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


# `PAGE` del JS del panel. Se lee del propio HTML en vez de clavarlo aquí: si alguien cambia el
# tamaño de página, este módulo debe seguir generando dos páginas y no fallar por un número viejo.
def _tam_pagina() -> int:
    marca = "const CPT = 4, F = new Intl.NumberFormat('es'), PAGE = "
    i = metrics.HTML.index(marca) + len(marca)
    return int(metrics.HTML[i : metrics.HTML.index(";", i)].strip())


def _eventos(cuantos: int) -> str:
    """Un JSONL de uso con `cuantos` eventos recientes y distinguibles entre sí."""
    ahora = datetime.now(UTC)
    lineas = []
    for n in range(cuantos):
        lineas.append(
            json.dumps(
                {
                    "ts": (ahora - timedelta(minutes=n)).isoformat(timespec="seconds"),
                    # El índice va en el nombre de la tool: así una fila de la página 2 es
                    # distinguible de una de la página 1 **por su texto**, que es lo que se compara.
                    "tool": f"local_tool_{n:03d}",
                    "model": "modelo-de-prueba",
                    "source": "path",
                    "chars_in": 1000 + n,
                    "chars_out": 100 + n,
                    "latency_ms": 10 + n,
                    "ok": True,
                    "tokens_in": 250 + n,
                    "backend": "local",
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lineas) + "\n"


class _Servidor:
    """Sirve el dashboard real en un hilo, contra un log de uso controlado."""

    def __init__(self, puerto: int) -> None:
        self._server = uvicorn.Server(
            uvicorn.Config(metrics.app, host="127.0.0.1", port=puerto, log_level="error")
        )
        self._hilo = threading.Thread(target=self._server.run, daemon=True)
        self.url = f"http://127.0.0.1:{puerto}/"

    def __enter__(self) -> Self:
        self._hilo.start()
        for _ in range(200):
            if self._server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("el dashboard no llegó a levantar")

    def __exit__(self, *_exc) -> None:
        self._server.should_exit = True
        self._hilo.join(timeout=10)


@pytest.fixture
def panel(tmp_path, monkeypatch):
    """Dashboard servido con dos páginas justas de actividad."""
    por_pagina = _tam_pagina()
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    hoy = datetime.now(UTC)
    (tmp_path / f"usage-{hoy:%Y%m}.jsonl").write_text(_eventos(por_pagina + 3), encoding="utf-8")
    metrics._FILE_CACHE.clear()  # cachea por (mtime, size); el fichero es nuevo en cada test

    with _Servidor(9498) as servidor:
        yield servidor.url, por_pagina


def _navegador(pw):
    try:
        return pw.chromium.launch()
    except PlaywrightError as exc:
        pytest.skip(f"no hay navegador de Playwright instalado: {exc}")


def _filas_visibles(pagina) -> list[str]:
    return pagina.eval_on_selector_all(
        "#activity tbody tr td:nth-child(2)", "tds => tds.map(td => td.innerText.trim())"
    )


def test_la_paginacion_de_la_tabla_cambia_las_filas(panel):
    """Lo que ninguna otra capa ve: que pulsar «siguiente» reescribe la tabla.

    El control positivo es la primera aserción: se comprueba que **había** más de una página antes
    de pulsar. Sin eso, un panel que no paginara nada pasaría este test enseñando la misma tabla
    dos veces.
    """
    url, por_pagina = panel
    with sync_playwright() as pw:
        navegador = _navegador(pw)
        pagina = navegador.new_page()
        pagina.goto(url)
        pagina.wait_for_selector("#activity tbody tr")

        assert pagina.locator("#pager").is_visible(), (
            "control positivo fallido: con más de una página el pager tiene que verse"
        )
        assert pagina.locator("#pgInfo").inner_text().strip().endswith("/ 2")
        assert pagina.locator("#pgPrev").is_disabled(), "en la página 1 no se puede retroceder"

        primera = _filas_visibles(pagina)
        assert len(primera) == por_pagina

        pagina.locator("#pgNext").click()
        pagina.wait_for_function(
            "n => document.querySelectorAll('#activity tbody tr').length !== n", arg=por_pagina
        )

        segunda = _filas_visibles(pagina)
        assert segunda and not set(segunda) & set(primera), (
            f"la página 2 debe traer filas distintas: {segunda[:3]} vs {primera[:3]}"
        )
        assert pagina.locator("#pgNext").is_disabled(), "en la última página no se puede avanzar"

        pagina.locator("#pgPrev").click()
        pagina.wait_for_function(
            "n => document.querySelectorAll('#activity tbody tr').length === n", arg=por_pagina
        )
        assert _filas_visibles(pagina) == primera, "volver atrás debe devolver la misma página 1"

        navegador.close()


def test_cambiar_el_rango_vuelve_a_pedir_los_datos_y_resetea_la_pagina(panel):
    """El selector de rango decide qué se le pide al backend, y reinicia el pager.

    Si no reiniciara, cambiar de rango desde la página 2 dejaría al usuario mirando una página que
    en el rango nuevo puede no existir.
    """
    url, _por_pagina = panel
    with sync_playwright() as pw:
        navegador = _navegador(pw)
        pagina = navegador.new_page()

        pedidos: list[str] = []
        pagina.on("request", lambda r: pedidos.append(r.url) if "/api/events" in r.url else None)

        pagina.goto(url)
        pagina.wait_for_selector("#activity tbody tr")
        pagina.locator("#pgNext").click()
        # `startsWith('2')` y no `includes('2')`: el texto es «1 / 2» en la primera página, así que
        # un `includes` daría por buena la espera sin que el clic hubiera hecho nada.
        pagina.wait_for_function(
            "() => document.getElementById('pgInfo').innerText.trim().startsWith('2')"
        )

        antes = len(pedidos)
        # El valor es "7", no "7d": se comprueba contra el `<option>` que existe de verdad. Un
        # `select_option` con un valor inventado no cambia nada y Playwright espera hasta agotar
        # el plazo, así que aquí el test fallaba por el test y no por el panel.
        pagina.select_option("#range", "7")
        for _ in range(100):
            if len(pedidos) > antes:
                break
            time.sleep(0.05)

        assert len(pedidos) > antes, "cambiar el rango tiene que volver a pedir /api/events"
        assert "from=" in pedidos[-1] and "to=" in pedidos[-1]
        pagina.wait_for_function(
            "() => document.getElementById('pgInfo').innerText.trim().startsWith('1')"
        )

        navegador.close()


def test_el_rango_personalizado_ensena_los_dos_campos_de_fecha(panel):
    """`custom` es el único valor que cambia la forma del panel, y estaba sin ejercer."""
    url, _ = panel
    with sync_playwright() as pw:
        navegador = _navegador(pw)
        pagina = navegador.new_page()
        pagina.goto(url)
        pagina.wait_for_selector("#activity tbody tr")

        assert not pagina.locator("#rangeFrom").is_visible()  # control positivo: parten ocultos

        pagina.select_option("#range", "custom")
        pagina.wait_for_selector("#rangeFrom", state="visible")
        assert pagina.locator("#rangeTo").is_visible()

        navegador.close()


@pytest.mark.skipif(
    os.environ.get("CI") != "true", reason="solo aplica al CI, que sí instala el navegador"
)
def test_en_el_CI_este_modulo_NO_puede_saltarse():
    """La guarda de «esto llegó a comprobar algo».

    Un módulo que se salta solo es cómodo en local y peligroso en el CI: si el paso que instala
    Chromium se rompe o se borra, los tests de arriba pasarían a saltarse y **nadie lo notaría** —
    verde para siempre sobre cero comprobaciones. Este test falla en ese caso.
    """
    with sync_playwright() as pw:
        navegador = pw.chromium.launch()  # sin `_navegador`: aquí un fallo debe ser rojo, no skip
        navegador.close()
