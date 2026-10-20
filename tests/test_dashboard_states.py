"""Estados del panel, **ejecutados** con node (T4 de `panel-cuentas-y-estados-honestos`).

Las decisiones del panel sobre el backend son funciones JS puras (`visibleState`, `badgeBackend`,
`modelState`, `sortModels`, `statusChip`, `statsText`, `systemRows`) para poder correrlas
aquí sin navegador, con `_extract`/`_run` de `test_dashboard_js.py`. Los sondeos (`pollInflight`,
`pollBackend`) se corren con un `fetch`, un `document` y un `setTimeout` de mentira: lo que se mira
es cuántas peticiones salen y qué se programa, que es lo que REQ-026 promete.

Los requisitos (REQ-014, REQ-020 a REQ-028) están en
`.sdd/changes/panel-cuentas-y-estados-honestos/spec.md`.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from test_dashboard_js import _extract, _formatters, _run

from local_delegate import config, i18n, server
from local_delegate.web import metrics

# --- piezas comunes ------------------------------------------------------------------------


def _const(name: str) -> str:
    """Una constante del panel definida como objeto literal (`const X = {…}`)."""
    return _extract(f"const {name} = {{") + ";"


# `_run` lee la salida con la codificación de la consola (cp1252 en Windows): todo lo que no es
# ASCII sale escapado en el JSON para que «Última» llegue como «Última» y no como «Ãšltima».
_EMIT = r"""
const emit = x => console.log(JSON.stringify(x).replace(/[\u007f-\uffff]/g,
  c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0')));
"""


def _globals() -> str:
    """Lo que las funciones de estado usan del panel: formateadores, `escHooks` y las tablas."""
    parts = [_EMIT, _formatters(), _extract("function escHooks(")]
    for function in ("initialView", "turnWords", "langQuery", "humanLabel", "labelFor"):
        if f"function {function}(" in metrics.HTML:
            parts.append(_extract(f"function {function}("))
    for name in ("CAUSES_ANSWERING", "RUNNING_WORDS", "WAIT_WORDS", "LABELS"):
        if f"const {name} = {{" in metrics.HTML:
            parts.append(_const(name))
    return "\n".join(parts)


def _js(tmp_path, functions: list[str], body: str, prelude: str = ""):
    return _run(tmp_path, functions, body, _globals() + "\n" + prelude)


def _f(name: str) -> str:
    """La cabecera con la que se recorta la función; con `async` delante si lo lleva."""
    async_header = f"async function {name}("
    return async_header if async_header in metrics.HTML else f"function {name}("


# Sondeos de `/api/backend` como los sirve el daemon.
GOOD = {
    "available": True,
    "running": [{"model": "gemma4-26b-a4b", "state": "ready"}],
    "running_ok": True,
    "models": [
        {"id": "gemma4-12b", "status": "unloaded"},
        {"id": "gemma4-26b-a4b", "status": "loaded"},
        {"id": "qwen35-2b", "status": "unloaded"},
        {"id": "qwen36-35b-a3b", "status": "unloaded"},
    ],
    "models_stale": False,
    "cause": None,
    "label": None,
    "detail": None,
}
FAILED = {
    "available": False,
    "running": [],
    "running_ok": False,
    "models": [{**m, "status": None} for m in GOOD["models"]],
    "models_stale": True,
    "cause": "dns",
    "label": "no resuelve",
    "detail": "no se resuelve el nombre pc.lan:9292 (¿VPN o DNS?)",
}
CATALOG = [
    {"role": "mechanical", "label": "mecánico", "model": "gemma4-26b-a4b"},
    {"role": "long", "label": "largo", "model": "gemma4-26b-a4b"},
    {"role": "code", "label": "código", "model": "qwen36-35b-a3b"},
    {"role": "vision", "label": "visión", "model": "gemma4-12b"},
]


def _failed(cause: str, label: str, detail: str) -> dict:
    return {**FAILED, "cause": cause, "label": label, "detail": detail}


# --- visibleState: dos sondeos fallidos antes de «caído» (REQ-028) ----------------------------


def test_two_failures_before_down(tmp_path):
    """Escenario «dos fallos antes de caído». Control (b): umbral 1 → `seen[1]` sería caído."""
    r = _js(
        tmp_path,
        [_f("visibleState")],
        f"""
        const B = {json.dumps(GOOD)}, X = {json.dumps(FAILED)};
        let v = null; const seenStates = [];
        for (const bj of [B, X, X, B]) {{ v = visibleState(v, bj); seenStates.push(v.status); }}
        const fromZero = [];
        let w = null;
        for (const bj of [X, X]) {{ w = visibleState(w, bj); fromZero.push(w.status); }}
        emit(({{seenStates, fromZero}}));
        """,
    )
    seen, seen_from_zero = r["seenStates"], r["fromZero"]
    assert seen[1] == "connected"
    assert seen == ["connected", "connected", "down", "connected"]
    assert seen_from_zero[0] == "checking"
    assert seen_from_zero[1] == "down"


def _rows_after(tmp_path, sequence: list[dict]) -> list[dict]:
    """La fila de `gemma4-26b-a4b` tras cada sondeo de la secuencia, sin nada en vuelo."""
    return _js(
        tmp_path,
        [_f("visibleState"), _f("modelState")],
        f"""
        let v = null; const rowsOut = [];
        for (const bj of {json.dumps(sequence)}) {{
          v = visibleState(v, bj);
          rowsOut.push(modelState({{model: 'gemma4-26b-a4b', view: v, inflight: []}}));
        }}
        emit((rowsOut));
        """,
    )


def test_the_rows_withstand_the_first_failure(tmp_path):
    """Escenario «las filas aguantan el primer fallo» (REQ-022, REQ-028).

    Control (b). Mutante 1: las filas leen el último `bj` y no el sondeo de referencia → tras el
    primer fallo dirían «frío» (`status: null`, `running_ok: false`, regla 5). Mutante 2: atenuar
    por `models_stale` → la fila saldría atenuada tras el primer fallo.
    """
    rows = _rows_after(tmp_path, [GOOD, FAILED, FAILED])
    assert rows[0]["text"] == "montado"
    row = rows[1]
    assert row["text"] == "montado"
    assert row["dimmed"] is False
    row = rows[2]
    assert row["text"] == "desconocido"
    assert row["dimmed"] is True
    assert row["title"] == "sin conexión con el backend: no resuelve"


# --- badgeBackend (REQ-014) ------------------------------------------------------------------


def _badge(tmp_path, sequence: list[dict]) -> dict:
    return _js(
        tmp_path,
        [_f("visibleState"), _f("badgeBackend")],
        f"""
        let v = null;
        for (const bj of {json.dumps(sequence)}) v = visibleState(v, bj);
        emit((badgeBackend(v, 'http://pc.lan:9292/v1')));
        """,
    )


def test_the_badge_states_the_cause(tmp_path):
    """Control (b). Mutante 1: `credential` como caída → falla `css_class == "warn"`. Mutante 2:
    `title` fijo → falla `title == detalle`."""
    det_401 = "pc.lan:9292 responde 401: está arriba pero rechaza la credencial"
    cred = _failed("credential", "sin acceso", det_401)
    b = _badge(tmp_path, [cred, cred])
    css_class, text, title = b["cls"], b["text"], b["title"]
    assert css_class == "warn"
    assert text == "sin acceso"
    assert title == det_401

    http = _failed("http_error", "responde con error", "pc.lan:9292 responde HTTP 500")
    b = _badge(tmp_path, [http, http])
    assert b["cls"] == "warn"
    assert "caído" not in b["text"]

    b = _badge(tmp_path, [FAILED, FAILED])
    assert b["text"] == "caído · no resuelve"
    assert b["cls"] == "down"
    assert b["title"] == FAILED["detail"]

    b = _badge(tmp_path, [GOOD])
    assert (b["text"], b["cls"], b["title"]) == ("conectado", "up", "http://pc.lan:9292/v1")


def test_the_badge_understands_the_old_cause_value(tmp_path):
    """REQ-009: el diccionario de causas del JS acepta el valor viejo y el nuevo, con la tabla que
    inyecta el servidor (`LEGACY_VALUES.connectionCause`), no con una copia propia."""
    det_401 = "pc.lan:9292 responde 401: está arriba pero rechaza la credencial"
    old = _failed("credencial", "sin acceso", det_401)
    b = _badge(tmp_path, [old, old])
    assert (b["cls"], b["text"]) == ("warn", "sin acceso")
    assert "credencial" not in re.sub(
        r"//[^\n]*", "", metrics.HTML.split("CAUSES_ANSWERING", 1)[1][:200]
    )


def test_the_badge_warns_about_the_last_probe_while_still_saying_connected(tmp_path):
    """REQ-028: un fallo tras uno bueno conserva «conectado» y lo cuenta en el `title`."""
    b = _badge(tmp_path, [GOOD, FAILED])
    assert b["text"] == "conectado"
    assert "último sondeo: " + FAILED["detail"] in b["title"]

    b = _badge(tmp_path, [FAILED])
    assert b["text"] == "comprobando…"
    assert b["cls"] == "neutral"


# --- modelState: la tabla de REQ-022, una fila por regla ------------------------------------


def _row(tmp_path, cases: list[dict]) -> list[dict]:
    """`cases`: [{sequence, inflight}] → la fila de `qwen36-35b-a3b` tras la secuencia."""
    return _js(
        tmp_path,
        [_f("visibleState"), _f("modelState")],
        f"""
        const out = [];
        for (const c of {json.dumps(cases)}) {{
          let v = null;
          for (const bj of c.sequence) v = visibleState(v, bj);
          out.push(modelState({{model: c.model || 'qwen36-35b-a3b', view: v,
                                  inflight: c.inflight}}));
        }}
        emit((out));
        """,
    )


def _with_running(
    running: list[dict], *, running_ok: bool = True, status: str = "unloaded"
) -> dict:
    models = [
        {**m, "status": status if m["id"] == "qwen36-35b-a3b" else m["status"]}
        for m in GOOD["models"]
    ]
    return {**GOOD, "running": running, "running_ok": running_ok, "models": models}


IN_FLIGHT = [{"model": "qwen36-35b-a3b", "tool": "local_summarize"}]
QWEN_STARTING = [{"model": "qwen36-35b-a3b", "state": "starting"}]
QWEN_READY = [{"model": "qwen36-35b-a3b", "state": "ready"}]


def test_model_state_one_row_per_rule(tmp_path):
    """Control (b), tres mutantes de orden y de regla (ver `verification.md`)."""
    cases = [
        # 1. no disponible y en vuelo
        {"sequence": [FAILED, FAILED], "inflight": IN_FLIGHT},
        # 2. no disponible
        {"sequence": [FAILED, FAILED], "inflight": []},
        # 3. en vuelo y en espera local (gana a running `ready`)
        {
            "sequence": [_with_running(QWEN_READY)],
            "inflight": [{**IN_FLIGHT[0], "local_wait": "slot"}],
        },
        # 4. running_ok falso y en vuelo
        {"sequence": [_with_running([], running_ok=False)], "inflight": IN_FLIGHT},
        # 5. running_ok falso: montado si loaded, si no frío
        {"sequence": [_with_running([], running_ok=False, status="loaded")], "inflight": []},
        {"sequence": [_with_running([], running_ok=False)], "inflight": []},
        # 6. starting, aunque /v1/models diga loaded y haya una llamada en vuelo
        {"sequence": [_with_running(QWEN_STARTING, status="loaded")], "inflight": IN_FLIGHT},
        # 7 y 8. ready
        {"sequence": [_with_running(QWEN_READY)], "inflight": IN_FLIGHT},
        {"sequence": [_with_running(QWEN_READY)], "inflight": []},
        # 9. en vuelo y el modelo no está en /running
        {
            "sequence": [_with_running([{"model": "gemma4-26b-a4b", "state": "ready"}])],
            "inflight": IN_FLIGHT,
        },
        # 10. stopping
        {
            "sequence": [_with_running([{"model": "qwen36-35b-a3b", "state": "stopping"}])],
            "inflight": [],
        },
        # 11. resto
        {"sequence": [_with_running([])], "inflight": []},
        # 1 con running_ok falso: la regla 1 gana a la 4
        {"sequence": [FAILED, FAILED], "inflight": IN_FLIGHT},
    ]
    rows = _row(tmp_path, cases)
    txt = [f["text"] for f in rows]
    assert txt[0] == "esperando al backend"
    assert txt[1] == "desconocido"
    assert txt[2] == "en cola local"
    assert txt[3] == "en curso"
    assert txt[4] == "montado"
    assert txt[5] == "frío"
    assert txt[6] == "cargando"
    assert txt[7] == "procesando"
    assert txt[8] == "montado"
    assert txt[9] == "esperando turno"
    assert txt[10] == "descargando"
    assert txt[11] == "frío"
    assert txt[12] == "esperando al backend"
    assert rows[2]["title"] == (
        "esperando dentro de local-delegate: esperando plaza (máximo de llamadas a la vez)"
    )
    assert [f["dimmed"] for f in rows[:2]] == [True, True]
    assert not any(f["dimmed"] for f in rows[2:12])


def test_the_local_wait_is_an_extension_point(tmp_path):
    """Un motivo que el panel no conoce también es «en cola local», y se pinta tal cual.

    Control (b). Mutante: la regla 3 exige `local_wait === 'slot'` → da «procesando».
    """
    row = _row(
        tmp_path,
        [
            {
                "sequence": [_with_running(QWEN_READY)],
                "inflight": [{**IN_FLIGHT[0], "local_wait": "group_turn"}],
            }
        ],
    )[0]
    txt, title = row["text"], row["title"]
    assert txt == "en cola local"
    assert "group_turn" in title


def test_the_local_wait_requires_every_call(tmp_path):
    """«En espera local» = TODAS las llamadas a ese modelo esperan dentro de local-delegate."""
    in_flight = [{**IN_FLIGHT[0], "local_wait": "slot"}, IN_FLIGHT[0]]
    row = _row(tmp_path, [{"sequence": [_with_running(QWEN_READY)], "inflight": in_flight}])[0]
    assert row["text"] == "procesando"


def test_waiting_for_turn_does_not_assert_the_cause(tmp_path):
    """Fila 9: el `title` lista /running en palabras. Control (b): solo los `ready` → falla."""
    running = [
        {"model": "gemma4-26b-a4b", "state": "ready"},
        {"model": "qwen35-2b", "state": "starting"},
    ]
    rows = _row(
        tmp_path,
        [
            {"sequence": [_with_running(running)], "inflight": IN_FLIGHT},
            {"sequence": [_with_running([])], "inflight": IN_FLIGHT},
        ],
    )
    assert rows[0]["text"] == "esperando turno"
    title = rows[0]["title"]
    assert "qwen35-2b cargando" in title
    assert (
        title
        == "llama-swap aún no lo atiende; en /running: gemma4-26b-a4b listo, qwen35-2b cargando"
    )
    assert rows[1]["title"] == "llama-swap aún no lo atiende; /running está vacío"


def test_scenario_loading_turn_and_own_queue(tmp_path):
    """Escenario de la spec, con los modelos que nombra: «qwen36-35b-a3b cargando» en el title."""
    running = [
        {"model": "gemma4-26b-a4b", "state": "ready"},
        {"model": "qwen36-35b-a3b", "state": "starting"},
    ]
    rows = _row(
        tmp_path,
        [
            {
                "model": "gemma4-12b",
                "sequence": [_with_running(running)],
                "inflight": [{"model": "gemma4-12b"}],
            },
        ],
    )
    assert rows[0]["text"] == "esperando turno"
    assert "qwen36-35b-a3b cargando" in rows[0]["title"]
    assert "gemma4-26b-a4b listo" in rows[0]["title"]


# --- sortModels (REQ-021) y statusChip (REQ-023) ------------------------------------------


def test_model_order_with_and_without_connection(tmp_path):
    """Control (b). Mutante: orden alfabético puro → `gemma4-12b` primero."""
    r = _js(
        tmp_path,
        [_f("sortModels")],
        f"""
        const cat = {json.dumps(CATALOG)};
        const withList = sortModels(['gemma4-12b','gemma4-26b-a4b','qwen35-2b','qwen36-35b-a3b'], cat);
        const withoutList = sortModels([], cat);
        emit(({{withList, withoutList}}));
        """,
    )
    ids = r["withList"]
    assert ids == ["gemma4-26b-a4b", "qwen36-35b-a3b", "gemma4-12b", "qwen35-2b"]
    assert r["withoutList"] == ["gemma4-26b-a4b", "qwen36-35b-a3b", "gemma4-12b"]


def test_status_chip_accepts_any_value(tmp_path):
    """Control (b). Mutante: todo lo que no es `loaded` con el estilo de `unloaded`."""
    r = _js(
        tmp_path,
        [_f("statusChip")],
        "emit((['loaded','unloaded','starting',null,undefined].map(statusChip)));",
    )
    assert r[0] == "loaded"
    assert r[1] == "unloaded"
    assert r[2] == "neutral"
    assert r[3] is None and r[4] is None


# --- renderBackendStats y statsText (REQ-020) ---------------------------------------------

_DOM = """
const _els = {};
const document = {
  visibilityState: 'visible',
  getElementById: id => (_els[id] = _els[id] || {id, innerHTML: '', textContent: '', style: {},
                                                  title: '', className: ''}),
};
"""


def test_the_llama_swap_version_is_blamed_only_on_a_404(tmp_path):
    """Control (a) con `dns`; (b) para la rama positiva: mutante «nunca menciona v236»."""
    functions = [_f("renderBackendStats")]
    if "function statsText(" in metrics.HTML:
        functions.insert(0, _f("statsText"))
    r = _js(
        tmp_path,
        functions,
        """
        renderBackendStats({available:false, cause:'dns', label:'no resuelve',
                            detail:'no se resuelve el nombre pc.lan (¿VPN o DNS?)'});
        const dns = _els.backendStats.innerHTML;
        renderBackendStats({available:false, cause:'http_error', label:'responde con error',
                            detail:'pc.lan responde HTTP 404', status_http:404});
        const e404 = _els.backendStats.innerHTML;
        emit(({dns, e404}));
        """,
        _DOM,
    )
    html = r["dns"]
    assert "v236" not in html
    assert "sin datos: no resuelve" in html
    html = r["e404"]
    assert "v236" in html


# --- systemRows (REQ-025) --------------------------------------------------------------------


def test_system_panel_rows(tmp_path):
    """La tarjeta Sistema dice lo que no mide con filas etiqueta/valor, no con prosa.

    Mutantes: sin la rama de `origin` → falla la fila «Backend» de la Mac; con el host completo
    (`own-pc…:9292`) → falla el valor sin puerto; sin validar el esquema → falla `javascript:`.
    """
    r = _js(
        tmp_path,
        [_f("systemRows")],
        """
        const testCases = [
          {platform:'darwin', origin:'remote', host:'pc.ts.net:9292',
           panel_url:'https://pc.ts.net:9393/', ram:null, vram:null, processes:[]},
          {platform:'win32', origin:'local', host:'127.0.0.1:9292', panel_url:'',
           ram:{pct:1}, vram:null, processes:[]},
          {platform:'linux', origin:'remote', host:'pc.lan:9292', panel_url:'javascript:alert(1)',
           ram:{pct:1}, vram:null, processes:[{name:'python', pid:1, ram_mb:10}]},
          {platform:'darwin', origin:'local', host:'127.0.0.1:9292', panel_url:'',
           ram:null, vram:null, processes:[]},
        ];
        emit(testCases.map(systemRows));
        """,
    )
    mac, win, linux, mac_local = r
    assert mac["rows"] == [
        {"label": "Backend", "value": "pc.ts.net", "href": "https://pc.ts.net:9393/"},
        {"label": "RAM / VRAM", "value": None, "href": None},
    ]
    assert mac["showProcs"] is False  # los procesos del backend no están en esta máquina
    assert win == {"rows": [], "showProcs": True}  # con RAM medida no hay filas de «—»
    assert linux["rows"] == [{"label": "Backend", "value": "pc.lan", "href": None}]
    assert linux["showProcs"] is True  # hay procesos locales que enseñar
    assert mac_local["rows"] == [
        {"label": "RAM / VRAM", "value": None, "href": None},
        {"label": "Procesos", "value": None, "href": None},
    ]
    assert mac_local["showProcs"] is False


# --- Sondeos: separados, sin solaparse y encadenados (REQ-026, REQ-027) ------------------------

_POLLING = (
    _DOM
    + """
const state = {inflight: [], activity: null, lastEvent: null, status: null, view: null,
               backendOrigin: null, backendHost: null};
const callCount = {};
let fetchPending = {};          // url -> true: esa ruta no resuelve nunca
let responses = {};              // url -> [json, json, …] (se consumen en orden)
globalThis.fetch = full => {
  const url = full.split('?')[0];   // el panel añade `?lang=` (D6): la cuenta es por ruta
  callCount[url] = (callCount[url] || 0) + 1;
  if (fetchPending[url]) return new Promise(() => {});
  const queue = responses[url] || [{}];
  const j = queue.length > 1 ? queue.shift() : queue[0];
  return Promise.resolve({json: () => Promise.resolve(j)});
};
const delays = [];
globalThis.setTimeout = (fn, ms) => { delays.push(ms); return delays.length; };
globalThis.clearTimeout = () => {};
let renders = 0;
function renderBackend(){} function renderTools(){} function updateLive(){}
function renderInflight(){ renders++; }
function renderBackendStats(){}
const tick = () => new Promise(r => setImmediate(r));
"""
)


def _polling_globals() -> str:
    """El estado de los sondeos (`const POLL = {…}`) si ya existe."""
    return _const("POLL") if "const POLL = {" in metrics.HTML else ""


def test_pollInflight_does_not_stack(tmp_path):
    """Control (a): hoy cada llamada lanza otra petición (3, más 3 de `/api/backend`)."""
    r = _js(
        tmp_path,
        [_f("pollInflight")],
        """
        fetchPending['/api/inflight'] = true; fetchPending['/api/backend'] = true;
        pollInflight(); pollInflight(); pollInflight();
        await tick();
        emit((callCount));
        """,
        _POLLING + _polling_globals(),
    )
    fetch_inflight_calls = r.get("/api/inflight", 0)
    assert fetch_inflight_calls == 1
    assert r.get("/api/backend", 0) == 0  # el sondeo de En curso ya no pide el backend


def test_pollInflight_chains_after_finishing(tmp_path):
    """Control (a): hoy `pollInflight` no programa nada (lo hacía un `setInterval` al arrancar)."""
    r = _js(
        tmp_path,
        [_f("pollInflight")],
        """
        responses['/api/inflight'] = [{inflight: [], now: new Date().toISOString()}];
        responses['/api/backend'] = [{available: true}];
        await pollInflight();
        await tick();
        emit(({delays}));
        """,
        _POLLING + _polling_globals(),
    )
    assert r["delays"] == [2000]


def test_a_slow_backend_does_not_freeze_in_progress(tmp_path):
    """Control (a): hoy `Promise.all` espera a `/api/backend` y no pinta «En curso»."""
    functions = [_f("pollInflight")]
    poll_call = "pollNow()" if "function pollNow(" in metrics.HTML else "pollInflight()"
    if "function pollNow(" in metrics.HTML:
        functions += [_f("pollBackend"), _f("applyBackend"), _f("pollNow")]
    r = _js(
        tmp_path,
        functions,
        f"""
        fetchPending['/api/backend'] = true;
        responses['/api/inflight'] = [{{inflight: [], now: new Date().toISOString()}}];
        {poll_call}; {poll_call}; {poll_call};
        for (let i = 0; i < 5; i++) await tick();
        emit(({{renders, callCount}}));
        """,
        _POLLING + _polling_globals(),
    )
    renders_inflight = r["renders"]
    assert renders_inflight >= 1
    assert r["callCount"].get("/api/backend", 0) <= 1
    assert r["callCount"].get("/api/inflight", 0) <= 1


def test_on_reconnect_everything_is_refreshed(tmp_path):
    """REQ-027. Control (b): sin `fetchStatus()` al pasar a disponible → 0 peticiones de status."""
    x, b = json.dumps(FAILED), json.dumps(GOOD)
    r = _js(
        tmp_path,
        [_f("visibleState"), _f("pollBackend"), _f("applyBackend"), _f("fetchStatus")],
        f"""
        responses['/api/backend'] = [{x}, {x}, {b}];
        const stateLog = [];
        for (let i = 0; i < 3; i++) {{
          await pollBackend(); await tick(); stateLog.push(state.view.status);
        }}
        await tick(); await tick();
        emit(({{stateLog, callCount, delays}}));
        """,
        _POLLING + _polling_globals(),
    )
    assert r["stateLog"] == ["checking", "down", "connected"]
    status_calls = r["callCount"].get("/api/status", 0)
    assert status_calls == 1
    assert r["callCount"].get("/api/backend/stats", 0) == 1
    assert r["delays"] == [2000, 2000, 2000]


# --- renderInflight (REQ-024) ----------------------------------------------------------------


def test_last_delegation_when_nothing_runs(tmp_path):
    """Control (a): hoy el título sigue «En curso» con la última terminada."""
    r = _js(
        tmp_path,
        [_f("renderInflight"), _f("fmtAgo")],
        """
        const state = {inflight: [], activity: {skewMs: 0},
                       lastEvent: {ts: new Date(Date.now() - 8000).toISOString(),
                                   tool: 'local_summarize', model: 'm', latency_ms: 1200,
                                   chars_in: 10, ok: true}};
        renderInflight();
        const lastHtml = _els.inflightHead.innerHTML;
        state.lastEvent = null; renderInflight();
        const emptyHtml = _els.inflightHead.innerHTML;
        state.inflight = [{tool: 't', model: 'm', elapsed_s: 1, chars_in: 1}]; renderInflight();
        const liveHtml = _els.inflightHead.innerHTML;
        emit(({lastHtml, emptyHtml, liveHtml}));
        """,
        _DOM,
    )
    head = r["lastHtml"]
    assert head == "Última delegación"
    assert r["emptyHtml"] == "En curso"
    assert r["liveHtml"].startswith("En curso")


def test_the_js_does_not_word_the_cause_labels():
    """REQ-011: la etiqueta corta llega del daemon (`failures.py`); el panel no tiene su copia."""
    for label in ("no resuelve", "nadie escucha", "sin acceso", "responde con error"):
        assert not re.search(rf"['\"]{label}['\"]", metrics.HTML), label


# --- T10 de daemon-reparte-el-backend: la espera de turno del daemon (REQ-008, REQ-027) --------


def test_turn_wait_shown_in_panel_as_local_wait(tmp_path, monkeypatch):
    """Escenario «la espera de turno se ve en el panel como espera local», de punta a punta.

    Una operación del 26B tiene el turno (atascada en el backend) y una de Qwen3.6 lo espera; se lee
    `/api/inflight` con `TestClient` y su entrada pasa a `modelState` con node, con Qwen3.6
    `ready` en `/running`. Control (b). Mutante 1: una clave propia (`esperando_turno: true`) en
    vez de `local_wait` → la fila sale «procesando». Mutante 2: `inflight_snapshot` sin copiar
    `turn_in_use` → el `title` dice «en uso: nada».
    """
    today = Path(__file__).parent / "fixtures" / "topology" / "today.yaml"
    copy = tmp_path / "llamaswap.yaml"
    copy.write_bytes(today.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copy))
    monkeypatch.setattr(config, "BASE_URL", "http://127.0.0.1:9292/v1")
    monkeypatch.setattr(server, "_chat_slots", threading.BoundedSemaphore(2))
    x_inside, continue_x = threading.Event(), threading.Event()

    def post_chat(model, _payload):
        if model == "gemma4-26b-a4b":
            x_inside.set()
            continue_x.wait(5)
        return server.ChatResult(text="ok", ok=True, finish_reason="stop")

    monkeypatch.setattr(server, "_post_chat", post_chat)

    def operation(model: str, tool: str) -> None:
        server._chat(model, "s", "u", 8, tool=tool, role="long")

    threads = [
        threading.Thread(target=operation, args=("gemma4-26b-a4b", "op_x"), daemon=True),
        threading.Thread(target=operation, args=("qwen36-35b-a3b", "op_y"), daemon=True),
    ]
    client = TestClient(metrics.app)

    def op_y_entry() -> dict | None:
        rows = client.get("/api/inflight").json()["inflight"]
        return next((e for e in rows if e.get("tool") == "op_y"), None)

    try:
        threads[0].start()
        assert x_inside.wait(2), "la operación del 26B no llegó al backend"
        threads[1].start()
        entry = None
        end = time.monotonic() + 2
        while time.monotonic() < end:
            e = op_y_entry()
            queued = bool(server._turn.snapshot().queue)
            # Las dos marcas: `turn_in_use` se publica antes que `local_wait` (server.py,
            # `on_wait`), y una entrada con solo la primera aún se pinta «procesando».
            if queued and e and e.get("local_wait") and e.get("turn_in_use"):
                entry = e
                break
            time.sleep(0.01)
        assert entry, f"la operación de Qwen3.6 no llegó a esperar turno: {op_y_entry()}"
    finally:
        continue_x.set()
        for thread in threads:
            thread.join(5)

    row = _row(tmp_path, [{"sequence": [_with_running(QWEN_READY)], "inflight": [entry]}])[0]
    assert row["text"] == "en cola local"
    assert "esperando turno del daemon" in row["title"]
    assert "en uso: gemma4-26b-a4b" in row["title"]
    assert row["title"].count("esperando") == 1, row["title"]  # sin «esperando … esperando»


def test_in_progress_shows_turn_wait(tmp_path):
    """«En curso» pinta la espera de turno con las mismas palabras que el `title` de la fila.

    Control (a): hoy «En curso» no dice nada de la espera.
    """
    r = _js(
        tmp_path,
        [_f("renderInflight")],
        """
        const state = {inflight: [{tool: 't', model: 'qwen36-35b-a3b', elapsed_s: 1, chars_in: 1,
                                   local_wait: 'turn', turn_in_use: ['gemma4-26b-a4b'],
                                   turn_position: 1}],
                       activity: {skewMs: 0}, lastEvent: null};
        renderInflight();
        emit(_els.inflightBody.innerHTML);
        """,
        _DOM,
    )
    assert "esperando turno del daemon (en uso: gemma4-26b-a4b)" in r


# --- Espera frente a lentitud (T14 de daemon-reparte-el-backend, REQ-027) ----------------------


def test_slow_mark_uses_the_panel_number_format(tmp_path):
    """Mutante (b): punto decimal (`toFixed`) → falla `assert txt == "lento ×0,37"`."""
    r = _js(
        tmp_path,
        [_f("slowMark")],
        """
        emit({txt: slowMark({slow: true, pace_rel: 0.37}),
                notSlow: slowMark({slow: false, pace_rel: 0.8}),
                noField: slowMark({pace_rel: 0.37})});
        """,
    )
    txt = r["txt"]
    assert txt == "lento ×0,37"
    assert r["notSlow"] == ""
    assert r["noField"] == ""


def test_wait_and_inference_shown_apart(tmp_path):
    """La espera y la inferencia por separado; sin `inference_ms`, nada (no se inventa reparto)."""
    r = _js(
        tmp_path,
        [_f("waitInferenceText")],
        """
        emit({both: waitInferenceText({wait_ms: 47000, inference_ms: 10500}),
                none: waitInferenceText({latency_ms: 57500})});
        """,
    )
    assert r["both"] == "espera 47,0 s · inferencia 10,5 s"
    assert r["none"] == ""


def test_activity_row_shows_wait_inference_and_slow_mark(tmp_path):
    """La fila de actividad de una llamada lenta lleva las dos cosas y la marca (escenario D).

    Control (a): hoy la fila solo enseña la latencia total.
    """
    # Las dos ayudantes solo si existen: así el control (a) cae en el assert y no al recortarlas.
    helpers = [
        _f(n)
        for n in ("slowMark", "waitInferenceText", *_EVENT_FUNCTIONS)
        if f"function {n}(" in metrics.HTML
    ]
    functions = [_f("fmtLocalTs"), *helpers, _f("drawActivity")]
    r = _js(
        tmp_path,
        functions,
        """
        drawActivity([{ts: '2026-10-07T10:00:00+00:00', tool: 'local_summarize',
                       model: 'gemma4-26b-a4b', source: 'inline', backend: 'local',
                       chars_in: 10000, chars_out: 300, latency_ms: 57500, ok: true,
                       inference_ms: 10500, wait_ms: 47000, tok_s: 15, pace_rel: 0.37,
                       slow: true}]);
        emit(_els.activity.innerHTML);
        """,
        _DOM
        + "\nconst PAGE = 10;\nconst state = {page: 0};\n"
        + "const FMT_TIME = new Intl.DateTimeFormat('es', {hour: '2-digit', minute: '2-digit'});\n",
    )
    assert "espera 47,0 s · inferencia 10,5 s" in r
    assert "lento ×0,37" in r
    # Marca propia, distinta de la del salto (`fbchip`): en una fila con las dos no se confunden.
    assert 'class="chunkchip slowchip"' in r
    assert "fbchip" not in r


def test_activity_row_affinity_has_no_fallback_chip(tmp_path):
    """T15 (REQ-016): la afinidad lleva `model_requested`, pero la fila no la marca como salto; un
    salto de verdad sí."""
    helpers = [
        _f(n)
        for n in ("slowMark", "waitInferenceText", *_EVENT_FUNCTIONS)
        if f"function {n}(" in metrics.HTML
    ]
    functions = [_f("fmtLocalTs"), *helpers, _f("drawActivity")]
    row = (
        "{ts: '2026-10-07T10:00:00+00:00', tool: 'local_translate', model: 'gemma4-26b-a4b',"
        " source: 'inline', backend: 'local', chars_in: 10, chars_out: 10, latency_ms: 900,"
        " ok: true, model_requested: 'gemma3-4b', %s}"
    )
    r = _js(
        tmp_path,
        functions,
        f"""
        drawActivity([{row % "routing: 'affinity'"}]);
        const affinity = _els.activity.innerHTML;
        drawActivity([{row % "fallback_reason: 'http_500'"}]);
        emit({{affinity: affinity, fallback: _els.activity.innerHTML}});
        """,
        _DOM
        + "\nconst PAGE = 10;\nconst state = {page: 0};\n"
        + "const FMT_TIME = new Intl.DateTimeFormat('es', {hour: '2-digit', minute: '2-digit'});\n",
    )
    assert "fbchip" in r["fallback"], "guarda: el mismo guion con un salto sí lleva la marca"
    assert "fbchip" not in r["affinity"]


# --- Parámetros por rol y razonamiento (T15 de backend-extra-params, REQ-019) -------------------

_ACTIVITY_PRELUDE = (
    _DOM
    + "\nconst PAGE = 10;\nconst state = {page: 0};\n"
    + "const FMT_TIME = new Intl.DateTimeFormat('es', {hour: '2-digit', minute: '2-digit'});\n"
)
_EVENT_FUNCTIONS = ("paramKeys", "activityMarks", "eventRows", "eventTable")


def _activity_html(tmp_path, *events: str) -> list[str]:
    """La fila que pinta `drawActivity` para cada evento (literal JS), una tabla por evento."""
    helpers = [
        _f(n)
        for n in ("slowMark", "waitInferenceText", *_EVENT_FUNCTIONS)
        if f"function {n}(" in metrics.HTML
    ]
    functions = [_f("fmtLocalTs"), *helpers, _f("drawActivity")]
    body = "const out = [];\n"
    for event in events:
        body += f"drawActivity([{event}]);\nout.push(_els.activity.innerHTML);\n"
    return _js(tmp_path, functions, body + "emit(out);", _ACTIVITY_PRELUDE)


_BASE = (
    "ts: '2026-10-20T10:00:00+00:00', tool: 'local_explain_code', model: 'qwen36-35b-a3b',"
    " source: 'path', backend: 'local', chars_in: 1000, chars_out: 200, latency_ms: 900, ok: true"
)


def test_activity_reasoning_chip(tmp_path):
    """`reasoning_chars > 0` → `reasonchip`, con su `title` del catálogo.

    Control positivo: mutante «`reasonchip` siempre» → falla el control sin razonamiento.
    """
    reasoned, plain, zero = _activity_html(
        tmp_path,
        f"{{{_BASE}, reasoning_chars: 1834}}",
        f"{{{_BASE}}}",
        f"{{{_BASE}, reasoning_chars: 0}}",
    )
    assert 'class="chunkchip reasonchip" title="Razonamiento: 1.834 caracteres">razonó</span>' in (
        reasoned
    )
    # Control: sin razonamiento (o con 0) no hay marca.
    assert "reasonchip" not in plain
    assert "reasonchip" not in zero


def test_activity_params_chip(tmp_path):
    """Con `backend_params`, `paramschip` sin el estado rechazado; su `title` nombra rol y claves,
    nunca los valores."""
    (row,) = _activity_html(
        tmp_path,
        f"{{{_BASE}, backend_params: {{role: 'code', values: {{reasoning_budget: 2048,"
        " temperature: 0.2}, source: {temperature: 'env'}}}",
    )
    assert (
        'class="chunkchip paramschip" title="Parámetros del rol code: reasoning_budget, '
        'temperature">parám.</span>'
    ) in row
    assert "rejected" not in row
    assert "2048" not in row and "0.2" not in row, "los valores van en el diálogo, no en la fila"


def test_activity_params_rejected_chip(tmp_path):
    """`backend_params_rejected: true` → la variante rechazada, con clase, etiqueta y `title`
    propios."""
    (row,) = _activity_html(
        tmp_path,
        f"{{{_BASE}, backend_params: {{role: 'code', values: {{reasoning_effort: 'high'}}}},"
        " backend_params_rejected: true}",
    )
    assert (
        'class="chunkchip paramschip rejected" title="El backend rechazó los parámetros del rol '
        'code (reasoning_effort)">parám. ✕</span>'
    ) in row
    assert row.count("paramschip") == 1, "una sola marca de parámetros, no la normal y la rechazada"


def test_activity_old_event_unchanged(tmp_path):
    """Un evento del formato viejo se pinta como hoy: sin marcas nuevas; la fila sigue siendo
    activable (`tabindex`, `aria-label` del catálogo)."""
    (row,) = _activity_html(tmp_path, f"{{{_BASE}}}")
    assert "reasonchip" not in row and "paramschip" not in row
    assert '<td><span class="badge model">qwen36-35b-a3b</span></td>' in row
    assert (
        '<tr data-i="0" tabindex="0" aria-label="Ver el detalle de local_explain_code '
        '(qwen36-35b-a3b)">'
    ) in row


def _event_rows(tmp_path, *events: str) -> list[list[list[str]]]:
    functions = [_f(n) for n in _EVENT_FUNCTIONS]
    body = "emit([" + ", ".join(f"eventRows({e})" for e in events) + "]);"
    return _js(tmp_path, functions, body)


def test_event_dialog_rows_without_empty(tmp_path):
    """El diálogo: clave → valor de lo que hay, sin filas vacías. El formato viejo solo da el modelo.

    Control positivo: mutante «`add` sin el `if(html)`» → falla el último assert (formato viejo).
    """
    full, old = _event_rows(
        tmp_path,
        "{tool: 'local_summarize', model: 'qwen36-35b-a3b',"
        " backend_params: {role: 'long', values: {reasoning_budget: 1024, temperature: 0.2},"
        " source: {temperature: 'env'}}, backend_params_rejected: true,"
        " reasoning_skipped: 'context', reasoning_chars: 51234,"
        " steps: [{kind: 'map'}, {kind: 'map'}, {kind: 'reduce'}],"
        " model_requested: 'gemma4-26b-a4b', fallback_reason: 'http_500'}",
        "{tool: 'local_summarize', model: 'gemma3-4b', chars_in: 10, ok: true}",
    )

    def label(key):
        return i18n.t_lang("es", f"panel.event.key.{key}")

    keys = ["model", "role", "params", "status", "reasoning_chars", "steps", "fallback"]
    assert [k for k, _ in full] == [label(k) for k in keys]
    assert all(v.strip() for _, v in full), "ninguna fila vacía"
    by_key = dict(zip(keys, (v for _, v in full), strict=True))
    assert "fichero</span>reasoning_budget = 1024" in by_key["params"]
    assert "variable</span>temperature = 0.2" in by_key["params"]
    assert "rechazados" in by_key["status"] and "sin razonamiento: contexto" in by_key["status"]
    assert by_key["reasoning_chars"] == "51.234"
    assert by_key["steps"] == "map ×2 → reduce"
    assert "gemma4-26b-a4b" in by_key["fallback"] and "http_500" in by_key["fallback"]
    assert [k for k, _ in old] == [label("model")]
