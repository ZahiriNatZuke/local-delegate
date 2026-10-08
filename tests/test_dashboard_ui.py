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
  // La nota de los hooks vive en el diálogo de información (su ⓘ), no en la tarjeta.
  const nota = Array.from(document.querySelectorAll('#dlgHooks p'))
    .find(d => d.textContent.includes('decides tú'));
  const hero = document.querySelector('.card.hero');
  const lat = Array.from(document.querySelectorAll('.card'))
    .find(c => (c.querySelector('.k-lbl')||{}).textContent?.includes('Latencia'));
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
    kpi: hero.querySelector('.k-num').firstChild.textContent.trim(),
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
    """REQ-034 (d): la nota dejó de reutilizar `.empty`, que es mono. Ahora va en el diálogo."""
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


def _log_coste_e_imagen(tmp_path, monkeypatch) -> None:
    """Un resumen por path y una imagen, hoy: hay cifra de coste y una imagen en el rango."""
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


# Lo que se mide de las tres tarjetas: ningún párrafo, la misma tipografía que los KPIs de arriba,
# el hueco con la fila de debajo y el diálogo de información con todo el texto que salió de ellas.
_MEDIR_TARJETAS = """() => {
  const cuerpos = ['costeBody', 'cuotaBody', 'imagenesBody'].map(i => document.getElementById(i));
  const textos = cuerpos.flatMap(c => [...c.querySelectorAll('*')]
    .filter(e => !e.children.length).map(e => e.textContent.trim()));
  const estilo = sel => { const e = document.querySelector(sel);
    if (!e) return null; const s = getComputedStyle(e);
    return [s.fontFamily, s.fontSize, s.fontWeight].join('|'); };
  const vis = id => getComputedStyle(document.getElementById(id)).display !== 'none';
  const coste = document.getElementById('costeCard').getBoundingClientRect();
  const fila = document.getElementById('cuotaImgRow').getBoundingClientRect();
  return {
    coste: document.getElementById('costeBody').innerText,
    imagenes: document.getElementById('imagenesBody').innerText,
    parrafos: cuerpos.reduce((n, c) => n + c.querySelectorAll('p, .nota').length, 0),
    masLargo: Math.max(...textos.map(t => t.length)),
    desglose: document.querySelectorAll('#costeBody tbody tr').length,
    cuotaVisible: vis('cuotaCard'), imagenesVisible: vis('imagenesCard'),
    valCoste: estilo('#costeBody .k-val'), valKpi: estilo('#kpis .card:not(.hero) .k-val'),
    lblCoste: estilo('#costeBody .k-lbl'), lblKpi: estilo('#kpis .k-lbl'),
    hueco: Math.round(fila.top - coste.bottom),
  };
}"""


def test_las_tarjetas_de_coste_cuota_e_imagenes_llevan_cifras_y_no_parrafos(tmp_path, monkeypatch):
    """El panel pinta lo que trae `/api/stats` como cifras con la forma de los KPIs: el coste con
    su cota baja, su estimación y el desglose; la imagen con sus bytes. La cuota «sin calibrar» (sin
    `coste-agregados.json` en esta carpeta) **no se pinta**. Ningún párrafo en el cuerpo."""
    _log_coste_e_imagen(tmp_path, monkeypatch)
    with _Servidor(9495) as servidor, sync_playwright() as pw:
        navegador = _navegador(pw)
        pagina = navegador.new_page()
        pagina.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        pagina.goto(servidor.url)
        pagina.wait_for_selector("#costeBody .kstat")
        pagina.wait_for_selector("#imagenesBody .kstat")
        m = pagina.evaluate(_MEDIR_TARJETAS)
        navegador.close()
    metrics._FILE_CACHE.clear()
    # Sin relleno: Opus 5.5 en subagente con N = 40 → $2,50 y ~$6,50 (escenario de la spec).
    assert "$2,50" in m["coste"]
    assert "~$6,50" in m["coste"]
    assert "no es un ahorro: tarifa plana" in m["coste"]
    assert m["desglose"] == 1
    assert not m["cuotaVisible"]  # sin calibrar no hay tarjeta
    assert m["imagenesVisible"]
    assert "250.000" in m["imagenes"]
    assert m["parrafos"] == 0
    assert m["masLargo"] <= 40, m["masLargo"]
    assert m["valCoste"] == m["valKpi"], (m["valCoste"], m["valKpi"])
    assert m["lblCoste"] == m["lblKpi"], (m["lblCoste"], m["lblKpi"])
    assert m["hueco"] == 16, m["hueco"]  # el mismo `gap` que entre el resto de tarjetas


