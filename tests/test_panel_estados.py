"""Estados del panel, **ejecutados** con node (T4 de `panel-cuentas-y-estados-honestos`).

Las decisiones del panel sobre el backend son funciones JS puras (`estadoVisible`, `badgeBackend`,
`estadoModelo`, `ordenModelos`, `chipEstado`, `textoStats`, `textosSistema`) para poder correrlas
aquí sin navegador, con `_extraer`/`_correr` de `test_dashboard_js.py`. Los sondeos (`pollInflight`,
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
from test_dashboard_js import _correr, _extraer, _formateadores

from local_delegate import config, server
from local_delegate.web import metrics

# --- piezas comunes ------------------------------------------------------------------------


def _const(nombre: str) -> str:
    """Una constante del panel definida como objeto literal (`const X = {…}`)."""
    return _extraer(f"const {nombre} = {{") + ";"


# `_correr` lee la salida con la codificación de la consola (cp1252 en Windows): todo lo que no es
# ASCII sale escapado en el JSON para que «Última» llegue como «Última» y no como «Ãšltima».
_SALIDA = r"""
const salida = x => console.log(JSON.stringify(x).replace(/[\u007f-\uffff]/g,
  c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0')));
"""


def _globales() -> str:
    """Lo que las funciones de estado usan del panel: formateadores, `escHooks` y las tablas."""
    partes = [_SALIDA, _formateadores(), _extraer("function escHooks(")]
    for funcion in ("vistaInicial", "turnWords"):
        if f"function {funcion}(" in metrics.HTML:
            partes.append(_extraer(f"function {funcion}("))
    for nombre in ("CAUSAS_CONTESTA", "PALABRAS_RUNNING", "PALABRAS_ESPERA"):
        if f"const {nombre} = {{" in metrics.HTML:
            partes.append(_const(nombre))
    return "\n".join(partes)


def _js(tmp_path, funciones: list[str], cuerpo: str, preludio: str = ""):
    return _correr(tmp_path, funciones, cuerpo, _globales() + "\n" + preludio)


def _f(nombre: str) -> str:
    """La cabecera con la que se recorta la función; con `async` delante si lo lleva."""
    asincrona = f"async function {nombre}("
    return asincrona if asincrona in metrics.HTML else f"function {nombre}("


# Sondeos de `/api/backend` como los sirve el daemon.
BUENO = {
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
    "causa": None,
    "etiqueta": None,
    "detalle": None,
}
FALLIDO = {
    "available": False,
    "running": [],
    "running_ok": False,
    "models": [{**m, "status": None} for m in BUENO["models"]],
    "models_stale": True,
    "causa": "dns",
    "etiqueta": "no resuelve",
    "detalle": "no se resuelve el nombre pc.lan:9292 (¿VPN o DNS?)",
}
CATALOGO = [
    {"role": "mechanical", "label": "mecánico", "model": "gemma4-26b-a4b"},
    {"role": "long", "label": "largo", "model": "gemma4-26b-a4b"},
    {"role": "code", "label": "código", "model": "qwen36-35b-a3b"},
    {"role": "vision", "label": "visión", "model": "gemma4-12b"},
]


def _fallido(causa: str, etiqueta: str, detalle: str) -> dict:
    return {**FALLIDO, "causa": causa, "etiqueta": etiqueta, "detalle": detalle}


# --- estadoVisible: dos sondeos fallidos antes de «caído» (REQ-028) ----------------------------


def test_dos_fallos_antes_de_caido(tmp_path):
    """Escenario «dos fallos antes de caído». Control (b): umbral 1 → `vistos[1]` sería caído."""
    r = _js(
        tmp_path,
        [_f("estadoVisible")],
        f"""
        const B = {json.dumps(BUENO)}, X = {json.dumps(FALLIDO)};
        let v = null; const vistos = [];
        for (const bj of [B, X, X, B]) {{ v = estadoVisible(v, bj); vistos.push(v.estado); }}
        const desdeCero = [];
        let w = null;
        for (const bj of [X, X]) {{ w = estadoVisible(w, bj); desdeCero.push(w.estado); }}
        salida(({{vistos, desdeCero}}));
        """,
    )
    vistos, vistos_desde_cero = r["vistos"], r["desdeCero"]
    assert vistos[1] == "conectado"
    assert vistos == ["conectado", "conectado", "caido", "conectado"]
    assert vistos_desde_cero[0] == "comprobando"
    assert vistos_desde_cero[1] == "caido"


def _filas_tras(tmp_path, secuencia: list[dict]) -> list[dict]:
    """La fila de `gemma4-26b-a4b` tras cada sondeo de la secuencia, sin nada en vuelo."""
    return _js(
        tmp_path,
        [_f("estadoVisible"), _f("estadoModelo")],
        f"""
        let v = null; const filas = [];
        for (const bj of {json.dumps(secuencia)}) {{
          v = estadoVisible(v, bj);
          filas.push(estadoModelo({{modelo: 'gemma4-26b-a4b', vista: v, inflight: []}}));
        }}
        salida((filas));
        """,
    )


def test_las_filas_aguantan_el_primer_fallo(tmp_path):
    """Escenario «las filas aguantan el primer fallo» (REQ-022, REQ-028).

    Control (b). Mutante 1: las filas leen el último `bj` y no el sondeo de referencia → tras el
    primer fallo dirían «frío» (`status: null`, `running_ok: false`, regla 5). Mutante 2: atenuar
    por `models_stale` → la fila saldría atenuada tras el primer fallo.
    """
    filas = _filas_tras(tmp_path, [BUENO, FALLIDO, FALLIDO])
    assert filas[0]["texto"] == "montado"
    fila = filas[1]
    assert fila["texto"] == "montado"
    assert fila["atenuada"] is False
    fila = filas[2]
    assert fila["texto"] == "desconocido"
    assert fila["atenuada"] is True
    assert fila["title"] == "sin conexión con el backend: no resuelve"


# --- badgeBackend (REQ-014) ------------------------------------------------------------------


def _badge(tmp_path, secuencia: list[dict]) -> dict:
    return _js(
        tmp_path,
        [_f("estadoVisible"), _f("badgeBackend")],
        f"""
        let v = null;
        for (const bj of {json.dumps(secuencia)}) v = estadoVisible(v, bj);
        salida((badgeBackend(v, 'http://pc.lan:9292/v1')));
        """,
    )


def test_el_badge_dice_la_causa(tmp_path):
    """Control (b). Mutante 1: `credencial` como caída → falla `clase == "warn"`. Mutante 2:
    `title` fijo → falla `title == detalle`."""
    det_401 = "pc.lan:9292 responde 401: está arriba pero rechaza la credencial"
    cred = _fallido("credencial", "sin acceso", det_401)
    b = _badge(tmp_path, [cred, cred])
    clase, texto, title = b["clase"], b["texto"], b["title"]
    assert clase == "warn"
    assert texto == "sin acceso"
    assert title == det_401

    http = _fallido("http_error", "responde con error", "pc.lan:9292 responde HTTP 500")
    b = _badge(tmp_path, [http, http])
    assert b["clase"] == "warn"
    assert "caído" not in b["texto"]

    b = _badge(tmp_path, [FALLIDO, FALLIDO])
    assert b["texto"] == "caído · no resuelve"
    assert b["clase"] == "down"
    assert b["title"] == FALLIDO["detalle"]

    b = _badge(tmp_path, [BUENO])
    assert (b["texto"], b["clase"], b["title"]) == ("conectado", "up", "http://pc.lan:9292/v1")


def test_el_badge_avisa_del_ultimo_sondeo_sin_dejar_de_decir_conectado(tmp_path):
    """REQ-028: un fallo tras uno bueno conserva «conectado» y lo cuenta en el `title`."""
    b = _badge(tmp_path, [BUENO, FALLIDO])
    assert b["texto"] == "conectado"
    assert "último sondeo: " + FALLIDO["detalle"] in b["title"]

    b = _badge(tmp_path, [FALLIDO])
    assert b["texto"] == "comprobando…"
    assert b["clase"] == "neutral"


# --- estadoModelo: la tabla de REQ-022, una fila por regla ------------------------------------


def _fila(tmp_path, casos: list[dict]) -> list[dict]:
    """`casos`: [{secuencia, inflight}] → la fila de `qwen36-35b-a3b` tras la secuencia."""
    return _js(
        tmp_path,
        [_f("estadoVisible"), _f("estadoModelo")],
        f"""
        const out = [];
        for (const c of {json.dumps(casos)}) {{
          let v = null;
          for (const bj of c.secuencia) v = estadoVisible(v, bj);
          out.push(estadoModelo({{modelo: c.modelo || 'qwen36-35b-a3b', vista: v,
                                  inflight: c.inflight}}));
        }}
        salida((out));
        """,
    )


def _con(running: list[dict], *, running_ok: bool = True, status: str = "unloaded") -> dict:
    modelos = [
        {**m, "status": status if m["id"] == "qwen36-35b-a3b" else m["status"]}
        for m in BUENO["models"]
    ]
    return {**BUENO, "running": running, "running_ok": running_ok, "models": modelos}


VUELO = [{"model": "qwen36-35b-a3b", "tool": "local_summarize"}]
QWEN_STARTING = [{"model": "qwen36-35b-a3b", "state": "starting"}]
QWEN_READY = [{"model": "qwen36-35b-a3b", "state": "ready"}]


def test_estado_modelo_una_fila_por_regla(tmp_path):
    """Control (b), tres mutantes de orden y de regla (ver `verification.md`)."""
    casos = [
        # 1. no disponible y en vuelo
        {"secuencia": [FALLIDO, FALLIDO], "inflight": VUELO},
        # 2. no disponible
        {"secuencia": [FALLIDO, FALLIDO], "inflight": []},
        # 3. en vuelo y en espera local (gana a running `ready`)
        {"secuencia": [_con(QWEN_READY)], "inflight": [{**VUELO[0], "local_wait": "slot"}]},
        # 4. running_ok falso y en vuelo
        {"secuencia": [_con([], running_ok=False)], "inflight": VUELO},
        # 5. running_ok falso: montado si loaded, si no frío
        {"secuencia": [_con([], running_ok=False, status="loaded")], "inflight": []},
        {"secuencia": [_con([], running_ok=False)], "inflight": []},
        # 6. starting, aunque /v1/models diga loaded y haya una llamada en vuelo
        {"secuencia": [_con(QWEN_STARTING, status="loaded")], "inflight": VUELO},
        # 7 y 8. ready
        {"secuencia": [_con(QWEN_READY)], "inflight": VUELO},
        {"secuencia": [_con(QWEN_READY)], "inflight": []},
        # 9. en vuelo y el modelo no está en /running
        {"secuencia": [_con([{"model": "gemma4-26b-a4b", "state": "ready"}])], "inflight": VUELO},
        # 10. stopping
        {"secuencia": [_con([{"model": "qwen36-35b-a3b", "state": "stopping"}])], "inflight": []},
        # 11. resto
        {"secuencia": [_con([])], "inflight": []},
        # 1 con running_ok falso: la regla 1 gana a la 4
        {"secuencia": [FALLIDO, FALLIDO], "inflight": VUELO},
    ]
    filas = _fila(tmp_path, casos)
    txt = [f["texto"] for f in filas]
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
    assert filas[2]["title"] == (
        "esperando dentro de local-delegate: esperando plaza (máximo de llamadas a la vez)"
    )
    assert [f["atenuada"] for f in filas[:2]] == [True, True]
    assert not any(f["atenuada"] for f in filas[2:12])


def test_la_espera_local_es_un_punto_de_extension(tmp_path):
    """Un motivo que el panel no conoce también es «en cola local», y se pinta tal cual.

    Control (b). Mutante: la regla 3 exige `local_wait === 'slot'` → da «procesando».
    """
    fila = _fila(
        tmp_path,
        [
            {
                "secuencia": [_con(QWEN_READY)],
                "inflight": [{**VUELO[0], "local_wait": "turno_grupo"}],
            }
        ],
    )[0]
    txt, title = fila["texto"], fila["title"]
    assert txt == "en cola local"
    assert "turno_grupo" in title


def test_la_espera_local_exige_todas_las_llamadas(tmp_path):
    """«En espera local» = TODAS las llamadas a ese modelo esperan dentro de local-delegate."""
    vuelo = [{**VUELO[0], "local_wait": "slot"}, VUELO[0]]
    fila = _fila(tmp_path, [{"secuencia": [_con(QWEN_READY)], "inflight": vuelo}])[0]
    assert fila["texto"] == "procesando"


def test_esperando_turno_no_afirma_la_causa(tmp_path):
    """Fila 9: el `title` lista /running en palabras. Control (b): solo los `ready` → falla."""
    running = [
        {"model": "gemma4-26b-a4b", "state": "ready"},
        {"model": "qwen35-2b", "state": "starting"},
    ]
    filas = _fila(
        tmp_path,
        [
            {"secuencia": [_con(running)], "inflight": VUELO},
            {"secuencia": [_con([])], "inflight": VUELO},
        ],
    )
    assert filas[0]["texto"] == "esperando turno"
    title = filas[0]["title"]
    assert "qwen35-2b cargando" in title
    assert (
        title
        == "llama-swap aún no lo atiende; en /running: gemma4-26b-a4b listo, qwen35-2b cargando"
    )
    assert filas[1]["title"] == "llama-swap aún no lo atiende; /running está vacío"


def test_escenario_cargando_turno_y_cola_propia(tmp_path):
    """Escenario de la spec, con los modelos que nombra: «qwen36-35b-a3b cargando» en el title."""
    running = [
        {"model": "gemma4-26b-a4b", "state": "ready"},
        {"model": "qwen36-35b-a3b", "state": "starting"},
    ]
    filas = _fila(
        tmp_path,
        [
            {
                "modelo": "gemma4-12b",
                "secuencia": [_con(running)],
                "inflight": [{"model": "gemma4-12b"}],
            },
        ],
    )
    assert filas[0]["texto"] == "esperando turno"
    assert "qwen36-35b-a3b cargando" in filas[0]["title"]
    assert "gemma4-26b-a4b listo" in filas[0]["title"]


# --- ordenModelos (REQ-021) y chipEstado (REQ-023) ------------------------------------------


def test_orden_de_modelos_con_y_sin_conexion(tmp_path):
    """Control (b). Mutante: orden alfabético puro → `gemma4-12b` primero."""
    r = _js(
        tmp_path,
        [_f("ordenModelos")],
        f"""
        const cat = {json.dumps(CATALOGO)};
        const con = ordenModelos(['gemma4-12b','gemma4-26b-a4b','qwen35-2b','qwen36-35b-a3b'], cat);
        const sinLista = ordenModelos([], cat);
        salida(({{con, sinLista}}));
        """,
    )
    ids = r["con"]
    assert ids == ["gemma4-26b-a4b", "qwen36-35b-a3b", "gemma4-12b", "qwen35-2b"]
    assert r["sinLista"] == ["gemma4-26b-a4b", "qwen36-35b-a3b", "gemma4-12b"]


def test_chip_de_estado_acepta_cualquier_valor(tmp_path):
    """Control (b). Mutante: todo lo que no es `loaded` con el estilo de `unloaded`."""
    r = _js(
        tmp_path,
        [_f("chipEstado")],
        "salida((['loaded','unloaded','starting',null,undefined].map(chipEstado)));",
    )
    assert r[0] == "loaded"
    assert r[1] == "unloaded"
    assert r[2] == "neutral"
    assert r[3] is None and r[4] is None


# --- renderBackendStats y textoStats (REQ-020) ---------------------------------------------

_DOM = """
const _els = {};
const document = {
  visibilityState: 'visible',
  getElementById: id => (_els[id] = _els[id] || {id, innerHTML: '', textContent: '', style: {},
                                                  title: '', className: ''}),
};
"""


def test_la_version_de_llama_swap_solo_se_culpa_con_un_404(tmp_path):
    """Control (a) con `dns`; (b) para la rama positiva: mutante «nunca menciona v236»."""
    funciones = [_f("renderBackendStats")]
    if "function textoStats(" in metrics.HTML:
        funciones.insert(0, _f("textoStats"))
    r = _js(
        tmp_path,
        funciones,
        """
        renderBackendStats({available:false, causa:'dns', etiqueta:'no resuelve',
                            detalle:'no se resuelve el nombre pc.lan (¿VPN o DNS?)'});
        const dns = _els.backendStats.innerHTML;
        renderBackendStats({available:false, causa:'http_error', etiqueta:'responde con error',
                            detalle:'pc.lan responde HTTP 404', status_http:404});
        const e404 = _els.backendStats.innerHTML;
        salida(({dns, e404}));
        """,
        _DOM,
    )
    html = r["dns"]
    assert "v236" not in html
    assert "sin datos: no resuelve" in html
    html = r["e404"]
    assert "v236" in html


# --- textosSistema (REQ-025) -----------------------------------------------------------------


def test_textos_del_panel_sistema(tmp_path):
    """Control (b). Mutante: sin la rama de `origin` → falla `"El backend corre en" in nota`."""
    r = _js(
        tmp_path,
        [_f("textosSistema")],
        """
        const casos = [
          {platform:'darwin', origin:'remote', host:'100.64.0.2:9292', ram:null, vram:null, processes:[]},
          {platform:'win32', origin:'local', host:'127.0.0.1:9292', ram:null, vram:null, processes:[]},
          {platform:'linux', origin:'remote', host:'pc.lan:9292', ram:null, vram:null,
           processes:[{name:'python', pid:1, ram_mb:10}]},
          {platform:'darwin', origin:'local', host:'127.0.0.1:9292', ram:null, vram:null, processes:[]},
        ];
        salida((casos.map(textosSistema)));
        """,
    )
    mac, win, linux, mac_local = r
    nota = mac["nota"] or ""
    assert "El backend corre en" in nota
    assert nota == (
        "El backend corre en 100.64.0.2:9292: su RAM y VRAM se ven en el panel de esa máquina"
    )
    assert mac["procesosVacia"] is None  # la nota es lo único que se ve
    assert mac["memoriaVacia"] == "RAM y VRAM no se miden en macOS todavía."
    assert win["nota"] is None
    assert win["procesosVacia"] == "Ningún proceso del backend detectado."
    assert win["memoriaVacia"] == "Métricas de sistema no disponibles en esta plataforma."
    assert linux["nota"].startswith("El backend corre en pc.lan:9292")
    assert (
        mac_local["procesosVacia"] == "La lista de procesos no está disponible en darwin todavía."
    )


# --- Sondeos: separados, sin solaparse y encadenados (REQ-026, REQ-027) ------------------------

_SONDEO = (
    _DOM
    + """
const state = {inflight: [], activity: null, lastEvent: null, status: null, vista: null,
               backendOrigin: null, backendHost: null};
const llamadas = {};
let fetchPendiente = {};          // url -> true: esa ruta no resuelve nunca
let respuestas = {};              // url -> [json, json, …] (se consumen en orden)
globalThis.fetch = url => {
  llamadas[url] = (llamadas[url] || 0) + 1;
  if (fetchPendiente[url]) return new Promise(() => {});
  const cola = respuestas[url] || [{}];
  const j = cola.length > 1 ? cola.shift() : cola[0];
  return Promise.resolve({json: () => Promise.resolve(j)});
};
const retrasos = [];
globalThis.setTimeout = (fn, ms) => { retrasos.push(ms); return retrasos.length; };
globalThis.clearTimeout = () => {};
let renders = 0;
function renderBackend(){} function renderTools(){} function updateLive(){}
function renderInflight(){ renders++; }
function renderBackendStats(){}
const tick = () => new Promise(r => setImmediate(r));
"""
)


def _sondeo_globales() -> str:
    """El estado de los sondeos (`const SONDEO = {…}`) si ya existe."""
    return _const("SONDEO") if "const SONDEO = {" in metrics.HTML else ""


def test_pollInflight_no_se_apila(tmp_path):
    """Control (a): hoy cada llamada lanza otra petición (3, más 3 de `/api/backend`)."""
    r = _js(
        tmp_path,
        [_f("pollInflight")],
        """
        fetchPendiente['/api/inflight'] = true; fetchPendiente['/api/backend'] = true;
        pollInflight(); pollInflight(); pollInflight();
        await tick();
        salida((llamadas));
        """,
        _SONDEO + _sondeo_globales(),
    )
    llamadas_fetch_inflight = r.get("/api/inflight", 0)
    assert llamadas_fetch_inflight == 1
    assert r.get("/api/backend", 0) == 0  # el sondeo de En curso ya no pide el backend


def test_pollInflight_se_encadena_tras_terminar(tmp_path):
    """Control (a): hoy `pollInflight` no programa nada (lo hacía un `setInterval` al arrancar)."""
    r = _js(
        tmp_path,
        [_f("pollInflight")],
        """
        respuestas['/api/inflight'] = [{inflight: [], now: new Date().toISOString()}];
        respuestas['/api/backend'] = [{available: true}];
        await pollInflight();
        await tick();
        salida(({retrasos}));
        """,
        _SONDEO + _sondeo_globales(),
    )
    assert r["retrasos"] == [2000]


def test_un_backend_lento_no_congela_en_curso(tmp_path):
    """Control (a): hoy `Promise.all` espera a `/api/backend` y no pinta «En curso»."""
    funciones = [_f("pollInflight")]
    sondear = "sondearAhora()" if "function sondearAhora(" in metrics.HTML else "pollInflight()"
    if "function sondearAhora(" in metrics.HTML:
        funciones += [_f("pollBackend"), _f("aplicarBackend"), _f("sondearAhora")]
    r = _js(
        tmp_path,
        funciones,
        f"""
        fetchPendiente['/api/backend'] = true;
        respuestas['/api/inflight'] = [{{inflight: [], now: new Date().toISOString()}}];
        {sondear}; {sondear}; {sondear};
        for (let i = 0; i < 5; i++) await tick();
        salida(({{renders, llamadas}}));
        """,
        _SONDEO + _sondeo_globales(),
    )
    renders_inflight = r["renders"]
    assert renders_inflight >= 1
    assert r["llamadas"].get("/api/backend", 0) <= 1
    assert r["llamadas"].get("/api/inflight", 0) <= 1


def test_al_reconectar_se_refresca_todo(tmp_path):
    """REQ-027. Control (b): sin `fetchStatus()` al pasar a disponible → 0 peticiones de status."""
    x, b = json.dumps(FALLIDO), json.dumps(BUENO)
    r = _js(
        tmp_path,
        [_f("estadoVisible"), _f("pollBackend"), _f("aplicarBackend"), _f("fetchStatus")],
        f"""
        respuestas['/api/backend'] = [{x}, {x}, {b}];
        const estados = [];
        for (let i = 0; i < 3; i++) {{
          await pollBackend(); await tick(); estados.push(state.vista.estado);
        }}
        await tick(); await tick();
        salida(({{estados, llamadas, retrasos}}));
        """,
        _SONDEO + _sondeo_globales(),
    )
    assert r["estados"] == ["comprobando", "caido", "conectado"]
    llamadas_status = r["llamadas"].get("/api/status", 0)
    assert llamadas_status == 1
    assert r["llamadas"].get("/api/backend/stats", 0) == 1
    assert r["retrasos"] == [2000, 2000, 2000]


# --- renderInflight (REQ-024) ----------------------------------------------------------------


def test_ultima_delegacion_cuando_nada_corre(tmp_path):
    """Control (a): hoy el título sigue «En curso» con la última terminada."""
    r = _js(
        tmp_path,
        [_f("renderInflight"), _f("fmtHace")],
        """
        const state = {inflight: [], activity: {skewMs: 0},
                       lastEvent: {ts: new Date(Date.now() - 8000).toISOString(),
                                   tool: 'local_summarize', model: 'm', latency_ms: 1200,
                                   chars_in: 10, ok: true}};
        renderInflight();
        const ultima = _els.inflightHead.innerHTML;
        state.lastEvent = null; renderInflight();
        const vacio = _els.inflightHead.innerHTML;
        state.inflight = [{tool: 't', model: 'm', elapsed_s: 1, chars_in: 1}]; renderInflight();
        const vivo = _els.inflightHead.innerHTML;
        salida(({ultima, vacio, vivo}));
        """,
        _DOM,
    )
    head = r["ultima"]
    assert head == "Última delegación"
    assert r["vacio"] == "En curso"
    assert r["vivo"].startswith("En curso")


def test_el_js_no_redacta_las_etiquetas_de_las_causas():
    """REQ-011: la etiqueta corta llega del daemon (`fallos.py`); el panel no tiene su copia."""
    for etiqueta in ("no resuelve", "nadie escucha", "sin acceso", "responde con error"):
        assert not re.search(rf"['\"]{etiqueta}['\"]", metrics.HTML), etiqueta


# --- T10 de daemon-reparte-el-backend: la espera de turno del daemon (REQ-008, REQ-027) --------


def test_turn_wait_shown_in_panel_as_local_wait(tmp_path, monkeypatch):
    """Escenario «la espera de turno se ve en el panel como espera local», de punta a punta.

    Una operación del 26B tiene el turno (atascada en el backend) y una de Qwen3.6 lo espera; se lee
    `/api/inflight` con `TestClient` y su entrada pasa a `estadoModelo` con node, con Qwen3.6
    `ready` en `/running`. Control (b). Mutante 1: una clave propia (`esperando_turno: true`) en
    vez de `local_wait` → la fila sale «procesando». Mutante 2: `inflight_snapshot` sin copiar
    `turn_in_use` → el `title` dice «en uso: nada».
    """
    today = Path(__file__).parent / "fixtures" / "topologia" / "hoy.yaml"
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
        server._chat(model, "s", "u", 8, tool=tool, rol="long")

    threads = [
        threading.Thread(target=operation, args=("gemma4-26b-a4b", "op_x"), daemon=True),
        threading.Thread(target=operation, args=("qwen36-35b-a3b", "op_y"), daemon=True),
    ]
    client = TestClient(metrics.app)

    def input_and() -> dict | None:
        rows = client.get("/api/inflight").json()["inflight"]
        return next((e for e in rows if e.get("tool") == "op_y"), None)

    try:
        threads[0].start()
        assert x_inside.wait(2), "la operación del 26B no llegó al backend"
        threads[1].start()
        entry = None
        end = time.monotonic() + 2
        while time.monotonic() < end:
            e = input_and()
            queued = bool(server._turn.snapshot().queue)
            if queued and e and (e.get("local_wait") or e.get("turn_in_use")):
                entry = e
                break
            time.sleep(0.01)
        assert entry, f"la operación de Qwen3.6 no llegó a esperar turno: {input_and()}"
    finally:
        continue_x.set()
        for thread in threads:
            thread.join(5)

    row = _fila(tmp_path, [{"secuencia": [_con(QWEN_READY)], "inflight": [entry]}])[0]
    assert row["texto"] == "en cola local"
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
        salida(_els.inflightBody.innerHTML);
        """,
        _DOM,
    )
    assert "esperando turno del daemon (en uso: gemma4-26b-a4b)" in r
