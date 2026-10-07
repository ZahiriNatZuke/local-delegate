"""T10 de `daemon-reparte-el-backend`: el turno por conjunto de modelos compatibles, en el daemon.

Los escenarios de la spec (REQ-002 a REQ-009) sobre el daemon de verdad (`server`), con la topología
de hoy (`tests/fixtures/topologia/hoy.yaml`, todo en un grupo `swap`) copiada a `tmp_path`. Cada test
de concurrencia lleva una guarda que demuestra que el guion discrimina —que sin turno el resultado
sería otro— antes del assert principal: un test que no puede ver la diferencia no es un control.

Los hilos esperan siempre con tope propio y fallan con un mensaje propio, nunca por el timeout del
runner.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import config, server, topologia
from local_delegate.fallos import Clase
from local_delegate.turno import Peticion

BASE = "http://127.0.0.1:9292/v1"
URL = f"{BASE}/chat/completions"
MECANICO = "gemma3-4b"
LARGO = "gemma4-26b-a4b"
CODIGO = "qwen36-35b-a3b"
HOY = Path(__file__).parent / "fixtures" / "topologia" / "hoy.yaml"

#: Una config en la que el 26B y Qwen3.6 NO chocan: cada uno en su grupo, ninguno exclusivo.
SEPARADOS = """\
models:
  gemma3-4b: {}
  gemma4-26b-a4b: {}
  qwen36-35b-a3b: {}
groups:
  largo:
    swap: true
    exclusive: false
    members: [gemma4-26b-a4b]
  codigo:
    swap: true
    exclusive: false
    members: [qwen36-35b-a3b]
  mecanico:
    swap: true
    exclusive: false
    members: [gemma3-4b]
"""

#: Router `matrix`: sin turno (REQ-002).
MATRIX = """\
models:
  gemma4-26b-a4b: {}
  qwen36-35b-a3b: {}
routing:
  router:
    use: matrix
    settings:
      matrix: {}