def test_el_dialogo_de_informacion_lleva_el_texto_y_se_cierra_con_esc(tmp_path, monkeypatch):
    """El ⓘ de la tarjeta de coste abre un diálogo con los supuestos, la calibración de la cuota y
    la nota de las imágenes; Esc lo cierra y el foco vuelve al botón."""
    _log_coste_e_imagen(tmp_path, monkeypatch)
    with _Servidor(9495) as servidor, sync_playwright() as pw:
        navegador = _navegador(pw)
        pagina = navegador.new_page()
        pagina.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        pagina.goto(servidor.url)
        pagina.wait_for_selector("#costeBody .kstat")
        pagina.focus("#costeInfo")
        pagina.keyboard.press("Enter")
        abierto = pagina.evaluate("() => document.getElementById('infoDlg').open")
        texto = pagina.inner_text("#infoDlg")
        pagina.keyboard.press("Escape")
        m = pagina.evaluate(
            """() => ({abierto: document.getElementById('infoDlg').open,
                       foco: document.activeElement && document.activeElement.id})"""
        )
        navegador.close()
    metrics._FILE_CACHE.clear()
    assert abierto
    assert "Equivalente estimado a precio de API: entre $2,50 y ~$6,50" in texto
    assert "No es dinero que hayas ahorrado: tu suscripción es de tarifa plana." in texto
    assert "1 de 1 con modelo supuesto: Opus 5.5 en subagente" in texto
    assert "Precios de la tabla del paquete del" in texto
    assert "sin calibrar" in texto
    assert "1 imagen" in texto
    assert "250.000 bytes" in texto
    assert not m["abierto"]
    assert m["foco"] == "costeInfo"


def test_la_cuota_calibrada_sale_como_medidor(tmp_path, monkeypatch):
    """Con una ventana calibrada la tarjeta aparece con la cifra A – B % y un medidor; la otra,
    sin calibrar, dice «sin calibrar» con «–». `/api/stats` se intercepta para inyectar la cuota:
    calibrarla de verdad pide tres puntos del statusline."""
    _log_coste_e_imagen(tmp_path, monkeypatch)
    cuota_calibrada = {
        "five_hour": {"estado": "calibrado", "puntos": 4, "a_pct": 3.4, "b_pct": 11.9},
        "seven_day": {"estado": "sin calibrar", "puntos": 1, "motivo": "faltan 2 puntos"},
        "hay_agregados": True,
        "comando": "local-delegate recalcular-coste",
    }

    def _inyectar(ruta):
        respuesta = ruta.fetch()
        datos = respuesta.json()
        datos["cuota"] = cuota_calibrada
        ruta.fulfill(response=respuesta, body=json.dumps(datos))

    with _Servidor(9495) as servidor, sync_playwright() as pw:
        navegador = _navegador(pw)
        pagina = navegador.new_page()
        pagina.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        pagina.route(re.compile(r"/api/stats(\?|$)"), _inyectar)
        pagina.goto(servidor.url)
        pagina.wait_for_selector("#cuotaBody .qrange")
        m = pagina.evaluate(
            """() => ({
              texto: document.getElementById('cuotaBody').innerText,
              cabecera: document.getElementById('cuotaHead').innerText,
              medidores: document.querySelectorAll('#cuotaBody .qrange').length,
              ancho: document.querySelector('#cuotaBody .qrange .qb').style.width,
            })"""
        )
        navegador.close()
    metrics._FILE_CACHE.clear()
    assert "3,4 – 11,9" in m["texto"]
    assert "sin calibrar" in m["texto"]
    assert m["cabecera"] == "1 ventana calibrada"
    assert m["medidores"] == 1
    assert m["ancho"] == "8.5%"


