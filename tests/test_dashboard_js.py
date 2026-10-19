"""Comportamiento del JavaScript del dashboard, **ejecutado** con node.

De las 674 líneas de JS del panel, hasta ahora solo una función se ejecutaba en la suite (la
paridad de `acct()` con Python); el resto se cubría con `node --check` y *grep* sobre el HTML —
que comprueba que el fichero parsea y que cierto texto está ahí, no lo que hace.

Este módulo cubre las funciones donde un fallo **cambia lo que el usuario ve**:

- `computeRange`: decide qué se le pide al backend. Si se equivoca, el panel entero enseña otro
  periodo y todo lo demás es coherente con el dato equivocado.
- `localDayKey` / `byDay`: agrupan por **tu** día natural. El log está en UTC, así que aquí es
  donde se cruza la frontera de zona horaria — y el comentario del propio código avisa: «no uses
  toISOString(): eso vuelve a UTC».
- `agg`: alimenta los donuts.
- `fmtAgo`: el «hace X» del indicador de actividad.

**Los tests fijan `TZ` a una zona con offset negativo** y no confían en la del que ejecuta: con
`TZ=UTC` un `localDayKey` mal escrito pasaría igual, que es exactamente cómo estos fallos
sobreviven.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

from local_delegate import legacy_names
from local_delegate.web import metrics

TEST_TZ = "America/Havana"  # UTC-5/-4: si algo cae a UTC, se nota


def _extract(header: str) -> str:
    """Recorta una función del `<script>` balanceando llaves. Igual que en `test_metrics.py`."""
    source = metrics.HTML
    i = source.index(header)
    depth, j = 0, i
    while True:
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[i : j + 1]
        j += 1


def _legacy() -> str:
    """La tabla de valores viejos que el servidor inyecta (`__LEGACY_VALUES__`) y su traductor.

    `metrics.HTML` es la plantilla sin rellenar: aquí se pone lo mismo que pone `render_index`.
    """
    table = json.dumps(legacy_names.PANEL_VALUE_ALIASES)
    return f"const LEGACY_VALUES = {table};\n" + _extract("function legacyValue(")


def i18n_prelude(lang: str = "es") -> str:
    """El catálogo `panel.*` que inyecta `render_index` (`__I18N__`) y `T`, con el panel en `lang`.

    Las funciones del panel sacan sus textos de `T`: sin esto, en node no tienen de dónde. El idioma
    va explícito, como el `locale` de Playwright (REQ-043): los asserts en español no dependen de
    nada de la máquina.
    """
    return (
        f"const I18N = {metrics._script_json(metrics.panel_catalogs())};\n"
        f"const LANGS = ['es', 'en'];\nlet LANG = {json.dumps(lang)};\n"
        + _extract("function T(")
        + "\n"
        + _extract("function pickLang(")
    )


def _run(tmp_path, functions: list[str], body: str, prelude: str = "", lang: str = "es"):
    """Ejecuta `body` con esas funciones del panel cargadas. Devuelve lo que imprima en JSON."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")

    program = tmp_path / "test.mjs"
    program.write_text(
        "\n".join(
            [i18n_prelude(lang), _legacy(), prelude, *(_extract(f) for f in functions), body]
        ),
        encoding="utf-8",
    )
    # El entorno se hereda ENTERO con `TZ` encima. Recortarlo a `PATH` + `TZ` mata a node en
    # Windows con SIGABRT: necesita `SYSTEMROOT` y compañía. Lo que importa aquí es fijar la zona,
    # no aislar el proceso.
    env = {**os.environ, "TZ": TEST_TZ}
    output = subprocess.run(
        [node, str(program)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        env=env,
    )
    return json.loads(output.stdout)


# --- computeRange: qué periodo se le pide al backend --------------------------

_DATES_DOM = """
const _inputs = {rangeFrom:{value:''}, rangeTo:{value:''}};
globalThis.document = {getElementById: id => _inputs[id]};
"""


def test_today_starts_at_YOUR_midnight_not_at_UTC(tmp_path):
    """«Hoy» tiene que empezar a tu medianoche local; en UTC empezaría a otra hora.

    Es el defecto que la propia documentación del panel señala como delicado, y con `TZ=UTC` en
    el runner un `from` mal calculado pasaría desapercibido.
    """
    result = _run(
        tmp_path,
        ["function localMidnight(d, deltaDays){", "function computeRange(preset){"],
        "const r = computeRange('today');\n"
        "const d = new Date(r.from);\n"
        "console.log(JSON.stringify({\n"
        "  localHour: d.getHours(), localMin: d.getMinutes(), localSec: d.getSeconds(),\n"
        "  isUtcMidnight: r.from.includes('T00:00:00'),\n"
        "}));",
        prelude=_DATES_DOM,
    )

    assert (result["localHour"], result["localMin"], result["localSec"]) == (0, 0, 0)
    assert not result["isUtcMidnight"], (
        "el 'from' cayó en medianoche UTC: se está usando la medianoche equivocada"
    )


@pytest.mark.parametrize(("preset", "days"), [("7", 7), ("30", 30)])
def test_day_presets_include_today(tmp_path, preset, days):
    """7 días son hoy y los seis anteriores, no hoy y los siete anteriores.

    Un `off-by-one` aquí no rompe nada visible: el panel enseña un día de más y todo cuadra
    consigo mismo. Solo se caza contando.
    """
    result = _run(
        tmp_path,
        ["function localMidnight(d, deltaDays){", "function computeRange(preset){"],
        f"const r = computeRange({preset!r});\n"
        "const start = new Date(r.from), end = new Date(r.to);\n"
        "const todayMidnight = new Date(end.getFullYear(), end.getMonth(), end.getDate());\n"
        "console.log(JSON.stringify({\n"
        "  days: Math.round((todayMidnight - start) / 86400000) + 1,\n"
        "  startsAtMidnight: start.getHours() === 0 && start.getMinutes() === 0,\n"
        "}));",
        prelude=_DATES_DOM,
    )

    assert result["days"] == days
    assert result["startsAtMidnight"]


def test_the_previous_month_goes_from_day_1_to_day_1(tmp_path):
    """Medio abierto: incluye el mes entero y no se cuela ningún evento del actual."""
    result = _run(
        tmp_path,
        ["function localMidnight(d, deltaDays){", "function computeRange(preset){"],
        "const r = computeRange('prev-month');\n"
        "const start = new Date(r.from), end = new Date(r.to);\n"
        "const today = new Date();\n"
        "console.log(JSON.stringify({\n"
        "  startDay: start.getDate(), endDay: end.getDate(),\n"
        "  monthsApart: (end.getFullYear()-start.getFullYear())*12 "
        "+ (end.getMonth()-start.getMonth()),\n"
        "  endIsThisMonth: end.getMonth() === today.getMonth(),\n"
        "}));",
        prelude=_DATES_DOM,
    )

    assert (result["startDay"], result["endDay"]) == (1, 1)
    assert result["monthsApart"] == 1
    assert result["endIsThisMonth"], "el corte superior debe ser el día 1 del mes actual"


def test_the_custom_range_covers_the_whole_last_day(tmp_path):
    """Un `to` a las 00:00 se comería el día final completo — el error clásico de este control."""
    result = _run(
        tmp_path,
        ["function localMidnight(d, deltaDays){", "function computeRange(preset){"],
        "_inputs.rangeFrom.value = '2026-03-10';\n"
        "_inputs.rangeTo.value   = '2026-03-12';\n"
        "const r = computeRange('custom');\n"
        "const start = new Date(r.from), end = new Date(r.to);\n"
        "console.log(JSON.stringify({\n"
        "  start: [start.getDate(), start.getHours(), start.getMinutes()],\n"
        "  end: [end.getDate(), end.getHours(), end.getMinutes(), end.getSeconds()],\n"
        "}));",
        prelude=_DATES_DOM,
    )

    assert result["start"] == [10, 0, 0]
    assert result["end"] == [12, 23, 59, 59], "el día final tiene que entrar entero"


def test_an_unknown_preset_does_not_make_up_a_range(tmp_path):
    """Sin rango, el backend aplica su default; con uno inventado, enseñaría datos arbitrarios."""
    result = _run(
        tmp_path,
        ["function localMidnight(d, deltaDays){", "function computeRange(preset){"],
        "console.log(JSON.stringify(computeRange('lo-que-sea')));",
        prelude=_DATES_DOM,
    )
    assert result == {"from": None, "to": None}


# --- Agrupación por día local -------------------------------------------------


def test_the_day_key_is_local_and_not_utc(tmp_path):
    """Un evento de las 21:00 en La Habana es del **día siguiente** en UTC.

    Si `localDayKey` usara `toISOString()`, ese evento saltaría de barra en el gráfico. El
    comentario del código avisa de esto; el test lo obliga.
    """
    result = _run(
        tmp_path,
        ["function localDayKey(d){"],
        # 2026-03-10T02:00:00Z = 2026-03-09 21:00 en La Habana (UTC-5)
        "const d = new Date('2026-03-10T02:00:00Z');\n"
        "console.log(JSON.stringify({local: localDayKey(d), utc: d.toISOString().slice(0,10)}));",
    )

    assert result["utc"] == "2026-03-10"
    assert result["local"] == "2026-03-09", "la clave del día se calculó en UTC"


def test_byDay_groups_by_local_day_in_order(tmp_path):
    """Los eventos llegan del backend **más recientes primero**, así que el orden lo pone `byDay`.

    Los datos entran a propósito en orden inverso al esperado: con la entrada ya ordenada, quitar
    el `sort` del código no cambiaría nada y el test aprobaría un gráfico con las barras
    desordenadas. Comprobado con un mutante.
    """
    events = [
        {"ts": "2026-03-11T15:00:00Z", "tool": "t", "source": "path", "chars_in": 4000},
        {"ts": "2026-03-10T02:00:00Z", "tool": "t", "source": "path", "chars_in": 4000},
        {"ts": "2026-03-09T15:00:00Z", "tool": "t", "source": "path", "chars_in": 4000},
    ]
    result = _run(
        tmp_path,
        [
            "function localDayKey(d){",
            "function claudeTokens(",
            "function acct(e){",
            "function byDay(ev){",
        ],
        f"const ev = {json.dumps(events)};\n"
        "console.log(JSON.stringify(byDay(ev).map(([k, v]) => [k, v.calls])));",
        prelude="const CPT = 4;\nconst tok = c => Math.floor(c/CPT);\n",
    )

    # Los dos primeros caen en el mismo día LOCAL (9 de marzo), el tercero en el 11.
    assert result == [["2026-03-09", 2], ["2026-03-11", 1]]


def test_byDay_ignores_an_unreadable_ts_instead_of_blowing_up(tmp_path):
    """Una línea con la fecha corrupta no puede dejar el gráfico en blanco."""
    events = [
        {"ts": "no es una fecha", "tool": "t", "source": "path", "chars_in": 4000},
        {"ts": "2026-03-09T15:00:00Z", "tool": "t", "source": "path", "chars_in": 4000},
    ]
    result = _run(
        tmp_path,
        [
            "function localDayKey(d){",
            "function claudeTokens(",
            "function acct(e){",
            "function byDay(ev){",
        ],
        f"console.log(JSON.stringify(byDay({json.dumps(events)}).length));",
        prelude="const CPT = 4;\nconst tok = c => Math.floor(c/CPT);\n",
    )
    assert result == 1


# --- agg: lo que alimenta los donuts ------------------------------------------


def test_agg_sums_by_key_and_sorts_descending(tmp_path):
    """Suma por clave y ordena de mayor a menor. Los empates conservan el orden de aparición.

    Lo del empate no es una decisión de diseño sino una consecuencia de que `Array.sort` es
    estable y `Map` conserva el orden de inserción. Se fija en el test para que se vea, no para
    obligar a nada: si un día importara, tendría que ser explícito en el comparador.
    """
    events = [
        {"tool": "a", "n": 1},
        {"tool": "b", "n": 5},
        {"tool": "a", "n": 2},
        {"tool": "c", "n": 3},
    ]
    result = _run(
        tmp_path,
        ["function agg(ev,key,valfn"],
        f"console.log(JSON.stringify(agg({json.dumps(events)}, 'tool', e => e.n)));",
    )
    assert result == [["b", 5], ["a", 3], ["c", 3]]


def test_agg_drops_zero_categories(tmp_path):
    """Un donut con porciones de tamaño 0 pinta leyenda para lo que no se ve."""
    events = [{"tool": "a", "n": 0}, {"tool": "b", "n": 4}]
    result = _run(
        tmp_path,
        ["function agg(ev,key,valfn"],
        f"console.log(JSON.stringify(agg({json.dumps(events)}, 'tool', e => e.n)));",
    )
    assert result == [["b", 4]]


def test_agg_with_negatives_keeps_tools_below_zero(tmp_path):
    """REQ-004: en «Ahorro por herramienta» un neto negativo se enseña; un neto 0, no."""
    events = [
        {"tool": "a", "n": 300},
        {"tool": "b", "n": -100},
        {"tool": "a", "n": 200},
        {"tool": "c", "n": 0},
    ]
    result = _run(
        tmp_path,
        # Sin `){`: la cabecera tiene que casar con la firma de antes y con la de cuatro argumentos.
        ["function agg(ev,key,valfn"],
        f"console.log(JSON.stringify(agg({json.dumps(events)}, 'tool', e => e.n, "
        "{withNegatives:true})));",
    )
    assert ["b", -100] in result
    assert result == [["a", 500], ["b", -100]], "la herramienta con neto 0 no sale"


def test_the_sparkline_accepts_negatives():
    """REQ-004: con `min:0` en el eje, un acumulado negativo se quedaría pegado al borde."""
    source = _extract("function drawSpark(ev){")
    assert "min:0" not in source


# --- acct: la conversión a tokens de Claude pasa por una sola función -------------------------


def test_acct_converts_only_with_claudeTokens(tmp_path):
    """REQ-008 en el JS: con `claudeTokens` sustituida por un 7 fijo, ahorro y devuelto son 7."""
    event = {
        "source": "path",
        "chars_in": 4000,
        "chars_out": 400,
        "ok": True,
        "tokens_in": 1100,
        "tokens_out": 90,
    }
    r = _run(
        tmp_path,
        ["function acct(e){"],
        f"console.log(JSON.stringify(acct({json.dumps(event)})));",
        # No se extrae la `claudeTokens` real: la sustituye este doble.
        prelude="const CPT = 4;\nconst tok = c => Math.floor(c/CPT);\n"
        "function claudeTokens(){ return 7; }\n",
    )
    assert r["saved"] == 7
    assert r.get("returned") == 7
    assert r.get("net") == 0
    assert r["tokensIn"] == 1100, "el coste del modelo local no pasa por la conversión"


# --- fmtAgo: el «hace X» del indicador ---------------------------------------


def test_fmtAgo_changes_unit_at_the_boundaries(tmp_path):
    """Las fronteras exactas, que es donde vive el off-by-one de este tipo de función."""
    cases = [0, 59, 60, 119, 3599, 3600, 7199, 86399, 86400, 172800]
    result = _run(
        tmp_path,
        ["function fmtAgo(s){"],
        f"console.log(JSON.stringify({json.dumps(cases)}.map(fmtAgo)));",
    )
    assert result == [
        "0s",
        "59s",
        "1 min",
        "1 min",
        "59 min",
        "1 h",
        "1 h",
        "23 h",
        "1 d",
        "2 d",
    ]


# --- Formato de números, latencias y plurales (REQ-030 a REQ-033) ------------------------------
#
# `F` no es una función: es la expresión de la sentencia `const CPT = 4, F = …, PAGE = 10;`. Se
# recorta con una regex no codiciosa hasta `, PAGE` y se evalúa tal cual, así que el test mira la
# definición que usa el panel y no una copia. `fmtNum`, `F1`, `fmtSec` y `plural` se añaden solo si
# existen: con el código de antes, `_extract` lanzaría `ValueError` y el test fallaría por la
# extracción en vez de por el assert que importa.

# Un navegador sin `Intl.NumberFormat` v3 convierte `useGrouping: 'always'` en `true`, y con `true`
# el español no agrupa los números de cuatro cifras. Envolver poniendo `useGrouping: true` NO emula
# nada (en node 24 `true` ya agrupa): hay que BORRAR la opción.
_WITHOUT_INTL_V3 = """
const _NF = Intl.NumberFormat;
Intl.NumberFormat = function(loc, opts){
  const o = Object.assign({}, opts || {});
  delete o.useGrouping;
  return new _NF(loc, o);
};
"""


def _formatters() -> str:
    html = metrics.HTML
    m = re.search(r"const CPT = 4, F = (.*?), PAGE = ", html, re.DOTALL)
    assert m, "no se encontró la sentencia `const CPT = 4, F = …, PAGE = …;`"
    parts = []
    if "function fmtNum(" in html:
        parts.append(_extract("function fmtNum("))
    parts.append(f"const F = {m.group(1)};")
    m1 = re.search(r"const F1 = (.*?);", html)
    if m1:
        parts.append(f"const F1 = {m1.group(1)};")
    for header in ("function fmtSec(", "function plural("):
        if header in html:
            parts.append(_extract(header))
    return "\n".join(parts)


def test_F_groups_thousands_from_four_digits(tmp_path):
    """REQ-030: `8.003`, no `8003`. Con `Intl.NumberFormat('es')` el español no agrupa 4 cifras."""
    r = _run(tmp_path, [], "console.log(JSON.stringify(F.format(8003)));", _formatters())
    assert r == "8.003"


def test_F_groups_even_if_the_browser_lacks_Intl_v3(tmp_path):
    """REQ-030: el agrupado no puede depender de `useGrouping: 'always'`."""
    r = _run(
        tmp_path,
        [],
        "console.log(JSON.stringify(F.format(8003)));",
        _WITHOUT_INTL_V3 + _formatters(),
    )
    assert r == "8.003"


def test_decimals_with_comma_and_latency_in_seconds(tmp_path):
    """REQ-031 y REQ-032: un decimal con coma, signo menos, y nunca «0,0 s»."""
    r = _run(
        tmp_path,
        [],
        "console.log(JSON.stringify({seg: [fmtSec(116948), fmtSec(120), fmtSec(30)],"
        " f1: F1.format(1718.25), neg: F.format(-1234567)}));",
        _WITHOUT_INTL_V3 + _formatters(),
    )
    assert r["seg"][0] == "116,9 s"
    assert r["seg"][1] == "0,1 s"
    assert r["seg"][2] == "< 0,1 s"
    assert r["f1"] == "1.718,3"
    assert r["neg"] == "-1.234.567"


def test_plural_without_parentheses(tmp_path):
    """REQ-033: «1 estimado / 4 estimados»."""
    r = _run(
        tmp_path,
        [],
        "console.log(JSON.stringify([plural(1,'unit.estimated'),"
        " plural(4,'unit.estimated'), plural(1234,'unit.event')]));",
        _formatters(),
    )
    assert r[0] == "1 estimado"
    assert r[1] == "4 estimados"
    assert r[2] == "1.234 eventos"


def test_plural_in_english_uses_the_english_forms_and_separators(tmp_path):
    """REQ-026 en el panel en inglés: la palabra del catálogo inglés y la coma de miles."""
    r = _run(
        tmp_path,
        [],
        "console.log(JSON.stringify([plural(1,'unit.event'), plural(1234,'unit.event'),"
        " F1.format(1234.5), fmtSec(20)]));",
        _formatters(),
        lang="en",
    )
    assert r == ["1 event", "1,234 events", "1,234.5", "< 0.1 s"]


def test_no_plurals_with_parentheses_or_toFixed_remain():
    """REQ-031 y REQ-033 en todo el panel. No se busca `(s)` suelto: choca con `renderClients(s)`,
    `escHooks(s)` y `fmtAgo(s)`."""
    html = metrics.HTML
    assert "estimado(s)" not in html
    assert "archivo(s)" not in html
    assert "leído(s)" not in html
    assert "delegación(es)" not in html
    assert "toFixed(" not in html, "los decimales pasan todos por F1 (coma y un decimal)"


# --- Interruptor «Pruebas» (test-windows-out-of-metrics, T5) ------------------------------------

_TESTS_TEXT = [
    "function fmtNum(",
    "function plural(",
    "function fmtLocalTs(",
    "function testsText(",
]
_PRELUDE_F = (
    "const F = {format: n => fmtNum(n, 0)};\n"
    "const FMT_TIME = new Intl.DateTimeFormat('es',{day:'2-digit',month:'2-digit',"
    "hour:'2-digit',minute:'2-digit',hour12:false});"
)


def _tests_text(tmp_path, stats) -> str:
    body = f"console.log(JSON.stringify(testsText({json.dumps(stats)}).join('\\n')));"
    return _run(tmp_path, _TESTS_TEXT, body, _PRELUDE_F)


def test_tests_text_says_how_many_rows_are_left_out(tmp_path):
    text = _tests_text(tmp_path, {"excluded_tests": 7, "tests_in_range": 7})
    assert "Fuera de las cifras: 7 filas de prueba" in text
    assert "test-window stop <id>" in text  # cómo cerrar una prueba en vivo


def test_tests_text_without_tests_and_with_tests_included(tmp_path):
    assert "no hay pruebas" in _tests_text(tmp_path, {"excluded_tests": 0, "tests_in_range": 0})
    included = _tests_text(tmp_path, {"excluded_tests": 0, "tests_in_range": 1})
    assert "Pruebas incluidas: 1 fila de prueba" in included


def test_tests_text_names_the_open_window_with_its_command(tmp_path):
    stats = {
        "excluded_tests": 0,
        "tests_in_range": 0,
        "open_test_windows": [{"id": "w-20261008T090000Z", "start": "2026-10-08T09:00:00.000Z"}],
    }
    text = _tests_text(tmp_path, stats)
    assert "`local-delegate test-window stop w-20261008T090000Z`" in text
    # La hora, legible y en la zona local (TZ_PRUEBA = La Habana, UTC-4 en octubre), no cruda.
    # Con el formato de la tabla de actividad (`fmtLocalTs`); el cero del día depende del ICU.
    assert re.search(r"desde 0?8/10 05:00\.", text), text
    assert "2026-10-08T09:00:00" not in text


@pytest.mark.parametrize("include", [False, True])
def test_build_query_carries_the_range_and_the_switch(tmp_path, include):
    body = (
        "const q = new URLSearchParams(buildQuery({from: 'F', to: 'T'}, "
        + ("true" if include else "false")
        + "));\nconsole.log(JSON.stringify(Object.fromEntries(q)));"
    )
    data = _run(tmp_path, ["function buildQuery("], body)
    expected = {"from": "F", "to": "T", **({"include_tests": "1"} if include else {})}
    assert data == expected


_PRELUDE_FETCH = """
const urls = [];
globalThis.fetch = async u => { urls.push(u); return {json: async () => ({})}; };
const state = {range: 'today', tests: TESTS, events: [], meta: {}};
function computeRange(){ return {from: '2026-10-08T04:00:00.000Z', to: '2026-10-08T16:00:00.000Z'}; }
function renderClients(){} function renderCost(){} function renderTestsInfo(){}
function renderHooks(){} function render(){} function updateLive(){} function renderFoot(){}
function plural(){ return ''; }
const CPT = 4, TZ = 'x', TZ_OFFSET_TXT = 'y';
const document = {getElementById: () => ({textContent: '', innerHTML: '', classList: {add(){}}})};
"""


@pytest.mark.parametrize("include", [False, True])
def test_the_three_requests_carry_the_same_query(tmp_path, include):
    """REQ-016. Control: mutante «/api/hooks con su propia query sin el parámetro» → falla."""
    prelude = _PRELUDE_FETCH.replace("TESTS", "true" if include else "false")
    body = "await fetchData();\nconsole.log(JSON.stringify(urls));"
    urls = _run(tmp_path, ["function buildQuery(", "async function fetchData("], body, prelude)
    assert [u.split("?")[0] for u in urls] == ["/api/events", "/api/stats", "/api/hooks"]
    queries = {u.split("?", 1)[1] for u in urls}
    assert len(queries) == 1, urls
    (query,) = queries
    assert ("include_tests=1" in query) is include


# --- Idioma del panel (B4, REQ-020) ---------------------------------------------------------------


def test_pick_lang_follows_the_saved_choice_and_then_the_browser(tmp_path):
    """Lo guardado gana; sin nada guardado, español si el navegador empieza por `es`, si no inglés
    (al revés que la landing, decisión del 2026-10-12)."""
    cases = [
        ["es", "en-US"],
        ["en", "es-ES"],
        [None, "es-ES"],
        [None, "es"],
        [None, "es-419"],
        [None, "ES-mx"],
        [None, "en-US"],
        [None, "fr-FR"],
        [None, "est"],
        [None, ""],
        [None, None],
        ["fr", "es-ES"],
    ]
    body = f"console.log(JSON.stringify({json.dumps(cases)}.map(([s, n]) => pickLang(s, n))));"
    assert _run(tmp_path, [], body) == [
        "es",
        "en",
        "es",
        "es",
        "es",
        "es",
        "en",
        "en",
        "en",
        "en",
        "en",
        "es",
    ]


def test_t_interpolates_and_falls_back_to_spanish_then_to_the_key(tmp_path):
    body = """
    I18N.en['panel.only.es'] = undefined; delete I18N.en['panel.only.es'];
    I18N.es['panel.only.es'] = 'solo {x}';
    console.log(JSON.stringify([T('kpi.latency.label'), T('only.es', {x: 1}), T('no.such.key'),
      T('backend.no_models', {url: 'http://h'})]));
    """
    assert _run(tmp_path, [], body, lang="en") == [
        "Latency",
        "solo 1",
        "panel.no.such.key",
        "The backend exposes no models (http://h).",
    ]


# --- fmtCompact: la forma corta de un KPI que no cabe en su tarjeta ------------


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("es", ["999.999", "1,2 M", "45,7 mil M", "-3,5 M"]),
        ("en", ["999,999", "1.2M", "45.7B", "-3.5M"]),
    ],
)
def test_the_compact_figure_speaks_the_panel_language(tmp_path, lang, expected):
    """Por debajo del millón, la cifra entera; encima, millones y miles de millones con los
    separadores del idioma. En español no se usa «B»: ahí sería billón (10^12)."""
    result = _run(
        tmp_path,
        ["function fmtNum(", "function fmtCompact("],
        "console.log(JSON.stringify([fmtCompact(999999), fmtCompact(1234567),"
        " fmtCompact(45678901234), fmtCompact(-3456789)]));",
        lang=lang,
    )
    assert result == expected
