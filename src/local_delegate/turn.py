"""Turno por conjunto de modelos compatibles (REQ-003 a REQ-007).

Dos capas:

- **Núcleo puro** (`evaluate` y sus ayudantes): recibe el estado, la función `clashes` y los
  relojes ya leídos, y dice a quién se concede el turno, con qué reserva y si es forzado. No tiene
  hilos ni reloj propio.
- **Envoltura** (`Turn`): guarda el estado único del daemon bajo una `threading.Condition`,
  despierta cada espera al menos una vez por `tick` (REQ-003, punto 6), lleva el contador de
  llamadas al backend en vuelo y el reloj de falta de progreso (REQ-007).

La compatibilidad llega como función (`choca(a, b) -> bool`) desde la foto de topología: este
módulo no lee la config ni conoce nombres de modelo.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Generator, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace

Clashes = Callable[[str, str], bool]
OnWait = Callable[[int, tuple[str, ...]], None]


# --------------------------------------------------------------------------------------------
# Núcleo puro
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingRequest:
    """Una operación que pide turno.

    - `A`: conjunto aceptable (REQ-003): el rol más los alternativos aprobados, `{model}` con
      modelo explícito o `{destino}` / el conjunto de `loaded` en un salto (REQ-006).
    - `role`: id real del modelo del rol. En una espera de salto puede no estar en `A`.
    - `chain_order`: orden de la cadena del rol; decide el modelo de una concesión forzada
      cuando el rol no está en `A` (REQ-007).
    - `direct`: modelos de `A` que entran en `A'` solo por ser compatibles, como el rol (por
      ejemplo, el destino de un salto). El rol, si está en `A`, siempre es directo. El resto de
      `A` son alternativos de afinidad: con alguien en `actives` solo entran si ya están en uso.
    """

    id: str
    A: frozenset[str]
    role: str
    chain_order: tuple[str, ...] = ()
    direct: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "A", frozenset(self.A))
        object.__setattr__(self, "direct", frozenset(self.direct))
        object.__setattr__(self, "chain_order", tuple(self.chain_order))
        if not self.A:
            raise ValueError(f"petición {self.id!r} sin conjunto aceptable")

    def is_direct(self, model: str) -> bool:
        return model == self.role or model in self.direct


@dataclass(frozen=True)
class Wait:
    """Una petición en la cola, con el instante en que llegó (`since`)."""

    request: PendingRequest
    since: float

    @property
    def id(self) -> str:
        return self.request.id


@dataclass(frozen=True)
class Active:
    """Una operación con turno: su reserva (un modelo = elegido) y si entró forzada."""

    wait: Wait
    reserve: frozenset[str]
    forced: bool = False

    @property
    def id(self) -> str:
        return self.wait.id

    @property
    def chosen(self) -> str | None:
        return next(iter(self.reserve)) if len(self.reserve) == 1 else None


@dataclass(frozen=True)
class State:
    """El estado único del turno: `actives` y `queue` (en orden de llegada)."""

    actives: tuple[Active, ...] = ()
    queue: tuple[Wait, ...] = ()

    def active(self, op_id: str) -> Active | None:
        return next((a for a in self.actives if a.id == op_id), None)

    def queued(self, op_id: str) -> Wait | None:
        return next((e for e in self.queue if e.id == op_id), None)


@dataclass(frozen=True)
class Grant:
    id: str
    reserve: frozenset[str]
    forced: bool = False

    @property
    def model(self) -> str | None:
        """El modelo elegido si la reserva tiene uno solo; si no, `None` (elige después)."""
        return next(iter(self.reserve)) if len(self.reserve) == 1 else None


@dataclass(frozen=True)
class Decision:
    state: State
    grants: tuple[Grant, ...] = ()

    def grant_for(self, op_id: str) -> Grant | None:
        return next((c for c in self.grants if c.id == op_id), None)


def models(actives: Iterable[Active]) -> frozenset[str]:
    """Unión de los modelos elegidos y de las reservas de `actives` (REQ-003)."""
    result: set[str] = set()
    for a in actives:
        result |= a.reserve
    return frozenset(result)


def compatible(model: str, case_set: Iterable[str], clashes: Clashes) -> bool:
    """`model` no choca con ningún modelo de `case_set`; nunca choca consigo mismo."""
    return not any(other != model and clashes(model, other) for other in case_set)


def grantable(
    request: PendingRequest, actives: tuple[Active, ...], clashes: Clashes
) -> frozenset[str]:
    """`A'` de REQ-003 para una petición frente a `actives`."""
    if not actives:
        return request.A
    in_use = models(actives)
    chosen_set = {a.chosen for a in actives if a.chosen is not None}
    return frozenset(
        m
        for m in request.A
        if compatible(m, in_use, clashes) and (request.is_direct(m) or m in chosen_set)
    )


def forced_model(request: PendingRequest) -> str:
    """REQ-007: el rol si está en `A`; si no, el primero de `A` en el orden de la cadena."""
    if request.role in request.A:
        return request.role
    for m in request.chain_order:
        if m in request.A:
            return m
    return min(request.A)


def must_force(wait: Wait, now: float, no_progress_since: float | None, turn_max_s: float) -> bool:
    """La cabeza lleva `turn_max_s` esperando **y** el daemon `turn_max_s` sin progreso.

    `no_progress_since` es `None` mientras hay alguna llamada al backend en vuelo: entonces el
    reloj de la red no corre (REQ-007).
    """
    if no_progress_since is None:
        return False
    return now - wait.since >= turn_max_s and now - no_progress_since >= turn_max_s


def _e1(
    wait: Wait, ahead: Iterable[Wait], in_use: frozenset[str], clashes: Clashes
) -> frozenset[str]:
    """Modelos de `A_R` que cumplen la excepción E-1 de REQ-005."""
    requests_ahead: set[str] = set()
    for d in ahead:
        requests_ahead |= d.request.A
    return frozenset(
        m
        for m in wait.request.A
        if compatible(m, in_use, clashes) and compatible(m, requests_ahead, clashes)
    )


def evaluate(
    state: State,
    clashes: Clashes,
    now: float,
    no_progress_since: float | None,
    turn_max_s: float,
) -> Decision:
    """Concede lo que se pueda conceder ahora (REQ-003, REQ-005 y REQ-007).

    1. La cabeza se concede si su `A'` no está vacío; después se mira la siguiente.
    2. Si la cabeza no se concede pero toca la red de seguridad, entra **forzada** con un solo
       modelo (como mucho una forzada por evaluación).
    3. Detrás de una cabeza no concedida solo pasa quien cumple E-1.
    """
    actives = list(state.actives)
    queue = list(state.queue)
    grants: list[Grant] = []
    had_forced = False

    def do_grant(wait: Wait, reserve: frozenset[str], forced: bool) -> None:
        actives.append(Active(wait, reserve, forced))
        queue.remove(wait)
        grants.append(Grant(wait.id, reserve, forced))

    change = True
    while change:
        change = False
        while queue:
            head = queue[0]
            reserve = grantable(head.request, tuple(actives), clashes)
            if reserve:
                do_grant(head, reserve, False)
                change = True
                continue
            if not had_forced and must_force(head, now, no_progress_since, turn_max_s):
                do_grant(head, frozenset({forced_model(head.request)}), True)
                had_forced = True
                change = True
                continue
            break
        i = 1
        while i < len(queue):
            r = queue[i]
            reserve = _e1(r, queue[:i], models(actives), clashes)
            if reserve:
                do_grant(r, reserve, False)
                change = True
            else:
                i += 1

    return Decision(State(tuple(actives), tuple(queue)), tuple(grants))


def compatible_when_choosing(state: State, op_id: str, clashes: Clashes) -> frozenset[str]:
    """Modelos de la reserva de `op_id` compatibles con `actives` sin contar la propia operación.

    Vacío solo tras una concesión forzada de otra: entonces la operación vuelve a la cabeza
    (REQ-003, «Elección»).
    """
    own = state.active(op_id)
    if own is None:
        raise KeyError(op_id)
    others = models(a for a in state.actives if a.id != op_id)
    return frozenset(m for m in own.reserve if compatible(m, others, clashes))


def reduce(state: State, op_id: str, model: str) -> State:
    """La reserva de `op_id` se reduce al modelo elegido."""
    own = state.active(op_id)
    if own is None:
        raise KeyError(op_id)
    if model not in own.reserve:
        raise ValueError(f"{model!r} no está en la reserva de {op_id!r}")
    new = replace(own, reserve=frozenset({model}))
    return replace(state, actives=tuple(new if a.id == op_id else a for a in state.actives))


def choose(
    state: State, op_id: str, candidates: Sequence[str], clashes: Clashes
) -> tuple[State, str | None]:
    """Elección atómica de REQ-003: reduce al primer candidato que cabe o vuelve a la cabeza.

    `candidates` va en orden de preferencia; solo cuentan los que están en la reserva. Devuelve
    el estado nuevo y el modelo elegido, o `None` si ninguno cabe sin contar la propia operación
    (tras una forzada de otra): entonces la operación ya está de vuelta en la cabeza de la cola.
    """
    own = state.active(op_id)
    if own is None:
        raise KeyError(op_id)
    if not own.reserve.intersection(candidates):
        raise ValueError(f"ningún candidato está en la reserva de {op_id!r}")
    fits = compatible_when_choosing(state, op_id, clashes)
    for model in candidates:
        if model in fits:
            return reduce(state, op_id, model), model
    return back_to_head(state, op_id), None


def release_slot(state: State, op_id: str) -> State:
    """`op_id` sale de `actives` (no hace nada si no estaba)."""
    return replace(state, actives=tuple(a for a in state.actives if a.id != op_id))


def back_to_head(state: State, op_id: str) -> State:
    """`op_id` suelta su reserva y vuelve a la **cabeza** de la cola, sin perder su puesto."""
    own = state.active(op_id)
    if own is None:
        raise KeyError(op_id)
    without_it = release_slot(state, op_id)
    return replace(without_it, queue=(own.wait, *without_it.queue))


# --------------------------------------------------------------------------------------------
# Orden de adquisición (REQ-004)
# --------------------------------------------------------------------------------------------

_thread_local = threading.local()


@contextmanager
def slot_taken() -> Generator[None, None, None]:
    """Marca que el hilo tiene una plaza mientras dura el bloque (la pone `_run_chat`)."""
    previous = getattr(_thread_local, "slots", 0)
    _thread_local.slots = previous + 1
    try:
        yield
    finally:
        _thread_local.slots = previous


def has_slot() -> bool:
    return getattr(_thread_local, "slots", 0) > 0


def _check_without_slot() -> None:
    # Lanza a mano y no con `assert`: con `python -O` el aserto desaparecería.
    if has_slot():
        raise AssertionError("orden de adquisición: se pidió turno con una plaza en la mano")


# --------------------------------------------------------------------------------------------
# Envoltura con hilos
# --------------------------------------------------------------------------------------------


class AbandonedWait(Exception):
    """La espera salió de la cola por abandono antes de concederse."""


@dataclass
class _Flight:
    calls: int = 0
    last_change: float = 0.0
    abandoned: set[str] = field(default_factory=set)


class Turn:
    """Estado único del turno del daemon, seguro entre hilos.

    `clock` es inyectable (por defecto `time.monotonic`); `tick` es el tope de cada `wait`
    (REQ-003, punto 6: 1 s por defecto). `on_tick`, opcional, se llama fuera del cerrojo antes de
    cada reevaluación por tic (añadido en T10 para releer la topología, REQ-009).
    """

    def __init__(
        self,
        clashes: Clashes,
        *,
        turn_max_s: float = 600.0,
        tick: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        on_tick: Callable[[], None] | None = None,
    ) -> None:
        self._clashes = clashes
        #: Se llama FUERA del cerrojo antes de cada reevaluación por tic de una espera. El daemon
        #: lo usa para releer la topología: una espera ya en cola ve la config nueva (REQ-009).
        self._on_tick = on_tick
        self._turn_max_s = turn_max_s
        self._tic = tick
        self._clock = clock
        self._cond = threading.Condition()
        self._state = State()
        self._granted: dict[str, Grant] = {}
        self._flight = _Flight(last_change=clock())

    # --- lectura -----------------------------------------------------------------------------

    def snapshot(self) -> State:
        with self._cond:
            return self._state

    def in_use(self) -> tuple[str, ...]:
        with self._cond:
            return tuple(sorted(models(self._state.actives)))

    # --- red de seguridad --------------------------------------------------------------------

    def _no_progress_since(self) -> float | None:
        if self._flight.calls > 0:
            return None
        return self._flight.last_change

    @contextmanager
    def in_flight(self) -> Generator[None, None, None]:
        """Envuelve cada llamada al backend: mueve el contador y pone a cero el reloj."""
        with self._cond:
            self._flight.calls += 1
            self._flight.last_change = self._clock()
        try:
            yield
        finally:
            with self._cond:
                self._flight.calls -= 1
                self._flight.last_change = self._clock()

    # --- evaluación (con el cerrojo tomado) --------------------------------------------------

    def _apply(self) -> None:
        decision = evaluate(
            self._state,
            self._clashes,
            self._clock(),
            self._no_progress_since(),
            self._turn_max_s,
        )
        self._state = decision.state
        for c in decision.grants:
            self._granted[c.id] = c
            if c.forced:
                # Una forzada cuenta como progreso: sin esto, la siguiente cabeza se forzaría en
                # el mismo tic, antes de que la forzada llegue a hacer su primera llamada.
                self._flight.last_change = self._clock()
        if decision.grants:
            self._cond.notify_all()

    def _warning(self, op_id: str) -> tuple[int, tuple[str, ...]]:
        position = next(i for i, e in enumerate(self._state.queue, 1) if e.id == op_id)
        return position, tuple(sorted(models(self._state.actives)))

    def _dequeue(self, op_id: str) -> bool:
        if self._state.queued(op_id) is None:
            return False
        self._state = replace(
            self._state, queue=tuple(e for e in self._state.queue if e.id != op_id)
        )
        return True

    def _busy(self, op_id: str) -> bool:
        return (
            self._state.active(op_id) is not None
            or self._state.queued(op_id) is not None
            or op_id in self._granted
        )

    # --- espera ------------------------------------------------------------------------------

    def _wait(
        self,
        op_id: str,
        on_wait: OnWait | None,
        on_grant: Callable[[Grant], None] | None,
    ) -> Grant:
        last_warning: tuple[int, tuple[str, ...]] | None = None
        try:
            while True:
                with self._cond:
                    grant = self._granted.pop(op_id, None)
                    if grant is not None:
                        break
                    if op_id in self._flight.abandoned:
                        self._flight.abandoned.discard(op_id)
                        raise AbandonedWait(op_id)
                    warning = self._warning(op_id)
                    tick = warning == last_warning
                    if tick:
                        self._cond.wait(timeout=self._tic)
                if tick:
                    # Fuera del cerrojo: el gancho puede traer una topología nueva
                    # (`topology_change`), y la reevaluación de abajo ya la usa (REQ-009).
                    if self._on_tick is not None:
                        self._on_tick()
                    with self._cond:
                        self._apply()
                    continue
                last_warning = warning
                if on_wait is not None:
                    on_wait(*warning)
        except BaseException:
            with self._cond:
                self._flight.abandoned.discard(op_id)
                exited = self._dequeue(op_id)
                pending = self._granted.pop(op_id, None)
                if pending is not None:
                    self._state = release_slot(self._state, op_id)
                if exited or pending is not None:
                    self._cond.notify_all()
            raise
        if on_grant is not None:
            try:
                on_grant(grant)
            except BaseException:
                self.release_slot(op_id)
                raise
        return grant

    def request(
        self,
        request: PendingRequest,
        on_wait: OnWait | None = None,
        on_grant: Callable[[Grant], None] | None = None,
    ) -> Grant:
        """Pide turno y bloquea hasta obtenerlo (o hasta `AbandonedWait`).

        `on_wait(posicion, in_use)` se llama al quedar en cola y cada vez que cambian la
        posición o los modelos en uso; `on_grant(concesion)`, al obtener el turno. Los dos se
        llaman fuera del cerrojo.
        """
        _check_without_slot()
        with self._cond:
            if self._busy(request.id):
                raise ValueError(f"la operación {request.id!r} ya está en el turno")
            self._state = replace(
                self._state, queue=(*self._state.queue, Wait(request, self._clock()))
            )
            self._apply()  # punto 1: llega una petición
        return self._wait(request.id, on_wait, on_grant)

    def choose_without_waiting(self, op_id: str, candidates: Sequence[str]) -> str | None:
        """La elección atómica de REQ-003, sin esperar: válida con una plaza en la mano.

        Bajo **un solo** cerrojo reduce la reserva al primer candidato que cabe y devuelve el
        modelo; si ninguno cabe (una forzada de otra entró tras la concesión), deja la operación
        en la **cabeza** de la cola, reevalúa y devuelve `None`. Entonces quien llama suelta su
        plaza y espera con `wait_for_grant` (aclaración de la ola 4: el daemon elige con la plaza
        de su primera llamada en la mano).
        """
        with self._cond:
            self._state, model = choose(self._state, op_id, candidates, self._clashes)
            self._cond.notify_all()  # punto 3 (se reduce) o punto 2 (sale de `actives`)
            if model is None:
                self._apply()
            return model

    def wait_for_grant(
        self,
        op_id: str,
        on_wait: OnWait | None = None,
        on_grant: Callable[[Grant], None] | None = None,
    ) -> Grant:
        """Espera la nueva concesión de una operación que volvió a la cabeza (REQ-004: sin plaza).

        Puede lanzar `AbandonedWait`.
        """
        _check_without_slot()
        return self._wait(op_id, on_wait, on_grant)

    def choose(
        self,
        op_id: str,
        candidates: Sequence[str],
        on_wait: OnWait | None = None,
        on_grant: Callable[[Grant], None] | None = None,
    ) -> str:
        """`choose_without_waiting` y, si vuelve a la cabeza, `wait_for_grant`, hasta elegir.

        Para quien elige **sin** plaza. El daemon no la usa: elige con la plaza de su primera
        llamada en la mano y la suelta antes de esperar. Devuelve el modelo elegido; puede lanzar
        `AbandonedWait`.
        """
        _check_without_slot()
        while True:
            model = self.choose_without_waiting(op_id, candidates)
            if model is not None:
                return model
            self.wait_for_grant(op_id, on_wait, on_grant)

    def compatible_models(self, op_id: str) -> frozenset[str]:
        """Modelos de la reserva que aún se pueden elegir (REQ-003, «Elección»).

        Solo para consulta y tests: `compatible_models` seguido de `reduce` son dos tomas del
        cerrojo y entre ellas puede entrar una forzada. Para elegir, usa `choose`.
        """
        with self._cond:
            return compatible_when_choosing(self._state, op_id, self._clashes)

    def reduce(self, op_id: str, model: str) -> None:
        """La reserva se reduce al modelo elegido (punto 3). Para elegir, usa `choose`."""
        with self._cond:
            self._state = reduce(self._state, op_id, model)
            self._cond.notify_all()

    def back(
        self,
        op_id: str,
        on_wait: OnWait | None = None,
        on_grant: Callable[[Grant], None] | None = None,
    ) -> Grant:
        """Ningún modelo de la reserva cabe: suelta la reserva, vuelve a la cabeza y espera."""
        _check_without_slot()
        with self._cond:
            self._state = back_to_head(self._state, op_id)
            self._cond.notify_all()  # punto 2: sale de `actives`
            self._apply()
        return self._wait(op_id, on_wait, on_grant)

    def release_slot(self, op_id: str) -> None:
        """La operación sale de `actives` (punto 2). Idempotente."""
        with self._cond:
            self._state = release_slot(self._state, op_id)
            self._cond.notify_all()

    def abandon(self, op_id: str) -> bool:
        """Saca una espera de la cola (punto 4); su `request` lanza `AbandonedWait`."""
        with self._cond:
            if not self._dequeue(op_id):
                return False
            self._flight.abandoned.add(op_id)
            self._cond.notify_all()
            return True

    def topology_change(self, clashes: Clashes) -> None:
        """La topología nueva rige desde la siguiente concesión (punto 5, REQ-009)."""
        with self._cond:
            self._clashes = clashes
            self._cond.notify_all()
