"""Tarea 26 de F3: el estado de enfriamiento compartido entre procesos (REQ-009 a REQ-012).

Todo con reloj inyectable: ningún test espera de verdad 120 s. «Dos procesos» son dos instancias de
`CooldownState` sobre el mismo fichero, que es lo que ven el daemon y un proceso stdio de la misma máquina.

Defectos de la spec que se fijan aquí, no se reinterpretan en cada consumidor:
- cuentan solo los fallos del modelo y los timeouts con el modelo cargado (tabla de F3);
- capacidad y configuración son neutras como el endpoint, la petición y lo sin clasificar: ni suman
  ni ponen a cero (decisión del plan, tarea 26);
- tras vencer, basta UN fallo para volver a enfriar, con la espera doblada y tope en Tmax (REQ-010).
"""

from __future__ import annotations

import json

import pytest

from local_delegate import cooldown
from local_delegate.failures import FailureClass

START = 1_800_000_000.0


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def path(tmp_path):
    return tmp_path / "cooldown.json"


def _state(path, clock, **options) -> cooldown.CooldownState:
    params = {"failures": 3, "wait_s": 120.0, "max_wait_s": 900.0, "enabled": True}
    params.update(options)
    return cooldown.CooldownState(path, clock=clock, **params)


def _fail(
    state: cooldown.CooldownState, model: str, times: int, failure_class=FailureClass.MODEL
) -> None:
    for _ in range(times):
        state.record_failure(model, failure_class)


# --- REQ-009: N fallos seguidos enfrían -------------------------------------------------------


def test_three_consecutive_failures_cool_the_model_for_120_s(path, clock):
    state = _state(path, clock)
    _fail(state, "m", 3)
    cooled = state.lookup("m")
    assert cooled is not None
    assert cooled.remaining_s == pytest.approx(120.0)
    assert cooled.reentries == 1


def test_the_cooldown_remembers_when_the_streak_started(path, clock):
    state = _state(path, clock)
    _fail(state, "m", 1)
    clock.advance(30)
    _fail(state, "m", 2)
    cooled = state.lookup("m")
    assert cooled is not None and cooled.since == START


def test_two_failures_do_not_cool(path, clock):
    """Control positivo del anterior: el umbral es N, no «cualquier fallo»."""
    state = _state(path, clock)
    _fail(state, "m", 2)
    assert state.lookup("m") is None


def test_failures_from_two_processes_add_up(path, clock):
    """REQ-009 y REQ-012: el daemon y un proceso stdio ven el mismo contador."""
    daemon = _state(path, clock)
    stdio = _state(path, clock)
    _fail(daemon, "m", 2)
    _fail(stdio, "m", 1)
    assert daemon.lookup("m") is not None
    assert stdio.lookup("m") is not None


def test_the_timeout_with_the_model_loaded_also_counts(path, clock):
    state = _state(path, clock)
    _fail(state, "m", 3, failure_class=FailureClass.READ_TIMEOUT)
    assert state.lookup("m") is not None


def test_each_model_keeps_its_own_counter(path, clock):
    state = _state(path, clock)
    _fail(state, "a", 2)
    _fail(state, "b", 2)
    assert state.lookup("a") is None
    assert state.lookup("b") is None


# --- REQ-011: el éxito pone a cero y las clases neutras no tocan nada ---------------------------


def test_a_success_resets_the_counter_to_zero(path, clock):
    state = _state(path, clock)
    _fail(state, "m", 2)
    state.record_success("m")
    _fail(state, "m", 2)
    assert state.lookup("m") is None


@pytest.mark.parametrize(
    "neutral",
    [
        FailureClass.ENDPOINT,
        FailureClass.REQUEST,
        FailureClass.UNCLASSIFIED,
        FailureClass.CAPACITY,
        FailureClass.CONFIGURATION,
    ],
)
def test_neutral_classes_neither_add_nor_reset(path, clock, neutral):
    state = _state(path, clock)
    _fail(state, "m", 2)
    _fail(state, "m", 5, failure_class=neutral)  # no suman...
    assert state.lookup("m") is None
    _fail(state, "m", 1)  # ...ni han puesto a cero: este es el tercero que cuenta
    assert state.lookup("m") is not None


# --- REQ-010: vencimiento, prueba y espera doblada ----------------------------------------------


def test_once_the_cooldown_expires_the_model_receives_again(path, clock):
    state = _state(path, clock)
    _fail(state, "m", 3)
    clock.advance(120.1)
    assert state.lookup("m") is None