"""


# --- piezas comunes ---------------------------------------------------------------------------


def _ok(texto: str = "ok") -> server.ChatResult:
    return server.ChatResult(text=texto, ok=True, finish_reason="stop")


def _fallo_del_modelo() -> server.ChatResult:
    return server.ChatResult(text="x", ok=False, error="http_500", clase=Clase.MODELO)


def _eventos(tmp_path: Path) -> list[dict]:
    lineas: list[str] = []
    for fichero in sorted(tmp_path.glob("usage*.jsonl")):
        lineas += fichero.read_text(encoding="utf-8").splitlines()
    return [json.loads(linea) for linea in lineas if linea.strip()]


def _del_tool(eventos: list[dict], tool: str) -> dict:
    return next((e for e in eventos if e.get("tool") == tool), {})


def _esperar(condicion: Callable[[], object], tope: float = 2.0) -> object:
    """El primer valor verdadero de `condicion` antes del tope, o `None`."""
    fin = time.monotonic() + tope
    while time.monotonic() < fin:
        valor = condicion()
        if valor:
            return valor
        time.sleep(0.01)
    return None


def _en_curso(tool: str) -> dict | None:
    return next((e for e in server.inflight_snapshot() if e.get("tool") == tool), None)


class _Hilo(threading.Thread):
    """Un hilo que guarda lo que devuelve su función, o la excepción con la que salió."""

    def __init__(self, nombre: str, funcion: Callable, *args, **kwargs) -> None:
        super().__init__(name=nombre, daemon=True)
        self._llamada = (funcion, args, kwargs)
        self.resultado: object = None
        self.error: BaseException | None = None

    def run(self) -> None:
        funcion, args, kwargs = self._llamada
        try:
            self.resultado = funcion(*args, **kwargs)
        except BaseException as e:  # el test lo mira; un hilo no puede propagarlo
            self.error = e


def _parrafos(n: int, largo: int = 600, letra: str = "p") -> str:
    """`n` párrafos de unos `largo` caracteres: con un presupuesto de 800, un trozo por párrafo."""
    return "\n\n".join(
        f"{letra}{i} " + ("palabra " * (largo // 8)).strip() for i in range(1, n + 1)
    )


def _diff(n: int) -> str:
    """Un diff de `n` archivos de unos 600 caracteres: con un presupuesto de 800, uno por trozo."""
    partes = []
    for i in range(1, n + 1):
        cuerpo = "".join(f"+linea {j} del archivo {i}\n" for j in range(25))
        partes.append(
            f"diff --git a/f{i}.py b/f{i}.py\n--- a/f{i}.py\n+++ b/f{i}.py\n@@ -1 +1,25 @@\n{cuerpo}"
        )
    return "".join(partes)


def _texto(caracteres: int) -> str:
    parrafo = ("palabra " * 375).strip() + "\n\n"
    return (parrafo * (caracteres // len(parrafo) + 1))[:caracteres]


@pytest.fixture
def con_topologia(tmp_path, monkeypatch) -> Path:
    """La topología de hoy (todo en un grupo `swap`), en una copia, con el backend en loopback."""
    copia = tmp_path / "llamaswap.yaml"
    copia.write_bytes(HOY.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copia))
    monkeypatch.setattr(config, "BASE_URL", BASE)
    monkeypatch.setattr(server, "_chat_slots", threading.BoundedSemaphore(2))
    return copia


# --- Escenario: dos tools en paralelo ya no se quitan el modelo -------------------------------


def _dos_tools(monkeypatch, tmp_path) -> tuple[backend_mock.CuentaCambios, list[dict]]:
    """`local_commit_msg` (Qwen3.6) y `local_lint_summary` (26B), de 3 trozos cada una, a la vez."""
    monkeypatch.setitem(config.MAX_CHARS_POR_ROL, "code", 1000)
    monkeypatch.setitem(config.MAX_CHARS_POR_ROL, "long", 1000)
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 100)
    antes = len(_eventos(tmp_path))
    arranque = threading.Barrier(2)

    def commit() -> str:
        arranque.wait(2)
        return server.local_commit_msg(diff=_diff(3))

    def lint() -> str:
        arranque.wait(2)
        return server.local_lint_summary(text=_parrafos(3))

    with backend_mock.mock:
        # La barrera hace que, sin turno, las dos primeras llamadas lleguen juntas: sin ella, una
        # tool podía acabar antes de que la otra empezara y el guion no intercalaba (medido). Con
        # turno la segunda no llega hasta que acaba la primera, y la barrera vence su tope de 1 s.
        servidor = backend_mock.cuenta_cambios(URL, latencia_s=0.03, barrera=2, tope_barrera_s=1.0)
        hilos = [_Hilo("commit", commit), _Hilo("lint", lint)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(10)
    assert not any(h.is_alive() for h in hilos), "las dos tools no terminaron en 10 s"
    assert [h.error for h in hilos] == [None, None]
    return servidor, _eventos(tmp_path)[antes:]


def test_dos_tools_en_paralelo_ya_no_se_quitan_el_modelo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", BASE)
    monkeypatch.setattr(server, "_chat_slots", threading.BoundedSemaphore(2))

    # Guarda: el mismo guion SIN topología intercala los modelos. Si no, no puede ver el turno.
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    sin_turno, _ = _dos_tools(monkeypatch, tmp_path)
    assert sin_turno.cambios >= 3, f"el guion no intercala: {sin_turno.servidos}"

    copia = tmp_path / "llamaswap.yaml"
    copia.write_bytes(HOY.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copia))
    con_turno, eventos = _dos_tools(monkeypatch, tmp_path)

    assert len(eventos) == 2
    assert all(e.get("ok") for e in eventos), eventos
    assert all((e.get("chunks") or 1) >= 3 for e in eventos), eventos  # de 3 trozos de verdad
    assert con_turno.cambios == 1, con_turno.servidos
    # La segunda operación es la que el backend atendió después, no la que escribió después su
    # línea: el turno se suelta antes de escribir el evento, y la otra puede acabar antes.
    tool_de = {CODIGO: "local_commit_msg", LARGO: "local_lint_summary"}
    linea_primera = _del_tool(eventos, tool_de[con_turno.servidos[0]])
    linea_segunda = _del_tool(eventos, tool_de[con_turno.servidos[-1]])
    assert "espera_turno_ms" not in linea_primera
    assert linea_segunda.get("espera_turno_ms", 0) > 0


# --- Escenario: el mismo modelo no se serializa de más ----------------------------------------


def test_el_mismo_modelo_no_se_serializa_de_mas(con_topologia, tmp_path):
    with backend_mock.mock:
        # La barrera solo deja contestar cuando las DOS han llegado: estaban a la vez, cada una
        # con su plaza.
        servidor = backend_mock.cuenta_cambios(URL, barrera=2)
        hilos = [_Hilo(n, server.local_summarize, text=_texto(7000)) for n in ("A", "B")]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(10)
    assert not any(h.is_alive() for h in hilos), "los dos resúmenes no terminaron en 10 s"
    assert not servidor.no_se_solaparon, "no se solaparon"
    assert servidor.servidos == [LARGO, LARGO]
    lineas = _eventos(tmp_path)
    assert len(lineas) == 2
    for linea in lineas:
        assert "espera_turno_ms" not in linea


# --- Escenario: dos saltos a la vez no bloquean -----------------------------------------------


def test_dos_saltos_a_la_vez_no_bloquean(con_topologia, monkeypatch):
    """C, troceada en 3, tiene el turno del 26B; A y B, también en el 26B, ocupan las dos plazas y
    saltan a la vez a Qwen3.6 mientras C espera plaza para su segundo trozo."""
    monkeypatch.setattr(config, "TURNO_MAX_S", 60.0)  # que la red de seguridad no tape un bloqueo
    server._reiniciar_turno()
    monkeypatch.setitem(config.FALLBACK_CHAINS, "long", "code")
    cerrojo = threading.Lock()
    servidos: list[tuple[str, str]] = []
    dentro_ab: set[str] = set()
    c1_dentro, seguir_c1 = threading.Event(), threading.Event()
    uno_dentro, ab_dentro, fallar = threading.Event(), threading.Event(), threading.Event()
    c_espera_plaza, c_termino = threading.Event(), threading.Event()

    def post_chat(model, _payload):
        hilo = threading.current_thread().name
        with cerrojo:
            servidos.append((hilo, model))
        if hilo == "C":
            if not c1_dentro.is_set():
                c1_dentro.set()
                seguir_c1.wait(5)
            return _ok()
        if model == LARGO:
            with cerrojo:
                dentro_ab.add(hilo)
                if len(dentro_ab) == 2:
                    ab_dentro.set()
            uno_dentro.set()
            fallar.wait(5)
            return _fallo_del_modelo()
        return _ok(f"ok de {model}")

    progreso = server._inflight_progress
    espera_local = server._inflight_espera_local

    def inflight_progress(entry_id, chunk):
        # C no pide plaza para su segundo trozo hasta que A y B tienen las dos.
        if threading.current_thread().name == "C" and chunk == 2:
            ab_dentro.wait(5)
        progreso(entry_id, chunk)

    def inflight_espera_local(entry_id, motivo):
        espera_local(entry_id, motivo)
        if threading.current_thread().name == "C" and motivo == "plaza":
            c_espera_plaza.set()

    monkeypatch.setattr(server, "_post_chat", post_chat)
    monkeypatch.setattr(server, "_inflight_progress", inflight_progress)
    monkeypatch.setattr(server, "_inflight_espera_local", inflight_espera_local)

    def operacion_c() -> str:
        try:
            return server._chat_chunked(
                LARGO,
                "s",
                _parrafos(3),
                lambda pieza: pieza,
                tool="op_c",
                source="inline",
                rol="long",
                chunk_chars=800,
            )
        finally:
            c_termino.set()

    c = _Hilo("C", operacion_c)
    a = _Hilo("A", server._chat, LARGO, "s", "u", 8, tool="op_a", rol="long")
    b = _Hilo("B", server._chat, LARGO, "s", "u", 8, tool="op_b", rol="long")
    c.start()
    assert c1_dentro.wait(2), "C no llegó a su primer trozo"
    a.start()
    b.start()
    assert uno_dentro.wait(2), "ni A ni B tomaron la plaza libre"
    seguir_c1.set()
    assert ab_dentro.wait(2), "A y B no llegaron a ocupar las dos plazas"
    assert c_espera_plaza.wait(2), "C no llegó a esperar plaza para su segundo trozo"
    fallar.set()  # A y B fallan a la vez con una clase que salta a Qwen3.6

    assert c_termino.wait(2), "sin progreso: bloqueo turno/plaza"
    a.join(2)
    b.join(2)
    assert not a.is_alive() and not b.is_alive(), "A y B no terminaron tras C"
    assert c.error is None and "[local-delegate error]" not in str(c.resultado)
    assert f"ok de {CODIGO}" in str(a.resultado) and f"ok de {CODIGO}" in str(b.resultado)
    de_c = [i for i, (hilo, _) in enumerate(servidos) if hilo == "C"]
    a_qwen = [i for i, (_, modelo) in enumerate(servidos) if modelo == CODIGO]
    assert len(de_c) == 3 and len(a_qwen) == 2
    assert max(de_c) < min(a_qwen), servidos  # A y B en Qwen3.6, después de los 3 trozos de C


# --- El salto suelta la plaza antes de pedir turno --------------------------------------------


class _SemaforoEspia:
    """Un `BoundedSemaphore` que anota cuándo se toma y se suelta una plaza."""

    def __init__(self, plazas: int, eventos: list[str]) -> None:
        self._s = threading.BoundedSemaphore(plazas)
        self._eventos = eventos

    def acquire(self, blocking: bool = True) -> bool:
        tomada = self._s.acquire(blocking)
        if tomada:
            self._eventos.append("tomar_plaza")
        return tomada

    def release(self) -> None:
        self._eventos.append("soltar_plaza")
        self._s.release()


def test_el_salto_suelta_la_plaza_antes_de_pedir_turno(con_topologia, monkeypatch):
    monkeypatch.setitem(config.FALLBACK_CHAINS, "long", "code")
    eventos: list[str] = []
    monkeypatch.setattr(server, "_chat_slots", _SemaforoEspia(2, eventos))
    pedir = server._turno.pedir

    def pedir_espia(peticion, *args, **kwargs):
        eventos.append("pedir_turno:" + ",".join(sorted(peticion.A)))
        return pedir(peticion, *args, **kwargs)

    monkeypatch.setattr(server._turno, "pedir", pedir_espia)
    monkeypatch.setattr(
        server, "_post_chat", lambda model, _p: _fallo_del_modelo() if model == LARGO else _ok()
    )

    try:
        server._chat(LARGO, "s", "u", 8, tool="op", rol="long")
        error = None
    except Exception as e:  # un mutante puede lanzar en el aserto de REQ-004: se mira el orden
        error = e

    salto = f"pedir_turno:{CODIGO}"
    assert salto in eventos, f"no hubo salto: {eventos} ({error!r})"
    assert eventos.index("soltar_plaza") < eventos.index(salto)


# --- El turno y la plaza se liberan con una excepción inesperada ------------------------------


def test_turno_y_plaza_se_liberan_con_una_excepcion_inesperada(con_topologia, monkeypatch):
    en_uso_durante: list[tuple[str, ...]] = []

    def post_chat(_model, _payload):
        en_uso_durante.append(server._turno.en_uso())
        raise RuntimeError("inesperada del backend")

    monkeypatch.setattr(server, "_post_chat", post_chat)
    with pytest.raises(RuntimeError, match="inesperada del backend"):
        server._chat(LARGO, "s", "u", 8, tool="op", rol="long")

    assert en_uso_durante == [(LARGO,)]  # guarda: la llamada tenía el turno
    assert server._turno.foto().activos == ()
    plazas = [server._chat_slots.acquire(blocking=False) for _ in range(2)]
    for tomada in plazas:
        if tomada:
            server._chat_slots.release()
    assert plazas == [True, True]


# --- Tras conceder, fuera las claves del turno; si espera plaza, «plaza» ----------------------


def test_tras_conceder_la_entrada_pasa_de_turno_a_plaza(con_topologia, monkeypatch):
    x_dentro, seguir_x = threading.Event(), threading.Event()

    def post_chat(model, _payload):
        if threading.current_thread().name == "X":
            x_dentro.set()
            seguir_x.wait(5)
        return _ok()

    monkeypatch.setattr(server, "_post_chat", post_chat)
    x = _Hilo("X", server._chat, LARGO, "s", "u", 8, tool="op_x", rol="long")
    y = _Hilo("Y", server._chat, CODIGO, "s", "u", 8, tool="op_y", rol="code")
    tomadas = 0
    try:
        x.start()
        assert x_dentro.wait(2), "X no llegó al backend"
        assert server._chat_slots.acquire(blocking=False)  # la otra plaza, para el final
        tomadas += 1
        y.start()
        entrada = _esperar(lambda: (e := _en_curso("op_y")) and e.get("espera_local") and e)
        entrada = entrada or _en_curso("op_y") or {}
        assert entrada.get("espera_local") == "turno"
        assert entrada.get("turno_en_uso") == [LARGO]
        assert entrada.get("turno_posicion") == 1

        # Cuando X suelta su plaza, esta se queda con ella ANTES de que X suelte el turno: así Y,
        # al recibir el turno, encuentra las dos plazas ocupadas y espera plaza.
        soltar = server._turno.soltar

        def soltar_y_quedarse_la_plaza(op_id):
            nonlocal tomadas
            if threading.current_thread().name == "X":
                server._chat_slots.acquire()
                tomadas += 1
            soltar(op_id)

        monkeypatch.setattr(server._turno, "soltar", soltar_y_quedarse_la_plaza)
        seguir_x.set()
        entrada = _esperar(
            lambda: (e := _en_curso("op_y")) and e.get("espera_local") == "plaza" and e
        )
        assert entrada, f"Y no llegó a esperar plaza: {_en_curso('op_y')}"
        assert "turno_en_uso" not in entrada
        assert "turno_posicion" not in entrada
    finally:
        seguir_x.set()
        for _ in range(tomadas):
            server._chat_slots.release()
        x.join(5)
        y.join(5)
    assert not x.is_alive() and not y.is_alive()
    assert y.error is None


# --- Escenario: sin topología o con backend remoto, como hoy ----------------------------------


def _dos_que_chocan(monkeypatch, tmp_path) -> list[dict]:
    """El 26B y Qwen3.6 a la vez; cada llamada tarda 0,15 s."""

    def post_chat(_model, _payload):
        time.sleep(0.15)
        return _ok()

    monkeypatch.setattr(server, "_post_chat", post_chat)
    antes = len(_eventos(tmp_path))
    arranque = threading.Barrier(2)

    def operacion(modelo: str, rol: str) -> str:
        arranque.wait(2)
        return server._chat(modelo, "s", "u", 8, tool=f"op_{rol}", rol=rol)

    hilos = [_Hilo("L", operacion, LARGO, "long"), _Hilo("C", operacion, CODIGO, "code")]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(5)
    assert not any(h.is_alive() for h in hilos)
    return _eventos(tmp_path)[antes:]


@pytest.mark.parametrize("caso", ["sin LLAMASWAP_CONFIG", "matrix", "backend remoto"])
def test_sin_topologia_o_con_backend_remoto_como_hoy(caso, con_topologia, monkeypatch, tmp_path):
    # Guarda: el mismo guion con backend en loopback y la topología de hoy SÍ hace esperar a una.
    guarda = _dos_que_chocan(monkeypatch, tmp_path)
    assert any(e.get("espera_turno_ms", 0) > 0 for e in guarda), guarda

    if caso == "sin LLAMASWAP_CONFIG":
        monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    elif caso == "matrix":
        con_topologia.write_text(MATRIX, encoding="utf-8")
    else:
        monkeypatch.setattr(config, "BASE_URL", "http://pc-remota.example:9292/v1")
    # El caso es el que dice ser, mirado sin pasar por `_topologia()` (que es lo que se prueba).
    if caso == "backend remoto":
        assert not server._backend_en_loopback()
        assert isinstance(topologia.foto(), topologia.Foto)
    else:
        assert getattr(topologia.foto(), "motivo", None) == caso

    lineas = _dos_que_chocan(monkeypatch, tmp_path)
    assert len(lineas) == 2
    for linea in lineas:
        assert "espera_turno_ms" not in linea


# --- local_status dice el turno y, sin topología, el motivo -----------------------------------


@backend_mock.mock
def test_local_status_dice_el_turno_y_sin_topologia_el_motivo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", BASE)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    backend_mock.get(f"{BASE}/models").mock(side_effect=httpx2.ConnectError("caido"))
    backend_mock.get("http://127.0.0.1:9292/running").mock(side_effect=httpx2.ConnectError("x"))
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)

    texto = server.local_status()
    assert "Turno: no (sin LLAMASWAP_CONFIG)" in texto

    copia = tmp_path / "llamaswap.yaml"
    copia.write_bytes(HOY.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copia))
    texto = server.local_status()
    linea = next((x for x in texto.splitlines() if x.startswith("Turno:")), "")
    assert linea.startswith("Turno: sí (choques: ")
    # Por grupos de la config (REQ-008), con sus banderas; el grupo `(default)` vacío no sale.
    assert (
        "choques: swap [swap, no exclusivo]: gemma3-4b, gemma4-26b-a4b, qwen36-35b-a3b, "
        "qwen35-2b, gemma4-12b;"
    ) in linea
    assert "(default)" not in linea
    assert linea.endswith("; en uso: nada; esperan: 0)")


# --- Topología nueva en la siguiente concesión (REQ-009) --------------------------------------


def test_topologia_nueva_en_la_siguiente_concesion(con_topologia, monkeypatch):
    x_dentro, seguir_x = threading.Event(), threading.Event()

    def post_chat(_model, _payload):
        if threading.current_thread().name == "X":
            x_dentro.set()
            seguir_x.wait(5)
        return _ok()

    monkeypatch.setattr(server, "_post_chat", post_chat)
    x = _Hilo("X", server._chat, LARGO, "s", "u", 8, tool="op_x", rol="long")
    y = _Hilo("Y", server._chat, CODIGO, "s", "u", 8, tool="op_y", rol="code")
    try:
        x.start()
        assert x_dentro.wait(2), "X no llegó al backend"
        topo = server._topologia()
        assert topo.choca(LARGO, CODIGO)  # guarda: con la de hoy, Qwen3.6 tendría que esperar
        # Con X en curso, la config pasa a una en la que el 26B y Qwen3.6 no chocan.
        con_topologia.write_text(SEPARADOS, encoding="utf-8")
        y.start()
        y.join(2)
        concedida_con_la_nueva = not y.is_alive() and y.error is None
    finally:
        seguir_x.set()
        x.join(5)
        y.join(5)
    assert concedida_con_la_nueva


# --- Un evento forzado lleva `turno: "forzado"` -----------------------------------------------


def test_un_evento_forzado_lleva_turno_forzado(con_topologia, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TURNO_MAX_S", 0.3)
    server._reiniciar_turno()
    monkeypatch.setattr(server, "_post_chat", lambda _m, _p: _ok())
    x_atascada, seguir_x = threading.Event(), threading.Event()

    def build_user(pieza: str) -> str:
        # X tiene el turno y se atasca FUERA del backend antes de su segundo trozo.
        if pieza.startswith("p2"):
            x_atascada.set()
            seguir_x.wait(10)
        return pieza

    x = _Hilo(
        "X",
        server._chat_chunked,
        LARGO,
        "s",
        _parrafos(2, largo=450),
        build_user,
        tool="op_x",
        source="inline",
        rol="long",
        chunk_chars=500,
    )
    y = _Hilo("Y", server._chat, CODIGO, "s", "u", 8, tool="op_y", rol="code")
    try:
        x.start()
        assert x_atascada.wait(2), "X no llegó a atascarse con el turno"
        y.start()
        y.join(4)  # 0,3 s de espera y de falta de progreso, más un tic de 1 s
        assert not y.is_alive(), "Y no se concedió forzada"
    finally:
        seguir_x.set()
        x.join(5)
        y.join(5)
    linea = _del_tool(_eventos(tmp_path), "op_y")
    assert linea.get("espera_turno_ms", 0) > 0  # guarda: Y esperó turno de verdad
    assert linea.get("turno") == "forzado"


# --- Corrección tras la revisión de la ola 4 --------------------------------------------------


def test_espera_en_cola_ve_la_topologia_nueva(con_topologia, monkeypatch):
    """Y ya espera en la cola cuando la config cambia a una en la que no choca con X.

    Nadie llega ni sale: solo el gancho por tic de cada espera relee la topología (REQ-009,
    REQ-003 punto 5). Mutante: el daemon no conecta el gancho → Y sigue esperando a que X acabe.
    (Test de la revisión de solo lectura, traído aquí.)
    """
    x_dentro, seguir_x = threading.Event(), threading.Event()

    def post_chat(_model, _payload):
        if threading.current_thread().name == "X":
            x_dentro.set()
            seguir_x.wait(10)
        return _ok()

    monkeypatch.setattr(server, "_post_chat", post_chat)
    x = _Hilo("X", server._chat, LARGO, "s", "u", 8, tool="op_x", rol="long")
    y = _Hilo("Y", server._chat, CODIGO, "s", "u", 8, tool="op_y", rol="code")
    try:
        x.start()
        assert x_dentro.wait(2), "X no llegó al backend"
        y.start()
        assert _esperar(lambda: (e := _en_curso("op_y")) and e.get("espera_local") == "turno")
        con_topologia.write_text(SEPARADOS, encoding="utf-8")
        y.join(4)  # varios tics de 1 s
        concedida = not y.is_alive()
    finally:
        seguir_x.set()
        x.join(5)
        y.join(5)
    assert concedida, "la espera en cola sigue con la topología vieja mientras X no acabe"


def test_una_foto_vieja_no_pisa_a_la_nueva(con_topologia):
    """Dos hilos con fotos distintas llegan a `_al_ver_foto` en orden inverso: gana la nueva.

    Mutante: comparar con `!=` en vez de `>` → la vieja vuelve a regir y el 26B y Qwen3.6 chocan.
    """
    vieja = topologia.foto()
    con_topologia.write_text(SEPARADOS, encoding="utf-8")
    nueva = topologia.foto()
    assert isinstance(vieja, topologia.Foto) and isinstance(nueva, topologia.Foto)
    assert nueva.version > vieja.version and vieja.choca(LARGO, CODIGO)  # guarda

    server._al_ver_foto(nueva)
    server._al_ver_foto(vieja)

    server._turno.pedir(Peticion("x", frozenset({LARGO}), LARGO))
    y = _Hilo("Y", server._turno.pedir, Peticion("y", frozenset({CODIGO}), CODIGO))
    y.start()
    # Menos que un tic (1 s): el gancho por tic también relee la topología y taparía el defecto.
    y.join(0.3)
    concedida_con_la_nueva = not y.is_alive() and y.error is None
    server._turno.soltar("x")
    y.join(2)
    assert concedida_con_la_nueva, "una foto vieja volvió a regir"


def test_un_turno_fallido_no_deja_la_operacion_creyendo_que_lo_tiene(con_topologia, monkeypatch):
    """Si `pedir` sale con error, la siguiente llamada vuelve a pedir turno.

    Mutante: `asegurar` fija el modelo ANTES de pedir → la segunda llamada cree que ya lo tiene y
    llama al backend sin turno.
    """
    op = server._TurnoDeOperacion(9999, LARGO)
    pedir = server._turno.pedir

    def pedir_que_falla(*_a, **_k):
        raise RuntimeError("fallo al pedir turno")

    monkeypatch.setattr(server._turno, "pedir", pedir_que_falla)
    with pytest.raises(RuntimeError, match="fallo al pedir turno"):
        op.asegurar(LARGO)
    monkeypatch.setattr(server._turno, "pedir", pedir)

    op.asegurar(LARGO)
    try:
        assert server._turno.en_uso() == (LARGO,)
    finally:
        op.soltar()
