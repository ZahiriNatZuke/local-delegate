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

from local_delegate import config, server, topology
from local_delegate.fallos import Clase
from local_delegate.turn import PendingRequest

BASE = "http://127.0.0.1:9292/v1"
URL = f"{BASE}/chat/completions"
MECHANICAL = "gemma3-4b"
LONG = "gemma4-26b-a4b"
CODE = "qwen36-35b-a3b"
TODAY = Path(__file__).parent / "fixtures" / "topologia" / "hoy.yaml"

#: Una config en la que el 26B y Qwen3.6 NO chocan: cada uno en su grupo, ninguno exclusivo.
SEPARATE = """\
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


def _ok(text: str = "ok") -> server.ChatResult:
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


def _model_failure() -> server.ChatResult:
    return server.ChatResult(text="x", ok=False, error="http_500", clase=Clase.MODELO)


def _events(tmp_path: Path) -> list[dict]:
    lines: list[str] = []
    for file in sorted(tmp_path.glob("usage*.jsonl")):
        lines += file.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _of_tool(events: list[dict], tool: str) -> dict:
    return next((e for e in events if e.get("tool") == tool), {})


def _wait(condition: Callable[[], object], cap: float = 2.0) -> object:
    """El primer valor verdadero de `condition` antes del tope, o `None`."""
    end = time.monotonic() + cap
    while time.monotonic() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.01)
    return None


def _in_progress(tool: str) -> dict | None:
    return next((e for e in server.inflight_snapshot() if e.get("tool") == tool), None)


class _Thread(threading.Thread):
    """Un hilo que guarda lo que devuelve su función, o la excepción con la que salió."""

    def __init__(self, name: str, function: Callable, *args, **kwargs) -> None:
        super().__init__(name=name, daemon=True)
        self._call = (function, args, kwargs)
        self.result: object = None
        self.error: BaseException | None = None

    def run(self) -> None:
        function, args, kwargs = self._call
        try:
            self.result = function(*args, **kwargs)
        except BaseException as e:  # el test lo mira; un hilo no puede propagarlo
            self.error = e


def _paragraphs(n: int, long: int = 600, letter: str = "p") -> str:
    """`n` párrafos de unos `long` caracteres: con un presupuesto de 800, un trozo por párrafo."""
    return "\n\n".join(
        f"{letter}{i} " + ("palabra " * (long // 8)).strip() for i in range(1, n + 1)
    )


def _diff(n: int) -> str:
    """Un diff de `n` archivos de unos 600 caracteres: con un presupuesto de 800, uno por trozo."""
    parts = []
    for i in range(1, n + 1):
        body = "".join(f"+linea {j} del archivo {i}\n" for j in range(25))
        parts.append(
            f"diff --git a/f{i}.py b/f{i}.py\n--- a/f{i}.py\n+++ b/f{i}.py\n@@ -1 +1,25 @@\n{body}"
        )
    return "".join(parts)


def _text(chars: int) -> str:
    paragraph = ("palabra " * 375).strip() + "\n\n"
    return (paragraph * (chars // len(paragraph) + 1))[:chars]


@pytest.fixture
def with_topology(tmp_path, monkeypatch) -> Path:
    """La topología de hoy (todo en un grupo `swap`), en una copia, con el backend en loopback."""
    copy = tmp_path / "llamaswap.yaml"
    copy.write_bytes(TODAY.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copy))
    monkeypatch.setattr(config, "BASE_URL", BASE)
    monkeypatch.setattr(server, "_chat_slots", threading.BoundedSemaphore(2))
    return copy


# --- Escenario: dos tools en paralelo ya no se quitan el modelo -------------------------------


def _two_tools(monkeypatch, tmp_path) -> tuple[backend_mock.ChangeCount, list[dict]]:
    """`local_commit_msg` (Qwen3.6) y `local_lint_summary` (26B), de 3 trozos cada una, a la vez."""
    monkeypatch.setitem(config.MAX_CHARS_POR_ROL, "code", 1000)
    monkeypatch.setitem(config.MAX_CHARS_POR_ROL, "long", 1000)
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 100)
    before = len(_events(tmp_path))
    startup = threading.Barrier(2)

    def commit() -> str:
        startup.wait(2)
        return server.local_commit_msg(diff=_diff(3))

    def lint() -> str:
        startup.wait(2)
        return server.local_lint_summary(text=_paragraphs(3))

    with backend_mock.mock:
        # La barrera hace que, sin turno, las dos primeras llamadas lleguen juntas: sin ella, una
        # tool podía acabar antes de que la otra empezara y el guion no intercalaba (medido). Con
        # turno la segunda no llega hasta que acaba la primera, y la barrera vence su tope de 1 s.
        server_ = backend_mock.count_changes(URL, latency_s=0.03, barrier=2, barrier_cap_s=1.0)
        threads = [_Thread("commit", commit), _Thread("lint", lint)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
    assert not any(h.is_alive() for h in threads), "las dos tools no terminaron en 10 s"
    assert [h.error for h in threads] == [None, None]
    return server_, _events(tmp_path)[before:]


def test_two_parallel_tools_no_longer_steal_the_model(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", BASE)
    monkeypatch.setattr(server, "_chat_slots", threading.BoundedSemaphore(2))

    # Guarda: el mismo guion SIN topología intercala los modelos. Si no, no puede ver el turno.
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    no_turn, _ = _two_tools(monkeypatch, tmp_path)
    assert no_turn.changes >= 3, f"el guion no intercala: {no_turn.served}"

    copy = tmp_path / "llamaswap.yaml"
    copy.write_bytes(TODAY.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copy))
    with_turn, events = _two_tools(monkeypatch, tmp_path)

    assert len(events) == 2
    assert all(e.get("ok") for e in events), events
    assert all((e.get("chunks") or 1) >= 3 for e in events), events  # de 3 trozos de verdad
    assert with_turn.changes == 1, with_turn.served
    # La segunda operación es la que el backend atendió después, no la que escribió después su
    # línea: el turno se suelta antes de escribir el evento, y la otra puede acabar antes.
    tool_of = {CODE: "local_commit_msg", LONG: "local_lint_summary"}
    first_line = _of_tool(events, tool_of[with_turn.served[0]])
    second_line = _of_tool(events, tool_of[with_turn.served[-1]])
    assert "turn_wait_ms" not in first_line
    assert second_line.get("turn_wait_ms", 0) > 0


# --- Escenario: el mismo modelo no se serializa de más ----------------------------------------


def test_same_model_not_overserialized(with_topology, tmp_path):
    with backend_mock.mock:
        # La barrera solo deja contestar cuando las DOS han llegado: estaban a la vez, cada una
        # con su plaza.
        server_ = backend_mock.count_changes(URL, barrier=2)
        threads = [_Thread(n, server.local_summarize, text=_text(7000)) for n in ("A", "B")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
    assert not any(h.is_alive() for h in threads), "los dos resúmenes no terminaron en 10 s"
    assert not server_.did_not_overlap, "no se solaparon"
    assert server_.served == [LONG, LONG]
    lines = _events(tmp_path)
    assert len(lines) == 2
    for line in lines:
        assert "turn_wait_ms" not in line


# --- Escenario: dos saltos a la vez no bloquean -----------------------------------------------


def test_two_simultaneous_hops_do_not_block(with_topology, monkeypatch):
    """C, troceada en 3, tiene el turno del 26B; A y B, también en el 26B, ocupan las dos plazas y
    saltan a la vez a Qwen3.6 mientras C espera plaza para su segundo trozo."""
    monkeypatch.setattr(config, "TURN_MAX_S", 60.0)  # que la red de seguridad no tape un bloqueo
    server._reset_turn()
    monkeypatch.setitem(config.FALLBACK_CHAINS, "long", "code")
    lock = threading.Lock()
    served: list[tuple[str, str]] = []
    inside_ab: set[str] = set()
    c1_inside, continue_c1 = threading.Event(), threading.Event()
    one_inside, ab_inside, fail = threading.Event(), threading.Event(), threading.Event()
    c_waits_slot, c_done = threading.Event(), threading.Event()

    def post_chat(model, _payload):
        thread = threading.current_thread().name
        with lock:
            served.append((thread, model))
        if thread == "C":
            if not c1_inside.is_set():
                c1_inside.set()
                continue_c1.wait(5)
            return _ok()
        if model == LONG:
            with lock:
                inside_ab.add(thread)
                if len(inside_ab) == 2:
                    ab_inside.set()
            one_inside.set()
            fail.wait(5)
            return _model_failure()
        return _ok(f"ok de {model}")

    progress = server._inflight_progress
    local_wait = server._inflight_espera_local

    def inflight_progress(entry_id, chunk):
        # C no pide plaza para su segundo trozo hasta que A y B tienen las dos.
        if threading.current_thread().name == "C" and chunk == 2:
            ab_inside.wait(5)
        progress(entry_id, chunk)

    def inflight_local_wait(entry_id, reason):
        local_wait(entry_id, reason)
        if threading.current_thread().name == "C" and reason == "slot":
            c_waits_slot.set()

    monkeypatch.setattr(server, "_post_chat", post_chat)
    monkeypatch.setattr(server, "_inflight_progress", inflight_progress)
    monkeypatch.setattr(server, "_inflight_espera_local", inflight_local_wait)

    def operation_c() -> str:
        try:
            return server._chat_chunked(
                LONG,
                "s",
                _paragraphs(3),
                lambda piece: piece,
                tool="op_c",
                source="inline",
                rol="long",
                chunk_chars=800,
            )
        finally:
            c_done.set()

    c = _Thread("C", operation_c)
    a = _Thread("A", server._chat, LONG, "s", "u", 8, tool="op_a", rol="long")
    b = _Thread("B", server._chat, LONG, "s", "u", 8, tool="op_b", rol="long")
    c.start()
    assert c1_inside.wait(2), "C no llegó a su primer trozo"
    a.start()
    b.start()
    assert one_inside.wait(2), "ni A ni B tomaron la plaza libre"
    continue_c1.set()
    assert ab_inside.wait(2), "A y B no llegaron a ocupar las dos plazas"
    assert c_waits_slot.wait(2), "C no llegó a esperar plaza para su segundo trozo"
    fail.set()  # A y B fallan a la vez con una clase que salta a Qwen3.6

    assert c_done.wait(2), "sin progreso: bloqueo turno/plaza"
    a.join(2)
    b.join(2)
    assert not a.is_alive() and not b.is_alive(), "A y B no terminaron tras C"
    assert c.error is None and "[local-delegate error]" not in str(c.result)
    assert f"ok de {CODE}" in str(a.result) and f"ok de {CODE}" in str(b.result)
    of_c = [i for i, (thread, _) in enumerate(served) if thread == "C"]
    a_qwen = [i for i, (_, model_) in enumerate(served) if model_ == CODE]
    assert len(of_c) == 3 and len(a_qwen) == 2
    assert max(of_c) < min(a_qwen), served  # A y B en Qwen3.6, después de los 3 trozos de C


# --- El salto suelta la plaza antes de pedir turno --------------------------------------------


class _SpySemaphore:
    """Un `BoundedSemaphore` que anota cuándo se toma y se suelta una plaza."""

    def __init__(self, slots: int, events: list[str]) -> None:
        self._s = threading.BoundedSemaphore(slots)
        self._events = events

    def acquire(self, blocking: bool = True) -> bool:
        taken = self._s.acquire(blocking)
        if taken:
            self._events.append("tomar_plaza")
        return taken

    def release(self) -> None:
        self._events.append("soltar_plaza")
        self._s.release()


def test_hop_releases_slot_before_requesting_turn(with_topology, monkeypatch):
    monkeypatch.setitem(config.FALLBACK_CHAINS, "long", "code")
    events: list[str] = []
    monkeypatch.setattr(server, "_chat_slots", _SpySemaphore(2, events))
    request = server._turn.request

    def spy_request(request_, *args, **kwargs):
        events.append("pedir_turno:" + ",".join(sorted(request_.A)))
        return request(request_, *args, **kwargs)

    monkeypatch.setattr(server._turn, "request", spy_request)
    monkeypatch.setattr(
        server, "_post_chat", lambda model, _p: _model_failure() if model == LONG else _ok()
    )

    try:
        server._chat(LONG, "s", "u", 8, tool="op", rol="long")
        error = None
    except Exception as e:  # un mutante puede lanzar en el aserto de REQ-004: se mira el orden
        error = e

    hop = f"pedir_turno:{CODE}"
    assert hop in events, f"no hubo salto: {events} ({error!r})"
    assert events.index("soltar_plaza") < events.index(hop)


# --- El turno y la plaza se liberan con una excepción inesperada ------------------------------


def test_turn_and_slot_released_on_unexpected_exception(with_topology, monkeypatch):
    in_use_during: list[tuple[str, ...]] = []

    def post_chat(_model, _payload):
        in_use_during.append(server._turn.in_use())
        raise RuntimeError("inesperada del backend")

    monkeypatch.setattr(server, "_post_chat", post_chat)
    with pytest.raises(RuntimeError, match="inesperada del backend"):
        server._chat(LONG, "s", "u", 8, tool="op", rol="long")

    assert in_use_during == [(LONG,)]  # guarda: la llamada tenía el turno
    assert server._turn.snapshot().actives == ()
    slots = [server._chat_slots.acquire(blocking=False) for _ in range(2)]
    for taken in slots:
        if taken:
            server._chat_slots.release()
    assert slots == [True, True]


# --- Tras conceder, fuera las claves del turno; si espera plaza, «plaza» ----------------------


def test_after_grant_entry_moves_from_turn_to_slot(with_topology, monkeypatch):
    x_inside, continue_x = threading.Event(), threading.Event()

    def post_chat(model, _payload):
        if threading.current_thread().name == "X":
            x_inside.set()
            continue_x.wait(5)
        return _ok()

    monkeypatch.setattr(server, "_post_chat", post_chat)
    x = _Thread("X", server._chat, LONG, "s", "u", 8, tool="op_x", rol="long")
    y = _Thread("Y", server._chat, CODE, "s", "u", 8, tool="op_y", rol="code")
    taken_ones = 0
    try:
        x.start()
        assert x_inside.wait(2), "X no llegó al backend"
        assert server._chat_slots.acquire(blocking=False)  # la otra plaza, para el final
        taken_ones += 1
        y.start()
        entry = _wait(lambda: (e := _in_progress("op_y")) and e.get("local_wait") and e)
        entry = entry or _in_progress("op_y") or {}
        assert entry.get("local_wait") == "turn"
        assert entry.get("turn_in_use") == [LONG]
        assert entry.get("turn_position") == 1

        # Cuando X suelta su plaza, esta se queda con ella ANTES de que X suelte el turno: así Y,
        # al recibir el turno, encuentra las dos plazas ocupadas y espera plaza.
        release_slot = server._turn.release_slot

        def release_and_keep_slot(op_id):
            nonlocal taken_ones
            if threading.current_thread().name == "X":
                server._chat_slots.acquire()
                taken_ones += 1
            release_slot(op_id)

        monkeypatch.setattr(server._turn, "release_slot", release_and_keep_slot)
        continue_x.set()
        entry = _wait(lambda: (e := _in_progress("op_y")) and e.get("local_wait") == "slot" and e)
        assert entry, f"Y no llegó a esperar plaza: {_in_progress('op_y')}"
        assert "turn_in_use" not in entry
        assert "turn_position" not in entry
    finally:
        continue_x.set()
        for _ in range(taken_ones):
            server._chat_slots.release()
        x.join(5)
        y.join(5)
    assert not x.is_alive() and not y.is_alive()
    assert y.error is None


# --- Escenario: sin topología o con backend remoto, como hoy ----------------------------------


def _two_that_clash(monkeypatch, tmp_path) -> list[dict]:
    """El 26B y Qwen3.6 a la vez; cada llamada tarda 0,15 s."""

    def post_chat(_model, _payload):
        time.sleep(0.15)
        return _ok()

    monkeypatch.setattr(server, "_post_chat", post_chat)
    before = len(_events(tmp_path))
    startup = threading.Barrier(2)

    def operation(model: str, role: str) -> str:
        startup.wait(2)
        return server._chat(model, "s", "u", 8, tool=f"op_{role}", rol=role)

    threads = [_Thread("L", operation, LONG, "long"), _Thread("C", operation, CODE, "code")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert not any(h.is_alive() for h in threads)
    return _events(tmp_path)[before:]


@pytest.mark.parametrize("case", ["sin LLAMASWAP_CONFIG", "matrix", "backend remoto"])
def test_without_topology_or_remote_backend_like_today(case, with_topology, monkeypatch, tmp_path):
    # Guarda: el mismo guion con backend en loopback y la topología de hoy SÍ hace esperar a una.
    guard = _two_that_clash(monkeypatch, tmp_path)
    assert any(e.get("turn_wait_ms", 0) > 0 for e in guard), guard

    if case == "sin LLAMASWAP_CONFIG":
        monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    elif case == "matrix":
        with_topology.write_text(MATRIX, encoding="utf-8")
    else:
        monkeypatch.setattr(config, "BASE_URL", "http://pc-remota.example:9292/v1")
    # El caso es el que dice ser, mirado sin pasar por `_topology()` (que es lo que se prueba).
    if case == "backend remoto":
        assert not server._backend_en_loopback()
        assert isinstance(topology.snapshot(), topology.Snapshot)
    else:
        assert getattr(topology.snapshot(), "reason", None) == case

    lines = _two_that_clash(monkeypatch, tmp_path)
    assert len(lines) == 2
    for line in lines:
        assert "turn_wait_ms" not in line


# --- local_status dice el turno y, sin topología, el motivo -----------------------------------


@backend_mock.mock
def test_local_status_shows_turn_and_no_topology_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", BASE)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    backend_mock.get(f"{BASE}/models").mock(side_effect=httpx2.ConnectError("caido"))
    backend_mock.get("http://127.0.0.1:9292/running").mock(side_effect=httpx2.ConnectError("x"))
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)

    text = server.local_status()
    assert "Turno: no (sin LLAMASWAP_CONFIG)" in text

    copy = tmp_path / "llamaswap.yaml"
    copy.write_bytes(TODAY.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copy))
    text = server.local_status()
    line = next((x for x in text.splitlines() if x.startswith("Turno:")), "")
    assert line.startswith("Turno: sí (choques: ")
    # Por grupos de la config (REQ-008), con sus banderas; el grupo `(default)` vacío no sale.
    assert (
        "choques: swap [swap, no exclusivo]: gemma3-4b, gemma4-26b-a4b, qwen36-35b-a3b, "
        "qwen35-2b, gemma4-12b;"
    ) in line
    assert "(default)" not in line
    assert line.endswith("; en uso: nada; esperan: 0)")


# --- Topología nueva en la siguiente concesión (REQ-009) --------------------------------------


def test_new_topology_on_next_grant(with_topology, monkeypatch):
    x_inside, continue_x = threading.Event(), threading.Event()

    def post_chat(_model, _payload):
        if threading.current_thread().name == "X":
            x_inside.set()
            continue_x.wait(5)
        return _ok()

    monkeypatch.setattr(server, "_post_chat", post_chat)
    x = _Thread("X", server._chat, LONG, "s", "u", 8, tool="op_x", rol="long")
    y = _Thread("Y", server._chat, CODE, "s", "u", 8, tool="op_y", rol="code")
    try:
        x.start()
        assert x_inside.wait(2), "X no llegó al backend"
        topo = server._topology()
        assert topo.clashes(LONG, CODE)  # guarda: con la de hoy, Qwen3.6 tendría que esperar
        # Con X en curso, la config pasa a una en la que el 26B y Qwen3.6 no chocan.
        with_topology.write_text(SEPARATE, encoding="utf-8")
        y.start()
        y.join(2)
        granted_with_new = not y.is_alive() and y.error is None
    finally:
        continue_x.set()
        x.join(5)
        y.join(5)
    assert granted_with_new


# --- Un evento forzado lleva `turn: "forced"` -----------------------------------------------


def test_forced_event_carries_turn_forced(with_topology, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TURN_MAX_S", 0.3)
    server._reset_turn()
    monkeypatch.setattr(server, "_post_chat", lambda _m, _p: _ok())
    x_stuck, continue_x = threading.Event(), threading.Event()

    def build_user(piece: str) -> str:
        # X tiene el turno y se atasca FUERA del backend antes de su segundo trozo.
        if piece.startswith("p2"):
            x_stuck.set()
            continue_x.wait(10)
        return piece

    x = _Thread(
        "X",
        server._chat_chunked,
        LONG,
        "s",
        _paragraphs(2, long=450),
        build_user,
        tool="op_x",
        source="inline",
        rol="long",
        chunk_chars=500,
    )
    y = _Thread("Y", server._chat, CODE, "s", "u", 8, tool="op_y", rol="code")
    try:
        x.start()
        assert x_stuck.wait(2), "X no llegó a atascarse con el turno"
        y.start()
        y.join(4)  # 0,3 s de espera y de falta de progreso, más un tic de 1 s
        assert not y.is_alive(), "Y no se concedió forzada"
    finally:
        continue_x.set()
        x.join(5)
        y.join(5)
    line = _of_tool(_events(tmp_path), "op_y")
    assert line.get("turn_wait_ms", 0) > 0  # guarda: Y esperó turno de verdad
    assert line.get("turn") == "forced"


# --- Corrección tras la revisión de la ola 4 --------------------------------------------------


def test_queued_wait_sees_new_topology(with_topology, monkeypatch):
    """Y ya espera en la cola cuando la config cambia a una en la que no choca con X.

    Nadie llega ni sale: solo el gancho por tic de cada espera relee la topología (REQ-009,
    REQ-003 punto 5). Mutante: el daemon no conecta el gancho → Y sigue esperando a que X acabe.
    (Test de la revisión de solo lectura, traído aquí.)
    """
    x_inside, continue_x = threading.Event(), threading.Event()

    def post_chat(_model, _payload):
        if threading.current_thread().name == "X":
            x_inside.set()
            continue_x.wait(10)
        return _ok()

    monkeypatch.setattr(server, "_post_chat", post_chat)
    x = _Thread("X", server._chat, LONG, "s", "u", 8, tool="op_x", rol="long")
    y = _Thread("Y", server._chat, CODE, "s", "u", 8, tool="op_y", rol="code")
    try:
        x.start()
        assert x_inside.wait(2), "X no llegó al backend"
        y.start()
        assert _wait(lambda: (e := _in_progress("op_y")) and e.get("local_wait") == "turn")
        with_topology.write_text(SEPARATE, encoding="utf-8")
        y.join(4)  # varios tics de 1 s
        granted = not y.is_alive()
    finally:
        continue_x.set()
        x.join(5)
        y.join(5)
    assert granted, "la espera en cola sigue con la topología vieja mientras X no acabe"


def test_old_snapshot_does_not_overwrite_new(with_topology):
    """Dos hilos con fotos distintas llegan a `_on_snapshot_seen` en orden inverso: gana la nueva.

    Mutante: comparar con `!=` en vez de `>` → la vieja vuelve a regir y el 26B y Qwen3.6 chocan.
    """
    old_one = topology.snapshot()
    with_topology.write_text(SEPARATE, encoding="utf-8")
    new_one = topology.snapshot()
    assert isinstance(old_one, topology.Snapshot) and isinstance(new_one, topology.Snapshot)
    assert new_one.version > old_one.version and old_one.clashes(LONG, CODE)  # guarda

    server._on_snapshot_seen(new_one)
    server._on_snapshot_seen(old_one)

    server._turn.request(PendingRequest("x", frozenset({LONG}), LONG))
    y = _Thread("Y", server._turn.request, PendingRequest("y", frozenset({CODE}), CODE))
    y.start()
    # Menos que un tic (1 s): el gancho por tic también relee la topología y taparía el defecto.
    y.join(0.3)
    granted_with_new = not y.is_alive() and y.error is None
    server._turn.release_slot("x")
    y.join(2)
    assert granted_with_new, "una foto vieja volvió a regir"


def test_failed_turn_does_not_leave_operation_believing_it_has_it(with_topology, monkeypatch):
    """Si `request` sale con error, la siguiente llamada vuelve a pedir turno.

    Mutante: `ensure` fija el modelo ANTES de pedir → la segunda llamada cree que ya lo tiene y
    llama al backend sin turno.
    """
    op = server._OperationTurn(9999, LONG)
    request = server._turn.request

    def failing_request(*_a, **_k):
        raise RuntimeError("fallo al pedir turno")

    monkeypatch.setattr(server._turn, "request", failing_request)
    with pytest.raises(RuntimeError, match="fallo al pedir turno"):
        op.ensure(LONG)
    monkeypatch.setattr(server._turn, "request", request)

    op.ensure(LONG)
    try:
        assert server._turn.in_use() == (LONG,)
    finally:
        op.release_slot()
