"""El panel **interactuado**, en un navegador de verdad.

Es la última capa que le faltaba al dashboard, y las tres se complementan sin solaparse:

- `test_metrics.py` prueba lo que sirve el backend (`/api/events`, `/api/stats`, …).
- `test_dashboard_js.py` **ejecuta con node** las funciones que deciden qué se pide y cómo se
  agrupa (`computeRange`, `localDayKey`, `byDay`, `agg`, `fmtAgo`).
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

# Todo el módulo en un mismo worker de `pytest-xdist` (`--dist loadgroup`): sus servidores
# escuchan en puertos fijos (9495 lo comparten una docena de tests), así que dos workers
# chocarían al levantarlos. En serie dentro del grupo, el resto de la suite sigue en paralelo.
pytestmark = pytest.mark.xdist_group("dashboard_ui")


# `PAGE` del JS del panel. Se lee del propio HTML en vez de clavarlo aquí: si alguien cambia el
# tamaño de página, este módulo debe seguir generando dos páginas y no fallar por un número viejo.
def _page_size() -> int:
    # Solo se fija lo que rodea a `PAGE`: la definición de `F` cambia (REQ-030) y no es asunto de
    # este módulo.
    m = re.search(r"const CPT = 4, F = .*?, PAGE = (\d+);", metrics.HTML)
    assert m, "no se encontró la sentencia `const CPT = 4, F = …, PAGE = …;`"
    return int(m.group(1))


def _events(count: int) -> str:
    """Un JSONL de uso con `count` eventos recientes y distinguibles entre sí.

    **Todos tienen que caer en TU día local**, porque el panel agrupa por día local y el rango que
    trae puesto es «hoy». Separarlos un minuto a ciegas hacía que el test dependiera de la hora a la
    que corriera: el CI lo cazó a las 00:06 UTC, con solo 7 de las 13 filas dentro del día, una sola
    página y el pager oculto — un test midiendo el entorno en vez del producto. El paso se acota al
    hueco que de verdad hay desde la medianoche, así que a las 00:00:05 se aprietan en esos cinco
    segundos y siguen siendo `cuantos` filas, que es lo que el test mide.
    """
    now = datetime.now(UTC)
    local_midnight = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    step = min(timedelta(minutes=1), (now - local_midnight) / max(count, 1))
    lines = []
    for n in range(count):
        lines.append(
            json.dumps(
                {
                    "ts": (now - step * n).isoformat(timespec="seconds"),
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
    return "\n".join(lines) + "\n"


class _Server:
    """Sirve el dashboard real en un hilo, contra un log de uso controlado."""

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
        raise RuntimeError("el dashboard no llegó a levantar")

    def __exit__(self, *_exc) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


@pytest.fixture
def panel(tmp_path, monkeypatch):
    """Dashboard servido con dos páginas justas de actividad."""
    per_page = _page_size()
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    today = datetime.now(UTC)
    (tmp_path / f"usage-{today:%Y%m}.jsonl").write_text(_events(per_page + 3), encoding="utf-8")
    metrics._FILE_CACHE.clear()  # cachea por (mtime, size); el fichero es nuevo en cada test

    with _Server(9498) as server:
        yield server.url, per_page


def _browser(pw):
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


def _visible_rows(page) -> list[str]:
    return page.eval_on_selector_all(
        "#activity tbody tr td:nth-child(2)", "tds => tds.map(td => td.innerText.trim())"
    )


def test_table_pagination_changes_the_rows(panel):
    """Lo que ninguna otra capa ve: que pulsar «siguiente» reescribe la tabla.

    El control positivo es la primera aserción: se comprueba que **había** más de una página antes
    de pulsar. Sin eso, un panel que no paginara nada pasaría este test enseñando la misma tabla
    dos veces.
    """
    url, per_page = panel
    with sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page.goto(url)
        page.wait_for_selector("#activity tbody tr")

        assert page.locator("#pager").is_visible(), (
            "control positivo fallido: con más de una página el pager tiene que verse"
        )
        assert page.locator("#pgInfo").inner_text().strip().endswith("/ 2")
        assert page.locator("#pgPrev").is_disabled(), "en la página 1 no se puede retroceder"

        first = _visible_rows(page)
        assert len(first) == per_page

        page.locator("#pgNext").click()
        page.wait_for_function(
            "n => document.querySelectorAll('#activity tbody tr').length !== n", arg=per_page
        )

        second = _visible_rows(page)
        assert second and not set(second) & set(first), (
            f"la página 2 debe traer filas distintas: {second[:3]} vs {first[:3]}"
        )
        assert page.locator("#pgNext").is_disabled(), "en la última página no se puede avanzar"

        page.locator("#pgPrev").click()
        page.wait_for_function(
            "n => document.querySelectorAll('#activity tbody tr').length === n", arg=per_page
        )
        assert _visible_rows(page) == first, "volver atrás debe devolver la misma página 1"

        browser.close()


def test_changing_the_range_refetches_the_data_and_resets_the_page(panel):
    """El selector de rango decide qué se le pide al backend, y reinicia el pager.

    Si no reiniciara, cambiar de rango desde la página 2 dejaría al usuario mirando una página que
    en el rango nuevo puede no existir.
    """
    url, _per_page = panel
    with sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()

        requested: list[str] = []
        page.on("request", lambda r: requested.append(r.url) if "/api/events" in r.url else None)

        page.goto(url)
        page.wait_for_selector("#activity tbody tr")
        page.locator("#pgNext").click()
        # `startsWith('2')` y no `includes('2')`: el texto es «1 / 2» en la primera página, así que
        # un `includes` daría por buena la espera sin que el clic hubiera hecho nada.
        page.wait_for_function(
            "() => document.getElementById('pgInfo').innerText.trim().startsWith('2')"
        )

        before = len(requested)
        # El valor es "7", no "7d": se comprueba contra el `<option>` que existe de verdad. Un
        # `select_option` con un valor inventado no cambia nada y Playwright espera hasta agotar
        # el plazo, así que aquí el test fallaba por el test y no por el panel.
        page.select_option("#range", "7")
        for _ in range(100):
            if len(requested) > before:
                break
            time.sleep(0.05)

        assert len(requested) > before, "cambiar el rango tiene que volver a pedir /api/events"
        assert "from=" in requested[-1] and "to=" in requested[-1]
        page.wait_for_function(
            "() => document.getElementById('pgInfo').innerText.trim().startsWith('1')"
        )

        browser.close()


def test_the_custom_range_shows_both_date_fields(panel):
    """`custom` es el único valor que cambia la forma del panel, y estaba sin ejercer."""
    url, _ = panel
    with sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page.goto(url)
        page.wait_for_selector("#activity tbody tr")

        assert not page.locator("#rangeFrom").is_visible()  # control positivo: parten ocultos

        page.select_option("#range", "custom")
        page.wait_for_selector("#rangeFrom", state="visible")
        assert page.locator("#rangeTo").is_visible()

        browser.close()


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
_CHARS_READ, _CHARS_RETURNED = 40_000, 4_000
_GROSS, _RETURNED, _NET = 16_597, 1_793, 14_804

_HOOKS = {
    "enabled": True,
    "total": 10,
    "suggested": 3,
    "rate": 0.3,
    "by_category": [{"category": "read", "total": 8, "suggested": 2}],
    "by_reason": [{"reason": "small", "total": 5}],
    "read_total": 5,
}

_PROCESS = {"name": "python.exe", "pid": 4321, "ram_mb": 2048, "vram_mb": None, "self": True}

_MEASURE = """() => {
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


def _thousands(n: int) -> str:
    """El formato que pide REQ-030: punto de miles siempre, desde cuatro cifras."""
    return f"{n:,}".replace(",", ".")


def _showcase_log() -> str:
    now = datetime.now(UTC)
    local_midnight = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    step = min(timedelta(seconds=30), (now - local_midnight) / 2)
    common = {"model": "modelo-de-prueba", "source": "path", "backend": "local"}
    events = [
        {
            **common,
            "ts": now.isoformat(timespec="seconds"),
            "tool": "local_summarize",
            "chars_in": _CHARS_READ,
            "chars_out": _CHARS_RETURNED,
            "latency_ms": 2000,
            "ok": True,
            "tokens_in": 9000,
            "tokens_out": 900,
            "client": "claude-code",
        },
        {
            **common,
            "ts": (now - step).isoformat(timespec="seconds"),
            "tool": "local_extract",
            "chars_in": 80_000,
            "chars_out": 0,
            "latency_ms": 4000,
            "ok": False,
            "error_class": "connect_error",
            "client": "claude-code",
        },
    ]
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"


@pytest.fixture(scope="module")
def measurements(tmp_path_factory):
    """Pinta el panel una vez con hooks, clientes, actividad y procesos, y lo mide todo."""
    folder = tmp_path_factory.mktemp("presentacion")
    today = datetime.now(UTC)
    (folder / f"usage-{today:%Y%m}.jsonl").write_text(_showcase_log(), encoding="utf-8")
    system = {"ram": None, "vram": None, "processes": [_PROCESS]}

    def _json(body):
        return lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(body)
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "LOG_DIR", folder)
        mp.setattr(config, "USAGE_LOG", folder / "usage.jsonl")
        mp.setattr(config, "WEB_FONTS", True)
        metrics._FILE_CACHE.clear()
        with _Server(9497) as server, sync_playwright() as pw:
            browser = _browser(pw)
            page = browser.new_page()
            # Sin red: `getComputedStyle` devuelve la familia declarada aunque no llegue la cara.
            page.route(
                re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort()
            )
            page.route(re.compile(r"/api/hooks(\?|$)"), _json(_HOOKS))
            page.route(re.compile(r"/api/system(\?|$)"), lambda r: _json(system)(r))
            page.goto(server.url)
            for selector in (
                "#activity tbody tr",
                "#hooksBody table",
                "#clientsBody table",
                "#procTable thead",
                ".card.hero",
            ):
                page.wait_for_selector(selector)
            m = page.evaluate(_MEASURE)

            # La fila vacía de procesos es otro estado de la misma tarjeta: se fuerza y se repinta.
            system["processes"] = []
            page.evaluate("() => pollSystem()")
            page.wait_for_function(
                "() => document.getElementById('procTable').innerText.includes('Ningún proceso')"
            )
            m["procesosVacia"] = page.evaluate(
                "() => getComputedStyle(document.querySelector('#procTable td')).fontFamily"
            )
            browser.close()
    metrics._FILE_CACHE.clear()
    return m


