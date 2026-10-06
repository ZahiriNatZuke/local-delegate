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
import re
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
    # Solo se fija lo que rodea a `PAGE`: la definición de `F` cambia (REQ-030) y no es asunto de
    # este módulo.
    m = re.search(r"const CPT = 4, F = .*?, PAGE = (\d+);", metrics.HTML)
    assert m, "no se encontró la sentencia `const CPT = 4, F = …, PAGE = …;`"
    return int(m.group(1))


def _eventos(cuantos: int) -> str:
    """Un JSONL de uso con `cuantos` eventos recientes y distinguibles entre sí.

    **Todos tienen que caer en TU día local**, porque el panel agrupa por día local y el rango que
    trae puesto es «hoy». Separarlos un minuto a ciegas hacía que el test dependiera de la hora a la
    que corriera: el CI lo cazó a las 00:06 UTC, con solo 7 de las 13 filas dentro del día, una sola
    página y el pager oculto — un test midiendo el entorno en vez del producto. El paso se acota al
    hueco que de verdad hay desde la medianoche, así que a las 00:00:05 se aprietan en esos cinco
    segundos y siguen siendo `cuantos` filas, que es lo que el test mide.
    """
    ahora = datetime.now(UTC)
    medianoche_local = ahora.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    paso = min(timedelta(minutes=1), (ahora - medianoche_local) / max(cuantos, 1))
    lineas = []
    for n in range(cuantos):
        lineas.append(
            json.dumps(
                {
                    "ts": (ahora - paso * n).isoformat(timespec="seconds"),
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
    """Lanza Chromium, o salta el test con motivo si no está instalado.

    El `raise` de después del `skip` es inalcanzable —`pytest.skip` lanza `Skipped`— y está para
    que la función no mezcle un `return` explícito con una caída implícita al final: de un vistazo
    no se ve que el camino de excepción no continúa, y un analizador estático lo marca con razón.
    """
    try:
        return pw.chromium.launch()
    except PlaywrightError as exc:
        pytest.skip(f"no hay navegador de Playwright instalado: {exc}")
        raise AssertionError("inalcanzable: pytest.skip lanza Skipped") from exc


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


# --- Presentación: tipografía por rol, KPI neto y latencia (REQ-004, REQ-030 a REQ-034) --------
#
# Un solo arranque del panel mide todo y cada test mira una cifra: así cada arreglo tiene su
# propio assert (y su propio control positivo) sin lanzar Chromium nueve veces. Los hooks y los
# procesos se simulan con `page.route` porque dependen de la telemetría y de la máquina; la
# actividad, el KPI y «Quién delegó» salen del log de verdad, por el `/api/stats` real.

# Una delegación buena por `path` con salida (bruto 16.597, devuelto 1.793, neto 14.804) y un
# fallo por `path` que, con la regla de T1, no suma nada. Con `chars_out > 0` bruto y neto difieren,
# que es lo que deja a los mutantes «hero con el bruto» y «columna con el bruto» a la vista.
# coste-api-y-cuota: en tokens de Claude, con la fila fundida por el respaldo (Opus 5.5): 40.000
# chars por `path` sin extensión (clase `otro`, respaldo (3), c = 2,41) → 40000 × 100 // 241 =
# 16.597; 4.000 chars devueltos en prosa sin numerar (c = 2,23) → 4000 × 100 // 223 = 1.793.
_CHARS_LEIDOS, _CHARS_DEVUELTOS = 40_000, 4_000
_BRUTO, _DEVUELTO, _NETO = 16_597, 1_793, 14_804

_HOOKS = {
    "enabled": True,
    "total": 10,
    "suggested": 3,
    "rate": 0.3,
    "by_category": [{"category": "read", "total": 8, "suggested": 2}],
    "by_motivo": [{"motivo": "pequeño", "total": 5}],
    "read_total": 5,
}

_PROCESO = {"name": "python.exe", "pid": 4321, "ram_mb": 2048, "vram_mb": None, "self": True}

_MEDIR = """() => {
  const fam = el => el ? getComputedStyle(el).fontFamily : null;
  const sonda = cls => {
    const e = document.createElement('span'); e.className = cls; e.textContent = 'x';
    document.getElementById('modelsBody').appendChild(e);
    const f = fam(e); e.remove(); return f;
  };
  const nota = Array.from(document.querySelectorAll('#hooksBody div'))
    .find(d => d.textContent.includes('decides tú') && !d.querySelector('div'));
  const hero = document.querySelector('.card.hero');
  const lat = Array.from(document.querySelectorAll('.card'))
    .find(c => (c.querySelector('.k-lbl')||{}).textContent?.includes('Latencia media'));
  const fonts = document.querySelector('link[href*="fonts.googleapis.com/css2"]');
  return {
    th: Array.from(document.querySelectorAll('thead th')).map(fam),
    selfchip: fam(document.querySelector('.selfchip')),
    mrole: sonda('mrole'),
    empty: sonda('empty'),
    nota: fam(nota),
    hooksPrimera: fam(document.querySelector('#hooksBody tbody td:first-child')),
    clientesPrimera: fam(document.querySelector('#clientsBody tbody td:first-child')),
    refrescar: fam(document.getElementById('reload')),
    cerrarAyuda: fam(document.getElementById('helpClose')),
    body: fam(document.body),
    fuentes: fonts ? fonts.href : '',
    kpi: hero.querySelector('.k-val').firstChild.textContent.trim(),
    pista: hero.querySelector('.k-hint').innerText,
    tooltip: hero.querySelector('.info')?.getAttribute('data-tip') || '',
    columnaNeto: document.querySelector('#clientsBody tbody td:nth-child(4)').innerText.trim(),
    latencia: lat.querySelector('.k-val').innerText.trim(),
    latenciaFilas: Array.from(document.querySelectorAll('#activity tbody td:nth-child(7)'))
      .map(td => td.innerText.trim()),
  };
}"""


def _miles(n: int) -> str:
    """El formato que pide REQ-030: punto de miles siempre, desde cuatro cifras."""
    return f"{n:,}".replace(",", ".")


def _log_presentacion() -> str:
    ahora = datetime.now(UTC)
    medianoche_local = ahora.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    paso = min(timedelta(seconds=30), (ahora - medianoche_local) / 2)
    comun = {"model": "modelo-de-prueba", "source": "path", "backend": "local"}
    eventos = [
        {
            **comun,
            "ts": ahora.isoformat(timespec="seconds"),
            "tool": "local_summarize",
            "chars_in": _CHARS_LEIDOS,
            "chars_out": _CHARS_DEVUELTOS,
            "latency_ms": 2000,
            "ok": True,
            "tokens_in": 9000,
            "tokens_out": 900,
            "client": "claude-code",
        },
        {
            **comun,
            "ts": (ahora - paso).isoformat(timespec="seconds"),
            "tool": "local_extract",
            "chars_in": 80_000,
            "chars_out": 0,
            "latency_ms": 4000,
            "ok": False,
            "error_class": "connect_error",
            "client": "claude-code",
        },
    ]
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in eventos) + "\n"


@pytest.fixture(scope="module")
def medidas(tmp_path_factory):
    """Pinta el panel una vez con hooks, clientes, actividad y procesos, y lo mide todo."""
    carpeta = tmp_path_factory.mktemp("presentacion")
    hoy = datetime.now(UTC)
    (carpeta / f"usage-{hoy:%Y%m}.jsonl").write_text(_log_presentacion(), encoding="utf-8")
    sistema = {"ram": None, "vram": None, "processes": [_PROCESO]}

    def _json(cuerpo):
        return lambda ruta: ruta.fulfill(
            status=200, content_type="application/json", body=json.dumps(cuerpo)
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "LOG_DIR", carpeta)
        mp.setattr(config, "USAGE_LOG", carpeta / "usage.jsonl")
        mp.setattr(config, "WEB_FONTS", True)
        metrics._FILE_CACHE.clear()
        with _Servidor(9497) as servidor, sync_playwright() as pw:
            navegador = _navegador(pw)
            pagina = navegador.new_page()
            # Sin red: `getComputedStyle` devuelve la familia declarada aunque no llegue la cara.
            pagina.route(
                re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort()
            )
            pagina.route(re.compile(r"/api/hooks(\?|$)"), _json(_HOOKS))
            pagina.route(re.compile(r"/api/system(\?|$)"), lambda r: _json(sistema)(r))
            pagina.goto(servidor.url)
            for selector in (
                "#activity tbody tr",
                "#hooksBody table",
                "#clientsBody table",
                "#procTable thead",
                ".card.hero",
            ):
                pagina.wait_for_selector(selector)
            m = pagina.evaluate(_MEDIR)

            # La fila vacía de procesos es otro estado de la misma tarjeta: se fuerza y se repinta.
            sistema["processes"] = []
            pagina.evaluate("() => pollSystem()")
            pagina.wait_for_function(
                "() => document.getElementById('procTable').innerText.includes('Ningún proceso')"
            )
            m["procesosVacia"] = pagina.evaluate(
                "() => getComputedStyle(document.querySelector('#procTable td')).fontFamily"
            )
            navegador.close()
    metrics._FILE_CACHE.clear()
    return m


def test_todas_las_cabeceras_comparten_familia(medidas):
    """REQ-034 (a): `.num` y `th.mono` ya no ponen mono a media fila de cabecera."""
    familias = set(medidas["th"])
    assert len(medidas["th"]) >= 10, "control positivo: hooks, clientes, actividad y procesos"
    assert len(familias) == 1, familias
    assert "Inter" in familias.pop()


def test_la_chip_del_daemon_va_como_sus_gemelas(medidas):
    """REQ-034 (b): «DAEMON MCP» con la familia de `.mrole`, no la mono de su celda."""
    assert medidas["selfchip"] == medidas["mrole"]


def test_la_fila_vacia_de_procesos_va_como_los_demas_vacios(medidas):
    """REQ-034 (c)."""
    assert medidas["procesosVacia"] == medidas["empty"]


def test_la_nota_de_hooks_es_prosa_en_Inter(medidas):
    """REQ-034 (d): la nota dejó de reutilizar `.empty`, que es mono."""
    assert medidas["nota"] is not None, "control positivo: la nota tiene que estar pintada"
    assert medidas["nota"].startswith("Inter")


def test_la_primera_columna_de_hooks_y_clientes_va_en_mono(medidas):
    """REQ-034 (e): categoría y cliente son identificadores de la telemetría."""
    assert "JetBrains Mono" in medidas["hooksPrimera"]
    assert "JetBrains Mono" in medidas["clientesPrimera"]


def test_los_botones_heredan_la_familia_del_body(medidas):
    """REQ-034 (g). «Refrescar» ya la tenía por `.btn`; el que no la tenía es el cierre de la
    ayuda (`.help-x`), que se quedaba con la del agente de usuario."""
    assert medidas["refrescar"] == medidas["body"]
    assert medidas["cerrarAyuda"] == medidas["body"]


def test_la_hoja_de_fuentes_pide_JetBrains_Mono_400(medidas):
    """REQ-034 (f). `getComputedStyle` no ve la cara que falta: se mira la URL."""
    assert "JetBrains+Mono:wght@400" in medidas["fuentes"]


def test_el_KPI_hero_ensena_el_neto_y_la_pista_el_bruto_y_el_devuelto(medidas):
    """REQ-004 en el navegador, con el formato de REQ-030."""
    assert medidas["kpi"] == _miles(_NETO)
    assert _miles(_BRUTO) in medidas["pista"]
    assert _miles(_DEVUELTO) in medidas["pista"]
    assert "relecturas" in medidas["tooltip"]


def test_quien_delego_ensena_el_neto_del_cliente(medidas):
    """REQ-004: la columna de ahorro de «Quién delegó» es `tokens_net`."""
    assert medidas["columnaNeto"] == _miles(_NETO)


def test_la_latencia_va_en_segundos(medidas):
    """REQ-032: KPI y columna de actividad en segundos, con coma."""
    assert medidas["latencia"].endswith(" s"), medidas["latencia"]
    assert medidas["latencia"] == "3,0 s"
    assert sorted(medidas["latenciaFilas"]) == ["2,0 s", "4,0 s"]


# --- Sistema con cómputo remoto (REQ-025, REQ-034 h) -------------------------------------------


def test_la_nota_de_computo_remoto_sale_en_Inter_y_sin_fila_vacia(tmp_path, monkeypatch):
    """La Mac contra el backend de la PC: la nota es lo único que se ve, y es prosa (Inter).

    `/api/system` se intercepta con `page.route` porque la plataforma y el origen son de la máquina.
    """
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    metrics._FILE_CACHE.clear()
    sistema = {
        "ram": None,
        "vram": None,
        "processes": [],
        "platform": "darwin",
        "origin": "remote",
        "host": "100.64.0.2:9292",
    }
    with _Servidor(9496) as servidor, sync_playwright() as pw:
        navegador = _navegador(pw)
        pagina = navegador.new_page()
        pagina.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        pagina.route(
            re.compile(r"/api/system(\?|$)"),
            lambda r: r.fulfill(
                status=200, content_type="application/json", body=json.dumps(sistema)
            ),
        )
        pagina.goto(servidor.url)
        pagina.wait_for_function(
            "() => !document.getElementById('metersBody').innerText.includes('Leyendo')"
        )
        m = pagina.evaluate(
            """() => {
              const n = document.getElementById('procNota');
              return {
                texto: n ? n.innerText : '',
                familia: n ? getComputedStyle(n).fontFamily : '',
                procesos: document.getElementById('procTable').innerText,
                memoria: document.getElementById('metersBody').innerText,
              };
            }"""
        )
        navegador.close()
    texto = m["texto"]
    assert "El backend corre en" in texto
    assert "100.64.0.2:9292" in texto
    assert m["familia"].startswith("Inter"), m["familia"]
    assert "Ningún proceso del backend detectado" not in m["procesos"]
    assert "RAM y VRAM no se miden en macOS todavía" in m["memoria"]


# --- Coste equivalente, cuota e imágenes (coste-api-y-cuota, T6) -------------------------------


def test_los_bloques_de_coste_cuota_e_imagenes(tmp_path, monkeypatch):
    """El panel pinta lo que trae `/api/stats`: el rótulo del coste con su nota de tarifa plana, la
    cuota «sin calibrar» (sin `coste-agregados.json` en esta carpeta) y el número de imágenes. Las
    líneas son prosa (`.nota`, en Inter)."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "COSTE_RESPALDO", "")
    ahora = datetime.now(UTC)
    medianoche_local = ahora.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    paso = min(timedelta(seconds=30), (ahora - medianoche_local) / 2)
    comun = {"ok": True, "client": "claude-code", "backend": "local", "model": "modelo-de-prueba"}
    eventos = [
        {
            **comun,
            "ts": ahora.isoformat(timespec="seconds"),
            "tool": "local_summarize",
            "source": "path",
            "path": "C:/docs/notas.md",
            "chars_in": 1_000_000,
            "chars_out": 0,
            "tokens_in": 9000,
            "tokens_out": 100,
        },
        {
            **comun,
            "ts": (ahora - paso).isoformat(timespec="seconds"),
            "tool": "local_describe_image",
            "source": "path",
            "chars_in": 250000,
            "chars_out": 800,
            "tokens_in": 1200,
            "tokens_out": 200,
        },
    ]
    (tmp_path / f"usage-{ahora:%Y%m}.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in eventos) + "\n", encoding="utf-8"
    )
    metrics._FILE_CACHE.clear()
    with _Servidor(9495) as servidor, sync_playwright() as pw:
        navegador = _navegador(pw)
        pagina = navegador.new_page()
        pagina.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        pagina.goto(servidor.url)
        pagina.wait_for_selector("#costeBody .nota")
        pagina.wait_for_selector("#cuotaBody .nota")
        pagina.wait_for_selector("#imagenesBody .nota")
        m = pagina.evaluate(
            """() => ({
              coste: document.getElementById('costeBody').innerText,
              cuota: document.getElementById('cuotaBody').innerText,
              cuotaHead: document.getElementById('cuotaHead').innerText,
              imagenes: document.getElementById('imagenesBody').innerText,
              familia: getComputedStyle(document.querySelector('#costeBody .nota')).fontFamily,
              desglose: document.querySelectorAll('#costeBody tbody tr').length,
            })"""
        )
        navegador.close()
    metrics._FILE_CACHE.clear()
    assert "Equivalente estimado a precio de API: entre $" in m["coste"]
    # Sin relleno: Opus 5.5 en subagente con N = 40 → $2,50 y ~$6,50 (escenario de la spec).
    assert "entre $2,50 y ~$6,50" in m["coste"]
    assert "No es dinero que hayas ahorrado: tu suscripción es de tarifa plana." in m["coste"]
    assert "1 de 1 con modelo supuesto: Opus 5.5 en subagente" in m["coste"]
    assert m["desglose"] == 1
    assert "sin calibrar" in m["cuota"]
    assert "%" not in m["cuota"].replace("dispersión", "")  # ningún % de cuota sin calibrar
    assert m["cuotaHead"] == "sin calibrar"
    assert "1 imagen" in m["imagenes"]
    assert "250.000 bytes" in m["imagenes"]
    assert m["familia"].startswith("Inter"), m["familia"]


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