def test_los_controles_nativos_siguen_al_tema(panel):
    """`color-scheme` sigue al tema: es lo que pinta claro el icono del calendario de los
    `<input type=date>` en oscuro (antes salía negro sobre el panel) y la lista del `<select>`."""
    url, _ = panel
    with sync_playwright() as pw:
        navegador = _navegador(pw)
        pagina = navegador.new_page()
        pagina.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        pagina.goto(url)
        oscuro = pagina.evaluate(
            "() => getComputedStyle(document.getElementById('rangeFrom')).colorScheme"
        )
        pagina.click("#theme")
        claro = pagina.evaluate(
            "() => getComputedStyle(document.getElementById('rangeFrom')).colorScheme"
        )
        navegador.close()
    assert oscuro == "dark"
    assert claro == "light"


# Cada cifra de los KPIs, con su unidad, dentro de su tarjeta: ni la cifra desborda su caja ni la
# unidad pasa del borde interior de la tarjeta (el hero tiene `overflow:hidden` y la cortaba).
_DESBORDES_KPI = """() => [...document.querySelectorAll('#kpis .k-val')].flatMap(v => {
  const card = v.closest('.card'), c = card.getBoundingClientRect();
  const borde = c.right - parseFloat(getComputedStyle(card).paddingRight) + 0.5;
  const fuera = [];
  if (v.scrollWidth > v.clientWidth) fuera.push(v.textContent + ': la cifra desborda su caja');
  const u = v.querySelector('.unit');
  if (u && u.getBoundingClientRect().right > borde) fuera.push(v.textContent + ': unidad cortada');
  return fuera;
})"""


def test_la_unidad_de_los_kpis_no_se_corta(tmp_path, monkeypatch):
    """«3.161.168 tok» en el hero salía como «3.161.168 to» entre 1320 y 1440 px. Con cifras de
    siete dígitos en los KPIs, a 1280, 1366 y 1440 px y en los dos temas, nada se sale."""
    _log_coste_e_imagen(tmp_path, monkeypatch)

    def _cifras_grandes(ruta):
        respuesta = ruta.fetch()
        datos = respuesta.json()
        datos.update(
            tokens_context_net=3_161_168,
            tokens_context_saved=3_250_647,
            tokens_returned=89_479,
            tokens_generated_local=123_478,
            tokens_local_input=1_898_456,
        )
        ruta.fulfill(response=respuesta, body=json.dumps(datos))

    desbordes = {}
    with _Servidor(9495) as servidor, sync_playwright() as pw:
        navegador = _navegador(pw)
        for ancho in (1280, 1366, 1440):
            for tema in ("dark", "light"):
                pagina = navegador.new_page(viewport={"width": ancho, "height": 900})
                pagina.add_init_script(
                    f"try{{localStorage.setItem('ld-theme','{tema}')}}catch(e){{}}"
                )
                pagina.route(
                    re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort()
                )
                pagina.route(re.compile(r"/api/stats(\?|$)"), _cifras_grandes)
                pagina.goto(servidor.url)
                pagina.wait_for_function(
                    "() => document.querySelector('#kpis .hero .k-val')?.textContent.includes('3.161.168')"
                )
                desbordes[(ancho, tema)] = pagina.evaluate(_DESBORDES_KPI)
                pagina.close()
        navegador.close()
    metrics._FILE_CACHE.clear()
    assert all(not v for v in desbordes.values()), desbordes


# --- Etiquetas legibles, tipografía, simetría de los KPIs y la tarjeta Sistema -----------------