def test_all_headers_share_the_family(measurements):
    """REQ-034 (a): `.num` y `th.mono` ya no ponen mono a media fila de cabecera."""
    families = set(measurements["th"])
    assert len(measurements["th"]) >= 10, "control positivo: hooks, clientes, actividad y procesos"
    assert len(families) == 1, families
    assert "Inter" in next(iter(families))


def test_the_daemon_chip_looks_like_its_twins(measurements):
    """REQ-034 (b): «DAEMON MCP» con la familia de `.mrole`, no la mono de su celda."""
    assert measurements["selfchip"] == measurements["mrole"]


def test_the_empty_processes_row_looks_like_the_other_empties(measurements):
    """REQ-034 (c)."""
    assert measurements["procesosVacia"] == measurements["empty"]


def test_the_hooks_note_is_prose_in_Inter(measurements):
    """REQ-034 (d): la nota dejó de reutilizar `.empty`, que es mono. Ahora va en el diálogo."""
    assert measurements["nota"] is not None, "control positivo: la nota tiene que estar pintada"
    assert measurements["nota"].startswith("Inter")


def test_the_first_column_of_hooks_and_clients_is_mono(measurements):
    """REQ-034 (e): categoría y cliente son identificadores de la telemetría."""
    assert "JetBrains Mono" in measurements["hooksPrimera"]
    assert "JetBrains Mono" in measurements["clientesPrimera"]


def test_buttons_inherit_the_body_family(measurements):
    """REQ-034 (g). «Refrescar» ya la tenía por `.btn`; el que no la tenía es el cierre de la
    ayuda (`.help-x`), que se quedaba con la del agente de usuario."""
    assert measurements["refrescar"] == measurements["body"]
    assert measurements["cerrarAyuda"] == measurements["body"]


def test_the_font_stylesheet_requests_JetBrains_Mono_400(measurements):
    """REQ-034 (f). `getComputedStyle` no ve la cara que falta: se mira la URL."""
    assert "JetBrains+Mono:wght@400" in measurements["fuentes"]


def test_the_hero_KPI_shows_the_net_and_the_hint_the_gross_and_returned(measurements):
    """REQ-004 en el navegador, con el formato de REQ-030."""
    assert measurements["kpi"] == _thousands(_NET)
    assert _thousands(_GROSS) in measurements["pista"]
    assert _thousands(_RETURNED) in measurements["pista"]
    assert "relecturas" in measurements["tooltip"]


def test_who_delegated_shows_the_client_net(measurements):
    """REQ-004: la columna de ahorro de «Quién delegó» es `tokens_net`."""
    assert measurements["columnaNeto"] == _thousands(_NET)