def test_expired_and_a_success_leaves_the_model_clean(path, clock):
    state = _state(path, clock)
    _fail(state, "m", 3)
    clock.advance(121)
    state.record_success("m")
    assert state.active() == {}
    _fail(state, "m", 2)
    assert state.lookup("m") is None, "el contador no volvió a cero"
    _fail(state, "m", 1)
    assert state.lookup("m").remaining_s == pytest.approx(120.0), "la espera no volvió a la base"


def test_expired_and_a_single_failure_cools_again_with_the_wait_doubled(path, clock):
    state = _state(path, clock)
    _fail(state, "m", 3)
    clock.advance(121)
    _fail(state, "m", 1)
    cooled = state.lookup("m")
    assert cooled is not None, "tras vencer tiene que bastar UN fallo"
    assert cooled.remaining_s == pytest.approx(240.0)
    assert cooled.reentries == 2


def test_the_wait_never_exceeds_tmax(path, clock):
    state = _state(path, clock)
    _fail(state, "m", 3)
    waits = []
    for _ in range(8):
        clock.advance(1000)
        _fail(state, "m", 1)
        waits.append(state.lookup("m").remaining_s)
    assert waits[:3] == [pytest.approx(240.0), pytest.approx(480.0), pytest.approx(900.0)]
    assert max(waits) == pytest.approx(900.0)
    # Lo que de verdad importa del tope: pasados Tmax segundos, el modelo QUEDA LIBRE. Mirar solo el
    # restante no basta: la lectura lo recorta y tapaba una espera guardada sin límite (mutante vivo).
    clock.advance(900.1)
    assert state.lookup("m") is None, "pasado Tmax el modelo sigue enfriado"


def test_the_stored_wait_does_not_exceed_tmax_either(path, clock):
    state = _state(path, clock)
    _fail(state, "m", 3)
    for _ in range(8):
        clock.advance(1000)
        _fail(state, "m", 1)
    entry = json.loads(path.read_text(encoding="utf-8"))["m"]
    assert entry["wait_s"] <= 900.0
    assert entry["until"] - clock.now <= 900.0


def test_an_expiry_in_the_far_future_is_clipped_to_tmax(path, clock):
    """Un cambio de hora puede dejar un `until` absurdo: ningún enfriamiento es permanente."""
    path.write_text(
        json.dumps({"m": {"failures": 0, "wait_s": 120.0, "until": START + 10**7, "reentries": 1}}),
        encoding="utf-8",
    )
    state = _state(path, clock)
    cooled = state.lookup("m")
    assert cooled is not None
    assert cooled.remaining_s <= 900.0
    # Y VENCE: recortar contra «ahora» en cada lectura dejaba siempre 900 s por delante, o sea un
    # enfriamiento permanente, justo lo que la spec prohíbe.
    clock.advance(900.1)
    assert state.lookup("m") is None, "el vencimiento lejano no vence nunca"


# --- REQ-012: el estado ilegible nunca bloquea ni falla -----------------------------------------


def test_a_corrupt_file_reads_as_no_cooldown(path, clock):
    path.write_text("{esto no es json", encoding="utf-8")
    state = _state(path, clock)
    assert state.lookup("m") is None
    _fail(state, "m", 3)  # no lanza
    assert state.lookup("m") is not None, "tras un fichero corrupto se vuelve a escribir bien"


def test_a_busy_lock_neither_blocks_nor_fails(path, clock, monkeypatch):
    class BusyLock:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            raise cooldown.Timeout(str(path))

        def __exit__(self, *_exc) -> None:
            return None

    state = _state(path, clock)
    _fail(state, "m", 3)
    monkeypatch.setattr(cooldown, "FileLock", BusyLock)
    assert state.lookup("m") is None, "sin el bloqueo se sigue como si no hubiera enfriamiento"
    _fail(state, "otro", 3)  # no lanza


def test_the_file_only_stores_counters_and_dates(path, clock):
    """Privacidad (spec, no funcionales): nombres de modelo, contadores y fechas; nunca contenido."""
    state = _state(path, clock)
    _fail(state, "m", 3)
    _fail(state, "n", 1)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"m", "n"}
    for entry in data.values():
        assert set(entry) == {"failures", "wait_s", "until", "reentries", "since"}
        assert all(value is None or isinstance(value, (int, float)) for value in entry.values())


# --- REQ-014: apagado ---------------------------------------------------------------------------


def test_disabled_neither_records_nor_cools(path, clock):
    state = _state(path, clock, enabled=False)
    _fail(state, "m", 10)
    assert state.lookup("m") is None
    assert not path.exists(), "apagado no debe ni tocar el fichero"
    assert not (path.parent / cooldown.EVENTS_FILE).exists(), "ni el de episodios"


# --- Tarea 30: los episodios, que el criterio de P-4 cuenta y el fichero de estado no guarda -----