# Claves internas tal como llegan del log y de la API, y una desconocida para el respaldo.
_HOOKS_CRUDOS = {
    "enabled": True,
    "log": "hooks.jsonl",
    "exists": True,
    "total": 60,
    "suggested": 20,
    "rate": 1 / 3,
    "by_category": [
        {"category": "read", "suggested": 8, "total": 30},
        {"category": "shell", "suggested": 6, "total": 10},
        {"category": "extract", "suggested": 4, "total": 5},
        {"category": "sin categoría", "suggested": 0, "total": 10},
        {"category": "clave_rara_nueva", "suggested": 2, "total": 5},
    ],
    "by_event": [],
    "by_day": [],
    "read_total": 30,
    "by_motivo": [
        {"motivo": "avisó", "total": 8},
        {"motivo": "acotada", "total": 6},
        {"motivo": "codigo", "total": 5},
        {"motivo": "pequeno", "total": 4},
        {"motivo": "mcp_ajeno", "total": 4},
        {"motivo": "motivo_que_no_existe", "total": 3},
    ],
    "by_ext": [],
}
_SISTEMA = {
    "ram": {"used_gb": 13.4, "total_gb": 31.1, "free_gb": 17.7, "pct": 43},
    "vram": {"used_mb": 8908, "total_mb": 16311, "pct": 54.6, "gpu_util_pct": 68},
    "processes": [{"pid": 4242, "name": "llama-server.exe", "ram_mb": 7640, "vram_mb": 8420}],
    "platform": "win32",
    "origin": "local",
    "host": "127.0.0.1:9292",
}


def _json(cuerpo):
    return lambda ruta: ruta.fulfill(
        status=200, content_type="application/json", body=json.dumps(cuerpo)
    )


def _clientes_crudos(ruta):
    """`/api/stats` real con un desglose por cliente que trae claves internas."""
    respuesta = ruta.fetch()
    datos = respuesta.json()
    fila = {"calls": 1, "backend_calls": 1, "tokens_net": 10, "tokens_saved": 10}
    datos["by_client"] = [
        {**fila, "client": "claude-code"},
        {**fila, "client": "codex-mcp-client"},
        {**fila, "client": "desconocido"},
        {**fila, "client": "cliente_nuevo"},
    ]
    ruta.fulfill(response=respuesta, body=json.dumps(datos))


def _pagina_completa(pw, url, ancho=1366, tema="dark"):
    navegador = _navegador(pw)
    pagina = navegador.new_page(viewport={"width": ancho, "height": 1000})
    pagina.add_init_script(f"try{{localStorage.setItem('ld-theme','{tema}')}}catch(e){{}}")
    pagina.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
    pagina.route(re.compile(r"/api/hooks(\?|$)"), _json(_HOOKS_CRUDOS))
    pagina.route(re.compile(r"/api/system(\?|$)"), _json(_SISTEMA))
    pagina.route(re.compile(r"/api/stats(\?|$)"), _clientes_crudos)
    pagina.goto(url)
    pagina.wait_for_selector("#hooksBody tbody tr")
    pagina.wait_for_selector("#clientsBody tbody tr")
    pagina.wait_for_selector("#costeBody tbody tr")
    pagina.wait_for_function(
        "() => document.getElementById('metersBody').innerText.includes('GiB')"
    )
    return navegador, pagina


_PRIMERAS_COLUMNAS = """() => {
  const ids = ['hooksBody', 'clientsBody', 'costeBody'];
  return ids.flatMap(id => [...document.querySelectorAll('#' + id + ' tbody tr td:first-child')]
    .map(td => td.innerText.trim()));
}"""


