"""Turno por conjunto de modelos compatibles (REQ-003 a REQ-007).

Dos capas:

- **Núcleo puro** (`evaluar` y sus ayudantes): recibe el estado, la función `choca` y los
  relojes ya leídos, y dice a quién se concede el turno, con qué reserva y si es forzado. No tiene
  hilos ni reloj propio.
- **Envoltura** (`Turno`): guarda el estado único del daemon bajo una `threading.Condition`,
  despierta cada espera al menos una vez por `tic` (REQ-003, punto 6), lleva el contador de
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

Choca = Callable[[str, str], bool]
AlEsperar = Callable[[int, tuple[str, ...]], None]


# --------------------------------------------------------------------------------------------
# Núcleo puro
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Peticion:
    """Una operación que pide turno.

    - `A`: conjunto aceptable (REQ-003): el rol más los alternativos aprobados, `{model}` con
      modelo explícito o `{destino}` / el conjunto de `cargado` en un salto (REQ-006).
    - `rol`: id real del modelo del rol. En una espera de salto puede no estar en `A`.
    - `orden_cadena`: orden de la cadena del rol; decide el modelo de una concesión forzada
      cuando el rol no está en `A` (REQ-007).
    - `directos`: modelos de `A` que entran en `A'` solo por ser compatibles, como el rol (por
      ejemplo, el destino de un salto). El rol, si está en `A`, siempre es directo. El resto de
      `A` son alternativos de afinidad: con alguien en `activos` solo entran si ya están en uso.
    """

    id: str
    A: frozenset[str]
    rol: str
    orden_cadena: tuple[str, ...] = ()
    directos: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "A", frozenset(self.A))
        object.__setattr__(self, "directos", frozenset(self.directos))
        object.__setattr__(self, "orden_cadena", tuple(self.orden_cadena))
        if not self.A:
            raise ValueError(f"petición {self.id!r} sin conjunto aceptable")

    def es_directo(self, modelo: str) -> bool:
        return modelo == self.rol or modelo in self.directos


@dataclass(frozen=True)
class Espera:
    """Una petición en la cola, con el instante en que llegó (`desde`)."""

    peticion: Peticion
    desde: float

    @property
    def id(self) -> str:
        return self.peticion.id


@dataclass(frozen=True)
class Activo:
    """Una operación con turno: su reserva (un modelo = elegido) y si entró forzada."""

    espera: Espera
    reserva: frozenset[str]
    forzada: bool = False

    @property
    def id(self) -> str:
        return self.espera.id

    @property
    def elegido(self) -> str | None:
        return next(iter(self.reserva)) if len(self.reserva) == 1 else None


@dataclass(frozen=True)
class Estado:
    """El estado único del turno: `activos` y `cola` (en orden de llegada)."""

    activos: tuple[Activo, ...] = ()
    cola: tuple[Espera, ...] = ()

    def activo(self, op_id: str) -> Activo | None:
        return next((a for a in self.activos if a.id == op_id), None)

    def en_cola(self, op_id: str) -> Espera | None:
        return next((e for e in self.cola if e.id == op_id), None)


@dataclass(frozen=True)
class Concesion:
    id: str
    reserva: frozenset[str]
    forzada: bool = False

    @property
    def modelo(self) -> str | None:
        """El modelo elegido si la reserva tiene uno solo; si no, `None` (elige después)."""
        return next(iter(self.reserva)) if len(self.reserva) == 1 else None


@dataclass(frozen=True)
class Decision:
    estado: Estado
    concesiones: tuple[Concesion, ...] = ()

    def para(self, op_id: str) -> Concesion | None:
        return next((c for c in self.concesiones if c.id == op_id), None)


def modelos(activos: Iterable[Activo]) -> frozenset[str]:
    """Unión de los modelos elegidos y de las reservas de `activos` (REQ-003)."""
    resultado: set[str] = set()
    for a in activos:
        resultado |= a.reserva
    return frozenset(resultado)


def compatible(modelo: str, conjunto: Iterable[str], choca: Choca) -> bool:
    """`modelo` no choca con ningún modelo de `conjunto`; nunca choca consigo mismo."""
    return not any(otro != modelo and choca(modelo, otro) for otro in conjunto)


def concedible(peticion: Peticion, activos: tuple[Activo, ...], choca: Choca) -> frozenset[str]:
    """`A'` de REQ-003 para una petición frente a `activos`."""
    if not activos:
        return peticion.A
    en_uso = modelos(activos)
    elegidos = {a.elegido for a in activos if a.elegido is not None}
    return frozenset(
        m
        for m in peticion.A
        if compatible(m, en_uso, choca) and (peticion.es_directo(m) or m in elegidos)
    )


def modelo_forzado(peticion: Peticion) -> str:
    """REQ-007: el rol si está en `A`; si no, el primero de `A` en el orden de la cadena."""
    if peticion.rol in peticion.A:
        return peticion.rol
    for m in peticion.orden_cadena:
        if m in peticion.A:
            return m
    return min(peticion.A)


def toca_forzar(
    espera: Espera, ahora: float, sin_progreso_desde: float | None, turno_max_s: float
) -> bool:
    """La cabeza lleva `turno_max_s` esperando **y** el daemon `turno_max_s` sin progreso.

    `sin_progreso_desde` es `None` mientras hay alguna llamada al backend en vuelo: entonces el
    reloj de la red no corre (REQ-007).
    """
    if sin_progreso_desde is None:
        return False
    return ahora - espera.desde >= turno_max_s and ahora - sin_progreso_desde >= turno_max_s


def _e1(
    espera: Espera, delante: Iterable[Espera], en_uso: frozenset[str], choca: Choca
) -> frozenset[str]:
    """Modelos de `A_R` que cumplen la excepción E-1 de REQ-005."""
    pedidos_delante: set[str] = set()
    for d in delante:
        pedidos_delante |= d.peticion.A
    return frozenset(
        m
        for m in espera.peticion.A
        if compatible(m, en_uso, choca) and compatible(m, pedidos_delante, choca)
    )


def evaluar(
    estado: Estado,
    choca: Choca,
    ahora: float,
    sin_progreso_desde: float | None,
    turno_max_s: float,
) -> Decision:
    """Concede lo que se pueda conceder ahora (REQ-003, REQ-005 y REQ-007).

    1. La cabeza se concede si su `A'` no está vacío; después se mira la siguiente.
    2. Si la cabeza no se concede pero toca la red de seguridad, entra **forzada** con un solo
       modelo (como mucho una forzada por evaluación).
    3. Detrás de una cabeza no concedida solo pasa quien cumple E-1.
    """
    activos = list(estado.activos)
    cola = list(estado.cola)
    concesiones: list[Concesion] = []
    hubo_forzada = False

    def conceder(espera: Espera, reserva: frozenset[str], forzada: bool) -> None:
        activos.append(Activo(espera, reserva, forzada))
        cola.remove(espera)
        concesiones.append(Concesion(espera.id, reserva, forzada))

    cambio = True
    while cambio:
        cambio = False
        while cola:
            cabeza = cola[0]
            reserva = concedible(cabeza.peticion, tuple(activos), choca)
            if reserva:
                conceder(cabeza, reserva, False)
                cambio = True
                continue
            if not hubo_forzada and toca_forzar(cabeza, ahora, sin_progreso_desde, turno_max_s):
                conceder(cabeza, frozenset({modelo_forzado(cabeza.peticion)}), True)
                hubo_forzada = True
                cambio = True
                continue
            break
        i = 1
        while i < len(cola):
            r = cola[i]
            reserva = _e1(r, cola[:i], modelos(activos), choca)
            if reserva:
                conceder(r, reserva, False)
                cambio = True
            else:
                i += 1

    return Decision(Estado(tuple(activos), tuple(cola)), tuple(concesiones))


def compatibles_al_elegir(estado: Estado, op_id: str, choca: Choca) -> frozenset[str]:
    """Modelos de la reserva de `op_id` compatibles con `activos` sin contar la propia operación.

    Vacío solo tras una concesión forzada de otra: entonces la operación vuelve a la cabeza
    (REQ-003, «Elección»).
    """
    propio = estado.activo(op_id)
    if propio is None:
        raise KeyError(op_id)
    otros = modelos(a for a in estado.activos if a.id != op_id)
    return frozenset(m for m in propio.reserva if compatible(m, otros, choca))


def reducir(estado: Estado, op_id: str, modelo: str) -> Estado:
    """La reserva de `op_id` se reduce al modelo elegido."""
    propio = estado.activo(op_id)
    if propio is None:
        raise KeyError(op_id)
    if modelo not in propio.reserva:
        raise ValueError(f"{modelo!r} no está en la reserva de {op_id!r}")
    nuevo = replace(propio, reserva=frozenset({modelo}))
    return replace(estado, activos=tuple(nuevo if a.id == op_id else a for a in estado.activos))


def elegir(
    estado: Estado, op_id: str, candidatos: Sequence[str], choca: Choca
) -> tuple[Estado, str | None]:
    """Elección atómica de REQ-003: reduce al primer candidato que cabe o vuelve a la cabeza.

    `candidatos` va en orden de preferencia; solo cuentan los que están en la reserva. Devuelve
    el estado nuevo y el modelo elegido, o `None` si ninguno cabe sin contar la propia operación
    (tras una forzada de otra): entonces la operación ya está de vuelta en la cabeza de la cola.
    """
    propio = estado.activo(op_id)
    if propio is None:
        raise KeyError(op_id)
    if not propio.reserva.intersection(candidatos):
        raise ValueError(f"ningún candidato está en la reserva de {op_id!r}")
    cabe = compatibles_al_elegir(estado, op_id, choca)
    for modelo in candidatos:
        if modelo in cabe:
            return reducir(estado, op_id, modelo), modelo
    return volver_a_la_cabeza(estado, op_id), None


def soltar(estado: Estado, op_id: str) -> Estado:
    """`op_id` sale de `activos` (no hace nada si no estaba)."""
    return replace(estado, activos=tuple(a for a in estado.activos if a.id != op_id))


def volver_a_la_cabeza(estado: Estado, op_id: str) -> Estado:
    """`op_id` suelta su reserva y vuelve a la **cabeza** de la cola, sin perder su puesto."""
    propio = estado.activo(op_id)
    if propio is None:
        raise KeyError(op_id)
    sin_el = soltar(estado, op_id)
    return replace(sin_el, cola=(propio.espera, *sin_el.cola))


# --------------------------------------------------------------------------------------------
# Orden de adquisición (REQ-004)
# --------------------------------------------------------------------------------------------

_hilo = threading.local()


@contextmanager
def plaza_tomada() -> Generator[None, None, None]:
    """Marca que el hilo tiene una plaza mientras dura el bloque (la pone `_run_chat`)."""
    anterior = getattr(_hilo, "plazas", 0)
    _hilo.plazas = anterior + 1
    try:
        yield
    finally:
        _hilo.plazas = anterior


def tiene_plaza() -> bool:
    return getattr(_hilo, "plazas", 0) > 0


def _comprobar_sin_plaza() -> None:
    # Lanza a mano y no con `assert`: con `python -O` el aserto desaparecería.
    if tiene_plaza():
        raise AssertionError("orden de adquisición: se pidió turno con una plaza en la mano")


# --------------------------------------------------------------------------------------------
# Envoltura con hilos
# --------------------------------------------------------------------------------------------


class EsperaAbandonada(Exception):
    """La espera salió de la cola por abandono antes de concederse."""


@dataclass
class _Vuelo:
    llamadas: int = 0
    ultimo_cambio: float = 0.0
    abandonadas: set[str] = field(default_factory=set)


class Turno:
    """Estado único del turno del daemon, seguro entre hilos.

    `reloj` es inyectable (por defecto `time.monotonic`); `tic` es el tope de cada `wait`
    (REQ-003, punto 6: 1 s por defecto).
    """

    def __init__(
        self,
        choca: Choca,
        *,
        turno_max_s: float = 600.0,
        tic: float = 1.0,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._choca = choca
        self._turno_max_s = turno_max_s
        self._tic = tic
        self._reloj = reloj
        self._cond = threading.Condition()
        self._estado = Estado()
        self._concedidas: dict[str, Concesion] = {}
        self._vuelo = _Vuelo(ultimo_cambio=reloj())

    # --- lectura -----------------------------------------------------------------------------

    def foto(self) -> Estado:
        with self._cond:
            return self._estado

    def en_uso(self) -> tuple[str, ...]:
        with self._cond:
            return tuple(sorted(modelos(self._estado.activos)))

    # --- red de seguridad --------------------------------------------------------------------

    def _sin_progreso_desde(self) -> float | None:
        if self._vuelo.llamadas > 0:
            return None
        return self._vuelo.ultimo_cambio

    @contextmanager
    def en_vuelo(self) -> Generator[None, None, None]:
        """Envuelve cada llamada al backend: mueve el contador y pone a cero el reloj."""
        with self._cond:
            self._vuelo.llamadas += 1
            self._vuelo.ultimo_cambio = self._reloj()
        try:
            yield
        finally:
            with self._cond:
                self._vuelo.llamadas -= 1
                self._vuelo.ultimo_cambio = self._reloj()

    # --- evaluación (con el cerrojo tomado) --------------------------------------------------

    def _aplicar(self) -> None:
        decision = evaluar(
            self._estado,
            self._choca,
            self._reloj(),
            self._sin_progreso_desde(),
            self._turno_max_s,
        )
        self._estado = decision.estado
        for c in decision.concesiones:
            self._concedidas[c.id] = c
            if c.forzada:
                # Una forzada cuenta como progreso: sin esto, la siguiente cabeza se forzaría en
                # el mismo tic, antes de que la forzada llegue a hacer su primera llamada.
                self._vuelo.ultimo_cambio = self._reloj()
        if decision.concesiones:
            self._cond.notify_all()

    def _aviso(self, op_id: str) -> tuple[int, tuple[str, ...]]:
        posicion = next(i for i, e in enumerate(self._estado.cola, 1) if e.id == op_id)
        return posicion, tuple(sorted(modelos(self._estado.activos)))

    def _sacar_de_la_cola(self, op_id: str) -> bool:
        if self._estado.en_cola(op_id) is None:
            return False
        self._estado = replace(
            self._estado, cola=tuple(e for e in self._estado.cola if e.id != op_id)
        )
        return True

    def _ocupado(self, op_id: str) -> bool:
        return (
            self._estado.activo(op_id) is not None
            or self._estado.en_cola(op_id) is not None
            or op_id in self._concedidas
        )

    # --- espera ------------------------------------------------------------------------------

    def _esperar(
        self,
        op_id: str,
        al_esperar: AlEsperar | None,
        al_conceder: Callable[[Concesion], None] | None,
    ) -> Concesion:
        ultimo_aviso: tuple[int, tuple[str, ...]] | None = None
        try:
            while True:
                with self._cond:
                    concesion = self._concedidas.pop(op_id, None)
                    if concesion is not None:
                        break
                    if op_id in self._vuelo.abandonadas:
                        self._vuelo.abandonadas.discard(op_id)
                        raise EsperaAbandonada(op_id)
                    aviso = self._aviso(op_id)
                    if aviso == ultimo_aviso:
                        self._cond.wait(timeout=self._tic)
                        self._aplicar()
                        continue
                ultimo_aviso = aviso
                if al_esperar is not None:
                    al_esperar(*aviso)
        except BaseException:
            with self._cond:
                self._vuelo.abandonadas.discard(op_id)
                salio = self._sacar_de_la_cola(op_id)
                pendiente = self._concedidas.pop(op_id, None)
                if pendiente is not None:
                    self._estado = soltar(self._estado, op_id)
                if salio or pendiente is not None:
                    self._cond.notify_all()
            raise
        if al_conceder is not None:
            try:
                al_conceder(concesion)
            except BaseException:
                self.soltar(op_id)
                raise
        return concesion

    def pedir(
        self,
        peticion: Peticion,
        al_esperar: AlEsperar | None = None,
        al_conceder: Callable[[Concesion], None] | None = None,
    ) -> Concesion:
        """Pide turno y bloquea hasta obtenerlo (o hasta `EsperaAbandonada`).

        `al_esperar(posicion, en_uso)` se llama al quedar en cola y cada vez que cambian la
        posición o los modelos en uso; `al_conceder(concesion)`, al obtener el turno. Los dos se
        llaman fuera del cerrojo.
        """
        _comprobar_sin_plaza()
        with self._cond:
            if self._ocupado(peticion.id):
                raise ValueError(f"la operación {peticion.id!r} ya está en el turno")
            self._estado = replace(
                self._estado, cola=(*self._estado.cola, Espera(peticion, self._reloj()))
            )
            self._aplicar()  # punto 1: llega una petición
        return self._esperar(peticion.id, al_esperar, al_conceder)

    def elegir(
        self,
        op_id: str,
        candidatos: Sequence[str],
        al_esperar: AlEsperar | None = None,
        al_conceder: Callable[[Concesion], None] | None = None,
    ) -> str:
        """Elige modelo de la reserva y la reduce a él, todo bajo **un solo** cerrojo (REQ-003).

        Es la entrada que debe usar el daemon (T10). Si ningún candidato cabe (una forzada de
        otra entró tras la concesión), la operación vuelve a la cabeza, espera nueva concesión y
        repite la elección. Devuelve el modelo elegido; puede lanzar `EsperaAbandonada`.
        """
        _comprobar_sin_plaza()
        while True:
            with self._cond:
                self._estado, modelo = elegir(self._estado, op_id, candidatos, self._choca)
                self._cond.notify_all()  # punto 3 (se reduce) o punto 2 (sale de `activos`)
                if modelo is not None:
                    return modelo
                self._aplicar()
            self._esperar(op_id, al_esperar, al_conceder)

    def compatibles(self, op_id: str) -> frozenset[str]:
        """Modelos de la reserva que aún se pueden elegir (REQ-003, «Elección»).

        Solo para consulta y tests: `compatibles` seguido de `reducir` son dos tomas del
        cerrojo y entre ellas puede entrar una forzada. Para elegir, usa `elegir`.
        """
        with self._cond:
            return compatibles_al_elegir(self._estado, op_id, self._choca)

    def reducir(self, op_id: str, modelo: str) -> None:
        """La reserva se reduce al modelo elegido (punto 3). Para elegir, usa `elegir`."""
        with self._cond:
            self._estado = reducir(self._estado, op_id, modelo)
            self._cond.notify_all()

    def volver(
        self,
        op_id: str,
        al_esperar: AlEsperar | None = None,
        al_conceder: Callable[[Concesion], None] | None = None,
    ) -> Concesion:
        """Ningún modelo de la reserva cabe: suelta la reserva, vuelve a la cabeza y espera."""
        _comprobar_sin_plaza()
        with self._cond:
            self._estado = volver_a_la_cabeza(self._estado, op_id)
            self._cond.notify_all()  # punto 2: sale de `activos`
            self._aplicar()
        return self._esperar(op_id, al_esperar, al_conceder)

    def soltar(self, op_id: str) -> None:
        """La operación sale de `activos` (punto 2). Idempotente."""
        with self._cond:
            self._estado = soltar(self._estado, op_id)
            self._cond.notify_all()

    def abandonar(self, op_id: str) -> bool:
        """Saca una espera de la cola (punto 4); su `pedir` lanza `EsperaAbandonada`."""
        with self._cond:
            if not self._sacar_de_la_cola(op_id):
                return False
            self._vuelo.abandonadas.add(op_id)
            self._cond.notify_all()
            return True

    def cambio_topologia(self, choca: Choca) -> None:
        """La topología nueva rige desde la siguiente concesión (punto 5, REQ-009)."""
        with self._cond:
            self._choca = choca
            self._cond.notify_all()
