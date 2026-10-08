"""T15 de `daemon-reparte-el-backend`: la afinidad (REQ-010 a REQ-017, miembros de `loaded` de REQ-019).

Escenarios sobre el daemon de verdad (`server`) con una config **sintética** en `tmp_path`: los GGUF
son ficheros pequeños creados aquí y las celdas de la matriz se rehacen con su huella (la ruta y el
tamaño de esos ficheros, los flags medidos y el prompt de la tool construido con el código
vigente). `llama-swap` lo simula `backend_mock`: `/running`, la foto `inflight` de `/api/events` y
`/api/metrics/activity`. Ningún test habla con el llama-swap real ni carga modelos.

La spec escribe los escenarios con `local_classify`, cuya celda salió `rechazada`; aquí van con
celdas aprobadas (`local_translate` y `local_delegate` frente al 4B), como prevé el plan. El de «una
celda no aprobada no se usa» usa `local_explain_code`, que no tiene dirección (REQ-011).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import cadenas, checks, config, footprint, matrix, server, turn
from local_delegate.turn import PendingRequest

BASE = "http://127.0.0.1:9292/v1"
CHAT = f"{BASE}/chat/completions"
LLAMASWAP = "http://127.0.0.1:9292"
MECH = "gemma3-4b"
LONG = "gemma4-26b-a4b"
CODE = "qwen36-35b-a3b"
VERDICT = Path(__file__).parent.parent / "benchmarks" / "afinidad-2026-10" / "veredicto.json"
CAP_S = 3.0

_FLAGS = {
    MECH: "--ctx-size 8192 --reasoning off",
    LONG: "-ncmoe {ncmoe} --ctx-size 38400 --reasoning off",
    CODE: "-ncmoe 20 --ctx-size 16384 --reasoning off",
}
_SIZES = {MECH: 11, LONG: 26, CODE: 36}


# --- montaje ----------------------------------------------------------------------------------


def _cmd(tmp_path: Path, model: str, ncmoe: int = 12) -> str:
    gguf = tmp_path / f"{model}.gguf"
    if not gguf.exists():
        gguf.write_bytes(b"x" * _SIZES[model])
    return f"llama-server --port ${{PORT}} --model {gguf} " + _FLAGS[model].format(ncmoe=ncmoe)


def _write_config(
    tmp_path: Path,
    *,
    ncmoe: int = 12,
    separate: bool = False,
    groups: list[str] | None = None,
    gguf_26b: Path | None = None,
) -> Path:
    """La config sintética: los tres modelos con TTL 120, en un grupo `swap` (como hoy), cada uno
    en el suyo (`separate`: no chocan) o con los `groups` dados. `gguf_26b` cambia el GGUF del 26B."""
    lines = ["models:"]
    for model in (MECH, LONG, CODE):
        cmd = _cmd(tmp_path, model, ncmoe)
        if model == LONG and gguf_26b is not None:
            cmd = cmd.replace(str(tmp_path / f"{LONG}.gguf"), str(gguf_26b))
        lines += [f"  {model}:", f"    cmd: '{cmd}'", "    ttl: 120"]
    lines.append("groups:")
    if groups is not None:
        lines += groups
    elif separate:
        for model in (MECH, LONG, CODE):
            lines += [
                f"  g-{model}:",
                "    swap: true",
                "    exclusive: false",
                f"    members: [{model}]",
            ]
    else:
        lines += [
            "  swap:",
            "    swap: true",
            "    exclusive: false",
            f"    members: [{MECH}, {LONG}, {CODE}]",
        ]
    path = tmp_path / "llamaswap.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _cell(tmp_path: Path, tool: str, alternative: str, role: str, ncmoe: int = 12) -> matrix.Cell:
    """Una celda con la huella del modelo de `tmp_path` tal como la mediría la evaluación."""
    prompt = server._affinity_prompt(tool)
    assert prompt is not None, tool
    fp = footprint.footprint({"cmd": _cmd(tmp_path, alternative, ncmoe)}, prompt)
    return matrix.Cell(tool, alternative, role, fp)


@pytest.fixture
def affinity(tmp_path, monkeypatch) -> Path:
    """Config sintética con turno, las celdas aprobadas de hoy rehechas sobre ella y el proveedor
    de `loaded` registrado (otro test puede haberlo quitado con `register_loaded_provider(None)`)."""
    path = _write_config(tmp_path)
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(path))
    monkeypatch.setattr(config, "BASE_URL", BASE)
    monkeypatch.setattr(server, "_chat_slots", threading.BoundedSemaphore(2))
    monkeypatch.setattr(
        matrix,
        "CELLS",
        (
            _cell(tmp_path, "local_translate", LONG, MECH),
            _cell(tmp_path, "local_translate", CODE, MECH),
            _cell(tmp_path, "local_lint_summary", LONG, MECH),
            _cell(tmp_path, "local_delegate", LONG, MECH),
        ),
    )
    monkeypatch.setattr(cadenas, "_loaded_provider", server._affinity_loaded_provider)
    return path


def _events(tmp_path: Path) -> list[dict]:
    lines: list[str] = []
    for file in sorted(tmp_path.glob("usage*.jsonl")):
        lines += file.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _line(tmp_path: Path, tool: str) -> dict:
    return next((e for e in reversed(_events(tmp_path)) if e.get("tool") == tool), {})


class _Backend:
    """El chat y el llama-swap simulados. Apunta los modelos servidos y las rutas de llama-swap."""

    def __init__(self) -> None:
        self.served: list[str] = []
        self.paths: list[str] = []
        self.chat: Callable[[str], httpx2.Response] = lambda model: backend_mock.chat_response(
            f"ok de {model}"
        )

    def _chat(self, request: httpx2.Request) -> httpx2.Response:
        model = json.loads(request.content)["model"]
        self.served.append(model)
        return self.chat(model)

    def install(
        self,
        *,
        ready: dict[str, int] | None = None,
        inflight: list[str] = (),
        ended_ago: dict[str, float] | None = None,
        before_running: Callable[[], None] | None = None,
        running_status: int = 200,
    ) -> _Backend:
        """`ready`: modelo → TTL de `/running`; `inflight`: modelos de las peticiones en vuelo;
        `ended_ago`: segundos desde el fin de la última petición de cada modelo."""
        backend_mock.post(CHAT).mock(side_effect=self._chat)
        running = [{"model": m, "state": "ready", "ttl": ttl} for m, ttl in (ready or {}).items()]

        def on_running(request: httpx2.Request) -> httpx2.Response:
            self.paths.append("/running")
            if before_running is not None:
                before_running()
            if running_status != 200:
                return httpx2.Response(running_status, text="no")
            return httpx2.Response(200, json={"running": running})

        def on_events(request: httpx2.Request) -> httpx2.Response:
            self.paths.append("/api/events")
            data = json.dumps({"requests": [{"model": m} for m in inflight]})
            body = f"data: {json.dumps({'type': 'inflight', 'data': data})}\n\n"
            return httpx2.Response(200, content=body.encode("utf-8"))

        backend_mock.get(f"{LLAMASWAP}/running").mock(side_effect=on_running)
        backend_mock.get(f"{LLAMASWAP}/api/events").mock(side_effect=on_events)
        for model in (MECH, LONG, CODE):
            ago = (ended_ago or {}).get(model)

            def on_activity(request: httpx2.Request, ago=ago, model=model) -> httpx2.Response:
                self.paths.append(f"/api/metrics/activity {model}")
                if ago is None:
                    return httpx2.Response(200, json={"data": []})
                end = datetime.now(UTC) - timedelta(seconds=ago)
                stamp = end.isoformat(timespec="seconds")  # truncada al segundo, como v255
                return httpx2.Response(200, json={"data": [{"model": model, "timestamp": stamp}]})

            backend_mock.get(f"{LLAMASWAP}/api/metrics/activity?model={model}&limit=1").mock(
                side_effect=on_activity
            )
        return self


class _Thread(threading.Thread):
    def __init__(self, function: Callable, *args, **kwargs) -> None:
        super().__init__(daemon=True)
        self._call = (function, args, kwargs)
        self.result: object = None
        self.error: BaseException | None = None

    def run(self) -> None:
        function, args, kwargs = self._call
        try:
            self.result = function(*args, **kwargs)
        except BaseException as e:  # el test lo mira
            self.error = e


def _until(condition: Callable[[], object], cap: float = CAP_S) -> object:
    end = time.monotonic() + cap
    while time.monotonic() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.005)
    return None


def _hold(op_id: str, model: str) -> None:
    """Otra operación de este daemon con `model` ya elegido (en `activos`)."""
    server._topology()  # la relación de choques de la config entra en el turno
    server._turn.request(PendingRequest(op_id, frozenset({model}), model))


def _translate() -> str:
    return server.local_translate(target_lang="inglés", text="hola mundo")


# --- Escenario «la tarea mecánica usa el 26B cargado» -----------------------------------------


@backend_mock.mock
def test_mechanical_task_uses_loaded_26b(affinity, tmp_path):
    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10})

    out = _translate()

    line = _line(tmp_path, "local_translate")
    assert line.get("routing") == "affinity"
    assert line.get("model_requested") == MECH
    assert line.get("model") == LONG
    assert backend.served == [LONG]
    assert "aviso" not in out, "la afinidad no añade texto a la respuesta (REQ-016)"
    assert line.get("affinity_foreign_flight") == 0
    assert "affinity_failed" not in line
    assert server._accounting(line)["fallback"] is False, "el panel no la cuenta como respaldo"
    assert backend.paths[:2] == ["/running", "/api/events"], "orden de REQ-013"
    assert backend.paths[-1] == f"/api/metrics/activity {LONG}", "la actividad, la última"


@backend_mock.mock
def test_affinity_failed_when_first_call_waited_for_a_load(affinity, tmp_path, monkeypatch):
    """Sin vuelo ajeno y con espera de backend larga en la primera llamada (aquí el umbral se baja
    a 50 ms para no dormir 3 s): `affinity_failed`."""
    monkeypatch.setattr(server, "_AFFINITY_FAILED_WAIT_MS", 50)
    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10})

    def slow(model: str) -> httpx2.Response:
        time.sleep(0.1)
        timings = backend_mock.llama_timings(prompt_ms=1.0, predicted_ms=1.0)
        return backend_mock.chat_response(f"ok de {model}", timings=timings)

    backend.chat = slow
    _translate()

    line = _line(tmp_path, "local_translate")
    assert line.get("routing") == "affinity"
    assert line.get("affinity_failed") is True


# --- Escenarios del margen ------------------------------------------------------------------


@pytest.mark.parametrize(("ago", "expected"), [(117, MECH), (80, LONG)], ids=["3s", "40s"])
@backend_mock.mock
def test_loaded_with_little_ttl_left_is_not_used(affinity, ago, expected):
    """«Al cargado le quedan 3 s» → el 4B; «le quedan 40 s» → el 26B (TTL 120, margen 5 s)."""
    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: ago})

    _translate()

    model = backend.served[0]
    assert model == expected


@backend_mock.mock
def test_loaded_working_for_another_client_is_used(affinity, tmp_path):
    """Con una petición ajena en vuelo el reloj del TTL está congelado: cuenta como cargado,
    aunque su última petición terminada sea de hace más que el TTL."""
    backend = _Backend().install(ready={LONG: 120}, inflight=[LONG], ended_ago={LONG: 300})

    _translate()

    model = backend.served[0]
    assert model == LONG
    assert _line(tmp_path, "local_translate").get("affinity_foreign_flight") == 1


@backend_mock.mock
def test_pending_model_switch_of_another_client_blocks_affinity(affinity):
    """Hay en vuelo una petición para Qwen, que choca con el 26B y no está `ready`: otro cliente
    va a cambiar de modelo. No se usa el 26B."""
    backend = _Backend().install(ready={LONG: 120}, inflight=[CODE], ended_ago={LONG: 10})

    _translate()

    model = backend.served[0]
    assert model == MECH


# --- Escenario «una celda no aprobada no se usa» --------------------------------------------


@backend_mock.mock
def test_cell_outside_allowed_directions_is_not_used(affinity, tmp_path, monkeypatch):
    """`local_explain_code` (rol de código) → 26B no es una dirección de REQ-011. El prompt se
    simula para que la huella coincida: la guarda de direcciones es lo único que la para."""
    prompt = server._affinity_prompt

    def with_explain(tool: str) -> str | None:
        return "prompt de explain" if tool == "local_explain_code" else prompt(tool)

    monkeypatch.setattr(server, "_affinity_prompt", with_explain)
    cell = _cell(tmp_path, "local_explain_code", LONG, CODE)
    monkeypatch.setattr(matrix, "CELLS", (*matrix.CELLS, cell))
    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10})

    server.local_explain_code(code="x = 1")

    model = backend.served[0]
    assert model == CODE


# --- Escenario «la huella cambió» -----------------------------------------------------------


@backend_mock.mock
def test_changed_footprint_is_not_used_and_doctor_warns(affinity, tmp_path, monkeypatch):
    """Celda medida con `-ncmoe 12` (el valor real de hoy) y la config con `-ncmoe 16`."""
    path = _write_config(tmp_path, ncmoe=16)
    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10})

    _translate()

    model = backend.served[0]
    assert model == MECH
    result = checks._probe_residency(checks.Context(home=tmp_path, config_path=path))
    assert result.status == checks.WARN
    assert "n_cpu_moe 12 -> 16" in result.detail
    assert "`local_translate` → `gemma4-26b-a4b`" in result.detail


def test_doctor_quiet_when_footprint_matches(affinity, tmp_path):
    """Sin cambios, `doctor` no dice nada de la afinidad."""
    result = checks._probe_residency(checks.Context(home=tmp_path, config_path=affinity))
    assert result.status == checks.OK, result.detail
    assert "afinidad" not in result.detail


def test_doctor_other_machine_is_ok_and_says_affinity_is_inert(affinity, tmp_path, monkeypatch):
    """Celdas medidas en otra máquina (su GGUF no existe aquí): sin `[WARN]`, pero lo dice."""
    elsewhere = tmp_path / "no-existe" / "gemma-4-26B.gguf"
    cells = tuple(
        matrix.Cell(c.tool, c.alternative, c.compared_role, {**c.footprint, "ruta": str(elsewhere)})
        for c in matrix.CELLS
    )
    monkeypatch.setattr(matrix, "CELLS", cells)
    result = checks._probe_residency(checks.Context(home=tmp_path, config_path=affinity))
    assert result.status == checks.OK, result.detail
    assert "afinidad inerte aquí" in result.detail


def test_doctor_warns_with_another_gguf_under_the_id_here(affinity, tmp_path):
    """Otra cuantización del 26B en esta misma máquina, bajo el mismo id: `[WARN]` (REQ-010)."""
    other = tmp_path / "gemma-4-26B-otra-cuantizacion.gguf"
    other.write_bytes(b"y" * 40)
    path = _write_config(tmp_path, gguf_26b=other)
    result = checks._probe_residency(checks.Context(home=tmp_path, config_path=path))
    assert result.status == checks.WARN
    assert "otro GGUF bajo el id" in result.detail


def test_doctor_warns_when_the_mechanical_role_changes_by_variable(affinity, tmp_path, monkeypatch):
    """Otro modelo en el rol mecánico (variable de entorno): la afinidad se apaga y `doctor` lo
    dice (REQ-010)."""
    original = config.modelos_por_rol

    def other_roles():
        return {**original(), "mechanical": "otro-4b"}

    monkeypatch.setattr(config, "modelos_por_rol", other_roles)
    result = checks._probe_residency(checks.Context(home=tmp_path, config_path=affinity))
    assert result.status == checks.WARN
    assert "el modelo del rol es otro-4b" in result.detail


# --- Escenarios del turno de punta a punta (los mutantes de T8 en la integración) -------------


@backend_mock.mock
def test_affinity_does_not_jump_queue_end_to_end(affinity):
    """El 26B está en uso y alguien espera a Qwen: la traducción no se cuela con el 26B."""
    backend = _Backend().install()  # sin modelos cargados: al final responde el 4B
    _hold("other-26b", LONG)
    waiting = _Thread(server._turn.request, PendingRequest("w-qwen", frozenset({CODE}), CODE))
    waiting.start()
    assert _until(lambda: server._turn.snapshot().queued("w-qwen")), "Qwen no llegó a la cola"

    translation = _Thread(_translate)
    translation.start()
    _until(lambda: backend.served, cap=0.5)
    granted = backend.served[0] if backend.served else None

    server._turn.release_slot("other-26b")
    waiting.join(CAP_S)
    server._turn.release_slot("w-qwen")
    translation.join(CAP_S)
    assert granted is None


@backend_mock.mock
def test_affinity_joins_if_nobody_waits_end_to_end(affinity, tmp_path):
    """El 26B ya está en uso por el propio daemon y nadie espera: se une, sin consultar nada."""
    backend = _Backend().install()
    _hold("other-26b", LONG)

    translation = _Thread(_translate)
    translation.start()
    translation.join(CAP_S)
    served = list(backend.served)
    server._turn.release_slot("other-26b")
    translation.join(CAP_S)

    assert served == [LONG]
    assert backend.paths == [], "el 26B estaba en `propios`: sin foto"
    assert _line(tmp_path, "local_translate").get("routing") == "affinity"


@backend_mock.mock
def test_reserve_shrinks_and_queue_is_rechecked_end_to_end(affinity, monkeypatch):
    """Con dos celdas, la traducción recibe `{4B, 26B, Qwen}`; al elegir el 26B su reserva se
    reduce y la espera del 26B entra **mientras** la traducción sigue en su llamada. El tic se
    sube a 5 s: sin el aviso de la reducción, la espera no entraría hasta que la traducción
    acabara."""
    monkeypatch.setattr(
        server,
        "_turn",
        turn.Turn(lambda _a, _b: False, tick=5.0, on_tick=server._refresh_topology),
    )
    monkeypatch.setattr(server, "_turn_version", None)
    w2_granted = threading.Event()
    seen: dict[str, bool] = {}

    def w2_queued() -> None:
        _until(lambda: server._turn.snapshot().queued("w2"))

    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10}, before_running=w2_queued)

    def w1_chat(model: str) -> httpx2.Response:
        # ¿Entró W2 mientras W1 sigue en su llamada? Con el tic de 5 s, solo si lo avisó la reducción.
        seen["w2_entered_while_w1_calls"] = w2_granted.wait(2.0)
        return backend_mock.chat_response(f"ok de {model}")

    backend.chat = w1_chat

    def w2() -> None:
        server._turn.request(PendingRequest("w2", frozenset({LONG}), LONG))
        w2_granted.set()
        server._turn.release_slot("w2")

    w1 = _Thread(_translate)
    w1.start()
    assert _until(lambda: any(a.wait.request.role == MECH for a in server._turn.snapshot().actives))
    w2_thread = _Thread(w2)
    w2_thread.start()
    w1.join(8.0)
    w2_thread.join(8.0)

    assert backend.served == [LONG]
    w2_entered_while_w1_calls = seen.get("w2_entered_while_w1_calls")
    assert w2_entered_while_w1_calls is True


# --- `matrix` = `veredicto.json` (REQ-043) ----------------------------------------------------


def test_matrix_cells_are_the_approved_cells_of_the_verdict():
    verdict = json.loads(VERDICT.read_text(encoding="utf-8"))
    verdict_approved_cells = {
        (c["tool"], c["alternativo"], c["rol_comparado"])
        for c in verdict["celdas"]
        if c["estado"] == "aprobada"
    }
    code_cells = {(c.tool, c.alternative, c.compared_role) for c in matrix.CELLS}

    assert code_cells == verdict_approved_cells
    footprints = {
        (c["tool"], c["alternativo"], c["rol_comparado"]): c["huella"]
        for c in verdict["celdas"]
        if c["estado"] == "aprobada"
    }
    for cell in matrix.CELLS:
        assert dict(cell.footprint) == footprints[(cell.tool, cell.alternative, cell.compared_role)]
    assert len(matrix.CELLS) == len(code_cells), "una celda repetida"


def test_prompt_footprint_of_the_code_is_the_measured_one():
    """El prompt que `server` reconstruye para cada tool da el `sha256` que midió la evaluación:
    si cambia `_guard` o el texto de la tool, este test lo dice (y la celda queda sin base)."""
    import hashlib

    for cell in matrix.CELLS:
        prompt = server._affinity_prompt(cell.tool)
        assert prompt is not None
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        assert digest == cell.footprint["prompt_sha256"], cell.tool


# --- Camino feliz sin red ---------------------------------------------------------------------


@backend_mock.mock
def test_happy_path_role_in_own_queries_nothing(affinity, tmp_path, monkeypatch):
    """Con el 4B en `propios` (y el 26B también, así que la reserva trae los dos) se elige el rol
    sin ninguna consulta a llama-swap. Topología sin choques para que convivan."""
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(_write_config(tmp_path, separate=True)))
    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10})
    _hold("other-4b", MECH)
    _hold("other-26b", LONG)
    try:
        _translate()
    finally:
        server._turn.release_slot("other-4b")
        server._turn.release_slot("other-26b")

    requested_paths = backend.paths
    assert backend.served == [MECH]
    assert requested_paths == []


# --- Backend remoto o modelo explícito --------------------------------------------------------


@backend_mock.mock
def test_remote_backend_has_no_affinity(affinity, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_backend_en_loopback", lambda: False)
    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10})

    _translate()

    line = _line(tmp_path, "local_translate")
    assert line.get("routing") is None
    assert backend.served == [MECH]


@backend_mock.mock
def test_explicit_model_has_no_affinity(affinity, tmp_path):
    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10})

    server.local_delegate(task="mayúsculas", input="hola", output_format="texto", model=MECH)

    line = _line(tmp_path, "local_delegate")
    assert line.get("routing") is None
    assert backend.served == [MECH]


@backend_mock.mock
def test_delegate_without_model_uses_affinity(affinity, tmp_path):
    """`local_delegate` sin `model` es una tool del rol mecánico con celda aprobada."""
    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10})

    server.local_delegate(task="mayúsculas", input="hola", output_format="texto")

    assert _line(tmp_path, "local_delegate").get("routing") == "affinity"
    assert backend.served == [LONG]


# --- Fallo del alternativo (REQ-015) --------------------------------------------------------


@pytest.fixture
def attempts(monkeypatch) -> list:
    """Los `Intento` de cada `_con_respaldo`, en orden: las llamadas reales al backend."""
    seen: list = []
    original = server._con_respaldo

    def spy(*args, **kwargs):
        result = original(*args, **kwargs)
        seen.extend(result[2])
        return result

    monkeypatch.setattr(server, "_con_respaldo", spy)
    return seen


@backend_mock.mock
def test_alternative_failure_falls_back_to_role_first(affinity, attempts, tmp_path):
    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10})
    backend.chat = lambda model: (
        httpx2.Response(500, text="boom") if model == LONG else backend_mock.chat_response("ok")
    )

    out = _translate()

    seen = attempts
    assert seen[0].modelo == LONG
    assert seen[1].modelo == MECH
    assert "aviso" not in out, "respondió el modelo pedido"
    line = _line(tmp_path, "local_translate")
    assert line.get("model") == MECH
    assert line.get("routing") is None
    assert line.get("affinity_dropped") == LONG, "el evento dice que se probó el 26B"


# --- Miembros de `loaded` (REQ-019) -----------------------------------------------------------


@backend_mock.mock
def test_loaded_hop_picks_member_with_margin(affinity, attempts):
    """El 4B falla: el salto a `loaded` pide turno con los alternativos aprobados y elige al
    conceder, con la foto, el que está cargado con margen (Qwen, no el 26B)."""
    # El 4B también está cargado: la primera llamada va a él (paso 1 de REQ-012).
    backend = _Backend().install(ready={MECH: 120, CODE: 120}, ended_ago={CODE: 10})
    backend.chat = lambda model: (
        httpx2.Response(500, text="boom") if model == MECH else backend_mock.chat_response("ok")
    )

    _translate()

    assert [i.modelo for i in attempts] == [MECH, CODE]


@backend_mock.mock
def test_loaded_hop_without_member_with_margin_is_skipped_without_spending_hop(
    affinity, attempts, monkeypatch
):
    """Nada cargado: el paso `loaded` se salta sin gastar salto y sigue la cadena (`long`).

    Con un solo salto permitido: si el paso vacío lo gastara, no quedaría salto para `long`.
    """
    monkeypatch.setattr(config, "FALLBACK_MAX_HOPS", 1)
    backend = _Backend().install()
    backend.chat = lambda model: (
        httpx2.Response(500, text="boom") if model == MECH else backend_mock.chat_response("ok")
    )

    _translate()

    assert [i.modelo for i in attempts] == [MECH, LONG]


# --- `matrix.choose`, pura (REQ-012) ----------------------------------------------------------


def _observed(**kw) -> matrix.Observed:
    base = {"now": 1000.0, "margin_s": 5.0, "clashes": lambda a, b: a != b, "in_flight": {}}
    return matrix.Observed(**{**base, **kw})


def test_choose_prefers_role_when_it_is_ready():
    observed = _observed(ready=frozenset({MECH, LONG}), ttl={MECH: 120, LONG: 0})
    pick = matrix.choose({MECH, LONG}, MECH, observed, (), approved={LONG})
    assert pick == MECH


def test_choose_tie_break_in_flight_then_ttl_then_chain_then_id():
    ready = frozenset({LONG, CODE})
    # Con una petición en vuelo gana aunque el otro tenga más TTL.
    busy = _observed(ready=ready, ttl={LONG: 0, CODE: 120}, in_flight={CODE: 1})
    assert matrix.choose({MECH, LONG, CODE}, MECH, busy, (), approved={LONG, CODE}) == CODE
    # Sin vuelo, más TTL restante (`ttl: 0` es infinito).
    ttl = _observed(ready=ready, ttl={LONG: 0, CODE: 120}, last_end={CODE: 990.0})
    assert matrix.choose({MECH, LONG, CODE}, MECH, ttl, (), approved={LONG, CODE}) == LONG
    # Empate de TTL: el orden de la cadena.
    tie = _observed(ready=ready, ttl={LONG: 0, CODE: 0})
    pick = matrix.choose(
        {MECH, LONG, CODE}, MECH, tie, (), approved={LONG, CODE}, chain_order=(CODE, LONG)
    )
    assert pick == CODE
    # Sin cadena: el id.
    assert matrix.choose({MECH, LONG, CODE}, MECH, tie, (), approved={LONG, CODE}) == LONG


def test_choose_loaded_hop_without_member_returns_none():
    """El rol no está en `A'` (salto a `loaded`) y ningún miembro cumple: `None`."""
    observed = _observed()
    assert matrix.choose({LONG, CODE}, MECH, observed, (), approved={LONG, CODE}) is None


def test_missing_in_flight_photo_means_not_loaded():
    observed = _observed(ready=frozenset({LONG}), ttl={LONG: 0}, in_flight=None)
    assert not observed.loaded_with_margin(LONG)


def test_direction_guard():
    roles = {"mechanical": MECH, "long": LONG, "code": CODE}
    fp: dict = {}
    assert matrix.allowed_direction(
        matrix.Cell("local_translate", LONG, MECH, fp), "mechanical", roles
    )
    # La misma tool usada en el rol largo (entrada grande) no tiene dirección.
    assert not matrix.allowed_direction(
        matrix.Cell("local_translate", CODE, MECH, fp), "long", roles
    )
    # Nunca hacia el mecánico, ni desde una tool de código o de largo.
    assert not matrix.allowed_direction(
        matrix.Cell("local_commit_msg", MECH, CODE, fp), "code", roles
    )
    assert not matrix.allowed_direction(
        matrix.Cell("local_summarize", LONG, MECH, fp), "mechanical", roles
    )
    assert matrix.allowed_direction(matrix.Cell("local_commit_msg", LONG, CODE, fp), "code", roles)
    # Otro modelo en el rol mecánico (por variable): la celda medida contra el 4B ya no vale.
    other = {**roles, "mechanical": "otro-4b"}
    assert not matrix.allowed_direction(
        matrix.Cell("local_translate", LONG, MECH, fp), "mechanical", other
    )


# --- Revisión de la ola 9 -----------------------------------------------------------------------


@backend_mock.mock
def test_reason_after_affinity_failure_is_the_real_one_chunked(affinity, attempts, tmp_path):
    """Hallazgo 1: el 26B (afinidad) da 500, el 4B da 500 y responde Qwen por `loaded`. El motivo
    es el 500 del primer intento, no un «en enfriamiento» inventado."""
    backend = _Backend().install(ready={LONG: 120, CODE: 120}, ended_ago={LONG: 10, CODE: 50})
    backend.chat = lambda model: (
        backend_mock.chat_response("ok de qwen")
        if model == CODE
        else httpx2.Response(500, text=f"boom de {model}")
    )

    out = _translate()

    assert [i.modelo for i in attempts] == [LONG, MECH, CODE]
    line = _line(tmp_path, "local_translate")
    assert line.get("fallback_class") == "modelo"
    assert line.get("fallback_reason") == "http_500"
    assert "enfriamiento" not in out


@backend_mock.mock
def test_reason_after_affinity_failure_is_the_real_one_single_call(
    affinity, attempts, tmp_path, monkeypatch
):
    """Lo mismo por `_chat` (una llamada): `local_delegate` con una segunda celda, la de Qwen."""
    monkeypatch.setattr(
        matrix, "CELLS", (*matrix.CELLS, _cell(tmp_path, "local_delegate", CODE, MECH))
    )
    backend = _Backend().install(ready={LONG: 120, CODE: 120}, ended_ago={LONG: 10, CODE: 50})
    backend.chat = lambda model: (
        backend_mock.chat_response("ok de qwen")
        if model == CODE
        else httpx2.Response(500, text=f"boom de {model}")
    )

    out = server.local_delegate(task="mayúsculas", input="hola", output_format="texto")

    assert [i.modelo for i in attempts] == [LONG, MECH, CODE]
    line = _line(tmp_path, "local_delegate")
    assert line.get("fallback_class") == "modelo"
    assert "enfriamiento" not in out


@backend_mock.mock
def test_affinity_failed_not_written_with_foreign_flight(affinity, tmp_path, monkeypatch):
    """Hallazgo 4: con una petición ajena en vuelo la espera puede ser de cola: no se escribe."""
    monkeypatch.setattr(server, "_AFFINITY_FAILED_WAIT_MS", 50)
    backend = _Backend().install(ready={LONG: 120}, inflight=[LONG], ended_ago={LONG: 10})

    def slow(model: str) -> httpx2.Response:
        time.sleep(0.1)
        timings = backend_mock.llama_timings(prompt_ms=1.0, predicted_ms=1.0)
        return backend_mock.chat_response(f"ok de {model}", timings=timings)

    backend.chat = slow
    _translate()

    line = _line(tmp_path, "local_translate")
    assert line.get("affinity_foreign_flight") == 1
    assert "affinity_failed" not in line


@backend_mock.mock
def test_foreign_flight_subtracts_own_requests_in_flight_not_operations(
    affinity, tmp_path, monkeypatch
):
    """Hallazgo 5: otra operación propia con el 26B elegido pero entre dos llamadas (sin petición
    en vuelo) no se descuenta: la petición en vuelo de la foto es de otro cliente."""
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(_write_config(tmp_path, separate=True)))
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(server, "_chat_slots", slots)
    backend = _Backend().install(ready={LONG: 120}, inflight=[LONG], ended_ago={LONG: 10})
    slots.acquire()  # la traducción obtiene turno (con `A'` = todo) y espera plaza
    translation = _Thread(_translate)
    translation.start()
    try:
        assert _until(
            lambda: any(a.wait.request.role == MECH for a in server._turn.snapshot().actives)
        )
        _hold("other-26b", LONG)  # propia, con el 26B elegido, sin llamada en vuelo
    finally:
        slots.release()
    translation.join(CAP_S)
    server._turn.release_slot("other-26b")

    assert backend.served == [LONG]
    assert _line(tmp_path, "local_translate").get("affinity_foreign_flight") == 1


_FAILS_400 = '{"error": "bad request"}'


@pytest.mark.parametrize("tool", ["local_delegate", "local_translate"])
@backend_mock.mock
def test_failed_affinity_operation_logs_the_alternative(affinity, tmp_path, tool):
    """Hallazgo 6: si la operación falla con la afinidad vigente (una clase que no salta), el
    `model` del evento es el alternativo que falló, igual por `_chat` y por trozos."""
    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10})
    backend.chat = lambda model: httpx2.Response(400, text=_FAILS_400)

    if tool == "local_delegate":
        server.local_delegate(task="mayúsculas", input="hola", output_format="texto")
    else:
        _translate()

    line = _line(tmp_path, tool)
    assert backend.served == [LONG], "un 400 no salta"
    assert line.get("ok") is False
    assert line.get("model") == LONG
    assert line.get("model_requested") == MECH
    assert line.get("routing") == "affinity"


@backend_mock.mock
def test_chunked_affinity_then_role_leaves_a_trace(affinity, tmp_path):
    """Hallazgo 7: el trozo 1 lo responde el 26B y en el trozo 2 se salta al rol. El evento no es
    `routing: "affinity"`, pero dice que el 26B se probó (`affinity_dropped`)."""
    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10})
    calls = {LONG: 0}

    def chat(model: str) -> httpx2.Response:
        if model == LONG:
            calls[LONG] += 1
            if calls[LONG] > 1:
                return httpx2.Response(500, text="boom")
        return backend_mock.chat_response(f"ok de {model}")

    backend.chat = chat
    text = "\n\n".join(("palabra " * 250).strip() for _ in range(2))  # 2 trozos, rol mecánico
    server.local_translate(target_lang="inglés", text=text)

    assert backend.served == [LONG, LONG, MECH]
    line = _line(tmp_path, "local_translate")
    assert line.get("routing") is None
    assert line.get("affinity_dropped") == LONG


_EXCLUSIVE_4B = [
    "  m:",
    "    swap: true",
    "    exclusive: true",
    f"    members: [{MECH}]",
    "  l:",
    "    swap: true",
    "    exclusive: false",
    f"    members: [{LONG}]",
    "  c:",
    "    swap: true",
    "    exclusive: false",
    f"    members: [{CODE}]",
]


@backend_mock.mock
def test_affinity_without_model_at_choice_goes_to_role(affinity, tmp_path, monkeypatch):
    """Hallazgo 8: `A'` con dos alternativos y sin el rol (el 4B, exclusivo, choca con los dos; 26B
    y Qwen conviven). Al elegir ya no están en uso y la foto falla (401): la operación va al rol,
    sin `AssertionError` ni error."""
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(_write_config(tmp_path, groups=_EXCLUSIVE_4B)))
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(server, "_chat_slots", slots)
    backend = _Backend().install(running_status=401)
    _hold("other-26b", LONG)
    _hold("other-qwen", CODE)
    slots.acquire()
    translation = _Thread(_translate)
    translation.start()
    try:
        granted = _until(
            lambda: any(a.wait.request.role == MECH for a in server._turn.snapshot().actives)
        )
        assert granted, "la traducción no obtuvo turno con los dos alternativos"
        mine = next(a for a in server._turn.snapshot().actives if a.wait.request.role == MECH)
        assert mine.reserve == {LONG, CODE}
        server._turn.release_slot("other-26b")
        server._turn.release_slot("other-qwen")
    finally:
        slots.release()
    translation.join(CAP_S)

    assert translation.error is None
    assert backend.served == [MECH]


@backend_mock.mock
def test_snapshot_queries_are_capped_at_one_second(affinity, monkeypatch):
    """Hallazgo 9: cada consulta de la foto, conexión incluida, con tope de 1 s (REQ-004)."""
    from local_delegate import llamaswap_api

    seen: list[tuple[float, float]] = []
    original = llamaswap_api._client

    def spy(read: float = llamaswap_api.READ_S, connect: float = llamaswap_api.CONNECT_S):
        seen.append((read, connect))
        return original(read, connect)

    monkeypatch.setattr(llamaswap_api, "_client", spy)
    _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10})

    _translate()

    assert len(seen) == 3, seen  # running, events, activity
    assert all(caps == (1.0, 1.0) for caps in seen), seen


def test_observed_uses_the_real_id_for_every_lookup():
    """Hallazgo 10: con un alias, `ready`, `ttl`, `in_flight` y `last_end` van por el id real."""
    observed = _observed(
        ready=frozenset({"real-26b"}),
        ttl={"real-26b": 120},
        last_end={"real-26b": 990.0},
        alias={"alias-26b": "real-26b"},
    )
    assert observed.loaded_with_margin("alias-26b")
    assert observed.ttl_left("alias-26b") == 110.0


def test_real_loaded_provider_stays_registered():
    """Hallazgo 12: los tests que ponen otro proveedor devuelven el anterior, no `None`. Sin
    fixture: si un test de antes lo dejó quitado, aquí se ve."""
    assert cadenas._loaded_provider is server._affinity_loaded_provider


# --- Decisión del usuario (2026-10-07): capacidad del alternativo de la afinidad -------------

_CAPACITY = '{"error":{"message":"unspecific error: upstream command exited prematurely"}}'


@backend_mock.mock
def test_capacity_failure_of_affinity_alternative_goes_to_role(affinity, attempts, tmp_path):
    """El 26B elegido por afinidad falla por capacidad: se prueba el rol (REQ-015), aunque
    REQ-021 no deje saltar a un fallo de capacidad. La afinidad la eligió el daemon."""
    backend = _Backend().install(ready={LONG: 120}, ended_ago={LONG: 10})
    backend.chat = lambda model: (
        httpx2.Response(500, text=_CAPACITY) if model == LONG else backend_mock.chat_response("ok")
    )

    out = _translate()

    assert attempts[0].clase == "capacidad_o_carga", "guarda: el 26B falló por capacidad"
    responded = backend.served[-1]
    assert responded == MECH
    line = _line(tmp_path, "local_translate")
    assert line.get("model") == MECH
    assert line.get("affinity_dropped") == LONG
    assert line.get("affinity_dropped_class") == "capacidad_o_carga"
    assert "aviso" not in out


@backend_mock.mock
def test_capacity_failure_without_affinity_still_does_not_hop(affinity, monkeypatch):
    """Fuera de la afinidad, REQ-021 sigue igual: el 4B falla por capacidad y, sin `loaded`, no
    salta (ni a `long`)."""
    monkeypatch.setattr(matrix, "CELLS", ())
    backend = _Backend().install()
    backend.chat = lambda model: (
        httpx2.Response(500, text=_CAPACITY) if model == MECH else backend_mock.chat_response("ok")
    )

    out = _translate()

    assert backend.served == [MECH]
    assert out.startswith("[local-delegate error]")