def test_latency_is_in_seconds(measurements):
    """REQ-032: KPI y columna de actividad en segundos, con coma."""
    assert measurements["latencia"].endswith(" s"), measurements["latencia"]
    assert measurements["latencia"] == "3,0 s"
    assert sorted(measurements["latenciaFilas"]) == ["2,0 s", "4,0 s"]


# --- Tarjeta Sistema y tipografía de todas las tarjetas (guardián) -----------------------------
#
# En la Mac (backend en la PC) la tarjeta Sistema enseñaba dos frases en dos fuentes y el host del
# backend como texto plano. Ya se había arreglado «a mano» antes y volvió: este guardián recorre
# TODOS los nodos de texto visibles de todas las tarjetas en los tres estados de la tarjeta y exige
# que su `font-family` computado sea una de las dos pilas del panel (`--sans`, `--mono`). Compara la
# pila declarada, no anchos: en el CI Linux la fuente web no carga, y medir anchos ahí miente.

_PANEL_URL = "https://pc.ejemplo.ts.net:9393/"
_SYSTEM_STATES = {
    # Windows con el backend en la misma máquina: medidores y procesos.
    "local": {
        "ram": {"used_gb": 18.5, "total_gb": 31.8, "free_gb": 13.3, "pct": 58.2},
        "vram": {"used_mb": 8908, "total_mb": 16311, "pct": 54.6, "gpu_util_pct": 68},
        "processes": [{"pid": 4242, "name": "llama-server.exe", "ram_mb": 7640, "vram_mb": 8420}],
        "platform": "win32",
        "origin": "local",
        "host": "127.0.0.1:9292",
        "panel_url": "",
    },
    # Linux contra un backend remoto: la RAM de aquí sí se mide; los procesos del backend, no.
    "remoto": {
        "ram": {"used_gb": 6.1, "total_gb": 15.5, "free_gb": 9.4, "pct": 39.4},
        "vram": None,
        "processes": [],
        "platform": "linux",
        "origin": "remote",
        "host": "pc.ejemplo.ts.net:9292",
        "panel_url": _PANEL_URL,
    },
    # La Mac contra la PC: ni RAM ni VRAM ni procesos aquí.
    "macos": {
        "ram": None,
        "vram": None,
        "processes": [],
        "platform": "darwin",
        "origin": "remote",
        "host": "pc.ejemplo.ts.net:9292",
        "panel_url": _PANEL_URL,
    },
}

_CARD_TYPOGRAPHY = """() => {
  const norm = f => f.replace(/["']/g, '').split(',').map(x => x.trim()).filter(Boolean).join(',');
  const raiz = getComputedStyle(document.documentElement);
  const permitidas = ['--sans', '--mono'].map(v => norm(raiz.getPropertyValue(v)));
  const fuera = [];
  let vistos = 0;
  // La barra de controles entra también: el interruptor «Pruebas» vive ahí (test-windows).
  for (const card of document.querySelectorAll('.card, .topbar .controls')) {
    if (!card.checkVisibility()) continue;
    const w = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const texto = n.textContent.trim();
      const el = n.parentElement;
      if (!texto || !el || !el.checkVisibility()) continue;
      vistos++;
      const familia = norm(getComputedStyle(el).fontFamily);
      if (!permitidas.includes(familia)) fuera.push(texto.slice(0, 50) + ' -> ' + familia);
    }
  }
  const sistema = document.getElementById('metersBody').closest('.card');
  const textos = [];
  const w = document.createTreeWalker(sistema, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    const t = n.textContent.trim();
    if (t && n.parentElement && n.parentElement.checkVisibility()) textos.push(t);
  }
  const a = sistema.querySelector('a[href]');
  const textos_barra = [...document.querySelectorAll('.topbar .controls button')]
    .map(b => b.innerText.trim()).filter(Boolean);
  return {
    permitidas, vistos, fuera, textos, textos_barra,
    enlace: a ? {href: a.getAttribute('href'), target: a.target, rel: a.rel, texto: a.innerText.trim()}
              : null,
  };
}"""


@pytest.mark.parametrize("state", list(_SYSTEM_STATES))
def test_cards_only_use_the_panel_fonts(tmp_path, monkeypatch, state):
    """Guardián: ningún texto visible de ninguna tarjeta sale en una fuente ajena al panel, y la
    tarjeta Sistema no lleva prosa ni el host como texto plano."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "WEB_FONTS", True)
    today = datetime.now(UTC)
    (tmp_path / f"usage-{today:%Y%m}.jsonl").write_text(_showcase_log(), encoding="utf-8")
    metrics._FILE_CACHE.clear()
    with _Server(9496) as server, sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        page.route(re.compile(r"/api/hooks(\?|$)"), _json(_HOOKS))
        page.route(re.compile(r"/api/system(\?|$)"), _json(_SYSTEM_STATES[state]))
        page.goto(server.url)
        page.wait_for_selector("#activity tbody tr")
        page.wait_for_selector("#hooksBody table")
        page.wait_for_function(
            "() => !document.getElementById('metersBody').innerText.includes('Leyendo')"
        )
        m = page.evaluate(_CARD_TYPOGRAPHY)
        browser.close()
    metrics._FILE_CACHE.clear()

    # Control positivo de la propia medida: las dos pilas se leyeron y hubo textos que mirar.
    assert all(m["permitidas"]) and len(set(m["permitidas"])) == 2, m["permitidas"]
    assert m["vistos"] >= 40, m["vistos"]
    assert not m["fuera"], "texto en una fuente ajena al panel: " + "; ".join(m["fuera"])
    # El botón «Pruebas» entra en lo que mide el guardián (y por tanto en `fuera` si se sale).
    assert "Pruebas" in m["textos_barra"], m["textos_barra"]

    # Sin prosa en la tarjeta Sistema: etiquetas y cifras, nada de frases (van en su ⓘ).
    sentences = [t for t in m["textos"] if len(t.split()) >= 6]
    assert not sentences, sentences

    if _SYSTEM_STATES[state]["origin"] == "remote":
        link = m["enlace"]
        assert link is not None, "el host del backend tiene que ser un enlace"
        assert link["href"] == _PANEL_URL
        assert link["texto"] == "pc.ejemplo.ts.net"
        assert link["target"] == "_blank"
        assert "noopener" in link["rel"].split()
        assert "Procesos del backend".upper() not in [t.upper() for t in m["textos"]]
    else:
        assert m["enlace"] is None
        assert "llama-server.exe" in m["textos"]
    if _SYSTEM_STATES[state]["ram"] is None:
        assert "RAM / VRAM" in m["textos"] and "—" in m["textos"]


# --- Coste equivalente, cuota e imágenes (coste-api-y-cuota, T6) -------------------------------


def _cost_and_image_log(tmp_path, monkeypatch) -> None:
    """Un resumen por path y una imagen, hoy: hay cifra de coste y una imagen en el rango."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "COST_FALLBACK", "")
    now = datetime.now(UTC)
    local_midnight = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    step = min(timedelta(seconds=30), (now - local_midnight) / 2)
    common = {"ok": True, "client": "claude-code", "backend": "local", "model": "modelo-de-prueba"}
    events = [
        {
            **common,
            "ts": now.isoformat(timespec="seconds"),
            "tool": "local_summarize",
            "source": "path",
            "path": "C:/docs/notas.md",
            "chars_in": 1_000_000,
            "chars_out": 0,
            "tokens_in": 9000,
            "tokens_out": 100,
        },
        {
            **common,
            "ts": (now - step).isoformat(timespec="seconds"),
            "tool": "local_describe_image",
            "source": "path",
            "chars_in": 250000,
            "chars_out": 800,
            "tokens_in": 1200,
            "tokens_out": 200,
        },
    ]
    (tmp_path / f"usage-{now:%Y%m}.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8"
    )
    metrics._FILE_CACHE.clear()