def _events(path) -> list[dict]:
    dest = path.parent / cooldown.EVENTS_FILE
    if not dest.exists():
        return []
    return [json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines()]


def test_entering_leaves_an_event_with_the_class_that_triggered_it(path, clock):
    state = _state(path, clock)
    _fail(state, "m", 2)
    assert _events(path) == [], "un fallo por debajo de N no es un episodio"
    _fail(state, "m", 1, failure_class=FailureClass.READ_TIMEOUT)
    (event,) = _events(path)
    assert event["event"] == "enter"
    assert event["model"] == "m"
    assert event["class"] == "read_timeout"
    assert event["reentries"] == 1
    assert event["wait_s"] == pytest.approx(120.0)
    assert event["ts"].startswith("2027-01-15T08:00:00")


def test_reentering_after_expiry_leaves_its_event_with_the_wait_doubled(path, clock):
    state = _state(path, clock)
    _fail(state, "m", 3)
    clock.advance(121)
    _fail(state, "m", 1)
    assert [e["event"] for e in _events(path)] == ["enter", "reenter"]
    reentry = _events(path)[1]
    assert reentry["reentries"] == 2
    assert reentry["wait_s"] == pytest.approx(240.0)


def test_failures_during_the_cooldown_leave_no_event(path, clock):
    """Solo le llegan llamadas con `model` explicito (REQ-005): no abren ni alargan un episodio."""
    state = _state(path, clock)
    _fail(state, "m", 3)
    _fail(state, "m", 4)
    assert [e["event"] for e in _events(path)] == ["enter"]


def test_success_after_expiry_closes_the_episode_as_recovered(path, clock):
    state = _state(path, clock)
    _fail(state, "m", 3)
    clock.advance(121)
    state.record_success("m")
    clean = _events(path)[-1]
    assert clean["event"] == "clear"
    assert clean["after_expiry"] is True
    assert clean["reentries"] == 1


def test_success_before_expiry_is_told_apart(path, clock):
    """Un exito durante el enfriamiento solo puede venir de `model` explicito: no es una prueba
    tras vencer, y el criterio no debe contarlo como recuperacion."""
    state = _state(path, clock)
    _fail(state, "m", 3)
    clock.advance(10)
    state.record_success("m")
    assert _events(path)[-1]["after_expiry"] is False


def test_success_of_a_model_with_scattered_failures_is_not_an_episode(path, clock):
    """Control positivo de los dos anteriores: limpiar un contador no es cerrar un enfriamiento."""
    state = _state(path, clock)
    _fail(state, "m", 2)
    state.record_success("m")
    state.record_success("otro")
    assert _events(path) == []


def test_events_from_two_processes_go_to_the_same_file(path, clock):
    daemon = _state(path, clock)
    stdio = _state(path, clock)
    _fail(daemon, "m", 2)
    _fail(stdio, "m", 1)
    clock.advance(121)
    daemon.record_success("m")
    assert [e["event"] for e in _events(path)] == ["enter", "clear"]


def test_the_episodes_file_only_stores_names_counters_and_dates(path, clock):
    state = _state(path, clock)
    _fail(state, "m", 3)
    clock.advance(121)
    _fail(state, "m", 1)
    clock.advance(241)
    state.record_success("m")
    allowed = {"ts", "model", "event", "class", "reentries", "wait_s", "after_expiry"}
    events = _events(path)
    assert len(events) == 3
    for event in events:
        assert set(event) <= allowed
        assert event["event"] in {"enter", "reenter", "clear"}


