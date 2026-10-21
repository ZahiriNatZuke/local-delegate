"""Enfriamiento por modelo, compartido entre procesos (F3: REQ-009 a REQ-012).

Un modelo que acumula N fallos seguidos de las clases que cuentan deja de recibir peticiones durante
T segundos. Al vencer vuelve a recibir: el primer éxito lo deja limpio y el primer fallo que cuente
lo enfría otra vez con la espera doblada, hasta Tmax. Ningún enfriamiento es permanente.

El estado vive en un fichero (`LOG_DIR/cooldown.json`) para que el daemon y cualquier proceso
stdio de la misma máquina vean el mismo contador y para que sobreviva a un reinicio. Se lee y se
escribe bajo bloqueo, y **si el fichero no se puede leer o el bloqueo no llega a tiempo, se sigue
como si no hubiera enfriamiento**: este módulo nunca bloquea ni hace fallar una delegación.

Hasta la 0.34.0 el fichero se llamaba `enfriamiento.json` y sus claves iban en español. Se lee el
nuevo y, si no existe, el viejo traducido (REQ-006: gana el nuevo). Solo se escribe el nuevo:
desde la 0.38.0 el daemon ya no deja una copia en `enfriamiento.json`, y uno que ya exista no se
borra ni se modifica.

Solo guarda nombres de modelo, contadores y fechas. Nunca prompts, rutas ni contenido.

Además del estado, cada transición deja una línea en `cooldown-events.jsonl`: `enter`, `reenter`
y `clear` (antes `enfriamiento-eventos.jsonl`, con `entra`, `reentra` y `limpia`; ese fichero ya
no se escribe, pero `scripts/measure_cooldown.py` lo sigue leyendo). El estado solo guarda el
presente y el primer éxito lo borra, así que sin ese registro nadie podría contar después cuántos
episodios hubo ni cómo acabaron, que es lo que decide el criterio de P-4 (tarea 30).

Este módulo decide el estado; quién lo consulta y qué hace con él (saltar al respaldo, fallar al
momento) es de la tarea 28.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock, Timeout

from . import config, legacy_names
from .failures import FailureClass
from .json_state import read_json, write_json_atomic

#: Las clases que suman para el enfriamiento (tabla de F3). El resto son neutras: ni suman ni ponen
#: a cero. Capacidad y configuración incluidas (plan, tarea 26): no dicen nada de si el modelo
#: responde bien cuando se le deja.
COUNTING_CLASSES = frozenset({FailureClass.MODEL, FailureClass.READ_TIMEOUT})

#: Cuánto se espera al bloqueo del fichero antes de seguir sin enfriamiento, como `inflight.json`.
LOCK_WAIT_S = 2.0

#: El fichero de estado y su nombre viejo, que solo se lee (lectura dual) si el nuevo no existe.
LEGACY_STATE_FILE, STATE_FILE = legacy_names.FILE_NAMES["cooldown_state"]

#: El registro de episodios, junto al fichero de estado. Lo lee `scripts/measure_cooldown.py`,
#: que lee también el viejo.
LEGACY_EVENTS_FILE, EVENTS_FILE = legacy_names.COOLDOWN_EVENTS_FILE_NAMES


def _append_lines(path: Path, events: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(event, ensure_ascii=False) + "\n" for event in events)


def _event_row(now: float, model: str, kind: str, entry: dict, extra: dict) -> dict:
    """Una línea del registro: nombre de modelo, contadores y fechas, como el estado.

    `extra` va como diccionario y no como argumentos con nombre porque una de sus claves es
    `class`, palabra reservada de Python.
    """
    return {
        "ts": datetime.fromtimestamp(now, UTC).isoformat(timespec="seconds"),
        "model": model,
        "event": kind,
        "reentries": entry["reentries"],
        "wait_s": entry["wait_s"],
        **extra,
    }


@dataclass(frozen=True)
class ActiveCooldown:
    """Un modelo que ahora mismo no debe recibir peticiones."""

    until: float
    remaining_s: float
    #: Cuántas veces seguidas ha vuelto a entrar sin un éxito de por medio (1 la primera).
    reentries: int


def _entry(raw: object) -> dict:
    """La entrada de un modelo con su esquema fijo, tolerando lo que haya dejado un fichero viejo
    (claves en español incluidas)."""
    entry: dict = {"failures": 0, "wait_s": 0.0, "until": None, "reentries": 0}
    if not isinstance(raw, dict):
        return entry
    raw = legacy_names.normalize("cooldown_state", raw)
    for key in ("failures", "reentries"):
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            entry[key] = value
    for key in ("wait_s", "until"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            entry[key] = float(value)
    return entry


class CooldownState:
    def __init__(
        self,
        path: Path,
        *,
        failures: int,
        wait_s: float,
        max_wait_s: float,
        enabled: bool = True,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = Path(path)
        self._events_path = self._path.with_name(EVENTS_FILE)
        self._legacy_path = self._path.with_name(LEGACY_STATE_FILE)
        self._failures = max(1, int(failures))
        self._max_wait_s = float(max_wait_s)
        self._wait_s = min(float(wait_s), self._max_wait_s)
        self._enabled = enabled
        self._clock = clock

    # --- Escribir ------------------------------------------------------------------------------

    def record_failure(self, model: str, failure_class: FailureClass | str) -> None:
        """Suma un fallo si su clase cuenta; enfría al llegar a N, o al primer fallo tras vencer."""
        if FailureClass(failure_class) not in COUNTING_CLASSES:
            return
        now = self._clock()
        events: list[dict] = []
        extra = {"class": FailureClass(failure_class).value}

        def apply(data: dict) -> None:
            entry = _entry(data.get(model))
            until = entry["until"]
            if until is not None and now < until:
                # Ya está enfriándose (solo le llegan llamadas con `model` explícito, REQ-005): no
                # se dobla la espera por cada una, o unas pocas lo llevarían a Tmax de golpe.
                pass
            elif until is not None:
                # Venció y el primer fallo que cuenta lo vuelve a enfriar con la espera doblada.
                entry["wait_s"] = min(entry["wait_s"] * 2, self._max_wait_s)
                entry["until"] = now + entry["wait_s"]
                entry["reentries"] += 1
                entry["failures"] = 0
                events.append(_event_row(now, model, "reenter", entry, extra))
            else:
                entry["failures"] += 1
                if entry["failures"] >= self._failures:
                    entry["wait_s"] = self._wait_s
                    entry["until"] = now + self._wait_s
                    entry["reentries"] = 1
                    entry["failures"] = 0
                    events.append(_event_row(now, model, "enter", entry, extra))
            data[model] = entry

        self._mutate(apply, events)

    def record_success(self, model: str) -> None:
        """Cualquier éxito deja el modelo limpio: sin contador y con la espera base (REQ-010/011).

        Sin entrada no hay nada que limpiar y no se escribe: el éxito es el camino de casi todas
        las delegaciones, y reescribir el fichero en cada una sería el coste que la spec no admite.
        Si el modelo llegó a enfriarse, el éxito cierra el episodio. `after_expiry` distingue la
        recuperación de verdad de un éxito con `model` explícito en pleno enfriamiento (REQ-005).
        """
        now = self._clock()
        events: list[dict] = []

        def apply(data: dict) -> bool:
            raw = data.pop(model, None)
            if raw is None:
                return False
            entry = _entry(raw)
            if entry["until"] is not None:
                after_expiry = now >= entry["until"]
                events.append(
                    _event_row(now, model, "clear", entry, {"after_expiry": after_expiry})
                )
            return True

        self._mutate(apply, events)

    # --- Leer ----------------------------------------------------------------------------------

    def lookup(self, model: str) -> ActiveCooldown | None:
        """El enfriamiento vigente del modelo, o None si puede recibir peticiones."""
        return self.active().get(model)

    def active(self) -> dict[str, ActiveCooldown]:
        """Los modelos que ahora mismo están enfriándose, para `local_status`."""
        data = self._read()
        now = self._clock()
        self._clamp_distant_expiries(data, now)
        current = {model: self._active_entry(raw, now) for model, raw in data.items()}
        return {model: cooled for model, cooled in current.items() if cooled is not None}

    # --- Interno -------------------------------------------------------------------------------

    def _clamp_distant_expiries(self, data: dict, now: float) -> None:
        """Un `until` más allá de Tmax (un cambio de hora, un fichero de otra máquina) se GUARDA
        recortado, no solo se recorta al leer.

        Recortar contra «ahora» en cada lectura dejaba siempre Tmax por delante: el modelo no
        vencía nunca, que es justo el enfriamiento permanente que la spec prohíbe. Lo destapó un
        test que comprobaba el restante y no que el modelo llegara a quedar libre.
        """
        limit = now + self._max_wait_s
        distant = [
            model
            for model, raw in data.items()
            if (until := _entry(raw)["until"]) is not None and until > limit
        ]
        if not distant:
            return

        def clamp(current: dict) -> None:
            for model in distant:
                entry = _entry(current.get(model))
                if entry["until"] is not None and entry["until"] > limit:
                    entry["until"] = limit
                    current[model] = entry

        self._mutate(clamp)
        for model in distant:
            entry = _entry(data[model])
            entry["until"] = limit
            data[model] = entry

    def _active_entry(self, raw: object, now: float) -> ActiveCooldown | None:
        entry = _entry(raw)
        until = entry["until"]
        if until is None or until <= now:
            return None
        return ActiveCooldown(until=until, remaining_s=until - now, reentries=entry["reentries"])

    def _lock(self) -> FileLock:
        return FileLock(str(self._path) + ".lock", timeout=LOCK_WAIT_S)

    def _load(self) -> dict:
        """El estado vigente: el fichero nuevo y, si aún no existe, el viejo traducido (REQ-006)."""
        if self._path.exists() or self._legacy_path == self._path:
            return read_json(self._path)
        return {
            model: _entry(raw) if isinstance(raw, dict) else raw
            for model, raw in read_json(self._legacy_path).items()
        }

    def _read(self) -> dict:
        if not self._enabled:
            return {}
        try:
            with self._lock():
                return self._load()
        except (Timeout, OSError):
            return {}  # REQ-012: sin bloqueo o sin disco, como si no hubiera enfriamiento

    def _mutate(self, apply: Callable[[dict], object], events: list[dict] | None = None) -> None:
        """Aplica un cambio bajo el bloqueo. `apply` llena `events` si hubo transición: se
        escriben bajo el mismo bloqueo para que el orden del registro sea el del estado."""
        if not self._enabled:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock():
                data = self._load()
                if apply(data) is False:
                    return  # nada cambió: no se reescribe el fichero
                write_json_atomic(self._path, data)
                if events:
                    try:
                        _append_lines(self._events_path, events)
                    except OSError:
                        pass  # el registro es para medir: perderlo no deshace el estado ya escrito
        except (Timeout, OSError):
            return  # REQ-012: nunca bloquea ni hace fallar una delegación


def from_config() -> CooldownState:
    """El estado con la configuración vigente, leída al llamar (los tests cambian `LOG_DIR`)."""
    return CooldownState(
        config.LOG_DIR / STATE_FILE,
        failures=config.COOLDOWN_FAILURES,
        wait_s=config.COOLDOWN_S,
        max_wait_s=config.COOLDOWN_MAX_S,
        enabled=config.COOLDOWN,
    )