# Lo que se mide de las tres tarjetas: ningún párrafo, la misma tipografía que los KPIs de arriba,
# el hueco con la fila de debajo y el diálogo de información con todo el texto que salió de ellas.
_MEASURE_CARDS = """() => {
  const cuerpos = ['costBody', 'quotaBody', 'imagesBody'].map(i => document.getElementById(i));
  const textos = cuerpos.flatMap(c => [...c.querySelectorAll('*')]
    .filter(e => !e.children.length).map(e => e.textContent.trim()));
  const estilo = sel => { const e = document.querySelector(sel);
    if (!e) return null; const s = getComputedStyle(e);
    return [s.fontFamily, s.fontSize, s.fontWeight].join('|'); };
  const vis = id => getComputedStyle(document.getElementById(id)).display !== 'none';
  const coste = document.getElementById('costCard').getBoundingClientRect();
  const fila = document.getElementById('quotaImgRow').getBoundingClientRect();
  return {
    coste: document.getElementById('costBody').innerText,
    imagenes: document.getElementById('imagesBody').innerText,
    parrafos: cuerpos.reduce((n, c) => n + c.querySelectorAll('p, .nota').length, 0),
    masLargo: Math.max(...textos.map(t => t.length)),
    desglose: document.querySelectorAll('#costBody tbody tr').length,
    cuotaVisible: vis('quotaCard'), imagenesVisible: vis('imagesCard'),
    valCoste: estilo('#costBody .k-val'), valKpi: estilo('#kpis .card:not(.hero) .k-val'),
    lblCoste: estilo('#costBody .k-lbl'), lblKpi: estilo('#kpis .k-lbl'),
    hueco: Math.round(fila.top - coste.bottom),
  };
}"""


def test_cost_quota_and_image_cards_carry_figures_not_paragraphs(tmp_path, monkeypatch):
    """El panel pinta lo que trae `/api/stats` como cifras con la forma de los KPIs: el coste con
    su cota baja, su estimación y el desglose; la imagen con sus bytes. La cuota «sin calibrar» (sin
    `cost-aggregates.json` en esta carpeta) **no se pinta**. Ningún párrafo en el cuerpo."""
    _cost_and_image_log(tmp_path, monkeypatch)
    with _Server(9495) as server, sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        page.goto(server.url)
        page.wait_for_selector("#costBody .kstat")
        page.wait_for_selector("#imagesBody .kstat")
        m = page.evaluate(_MEASURE_CARDS)
        browser.close()
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


def test_the_info_dialog_carries_the_text_and_closes_with_esc(tmp_path, monkeypatch):
    """El ⓘ de la tarjeta de coste abre un diálogo con los supuestos, la calibración de la cuota y
    la nota de las imágenes; Esc lo cierra y el foco vuelve al botón."""
    _cost_and_image_log(tmp_path, monkeypatch)
    with _Server(9495) as server, sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        page.goto(server.url)
        page.wait_for_selector("#costBody .kstat")
        page.focus("#costInfo")
        page.keyboard.press("Enter")
        opened = page.evaluate("() => document.getElementById('infoDlg').open")
        text = page.inner_text("#infoDlg")
        page.keyboard.press("Escape")
        m = page.evaluate(
            """() => ({abierto: document.getElementById('infoDlg').open,
                       foco: document.activeElement && document.activeElement.id})"""
        )
        browser.close()
    metrics._FILE_CACHE.clear()
    assert opened
    assert "Equivalente estimado a precio de API: entre $2,50 y ~$6,50" in text
    assert "No es dinero que hayas ahorrado: tu suscripción es de tarifa plana." in text
    assert "1 de 1 con modelo supuesto: Opus 5.5 en subagente" in text
    assert "Precios de la tabla del paquete del" in text
    assert "sin calibrar" in text
    assert "1 imagen" in text
    assert "250.000 bytes" in text
    assert not m["abierto"]
    assert m["foco"] == "costInfo"


def test_the_calibrated_quota_appears_as_a_meter(tmp_path, monkeypatch):
    """Con una ventana calibrada la tarjeta aparece con la cifra A – B % y un medidor; la otra,
    sin calibrar, dice «sin calibrar» con «–». `/api/stats` se intercepta para inyectar la cuota:
    calibrarla de verdad pide tres puntos del statusline."""
    _cost_and_image_log(tmp_path, monkeypatch)
    calibrated_quota = {
        "five_hour": {"status": "calibrated", "points": 4, "a_pct": 3.4, "b_pct": 11.9},
        "seven_day": {"status": "uncalibrated", "points": 1, "reason": "faltan 2 puntos"},
        "has_aggregates": True,
        "command": "local-delegate recompute-cost",
    }

    def _inject(path):
        response = path.fetch()
        data = response.json()
        data["quota"] = calibrated_quota
        path.fulfill(response=response, body=json.dumps(data))

    with _Server(9495) as server, sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        page.route(re.compile(r"/api/stats(\?|$)"), _inject)
        page.goto(server.url)
        page.wait_for_selector("#quotaBody .qrange")
        m = page.evaluate(
            """() => ({
              texto: document.getElementById('quotaBody').innerText,
              cabecera: document.getElementById('quotaHead').innerText,
              medidores: document.querySelectorAll('#quotaBody .qrange').length,
              ancho: document.querySelector('#quotaBody .qrange .qb').style.width,
            })"""
        )
        browser.close()
    metrics._FILE_CACHE.clear()
    assert "3,4 – 11,9" in m["texto"]
    assert "sin calibrar" in m["texto"]
    assert m["cabecera"] == "1 ventana calibrada"
    assert m["medidores"] == 1
    assert m["ancho"] == "8.5%"