def test_ninguna_tabla_ensena_claves_internas(tmp_path, monkeypatch):
    """La primera columna de las tablas de hooks, clientes y coste dice etiquetas legibles: ni
    guiones bajos ni minúscula inicial. Una clave desconocida sale humanizada, no cruda. Los nombres
    de modelo (primera columna del coste) ya empiezan en mayúscula; los de proceso y tool no pasan
    por aquí (son nombres propios)."""
    _log_coste_e_imagen(tmp_path, monkeypatch)
    with _Servidor(9495) as servidor, sync_playwright() as pw:
        navegador, pagina = _pagina_completa(pw, servidor.url)
        celdas = pagina.evaluate(_PRIMERAS_COLUMNAS)
        esfuerzo = pagina.inner_text("#costeBody tbody tr td:nth-child(3)")
        hilo = pagina.inner_text("#costeBody tbody tr td:nth-child(2)")
        navegador.close()
    metrics._FILE_CACHE.clear()
    assert len(celdas) == 5 + 6 + 4 + 1, celdas  # guarda: llegaron todas las filas
    malas = [c for c in celdas if "_" in c or not c[:1].isupper()]
    assert not malas, malas
    for esperada in (
        "Lectura",
        "Shell",
        "Extracción",
        "Sin categoría",
        "Avisó",
        "Lectura acotada",
        "Código",
        "Pequeño",
        "Por otro MCP",
        "Claude Code",
        "Codex",
        "Desconocido",
    ):
        assert esperada in celdas, (esperada, celdas)
    # El respaldo: la clave desconocida, sin guiones bajos y con mayúscula.
    assert "Clave rara nueva" in celdas
    assert "Motivo que no existe" in celdas
    assert "Cliente nuevo" in celdas
    assert hilo == "Subagente"
    assert esfuerzo == "Sin dato"


_TIPOGRAFIA_TABLAS = """() => {
  const estilo = el => { const s = getComputedStyle(el); return s.fontFamily + '|' + s.fontSize; };
  const tablas = [...document.querySelectorAll('table')].filter(t => t.querySelector('tbody td'));
  return tablas.map(t => ({
    id: t.id || t.closest('.card').querySelector('h2').textContent,
    primera: estilo(t.querySelector('tbody td:first-child')),
    cabecera: t.querySelector('thead th') ? estilo(t.querySelector('thead th')) : null,
  }));
}"""


def test_todas_las_tablas_comparten_tipografia_por_columna(tmp_path, monkeypatch):
    """Primera columna y cabecera con la misma familia y tamaño en todas las tablas del panel,
    también la de procesos de Sistema (antes en 12 px)."""
    _log_coste_e_imagen(tmp_path, monkeypatch)
    with _Servidor(9495) as servidor, sync_playwright() as pw:
        navegador, pagina = _pagina_completa(pw, servidor.url)
        pagina.wait_for_selector("#procTable tbody td")
        tablas = pagina.evaluate(_TIPOGRAFIA_TABLAS)
        navegador.close()
    metrics._FILE_CACHE.clear()
    assert len(tablas) >= 6, tablas  # procesos, coste, actividad, clientes y las dos de hooks
    assert len({t["primera"] for t in tablas}) == 1, tablas
    assert len({t["cabecera"] for t in tablas if t["cabecera"]}) == 1, tablas


def test_la_nota_de_los_hooks_esta_en_el_dialogo(tmp_path, monkeypatch):
    """El párrafo de «los hooks sugieren» ya no está en la tarjeta: lo abre su ⓘ."""
    _log_coste_e_imagen(tmp_path, monkeypatch)
    with _Servidor(9495) as servidor, sync_playwright() as pw:
        navegador, pagina = _pagina_completa(pw, servidor.url)
        cuerpo = pagina.inner_text("#hooksBody")
        parrafos = pagina.evaluate(
            "() => document.querySelectorAll('#hooksBody p, #hooksBody .nota').length"
        )
        pagina.click("#hooksInfo")
        titulo = pagina.inner_text("#infoDlgTitle")
        visible = pagina.inner_text("#dlgHooks")
        oculto = pagina.evaluate("() => document.getElementById('dlgCoste').hidden")
        navegador.close()
    metrics._FILE_CACHE.clear()
    assert "sugieren" not in cuerpo
    assert parrafos == 0
    assert titulo == "Sugerencias de los hooks"
    assert "Los hooks sugieren; delegar lo decides tú." in visible
    assert oculto  # el diálogo enseña solo las secciones de su grupo


