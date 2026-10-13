"""Coste, cuota e imágenes en `/api/stats` y en el JS del panel (coste-api-y-cuota, T6).

Lo que sirve el backend se prueba con `TestClient`; las funciones puras del panel (`costText`,
`quotaText`, `imagesText`) se **ejecutan con node** sobre esa misma respuesta, como las demás
del panel. El HOME es sintético en todos los tests: el panel no puede leer `~/.claude` (REQ-073) y
un test que lo comprueba necesita un `~/.claude` que pueda leer si estuviera mal.
"""

from __future__ import annotations

import builtins
import inspect
import io
import json
import os
import pathlib
import shutil
import socket
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from local_delegate import attribution, cost, quota, recompute, server
from local_delegate import config as cfg
from local_delegate.web import metrics

FRASES_PROHIBIDAS = (
    "ahorraste $",
    "ahorro en dólares",
    "dinero ahorrado",
    "tokens de tu cuota",
    "ahorro de cuota",
    "cuota que no gastaste",
)


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """LOG_DIR y HOME sintéticos, respaldo declarado, caché del lector limpia."""
    logs = tmp_path / "logs"
    logs.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(cfg, "LOG_DIR", logs)
    monkeypatch.setattr(cfg, "USAGE_LOG", logs / "usage.jsonl")
    monkeypatch.setattr(cfg, "COST_FALLBACK", "")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    metrics._FILE_CACHE.clear()
    yield logs, home
    metrics._FILE_CACHE.clear()


def _ahora() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _linea(ts: datetime, n: int = 0, **extra) -> dict:
    fila = {
        "ts": ts.isoformat(timespec="seconds"),
        "tool": "local_summarize",
        "source": "path",
        "path": f"C:/docs/notas-{n}.md",
        "chars_in": 3_000_000,
        "chars_out": 0,
        "ok": True,
        "tokens_in": 9000,
        "tokens_out": 100,
        "client": "claude-code",
        "tool_use_id": f"toolu_{n:04d}",
    }
    fila.update(extra)
    return fila


IMAGEN = {
    "tool": "local_describe_image",
    "source": "path",
    "chars_in": 250000,
    "chars_out": 800,
    "ok": True,
    "tokens_in": 1200,
    "tokens_out": 200,
    "client": "claude-code",
}


def _escribir_log(logs: Path, filas: list[dict]) -> None:
    por_mes: dict[str, list[dict]] = {}
    for f in filas:
        por_mes.setdefault(f["ts"][:7].replace("-", ""), []).append(f)
    for mes, del_mes in por_mes.items():
        with (logs / f"usage-{mes}.jsonl").open("a", encoding="utf-8") as flujo:
            for f in del_mes:
                flujo.write(json.dumps(f, ensure_ascii=False) + "\n")
    metrics._FILE_CACHE.clear()


def _stats(desde: datetime | None = None, hasta: datetime | None = None, **kw) -> dict:
    cliente = TestClient(metrics.app, **kw)
    if desde is None:
        return cliente.get("/api/stats").json()
    qs = f"from={desde.isoformat()}&to={hasta.isoformat()}".replace("+", "%2B")
    return cliente.get("/api/stats?" + qs).json()


def _punto(fin: datetime, c: float, fuente: str = "statusline", horas: int = 4) -> dict:
    return {
        "source": fuente,
        "type": "five_hour",
        "start": (fin - timedelta(hours=horas)).isoformat(),
        "end": fin.isoformat(),
        "delta_pct": 40 if fuente == "statusline" else 100,
        "delta_usd": round(c * 0.4, 2),
        "C": c,
        "marks": [quota.MARK_OTHER_SURFACES],
        "unpriced_requests": None,
    }


def _agregados(logs: Path, puntos: list[dict]) -> None:
    recompute.write_aggregates(
        logs,
        {
            "version": 1,
            "generated": _ahora().isoformat(),
            "cleanup_days": 30,
            "check": None,
            "n_by_month": {},
            "points": puntos,
            "discards": {"five_hour": {}, "seven_day": {}},
            "resets": {"five_hour": None, "seven_day": None},
            "sources": {"transcripts": True, "statusline": True},
        },
    )


# --- node: las funciones puras del panel --------------------------------------------------------