def test_native_controls_follow_the_theme(panel):
    """`color-scheme` sigue al tema: es lo que pinta claro el icono del calendario de los
    `<input type=date>` en oscuro (antes salía negro sobre el panel) y la lista del `<select>`."""
    url, _ = panel
    with sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        page.goto(url)
        dark = page.evaluate(
            "() => getComputedStyle(document.getElementById('rangeFrom')).colorScheme"
        )
        page.click("#theme")
        light = page.evaluate(
            "() => getComputedStyle(document.getElementById('rangeFrom')).colorScheme"
        )
        browser.close()
    assert dark == "dark"
    assert light == "light"


# Tres situaciones de fuente, porque la simetría no puede depender de cuál cargue:
# - `bloqueadas`: Google Fonts no responde (lo del CI y de un equipo sin red), queda la de reserva;
# - `ancha`: además se fuerza una de reserva ANCHA (Verdana / DejaVu Sans, Courier New / DejaVu
#   Sans Mono), la peor que puede tocar en otro sistema;
# - `cargadas`: se deja pedir Inter y JetBrains Mono (solo se cargan si hay red).
FONT_STATES = ("bloqueadas", "ancha", "cargadas")
_WIDE_FONT = (
    ":root,:root[data-theme]{--sans:'Verdana','DejaVu Sans',sans-serif;"
    "--mono:'Courier New','DejaVu Sans Mono',monospace}"
)
# Inter de verdad cargada (no basta `document.fonts.check`: sin la hoja de Google Fonts no hay
# ninguna cara registrada y `check` devuelve true).
_INTER_LOADED = (
    "() => document.fonts.ready.then(() => [...document.fonts].some(f =>"
    " f.family.replace(/[\"']/g, '') === 'Inter' && f.status === 'loaded'))"
)


def _before_loading(page, fonts):
    if fonts != "cargadas":
        page.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())


def _after_loading(page, fonts):
    if fonts == "ancha":
        page.add_style_tag(content=_WIDE_FONT)
    page.evaluate("() => document.fonts.ready.then(() => 1)")


# Cada cifra de los KPIs, con su unidad, dentro de su tarjeta: ni la cifra desborda su caja ni la
# unidad pasa del borde interior de la tarjeta (el hero tiene `overflow:hidden` y la cortaba).
_KPI_OVERFLOWS = """() => [...document.querySelectorAll('#kpis .k-val')].flatMap(v => {
  const card = v.closest('.card'), c = card.getBoundingClientRect();
  const borde = c.right - parseFloat(getComputedStyle(card).paddingRight) + 0.5;
  const fuera = [];
  if (v.scrollWidth > v.clientWidth) fuera.push(v.textContent + ': la cifra desborda su caja');
  const u = v.querySelector('.unit');
  if (u && u.getBoundingClientRect().right > borde) fuera.push(v.textContent + ': unidad cortada');
  return fuera;
})"""


@pytest.mark.parametrize("fonts", FONT_STATES)
def test_the_kpi_unit_is_not_cut_off(tmp_path, monkeypatch, fonts):
    """«3.161.168 tok» en el hero salía como «3.161.168 to» entre 1320 y 1440 px. Con cifras de
    siete dígitos en los KPIs, a 1280, 1366 y 1440 px y en los dos temas, nada se sale."""
    _cost_and_image_log(tmp_path, monkeypatch)

    def _large_figures(path):
        response = path.fetch()
        data = response.json()
        data.update(
            tokens_context_net=3_161_168,
            tokens_context_saved=3_250_647,
            tokens_returned=89_479,
            tokens_generated_local=123_478,
            tokens_local_input=1_898_456,
        )
        path.fulfill(response=response, body=json.dumps(data))

    overflows = {}
    with _Server(9495) as server, sync_playwright() as pw:
        browser = _browser(pw)
        for width in (1280, 1366, 1440):
            for theme in ("dark", "light"):
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.add_init_script(
                    f"try{{localStorage.setItem('ld-theme','{theme}')}}catch(e){{}}"
                )
                _before_loading(page, fonts)
                page.route(re.compile(r"/api/stats(\?|$)"), _large_figures)
                page.goto(server.url)
                page.wait_for_function(
                    "() => document.querySelector('#kpis .hero .k-val')?.textContent.includes('3.161.168')"
                )
                _after_loading(page, fonts)
                overflows[(width, theme)] = page.evaluate(_KPI_OVERFLOWS)
                page.close()
        browser.close()
    metrics._FILE_CACHE.clear()
    assert all(not v for v in overflows.values()), overflows


# --- Etiquetas legibles, tipografía, simetría de los KPIs y la tarjeta Sistema -----------------

# Claves internas tal como llegan del log y de la API, y una desconocida para el respaldo.
_RAW_HOOKS = {
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
    # Valores nuevos y viejos mezclados (REQ-009): los viejos se pintan con la misma etiqueta.
    "by_reason": [
        {"reason": "suggested", "total": 8},
        {"reason": "acotada", "total": 6},
        {"reason": "code", "total": 5},
        {"reason": "pequeno", "total": 4},
        {"reason": "foreign_mcp", "total": 4},
        {"reason": "motivo_que_no_existe", "total": 3},
    ],
    "by_ext": [],
}
_SYSTEM = {
    "ram": {"used_gb": 13.4, "total_gb": 31.1, "free_gb": 17.7, "pct": 43},
    "vram": {"used_mb": 8908, "total_mb": 16311, "pct": 54.6, "gpu_util_pct": 68},
    "processes": [{"pid": 4242, "name": "llama-server.exe", "ram_mb": 7640, "vram_mb": 8420}],
    "platform": "win32",
    "origin": "local",
    "host": "127.0.0.1:9292",
}


def _json(body):
    return lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(body)
    )


def _raw_clients(path):
    """`/api/stats` real con un desglose por cliente que trae claves internas."""
    response = path.fetch()
    data = response.json()
    row = {"calls": 1, "backend_calls": 1, "tokens_net": 10, "tokens_saved": 10}
    data["by_client"] = [
        {**row, "client": "claude-code"},
        {**row, "client": "codex-mcp-client"},
        {**row, "client": "desconocido"},
        {**row, "client": "cliente_nuevo"},
    ]
    path.fulfill(response=response, body=json.dumps(data))