# Por tarjeta de la fila de KPIs: dónde empieza la cifra y cuánto mide el bloque del título,
# relativo a la propia tarjeta (a 400 px van apiladas, una por fila).
_SIMETRIA_KPIS = """() => [...document.querySelectorAll('#kpis > .card')].map(card => {
  const c = card.getBoundingClientRect();
  return {
    lbl: card.querySelector('.k-lbl').textContent.trim(),
    cifra: Math.round(card.querySelector('.k-val').getBoundingClientRect().top - c.top),
    titulo: Math.round(card.querySelector('.k-top').getBoundingClientRect().height),
    pista: Math.round(card.querySelector('.k-hint').getBoundingClientRect().height),
    texto: card.querySelector('.k-val').innerText + ' ' + card.querySelector('.k-hint').innerText,
  };
})"""

# Un decimal con punto («0.0», «13.4»): un punto seguido de uno o dos dígitos y nada más. El punto
# de miles (1.514) lleva tres dígitos detrás y no cuenta.
_DECIMAL_CON_PUNTO = re.compile(r"\d\.\d{1,2}(?!\d)")


def test_la_fila_de_kpis_es_simetrica_y_usa_coma_decimal(tmp_path, monkeypatch):
    """A 1280, 1366, 1440 y 400 px, en los dos temas: misma altura del título, la cifra empieza a la
    misma altura en todas las tarjetas, la pista ocupa lo mismo y ningún número usa punto decimal."""
    _log_coste_e_imagen(tmp_path, monkeypatch)
    resultados = {}
    with _Servidor(9495) as servidor, sync_playwright() as pw:
        for ancho in (1280, 1366, 1440, 400):
            for tema in ("dark", "light"):
                navegador, pagina = _pagina_completa(pw, servidor.url, ancho, tema)
                resultados[(ancho, tema)] = pagina.evaluate(_SIMETRIA_KPIS)
                navegador.close()
    metrics._FILE_CACHE.clear()
    for clave, tarjetas in resultados.items():
        assert len(tarjetas) == 6, (clave, tarjetas)
        cifras = [t["cifra"] for t in tarjetas]
        assert max(cifras) - min(cifras) <= 2, (clave, tarjetas)
        assert len({t["titulo"] for t in tarjetas}) == 1, (clave, tarjetas)
        pistas = [t["pista"] for t in tarjetas]
        assert max(pistas) - min(pistas) <= 1, (clave, tarjetas)
        for t in tarjetas:
            assert not _DECIMAL_CON_PUNTO.search(t["texto"]), (clave, t)
    # La pista de «Delegaciones» es una frase corta; el desglose va al tooltip.
    delegaciones = next(t for t in resultados[(1366, "dark")] if "Delegaciones" in t["lbl"])
    assert "trocear" not in delegaciones["texto"]
    assert "llamada" in delegaciones["texto"]


def test_sistema_ensena_la_carga_de_la_gpu_como_barra(tmp_path, monkeypatch):
    """La cabecera de Sistema ya no lleva «GPU 68%»: la carga es una fila con barra, entre la RAM y
    la VRAM, y todas las cifras van con coma decimal y espacio antes de %."""
    _log_coste_e_imagen(tmp_path, monkeypatch)
    with _Servidor(9495) as servidor, sync_playwright() as pw:
        navegador, pagina = _pagina_completa(pw, servidor.url)
        cabecera = pagina.evaluate(
            "() => [...document.querySelectorAll('.panel-h')]"
            ".find(h => h.querySelector('h2').textContent === 'Sistema').innerText"
        )
        filas = pagina.evaluate(
            "() => [...document.querySelectorAll('#metersBody .meter-lbl')].map(e => e.innerText)"
        )
        barras = pagina.evaluate("() => document.querySelectorAll('#metersBody .meter').length")
        navegador.close()
    metrics._FILE_CACHE.clear()
    assert "GPU" not in cabecera and "%" not in cabecera, cabecera
    assert len(filas) == 3 and barras == 3, filas
    assert filas[1].upper().startswith("CARGA DE LA GPU"), filas
    assert "68 %" in filas[1]
    assert "13,4 / 31,1 GiB · 43 %" in filas[0]
    assert "55 %" in filas[2]  # 54,6 redondeado, sin punto decimal
    for f in filas:
        assert not _DECIMAL_CON_PUNTO.search(f), f