def _extraer(cabecera: str) -> str:
    """Recorta una función (o un objeto) del `<script>` balanceando llaves."""
    fuente = metrics.HTML
    i = fuente.index(cabecera)
    profundidad, j = 0, i
    while True:
        if fuente[j] == "{":
            profundidad += 1
        elif fuente[j] == "}":
            profundidad -= 1
            if profundidad == 0:
                return fuente[i : j + 1]
        j += 1


_FUNCIONES = (
    "function fmtNum(",
    "function plural(",
    "function dollars(",
    "function costText(",
    "function quotaText(",
    "function imagesText(",
)


def _textos(tmp_path, stats: dict) -> dict[str, str]:
    """`costText`, `quotaText` y `imagesText` del panel sobre esa respuesta, en node."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")
    preludio = (
        "const F = {format: n => fmtNum(n, 0)};\n"
        "const F1 = {format: n => fmtNum(n, 1)};\n" + _extraer("const THREAD_TXT = {") + ";\n"
    )
    cuerpo = (
        f"const j = {json.dumps(stats)};\n"
        "console.log(JSON.stringify({coste: costText(j).join('\\n'), "
        "cuota: quotaText(j).join('\\n'), imagenes: imagesText(j).join('\\n')}));\n"
    )
    programa = tmp_path / "textos.mjs"
    programa.write_text(
        "\n".join([preludio, *(_extraer(f) for f in _FUNCIONES), cuerpo]), encoding="utf-8"
    )
    salida = subprocess.run(
        [node, str(programa)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    return json.loads(salida.stdout)


# --- La barra y el relleno (REQ-007) -------------------------------------------------------------


def test_la_carrera_la_cierra_el_relleno(entorno, tmp_path):
    """Escenario de la spec: la línea tiene nota del hook pero no el modelo (`caller_src: hook`).
    Primero cuenta como `pendiente`, valorada con el respaldo; tras el relleno, `por relleno`."""
    logs, _home = entorno
    ts = _ahora() - timedelta(hours=1)
    _escribir_log(logs, [_linea(ts, caller_src="hook", caller_kind="subagent")])

    barra = _stats()["cost"]["bar"]
    assert barra["pending"] == 1
    assert barra["backfilled"] == 0

    attribution.write_backfill(
        logs,
        f"{ts:%Y%m}",
        {
            "toolu_0000": {
                "caller_model": "claude-opus-5-5",
                "caller_kind": "subagent",
                "caller_effort": "high",
                "n": 40,
                "expiries": 0,
                "match": "exact",
            }
        },
    )
    c = _stats()["cost"]
    assert c["bar"]["backfilled"] == 1
    assert c["bar"]["pending"] == 0
    assert c["n_origin"]["backfill"] == 1
    # 3 000 000 × 100 // 200 = 1 500 000 tokens: $7,50 y $19,50 con N = 40.
    assert c["figure"] == {"low_bound": 7.5, "estimate": 19.5}


def test_api_stats_trae_coste_cuota_e_imagenes(entorno):
    logs, _home = entorno
    ahora = _ahora()
    imagen = {**IMAGEN, "ts": (ahora - timedelta(minutes=5)).isoformat(timespec="seconds")}
    _escribir_log(logs, [_linea(ahora - timedelta(minutes=10)), imagen])
    j = _stats()
    assert j.get("cost") is not None
    assert j.get("images") == {"n": 1, "bytes": 250000, "chars_returned": 800}
    assert j.get("quota", {}).get("five_hour", {}).get("status") == "uncalibrated"
    assert set(j.get("density_table", {}).get("families", {})) == {"new", "previous"}
    # Las claves de siempre siguen ahí: las nuevas son aditivas.
    assert j["total"]["calls"] == 2


# --- La cuota (REQ-054, REQ-058, REQ-060, REQ-061) -----------------------------------------------


def test_la_cuota_no_depende_del_rango(entorno):
    """Tres puntos del statusline que calibran; delegaciones de hace 3 h; el panel mira el mes
    pasado. El % sale de las últimas 5 h, no del rango."""
    logs, _home = entorno
    ahora = _ahora()
    _agregados(
        logs,
        [_punto(ahora - timedelta(days=d), c) for d, c in ((20, 150.0), (10, 160.0), (2, 170.0))],
    )
    _escribir_log(logs, [_linea(ahora - timedelta(hours=3))])

    j = _stats(ahora - timedelta(days=60), ahora - timedelta(days=35))
    assert j["cost"]["reason"] == "sin delegaciones en el periodo"  # el rango está vacío
    c = j["quota"]
    assert c["five_hour"]["status"] == "calibrated"
    assert (c["five_hour"].get("a_pct") or 0) > 0, c["five_hour"].get("pct_reason")
    # 1 500 000 tokens × $5/MTok = $7,50 de cota baja; mediana(C) = 160 → 4,7 %.
    assert c["five_hour"]["a_pct"] == 4.7
    assert c["five_hour"]["b_pct"] == round(7.5 * (1 + 40 * 0.2 / 5) / 160 * 100, 1)
    assert c["seven_day"]["status"] == "uncalibrated"


def test_un_punto_viejo_caduca_sin_regenerar(entorno, tmp_path):
    """Escenario de la spec: tres puntos que calibran, uno con `fin` hace 61 días, y el JSON sin
    regenerar: el panel aplica la vigencia al leer."""
    logs, _home = entorno
    ahora = _ahora()
    _agregados(
        logs,
        [_punto(ahora - timedelta(days=d), c) for d, c in ((61, 150.0), (10, 160.0), (2, 170.0))],
    )
    j = _stats()
    c = j["quota"]
    assert c["five_hour"]["status"] == "uncalibrated"
    assert "faltan 1 puntos" in c["five_hour"]["reason"]
    texto = _textos(tmp_path, j)["cuota"]
    assert "faltan 1 puntos" in texto
    assert "de una ventana de 5 h" not in texto  # ningún % sin calibrar (REQ-059)


def test_aviso_contra_un_rechazo(entorno, tmp_path):
    """REQ-058: calibrado con mediana(C) = 160 y un rechazo vigente con C = 300."""
    logs, _home = entorno
    ahora = _ahora()
    puntos = [
        _punto(ahora - timedelta(days=d), c) for d, c in ((20, 150.0), (10, 160.0), (2, 170.0))
    ]
    puntos.append(_punto(ahora - timedelta(days=5), 300.0, fuente="rejection"))
    _agregados(logs, puntos)
    _escribir_log(logs, [_linea(ahora - timedelta(hours=1))])
    j = _stats()
    assert j["quota"]["five_hour"]["status"] == "calibrated"  # guarda: el aviso solo va calibrado
    texto = _textos(tmp_path, j)["cuota"]
    assert "probable uso en otras superficies" in texto
    assert "de una ventana de 5 h" in texto


def test_un_punto_mal_formado_se_descarta_sin_tumbar_la_respuesta(entorno):
    """REQ-061 sobre `cost-aggregates.json` editado a mano: los puntos rotos se saltan y cuentan
    como `linea_corrupta` (en su tipo, o en los dos si el tipo no se lee), y los buenos calibran."""
    logs, _home = entorno
    ahora = _ahora()
    buenos = [
        _punto(ahora - timedelta(days=d), c) for d, c in ((20, 150.0), (10, 160.0), (2, 170.0))
    ]
    sin_c = _punto(ahora - timedelta(days=3), 155.0)
    del sin_c["C"]
    c_texto = {**_punto(ahora - timedelta(days=4), 155.0), "C": "abc"}
    tipo_raro = {**_punto(ahora - timedelta(days=5), 155.0), "type": "un_mes"}
    _agregados(logs, [*buenos, sin_c, c_texto, tipo_raro, "no soy un punto"])

    r = TestClient(metrics.app, raise_server_exceptions=False).get("/api/stats")
    assert r.status_code == 200
    q = r.json()["quota"]
    assert q["five_hour"]["status"] == "calibrated"
    assert q["five_hour"]["points"] == 3
    assert q["five_hour"]["discards"]["corrupt_line"] == 4
    assert q["seven_day"]["discards"]["corrupt_line"] == 2


def test_discard_reasons_are_said_in_words(tmp_path):
    """Los motivos de descarte llegan como valores de máquina en inglés y el panel los dice en
    palabras, también los tres que antes no tenían rótulo (`overlapping`, `expired`, `reset`).

    Control: mutante «`DISCARD` con la clave vieja `delta_pequeno`» → sale «small delta 1»."""
    discards = {"small_delta": 1, "overlapping": 2, "expired": 3, "reset": 4, "corrupt_line": 5}
    stats = {
        "quota": {
            "five_hour": {
                "status": "uncalibrated",
                "reason": "faltan 3 puntos",
                "points": 0,
                "rejection_points": 0,
                "discards": discards,
                "drift": False,
                "reset": None,
            },
            "has_aggregates": True,
            "command": "local-delegate recompute-cost",
        }
    }
    texto = _textos(tmp_path, stats)["cuota"]
    assert (
        "descartes: variación pequeña 1, solapado 2, caducado 3, reinicio 4, línea corrupta 5"
        in texto
    )


def test_home_vacio(entorno, tmp_path):
    """Escenario «otra máquina sin datos»: ni `~/.claude` ni `cost-aggregates.json`. El coste usa el
    respaldo y el `N` declarado; la cuota dice que no hay datos y qué comando los genera. Y un
    `cost-aggregates.json` corrupto no tumba `/api/stats`."""
    logs, home = entorno
    assert not (home / ".claude").exists()
    _escribir_log(logs, [_linea(_ahora() - timedelta(hours=1))])

    j = _stats()
    b = j["cost"]["bar"]
    assert b["pending"] + b["assumed"] == b["valued"] == 1
    assert j["cost"]["n_origin"]["declared"] == 1
    assert j["cost"]["figure"] is not None
    q = j["quota"]
    assert q["five_hour"]["reason"] == "no hay datos de calibración en esta máquina"
    assert q["has_aggregates"] is False
    texto = _textos(tmp_path, j)["cuota"]
    assert "no hay datos de calibración en esta máquina" in texto
    assert "local-delegate recompute-cost" in texto

    (logs / recompute.FILE_NAME).write_text("{ esto no es JSON", encoding="utf-8")
    r = TestClient(metrics.app, raise_server_exceptions=False).get("/api/stats")
    assert r.status_code == 200
    assert r.json()["quota"]["five_hour"]["reason"] == "no hay datos de calibración en esta máquina"


# --- Lo que el panel no hace (REQ-012, REQ-073) --------------------------------------------------


def test_el_panel_no_lee_claude(entorno, monkeypatch):
    """`/api/stats` y `/api/events` con un `~/.claude` sintético con transcripts y registro: ni una
    apertura de fichero cuelga de él."""
    logs, home = entorno
    claude = home / ".claude"
    (claude / "projects" / "C--proyecto").mkdir(parents=True)
    (claude / "projects" / "C--proyecto" / "sesion.jsonl").write_text("{}\n", encoding="utf-8")
    (claude / "cuota-statusline.jsonl").write_text("{}\n", encoding="utf-8")
    (claude / "settings.json").write_text('{"cleanupPeriodDays": 90}', encoding="utf-8")
    _escribir_log(logs, [_linea(_ahora() - timedelta(hours=1), caller_src="hook")])

    lecturas: list[str] = []
    raiz = str(claude.resolve()).lower()

    def _anotar(ruta) -> None:
        try:
            s = str(Path(os.fspath(ruta)).resolve()).lower()
        except TypeError:
            return  # un descriptor de fichero
        if s.startswith(raiz):
            lecturas.append(s)

    open_, io_open = builtins.open, io.open
    path_open, read_text, read_bytes = Path.open, Path.read_text, Path.read_bytes

    def _open(f, *a, **k):
        _anotar(f)
        return open_(f, *a, **k)

    def _io_open(f, *a, **k):
        _anotar(f)
        return io_open(f, *a, **k)

    def _path_open(self, *a, **k):
        _anotar(self)
        return path_open(self, *a, **k)

    def _read_text(self, *a, **k):
        _anotar(self)
        return read_text(self, *a, **k)

    def _read_bytes(self, *a, **k):
        _anotar(self)
        return read_bytes(self, *a, **k)

    monkeypatch.setattr(builtins, "open", _open)
    monkeypatch.setattr(io, "open", _io_open)
    monkeypatch.setattr(pathlib.Path, "open", _path_open)
    monkeypatch.setattr(pathlib.Path, "read_text", _read_text)
    monkeypatch.setattr(pathlib.Path, "read_bytes", _read_bytes)

    # Control positivo: el espía ve una lectura bajo `~/.claude` cuando la hay (la misma lectura
    # pasa por varias capas: `read_text` → `open` → `io.open`, de ahí el conjunto).
    (claude / "settings.json").read_text(encoding="utf-8")
    assert set(lecturas) == {str((claude / "settings.json").resolve()).lower()}, (
        "el espía no ve las lecturas: el test no comprobaría nada"
    )
    lecturas.clear()

    cliente = TestClient(metrics.app)
    assert cliente.get("/api/stats").status_code == 200
    assert cliente.get("/api/events").status_code == 200
    assert lecturas == []


def test_api_stats_no_abre_sockets(entorno, monkeypatch):
    logs, _home = entorno
    _escribir_log(
        logs, [_linea(_ahora() - timedelta(hours=1)), {**IMAGEN, "ts": _ahora().isoformat()}]
    )
    intentos: list[str] = []
    # El bucle de asyncio en Windows se conecta a sí mismo por loopback (`socketpair`): eso no es
    # salir a la red, y bloquearlo tumbaría el `TestClient` en vez de probar el panel.
    local = {"127.0.0.1", "::1", "localhost", None}

    def _registrar(nombre, original, host_de):
        def _falso(*a, **k):
            if host_de(a) in local:
                return original(*a, **k)
            intentos.append(nombre)
            raise OSError(f"red prohibida en el test: {nombre}")

        return _falso

    monkeypatch.setattr(
        socket, "getaddrinfo", _registrar("getaddrinfo", socket.getaddrinfo, lambda a: a[0])
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        _registrar("create_connection", socket.create_connection, lambda a: a[0][0]),
    )
    monkeypatch.setattr(
        socket.socket, "connect", _registrar("connect", socket.socket.connect, lambda a: a[1][0])
    )

    # Control positivo: los registradores ven un intento de verdad.
    try:
        socket.create_connection(("192.0.2.1", 80), timeout=0.01)
    except OSError:
        # Esperado: 192.0.2.1 es TEST-NET y no responde. Aquí solo cuenta que el registrador
        # haya visto el intento, que es lo que comprueba el assert siguiente.
        pass
    assert intentos == ["create_connection"]
    intentos.clear()

    r = TestClient(metrics.app).get("/api/stats")
    assert r.status_code == 200
    assert r.json()["cost"]["figure"] is not None  # guarda: la tabla se cargó y se usó
    assert intentos == []


def test_frases_prohibidas(entorno, tmp_path, monkeypatch):
    """REQ-045 sobre el HTML, la respuesta de `/api/stats`, los textos del panel y los tres
    mensajes a Claude de T4 (coletilla, recibo de salida a fichero y `tokens_aprox`)."""
    logs, _home = entorno
    ahora = _ahora()
    _escribir_log(
        logs,
        [_linea(ahora - timedelta(hours=1)), {**IMAGEN, "ts": ahora.isoformat(timespec="seconds")}],
    )
    monkeypatch.setattr(cfg, "FEEDBACK_ENABLED", True)

    html = TestClient(metrics.app).get("/").text
    stats = _stats()
    textos = _textos(tmp_path, stats)
    coletilla = server._savings_feedback(
        4000,
        "chars",
        event=cost.in_flight_row(tool="local_summarize", source="path", path="a.md"),
    )
    coletilla_imagen = server._savings_feedback(
        250000,
        "bytes imagen",
        event=cost.in_flight_row(
            tool="local_describe_image", source="path", path="a.png", input_unit="bytes"
        ),
    )
    recibo = server._write_target(
        tmp_path / "salida.py",
        "x = 1\n",
        event=cost.in_flight_row(tool="local_boilerplate", source="inline"),
    )
    fuente_extract = inspect.getsource(server.local_extract)
    i = fuente_extract.index('meta["leido_server_side"]')
    tokens_aprox = fuente_extract[i : fuente_extract.index("}", i) + 1]
    assert "tokens_aprox" in tokens_aprox  # guarda: el recorte encontró el bloque
    assert "tokens de Claude" in coletilla and "tokens de Claude" in recibo  # guarda

    superficies = {
        "html": html,
        "metrics.HTML": metrics.HTML,
        "/api/stats": json.dumps(stats, ensure_ascii=False),
        "costText": textos["coste"],
        "quotaText": textos["cuota"],
        "imagesText": textos["imagenes"],
        "coletilla": coletilla,
        "coletilla de imagen": coletilla_imagen,
        "recibo": recibo,
        "tokens_aprox": tokens_aprox,
    }
    assert "cuota que no gastaste" not in html
    assert "ahorro de cuota" not in html.lower()
    for nombre, texto in superficies.items():
        for frase in FRASES_PROHIBIDAS:
            assert frase not in texto.lower(), f"«{frase}» en {nombre}"
    # El rótulo y la nota de REQ-045 sí están.
    assert "Equivalente estimado a precio de API: entre $" in textos["coste"]
    assert "no es dinero que hayas ahorrado: tu suscripción es de tarifa plana" in (
        textos["coste"].lower()
    )


def test_texto_del_coste_con_la_barra_y_el_respaldo(entorno, tmp_path):
    """node: el rótulo nombra el respaldo con su número, y los supuestos de REQ-044 están todos."""
    logs, _home = entorno
    ahora = _ahora()
    viejo = ahora - timedelta(days=45)  # sin relleno y fuera del plazo: `supuesto`
    _escribir_log(logs, [_linea(viejo, 0), _linea(ahora - timedelta(hours=1), 1)])
    j = _stats(ahora - timedelta(days=60), ahora)
    assert j["cost"]["bar"]["assumed"] == 1  # guarda: la fila vieja cayó donde debía
    texto = _textos(tmp_path, j)["coste"]
    assert "2 de 2 con modelo supuesto: Opus 5.5 en subagente" in texto
    assert "cota baja con estos supuestos" in texto
    assert "neto de la respuesta de la tool" in texto.lower()
    assert "si Claude hubiera leído el fichero entero una vez con Read" in texto
    assert "No descuenta las relecturas del mismo fichero (medidas entre ~3 % y ~30 %)" in texto
    assert "Precios de la tabla del paquete del 20" in texto
    assert (
        "Relecturas (N): 0 del relleno, 0 de la mediana de su grupo, 2 con el valor declarado"
        in texto
    )


def test_families_are_said_in_words(entorno, tmp_path):
    """Las familias de tokenizador llegan como `new` y `previous` y el panel las dice en palabras.

    Control: mutante «`FAMILY` con la clave vieja `nueva`» → sale «new 2»."""
    logs, _home = entorno
    _escribir_log(logs, [_linea(_ahora() - timedelta(hours=1))])
    j = _stats()
    assert j["cost"]["density"]["families"] == {"new": 1}  # guarda: la fila trae la familia
    j["cost"]["density"]["families"] = {"new": 2, "previous": 1}
    texto = _textos(tmp_path, j)["coste"]
    assert "familia de tokenizador (nueva 2, anterior 1)" in texto


def test_una_fila_sin_ahorro_no_pinta_dolares(entorno, tmp_path):
    """Arreglo tras T10: una fila del desglose con T ≤ 0 (la tool devolvió más de lo que leyó) dice
    «sin ahorro» en vez de «$0,00 $0,00». node, sobre las filas de `/api/stats`."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")
    logs, _home = entorno
    ahora = _ahora()
    negativa = _linea(
        ahora - timedelta(hours=2),
        1,
        chars_in=100,
        chars_out=500,
        caller_model="claude-sonnet-5-5",
        caller_kind="subagent",
        caller_effort="medium",
    )
    _escribir_log(logs, [_linea(ahora - timedelta(hours=1), 0), negativa])
    desglose = _stats(ahora - timedelta(days=1), ahora)["cost"]["breakdown"]
    por_t = sorted(desglose, key=lambda g: g["T"])
    assert len(por_t) == 2 and por_t[0]["T"] < 0 < por_t[1]["T"]  # guarda: una de cada
    assert por_t[0]["estimate"] == 0.0  # sin signo: redondea a cero

    programa = tmp_path / "celdas.mjs"
    programa.write_text(
        "\n".join(
            [
                *(_extraer(f) for f in ("function fmtNum(", "function dollars(")),
                _extraer("function costCells("),
                f"const filas = {json.dumps(por_t)};",
                "console.log(JSON.stringify(filas.map(costCells)));",
            ]
        ),
        encoding="utf-8",
    )
    salida = subprocess.run(
        [node, str(programa)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    sin, con = json.loads(salida.stdout)
    assert "sin ahorro" in sin
    assert "$" not in sin
    assert "sin ahorro" not in con
    assert con.count("$") == 2