def test_without_disk_for_the_episodes_the_cooldown_goes_on(path, clock, monkeypatch):
    """REQ-012 tambien para el registro: que no se pueda escribir no hace fallar ni deshace nada."""

    def without_disk(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(cooldown, "_append_lines", without_disk)
    state = _state(path, clock)
    _fail(state, "m", 3)  # no lanza
    assert state.lookup("m") is not None


# --- Ola A4 del renombrado: `cooldown.json` y la lectura dual de `enfriamiento.json` -------------
#
# REQ-006 (english-names-bilingual-output): se lee `cooldown.json` y, si no existe,
# `enfriamiento.json` traducido; gana el nuevo. La escritura doble se retiró en la 0.38.0
# (REQ-006 de retire-legacy-aliases): el daemon solo escribe `cooldown.json`.


def _new(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_daemon_never_writes_the_old_file(path, clock):
    """Tras entrar, reentrar y limpiar existe `cooldown.json` y nunca `enfriamiento.json`."""
    old_file = path.with_name("enfriamiento.json")
    state = _state(path, clock)
    _fail(state, "m", 3)
    assert _new(path)["m"]["until"] is not None, "tras entrar"
    assert not old_file.exists(), "tras entrar"
    clock.advance(121)
    _fail(state, "m", 1)
    assert _new(path)["m"]["reentries"] == 2, "tras reentrar"
    assert not old_file.exists(), "tras reentrar"
    clock.advance(241)
    state.record_success("m")
    assert path.exists() and _new(path) == {}, "tras limpiar"
    assert not old_file.exists(), "tras limpiar"
    assert [e["event"] for e in _events(path)] == ["enter", "reenter", "clear"]


def test_an_existing_old_file_is_neither_deleted_nor_modified(path, clock):
    old_file = path.with_name("enfriamiento.json")
    # Con sangría y salto final: cualquier reescritura, aunque dijera lo mismo, cambiaría los bytes.
    old_file.write_text(
        json.dumps(
            {"m": {"fallos": 0, "espera_s": 120.0, "hasta": START + 60, "reentradas": 1}}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    before = old_file.read_bytes()
    state = _state(path, clock)
    _fail(state, "n", 3)
    clock.advance(121)
    _fail(state, "n", 1)
    clock.advance(241)
    state.record_success("n")
    assert path.exists(), "el estado nuevo no se escribió"
    assert old_file.read_bytes() == before


def test_an_old_state_from_a_previous_daemon_is_read_if_there_is_no_new_one(path, clock):
    path.with_name("enfriamiento.json").write_text(
        json.dumps({"m": {"fallos": 0, "espera_s": 120.0, "hasta": START + 60, "reentradas": 1}}),
        encoding="utf-8",
    )
    state = _state(path, clock)
    cooled = state.lookup("m")
    assert cooled is not None, "el estado viejo no se leyó"
    assert cooled.remaining_s == pytest.approx(60.0)
    # Y la siguiente escritura parte de él: el nuevo nace con el modelo enfriado, en claves nuevas.
    _fail(state, "n", 1)
    assert _new(path)["m"]["until"] == pytest.approx(START + 60)
    assert set(_new(path)["m"]) == {"failures", "wait_s", "until", "reentries"}


def test_with_both_files_the_new_one_wins(path, clock):
    path.with_name("enfriamiento.json").write_text(
        json.dumps({"m": {"fallos": 0, "espera_s": 120.0, "hasta": START + 60, "reentradas": 1}}),
        encoding="utf-8",
    )
    path.write_text("{}", encoding="utf-8")
    assert _state(path, clock).lookup("m") is None


def test_from_config_writes_cooldown_json_and_the_new_log(tmp_path, monkeypatch):
    from local_delegate import config

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "COOLDOWN", True)
    monkeypatch.setattr(config, "COOLDOWN_FAILURES", 1)
    cooldown.from_config().record_failure("m", FailureClass.MODEL)
    assert (tmp_path / "cooldown.json").exists()
    assert not (tmp_path / "enfriamiento.json").exists()
    assert (tmp_path / "cooldown-events.jsonl").exists()
    assert not (tmp_path / "enfriamiento-eventos.jsonl").exists()


# --- La copia de los hooks: lee los dos ficheros (gana `cooldown.json`) --------------------------


@pytest.fixture
def hook(tmp_path, monkeypatch):
    from local_delegate.resources.hooks import hook_common

    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path))
    return hook_common


def _write(path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_the_new_hook_sees_the_model_cooled_by_an_old_daemon(hook, tmp_path):
    import time

    _write(tmp_path / "enfriamiento.json", {"m": {"hasta": time.time() + 60}})
    assert hook.cooled_model("m")


def test_the_new_hook_reads_cooldown_json_and_there_the_new_one_wins(hook, tmp_path):
    import time

    _write(tmp_path / "cooldown.json", {"m": {"until": time.time() + 60}})
    assert hook.cooled_model("m")
    _write(tmp_path / "enfriamiento.json", {"n": {"hasta": time.time() + 60}})
    assert not hook.cooled_model("n"), "con cooldown.json presente no se mira el viejo"


def test_the_hook_reads_what_the_daemon_writes(hook, tmp_path, clock):
    import time

    clock.now = time.time()
    _fail(_state(tmp_path / "cooldown.json", clock), "m", 3)
    assert hook.cooled_model("m")
    assert not hook.cooled_model("otro")


def test_the_hook_key_table_is_the_package_one():
    from local_delegate import legacy_names
    from local_delegate.resources.hooks import hook_common

    assert hook_common.COOLDOWN_STATE_KEYS == legacy_names.FORMATS["cooldown_state"]["keys"]
    assert hook_common.FILE_NAMES["cooldown_state"] == legacy_names.FILE_NAMES["cooldown_state"]