def test_la_flecha_del_selector_de_rango_no_se_va_al_pasar_el_raton(panel):
    """`.btn:hover` cambiaba el atajo `background` y borraba la flecha (un `background-image`)."""
    url, _ = panel
    with sync_playwright() as pw:
        navegador = _navegador(pw)
        pagina = navegador.new_page()
        pagina.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        pagina.goto(url)
        imagen = "() => getComputedStyle(document.getElementById('range')).backgroundImage"
        reposo = pagina.evaluate(imagen)
        pagina.hover("#range")
        encima = pagina.evaluate(imagen)
        pagina.focus("#range")
        foco = pagina.evaluate(imagen)
        navegador.close()
    assert "gradient" in reposo
    assert encima == reposo
    assert foco == reposo


_SPARK_Y_PISTA = """() => {
  const hero = document.querySelector('#kpis .hero');
  const canvas = hero.querySelector('.spark canvas').getBoundingClientRect();
  const rango = document.createRange();
  rango.selectNodeContents(hero.querySelector('.k-hint'));
  const texto = rango.getBoundingClientRect();
  const lineas = [...document.querySelectorAll('#kpis .k-lbl')].map(l => ({
    lbl: l.textContent.trim(), alto: Math.round(l.getBoundingClientRect().height)}));
  return {canvasTop: canvas.top, canvasAlto: canvas.height, textoBottom: texto.bottom, lineas};
}"""


def test_la_linea_del_hero_no_pisa_su_pista(tmp_path, monkeypatch):
    """La línea del hero cruzaba «bruto … − devuelto …». La caja del gráfico empieza por debajo
    del texto de la pista, en los cuatro anchos y los dos temas. A 1366 px y más, además, cada
    título de KPI cabe en una línea."""
    _log_coste_e_imagen(tmp_path, monkeypatch)
    medidas = {}
    with _Servidor(9495) as servidor, sync_playwright() as pw:
        for ancho in (1280, 1366, 1440, 400):
            for tema in ("dark", "light"):
                navegador, pagina = _pagina_completa(pw, servidor.url, ancho, tema)
                medidas[(ancho, tema)] = pagina.evaluate(_SPARK_Y_PISTA)
                navegador.close()
    metrics._FILE_CACHE.clear()
    for clave, m in medidas.items():
        assert m["canvasAlto"] > 0, (clave, m)  # guarda: el gráfico se pintó
        assert m["canvasTop"] >= m["textoBottom"], (clave, m)
        if clave[0] >= 1366:
            altos = {x["alto"] for x in m["lineas"]}
            assert max(altos) <= 24, (clave, m["lineas"])  # una línea (19 px); dos son 35