def _full_page(pw, url, width=1366, theme="dark", fonts="bloqueadas"):
    browser = _browser(pw)
    page = browser.new_page(viewport={"width": width, "height": 1000})
    page.add_init_script(f"try{{localStorage.setItem('ld-theme','{theme}')}}catch(e){{}}")
    _before_loading(page, fonts)
    page.route(re.compile(r"/api/hooks(\?|$)"), _json(_RAW_HOOKS))
    page.route(re.compile(r"/api/system(\?|$)"), _json(_SYSTEM))
    page.route(re.compile(r"/api/stats(\?|$)"), _raw_clients)
    page.goto(url)
    page.wait_for_selector("#hooksBody tbody tr")
    page.wait_for_selector("#clientsBody tbody tr")
    page.wait_for_selector("#costBody tbody tr")
    page.wait_for_function("() => document.getElementById('metersBody').innerText.includes('GiB')")
    _after_loading(page, fonts)
    return browser, page


_FIRST_COLUMNS = """() => {
  const ids = ['hooksBody', 'clientsBody', 'costBody'];
  return ids.flatMap(id => [...document.querySelectorAll('#' + id + ' tbody tr td:first-child')]
    .map(td => td.innerText.trim()));
}"""


def test_no_table_shows_internal_keys(tmp_path, monkeypatch):
    """La primera columna de las tablas de hooks, clientes y coste dice etiquetas legibles: ni
    guiones bajos ni minúscula inicial. Una clave desconocida sale humanizada, no cruda. Los nombres
    de modelo (primera columna del coste) ya empiezan en mayúscula; los de proceso y tool no pasan
    por aquí (son nombres propios)."""
    _cost_and_image_log(tmp_path, monkeypatch)
    with _Server(9495) as server, sync_playwright() as pw:
        browser, page = _full_page(pw, server.url)
        cells = page.evaluate(_FIRST_COLUMNS)
        effort = page.inner_text("#costBody tbody tr td:nth-child(3)")
        thread = page.inner_text("#costBody tbody tr td:nth-child(2)")
        browser.close()
    metrics._FILE_CACHE.clear()
    assert len(cells) == 5 + 6 + 4 + 1, cells  # guarda: llegaron todas las filas
    bad = [c for c in cells if "_" in c or not c[:1].isupper()]
    assert not bad, bad
    for expected in (
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
        assert expected in cells, (expected, cells)
    # El respaldo: la clave desconocida, sin guiones bajos y con mayúscula.
    assert "Clave rara nueva" in cells
    assert "Motivo que no existe" in cells
    assert "Cliente nuevo" in cells
    assert thread == "Subagente"
    assert effort == "Sin dato"


_TABLE_TYPOGRAPHY = """() => {
  const estilo = el => { const s = getComputedStyle(el); return s.fontFamily + '|' + s.fontSize; };
  const tablas = [...document.querySelectorAll('table')].filter(t => t.querySelector('tbody td'));
  return tablas.map(t => ({
    id: t.id || t.closest('.card').querySelector('h2').textContent,
    primera: estilo(t.querySelector('tbody td:first-child')),
    cabecera: t.querySelector('thead th') ? estilo(t.querySelector('thead th')) : null,
  }));
}"""


def test_all_tables_share_typography_per_column(tmp_path, monkeypatch):
    """Primera columna y cabecera con la misma familia y tamaño en todas las tablas del panel,
    también la de procesos de Sistema (antes en 12 px)."""
    _cost_and_image_log(tmp_path, monkeypatch)
    with _Server(9495) as server, sync_playwright() as pw:
        browser, page = _full_page(pw, server.url)
        page.wait_for_selector("#procTable tbody td")
        tables = page.evaluate(_TABLE_TYPOGRAPHY)
        browser.close()
    metrics._FILE_CACHE.clear()
    assert len(tables) >= 6, tables  # procesos, coste, actividad, clientes y las dos de hooks
    assert len({t["primera"] for t in tables}) == 1, tables
    assert len({t["cabecera"] for t in tables if t["cabecera"]}) == 1, tables


def test_the_hooks_note_is_in_the_dialog(tmp_path, monkeypatch):
    """El párrafo de «los hooks sugieren» ya no está en la tarjeta: lo abre su ⓘ."""
    _cost_and_image_log(tmp_path, monkeypatch)
    with _Server(9495) as server, sync_playwright() as pw:
        browser, page = _full_page(pw, server.url)
        body = page.inner_text("#hooksBody")
        paragraphs = page.evaluate(
            "() => document.querySelectorAll('#hooksBody p, #hooksBody .nota').length"
        )
        page.click("#hooksInfo")
        title = page.inner_text("#infoDlgTitle")
        visible = page.inner_text("#dlgHooks")
        hidden = page.evaluate("() => document.getElementById('dlgCost').hidden")
        browser.close()
    metrics._FILE_CACHE.clear()
    assert "sugieren" not in body
    assert paragraphs == 0
    assert title == "Sugerencias de los hooks"
    assert "Los hooks sugieren; delegar lo decides tú." in visible
    assert hidden  # el diálogo enseña solo las secciones de su grupo


# Por tarjeta de la fila de KPIs: dónde empieza la cifra y cuánto mide el bloque del título,
# relativo a la propia tarjeta (a 400 px van apiladas, una por fila).
_KPI_SYMMETRY = """() => [...document.querySelectorAll('#kpis > .card')].map(card => {
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
_DECIMAL_WITH_DOT = re.compile(r"\d\.\d{1,2}(?!\d)")


@pytest.mark.parametrize("fonts", FONT_STATES)
def test_the_kpi_row_is_symmetric_and_uses_decimal_comma(tmp_path, monkeypatch, fonts):
    """A 1280, 1366, 1440 y 400 px, en los dos temas y con cualquier fuente: misma altura del
    título, la cifra empieza a la misma altura en todas las tarjetas, la pista ocupa lo mismo y
    ningún número usa punto decimal."""
    _cost_and_image_log(tmp_path, monkeypatch)
    results = {}
    with _Server(9495) as server, sync_playwright() as pw:
        for width in (1280, 1366, 1440, 400):
            for theme in ("dark", "light"):
                browser, page = _full_page(pw, server.url, width, theme, fonts)
                results[(width, theme)] = page.evaluate(_KPI_SYMMETRY)
                browser.close()
    metrics._FILE_CACHE.clear()
    for key, cards in results.items():
        assert len(cards) == 6, (key, cards)
        figures = [t["cifra"] for t in cards]
        assert max(figures) - min(figures) <= 2, (key, cards)
        assert len({t["titulo"] for t in cards}) == 1, (key, cards)
        hints = [t["pista"] for t in cards]
        assert max(hints) - min(hints) <= 1, (key, cards)
        for t in cards:
            assert not _DECIMAL_WITH_DOT.search(t["texto"]), (key, t)
    # La pista de «Delegaciones» es una frase corta; el desglose va al tooltip.
    delegations = next(t for t in results[(1366, "dark")] if "Delegaciones" in t["lbl"])
    assert "trocear" not in delegations["texto"]
    assert "llamada" in delegations["texto"]


def test_system_shows_the_gpu_load_as_a_bar(tmp_path, monkeypatch):
    """La cabecera de Sistema ya no lleva «GPU 68%»: la carga es una fila con barra, entre la RAM y
    la VRAM, y todas las cifras van con coma decimal y espacio antes de %."""
    _cost_and_image_log(tmp_path, monkeypatch)
    with _Server(9495) as server, sync_playwright() as pw:
        browser, page = _full_page(pw, server.url)
        header = page.evaluate(
            "() => [...document.querySelectorAll('.panel-h')]"
            ".find(h => h.querySelector('h2').textContent === 'Sistema').innerText"
        )
        rows = page.evaluate(
            "() => [...document.querySelectorAll('#metersBody .meter-lbl')].map(e => e.innerText)"
        )
        bars = page.evaluate("() => document.querySelectorAll('#metersBody .meter').length")
        browser.close()
    metrics._FILE_CACHE.clear()
    assert "GPU" not in header and "%" not in header, header
    assert len(rows) == 3 and bars == 3, rows
    assert rows[1].upper().startswith("CARGA DE LA GPU"), rows
    assert "68 %" in rows[1]
    assert "13,4 / 31,1 GiB · 43 %" in rows[0]
    assert "55 %" in rows[2]  # 54,6 redondeado, sin punto decimal
    for f in rows:
        assert not _DECIMAL_WITH_DOT.search(f), f


def test_the_range_selector_arrow_does_not_move_on_hover(panel):
    """`.btn:hover` cambiaba el atajo `background` y borraba la flecha (un `background-image`)."""
    url, _ = panel
    with sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        page.goto(url)
        image = "() => getComputedStyle(document.getElementById('range')).backgroundImage"
        idle = page.evaluate(image)
        page.hover("#range")
        on_top = page.evaluate(image)
        page.focus("#range")
        focus = page.evaluate(image)
        browser.close()
    assert "gradient" in idle
    assert on_top == idle
    assert focus == idle


_SPARK_AND_HINT = """() => {
  const hero = document.querySelector('#kpis .hero');
  const canvas = hero.querySelector('.spark canvas').getBoundingClientRect();
  const rango = document.createRange();
  rango.selectNodeContents(hero.querySelector('.k-hint'));
  const texto = rango.getBoundingClientRect();
  const lineas = [...document.querySelectorAll('#kpis .k-lbl')].map(l => {
    const t = l.querySelector('.k-lbl-t'), card = l.closest('.card').getBoundingClientRect();
    const info = l.querySelector('.info');
    return {lbl: t.textContent.trim(), title: l.getAttribute('title'),
      alto: Math.round(l.getBoundingClientRect().height),
      recortado: t.scrollWidth > t.clientWidth,
      infoDentro: !info || info.getBoundingClientRect().right <= card.right};
  });
  return {canvasTop: canvas.top, canvasAlto: canvas.height, textoBottom: texto.bottom, lineas};
}"""


@pytest.mark.parametrize("fonts", FONT_STATES)
def test_the_hero_line_does_not_overlap_its_hint(tmp_path, monkeypatch, fonts):
    """La línea del hero cruzaba «bruto … − devuelto …». La caja del gráfico empieza por debajo
    del texto de la pista, en los cuatro anchos y los dos temas. El título de cada KPI va en UNA
    línea con cualquier fuente (si no cabe se recorta con «…», el ⓘ sigue dentro de la tarjeta y
    el título entero queda en `title`); que quepa SIN recortar solo se exige a 1366 px y más con
    Inter cargada de verdad, porque con otra fuente lo que se mide es el entorno (lo cazó el CI:
    en ubuntu la de reserva es más ancha)."""
    _cost_and_image_log(tmp_path, monkeypatch)
    measurements = {}
    with _Server(9495) as server, sync_playwright() as pw:
        for width in (1280, 1366, 1440, 400):
            for theme in ("dark", "light"):
                browser, page = _full_page(pw, server.url, width, theme, fonts)
                measurements[(width, theme)] = page.evaluate(_SPARK_AND_HINT)
                measurements[(width, theme)]["inter"] = page.evaluate(_INTER_LOADED)
                browser.close()
    metrics._FILE_CACHE.clear()
    for key, m in measurements.items():
        assert m["canvasAlto"] > 0, (key, m)  # guarda: el gráfico se pintó
        assert m["canvasTop"] >= m["textoBottom"], (key, m)
        for line in m["lineas"]:
            assert line["alto"] <= 24, (key, line)  # una línea (~19 px); dos son ~35
            assert line["title"] == line["lbl"], (key, line)
            assert line["infoDentro"], (key, line)
        if fonts == "bloqueadas" or fonts == "ancha":
            assert not m["inter"], (key, "la fuente tenía que estar bloqueada")
        if m["inter"] and key[0] >= 1366:
            assert not any(x["recortado"] for x in m["lineas"]), (key, m["lineas"])


def test_backend_and_in_flight_speak_spanish(tmp_path, monkeypatch):
    """Estados de modelo con mayúscula inicial, «Trozo 9/14», «· 39.110 car.» y «peticiones» /
    «caché» en el rendimiento del backend: nada en minúscula de máquina ni en inglés."""
    _cost_and_image_log(tmp_path, monkeypatch)
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
    in_flight = {
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
    performance = {
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
    with _Server(9495) as server, sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        page.route(re.compile(r"/api/backend(\?|$)"), _json(backend))
        page.route(re.compile(r"/api/inflight(\?|$)"), _json(in_flight))
        page.route(re.compile(r"/api/backend/stats(\?|$)"), _json(performance))
        page.goto(server.url)
        page.wait_for_selector("#inflightBody .chunkchip")
        page.wait_for_function("() => document.getElementById('bstatsHead').textContent")
        m = page.evaluate(
            """() => ({
              estados: [...document.querySelectorAll('#modelsBody .mstate')].map(e => e.textContent),
              curso: document.getElementById('inflightBody').textContent,
              cabecera: document.getElementById('bstatsHead').textContent,
              rendimiento: document.getElementById('backendStats').textContent,
            })"""
        )
        browser.close()
    metrics._FILE_CACHE.clear()
    assert m["estados"], m  # guarda: hay filas de modelos
    assert all(e[:1].isupper() for e in m["estados"]), m["estados"]
    assert "Trozo 9/14" in m["curso"], m["curso"]
    assert "· 39.110 car." in m["curso"], m["curso"]
    assert "chars" not in m["curso"]
    assert "1.284 peticiones" in m["cabecera"], m["cabecera"]
    assert "caché" in m["rendimiento"] and "cache " not in m["rendimiento"], m["rendimiento"]


def test_the_input_origin_legend_is_in_spanish(panel):
    """«path»/«inline» pasan a «Por ruta (path)» y «Texto en línea (inline)»; el centro dice «por
    ruta». Se lee del gráfico de Chart.js: la leyenda se pinta en el canvas."""
    url, _ = panel
    with sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        page.goto(url)
        page.wait_for_function("() => state.charts && state.charts.srcDonut")
        m = page.evaluate(
            """() => ({etiquetas: state.charts.srcDonut.data.labels,
                       centro: state.charts.srcDonut.options.plugins.centerText.sub})"""
        )
        browser.close()
    assert m["etiquetas"] == ["Por ruta (path)"], m  # el log de `panel` es todo por path
    assert m["centro"] == "por ruta"


def test_there_is_no_longer_a_card_for_where_the_compute_ran(panel):
    """Se quitó: el backend es fijo por instalación y el donut siempre daba 100 % de un lado. La
    columna de origen de la actividad sigue, con etiqueta legible."""
    url, _ = panel
    with sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        page.goto(url)
        page.wait_for_selector("#activity tbody tr .org")
        m = page.evaluate(
            """() => ({
              donut: !!document.getElementById('originDonut'),
              titulos: [...document.querySelectorAll('h2')].map(h => h.textContent),
              origen: document.querySelector('#activity tbody tr .org').textContent,
              fila: getComputedStyle(document.getElementById('modelBar').closest('.grid'))
                .gridTemplateColumns.split(' ').length,
            })"""
        )
        browser.close()
    assert not m["donut"]
    assert "Dónde corrió el cómputo" not in m["titulos"]
    assert m["origen"] == "Local"
    assert m["fila"] == 2  # la fila de donuts queda en dos columnas, sin hueco


@pytest.mark.skipif(
    os.environ.get("CI") != "true", reason="solo aplica al CI, que sí instala el navegador"
)
def test_in_CI_this_module_can_NOT_be_skipped():
    """La guarda de «esto llegó a comprobar algo».

    Un módulo que se salta solo es cómodo en local y peligroso en el CI: si el paso que instala
    Chromium se rompe o se borra, los tests de arriba pasarían a saltarse y **nadie lo notaría** —
    verde para siempre sobre cero comprobaciones. Este test falla en ese caso.
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch()  # sin `_browser`: aquí un fallo debe ser rojo, no skip
        browser.close()


# --- Interruptor «Pruebas» (test-windows-out-of-metrics, REQ-016 y REQ-026) ----------------------


def test_the_tests_switch_requests_all_three_with_the_parameter(tmp_path, monkeypatch):
    """Empieza apagado; con una ventana abierta enseña el punto; su ⓘ dice cuántas filas quedan
    fuera; al pulsarlo, las tres peticiones llevan `include_tests=1` y el estado se recuerda."""
    from local_delegate import test_windows

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", None)
    now = datetime.now(UTC)
    test_window = {
        "ts": now.isoformat(timespec="seconds"),
        "tool": "local_extract",
        "model": "modelo-de-prueba",
        "source": "inline",
        "chars_in": 10,
        "chars_out": 5,
        "ok": True,
        "client": "mcp",
        "backend": "local",
    }
    (tmp_path / f"usage-{now:%Y%m}.jsonl").write_text(
        _events(4) + json.dumps(test_window) + "\n", encoding="utf-8"
    )
    # Abierta DESPUÉS de las filas: si no, taparía la última fila real del mismo segundo.
    opened = test_windows.start(tmp_path, "en vivo", now=now + timedelta(seconds=5))
    metrics._FILE_CACHE.clear()
    requested: list[str] = []
    with _Server(9487) as server, sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        page.on("request", lambda r: requested.append(r.url) if "/api/" in r.url else None)
        page.goto(server.url)
        page.wait_for_selector("#activity tbody tr")
        initial = page.evaluate(
            """() => ({on: document.getElementById('tests').classList.contains('on'),
                       pressed: document.getElementById('tests').getAttribute('aria-pressed'),
                       punto: document.getElementById('testsDot').checkVisibility()})"""
        )
        page.click("#testsInfo")
        text_off = page.inner_text("#dlgTests")
        code = page.evaluate(
            """() => {
              const mono = getComputedStyle(document.documentElement).getPropertyValue('--mono');
              const norm = f => f.replace(/["']/g, '').split(',').map(x => x.trim()).join(',');
              return [...document.querySelectorAll('#dlgTests code')].map(c => ({
                texto: c.innerText.trim(),
                mono: norm(getComputedStyle(c).fontFamily) === norm(mono)}));
            }"""
        )
        page.keyboard.press("Escape")
        before = [u for u in requested if re.search(r"/api/(events|stats|hooks)\?", u)]
        requested.clear()
        with page.expect_response(lambda r: "/api/stats" in r.url and "include_tests=1" in r.url):
            page.click("#tests")
        page.wait_for_function(
            "() => document.getElementById('dlgTestsBody').innerText.includes('incluidas')"
        )
        after = [u for u in requested if re.search(r"/api/(events|stats|hooks)\?", u)]
        remembered = page.evaluate("() => localStorage.getItem('ld-tests')")
        enabled = page.evaluate("() => document.getElementById('tests').classList.contains('on')")
        browser.close()
    metrics._FILE_CACHE.clear()

    assert initial == {"on": False, "pressed": "false", "punto": True}
    assert "Fuera de las cifras: 1 fila de prueba" in text_off
    assert f"local-delegate test-window stop {opened.id}" in text_off
    # Los comandos y el id van como código, en la mono del panel; la fecha, legible.
    code_texts = [c["texto"] for c in code]
    assert f"local-delegate test-window stop {opened.id}" in code_texts, code
    assert opened.id in code_texts
    assert code and all(c["mono"] for c in code), code
    assert "T" not in text_off.split(" desde ", 1)[1].split(".", 1)[0], text_off
    assert len(before) >= 3 and not any("include_tests" in u for u in before), before
    assert sorted(u.split("?")[0].rsplit("/", 1)[1] for u in after) == [
        "events",
        "hooks",
        "stats",
    ]
    assert all("include_tests=1" in u for u in after), after
    assert (remembered, enabled) == ("1", True)