def test_backend_y_en_curso_hablan_en_espanol(tmp_path, monkeypatch):
    """Estados de modelo con mayúscula inicial, «Trozo 9/14», «· 39.110 car.» y «peticiones» /
    «caché» en el rendimiento del backend: nada en minúscula de máquina ni en inglés."""
    _log_coste_e_imagen(tmp_path, monkeypatch)
    backend = {
        "available": True,
        "running": [{"model": "modelo-b", "state": "ready"}],
        "running_ok": True,
        "models_stale": False,
        "causa": None,
        "etiqueta": None,
        "detalle": None,
        "origin": "local",
        "host": "127.0.0.1:9292",
        "models": [
            {"id": "modelo-a", "status": "unloaded"},
            {"id": "modelo-b", "status": "loaded"},
        ],
    }
    en_curso = {
        "inflight": [
            {
                "id": "1:1",
                "tool": "local_translate",
                "model": "modelo-a",
                "source": "path",
                "chars_in": 39110,
                "backend": "local",
                "elapsed_s": 13.4,
                "chunks": 14,
                "chunk": 9,
            }
        ],
        "count": 1,
        "last_event_ts": datetime.now(UTC).isoformat(),
        "now": datetime.now(UTC).isoformat(),
    }
    rendimiento = {
        "available": True,
        "stats": {
            "total_requests": 1284,
            "gen_histogram": {"p50": 61.4, "p95": 48.2},
            "prompt_histogram": {"p50": 1840.5, "p95": 1210.7},
            "total_input_tokens": 486320,
            "total_output_tokens": 138940,
            "total_cache_tokens": 214880,
        },
    }
    with _Servidor(9495) as servidor, sync_playwright() as pw:
        navegador = _navegador(pw)
        pagina = navegador.new_page()
        pagina.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        pagina.route(re.compile(r"/api/backend(\?|$)"), _json(backend))
        pagina.route(re.compile(r"/api/inflight(\?|$)"), _json(en_curso))
        pagina.route(re.compile(r"/api/backend/stats(\?|$)"), _json(rendimiento))
        pagina.goto(servidor.url)
        pagina.wait_for_selector("#inflightBody .chunkchip")
        pagina.wait_for_function("() => document.getElementById('bstatsHead').textContent")
        m = pagina.evaluate(
            """() => ({
              estados: [...document.querySelectorAll('#modelsBody .mstate')].map(e => e.textContent),
              curso: document.getElementById('inflightBody').textContent,
              cabecera: document.getElementById('bstatsHead').textContent,
              rendimiento: document.getElementById('backendStats').textContent,
            })"""
        )
        navegador.close()
    metrics._FILE_CACHE.clear()
    assert m["estados"], m  # guarda: hay filas de modelos
    assert all(e[:1].isupper() for e in m["estados"]), m["estados"]
    assert "Trozo 9/14" in m["curso"], m["curso"]
    assert "· 39.110 car." in m["curso"], m["curso"]
    assert "chars" not in m["curso"]
    assert "1.284 peticiones" in m["cabecera"], m["cabecera"]
    assert "caché" in m["rendimiento"] and "cache " not in m["rendimiento"], m["rendimiento"]


def test_la_leyenda_del_origen_del_input_esta_en_espanol(panel):
    """«path»/«inline» pasan a «Por ruta (path)» y «Texto en línea (inline)»; el centro dice «por
    ruta». Se lee del gráfico de Chart.js: la leyenda se pinta en el canvas."""
    url, _ = panel
    with sync_playwright() as pw:
        navegador = _navegador(pw)
        pagina = navegador.new_page()
        pagina.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        pagina.goto(url)
        pagina.wait_for_function("() => state.charts && state.charts.srcDonut")
        m = pagina.evaluate(
            """() => ({etiquetas: state.charts.srcDonut.data.labels,
                       centro: state.charts.srcDonut.options.plugins.centerText.sub})"""
        )
        navegador.close()
    assert m["etiquetas"] == ["Por ruta (path)"], m  # el log de `panel` es todo por path
    assert m["centro"] == "por ruta"


def test_ya_no_hay_tarjeta_de_donde_corrio_el_computo(panel):
    """Se quitó: el backend es fijo por instalación y el donut siempre daba 100 % de un lado. La
    columna de origen de la actividad sigue, con etiqueta legible."""
    url, _ = panel
    with sync_playwright() as pw:
        navegador = _navegador(pw)
        pagina = navegador.new_page()
        pagina.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        pagina.goto(url)
        pagina.wait_for_selector("#activity tbody tr .org")
        m = pagina.evaluate(
            """() => ({
              donut: !!document.getElementById('originDonut'),
              titulos: [...document.querySelectorAll('h2')].map(h => h.textContent),
              origen: document.querySelector('#activity tbody tr .org').textContent,
              fila: getComputedStyle(document.getElementById('modelBar').closest('.grid'))
                .gridTemplateColumns.split(' ').length,
            })"""
        )
        navegador.close()
    assert not m["donut"]
    assert "Dónde corrió el cómputo" not in m["titulos"]
    assert m["origen"] == "Local"
    assert m["fila"] == 2  # la fila de donuts queda en dos columnas, sin hueco


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
