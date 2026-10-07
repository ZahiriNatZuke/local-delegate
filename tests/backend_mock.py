"""Mock del backend HTTP para la suite, sobre ``httpx2.MockTransport``.

Ocupa el sitio que tenía ``respx``, que se quedó fuera: declara ``httpx>=0.25.0`` y no soporta
``httpx2``, así que mantenerlo habría devuelto al entorno la librería HTTP que el paquete acaba de
quitar.

La diferencia de fondo con ``respx`` es que aquel interceptaba de forma **global**, mientras que
``MockTransport`` hay que **inyectarlo** en cada cliente. Como el paquete crea clientes en varios
sitios (uno cacheado en ``server`` y varios locales del tipo ``httpx2.Client(timeout=…)``), el
decorador sustituye la clase ``httpx2.Client`` mientras dura el test y le pasa el transport. Por eso
también invalida el cliente cacheado de ``server``: uno creado antes del mock traería su transport
real y se saltaría el enrutado.

Una petición que no case con ninguna ruta registrada **falla el test**, en vez de salir a la red.
"""

from __future__ import annotations

import contextlib
import functools
import json
import threading
import time
from collections.abc import Callable

import httpx2

from local_delegate import server

_rutas: list[Ruta] = []


class _Llamada:
    """Una petición atendida, con su respuesta (``None`` si la ruta lanzó)."""

    def __init__(self, request: httpx2.Request, response: httpx2.Response | None) -> None:
        self.request = request
        self.response = response


class _Llamadas(list):
    @property
    def last(self) -> _Llamada:
        return self[-1]


class Ruta:
    """Una URL y un método mockeados. El equivalente al ``Route`` de respx."""

    def __init__(self, metodo: str, url: str) -> None:
        self.metodo = metodo.upper()
        self.url = url
        self.calls = _Llamadas()
        self._return_value: httpx2.Response | None = None
        self._side_effect = None

    def mock(self, return_value=None, side_effect=None) -> Ruta:
        self._return_value = return_value
        self._side_effect = side_effect
        return self

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def _coincide(self, request: httpx2.Request) -> bool:
        return request.method == self.metodo and str(request.url) == self.url

    def _resolver(self, request: httpx2.Request) -> httpx2.Response:
        indice = len(self.calls)
        efecto = self._side_effect

        if efecto is not None:
            if isinstance(efecto, (list, tuple)):
                # Secuencia de respuestas: una por llamada, como `side_effect=[r1, r2]`.
                efecto = efecto[indice] if indice < len(efecto) else efecto[-1]
            elif callable(efecto) and not isinstance(efecto, type):
                efecto = efecto(request)

            if isinstance(efecto, BaseException) or (
                isinstance(efecto, type) and issubclass(efecto, BaseException)
            ):
                self.calls.append(_Llamada(request, None))
                raise efecto

            self.calls.append(_Llamada(request, efecto))
            return efecto

        if self._return_value is None:
            raise AssertionError(f"ruta sin respuesta configurada: {self.metodo} {self.url}")

        self.calls.append(_Llamada(request, self._return_value))
        return self._return_value


def post(url: str) -> Ruta:
    ruta = Ruta("POST", url)
    _rutas.append(ruta)
    return ruta


def get(url: str) -> Ruta:
    ruta = Ruta("GET", url)
    _rutas.append(ruta)
    return ruta


def _handler(request: httpx2.Request) -> httpx2.Response:
    for ruta in _rutas:
        if ruta._coincide(request):
            return ruta._resolver(request)
    raise AssertionError(f"petición no mockeada: {request.method} {request.url}")


@contextlib.contextmanager
def _activo():
    _rutas.clear()
    cliente_original = httpx2.Client
    server._client = None

    def cliente_mockeado(*args, **kwargs):
        kwargs["transport"] = httpx2.MockTransport(_handler)
        return cliente_original(*args, **kwargs)

    httpx2.Client = cliente_mockeado
    try:
        yield
    finally:
        httpx2.Client = cliente_original
        server._client = None
        _rutas.clear()


class _Mock:
    """Equivalente a ``respx.mock``, que valía a la vez de decorador y de context manager.

    La suite usa las dos formas: ``@backend_mock.mock`` sobre el test, y ``with backend_mock.mock:``
    cuando solo hace falta mockear un tramo.
    """

    def __init__(self) -> None:
        self._pila: list = []

    def __call__(self, func):
        @functools.wraps(func)
        def envoltorio(*args, **kwargs):
            with _activo():
                return func(*args, **kwargs)

        return envoltorio

    def __enter__(self):
        contexto = _activo()
        self._pila.append(contexto)
        return contexto.__enter__()

    def __exit__(self, *excepcion):
        return self._pila.pop().__exit__(*excepcion)


mock = _Mock()


# --- Modo «cuenta cambios» (T10 de daemon-reparte-el-backend) ----------------------------------


def _ok_response(model: str) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={"choices": [{"message": {"content": f"ok de {model}"}, "finish_reason": "stop"}]},
    )


class ChangeCount:
    """Un backend de chat que atiende UNA petición a la vez, en orden de llegada, y cuenta cambios.

    Hace lo que hace llama-swap con `-np 1` y su cola FIFO: la segunda petición espera a que acabe
    la primera. Cada vez que el modelo servido difiere del anterior cuenta un **cambio** (el primero
    no cuenta: cargar el primer modelo no quita a nadie). Es lo que mide si dos operaciones se
    quitan el modelo una a otra.

    - `latency_s`: lo que tarda en contestar cada petición, ya con el turno de servicio.
    - `barrera`: si es N > 0, ninguna petición se atiende hasta que hayan **llegado** N, con un tope
      de `barrier_cap_s`. Si el tope vence, `did_not_overlap` queda en `True`: las N no estuvieron
      a la vez dentro del daemon (cada una con su plaza).
    - `responder(modelo, request)`: la respuesta; por defecto, un 200 con `ok de <modelo>`.
    """

    def __init__(
        self,
        *,
        latency_s: float = 0.01,
        barrier: int = 0,
        barrier_cap_s: float = 2.0,
        respond: Callable[[str, httpx2.Request], httpx2.Response] | None = None,
    ) -> None:
        self.latency_s = latency_s
        self.barrier = barrier
        self.barrier_cap_s = barrier_cap_s
        self.respond = respond or (lambda model, _request: _ok_response(model))
        self.arrivals: list[str] = []
        self.served: list[str] = []
        self.changes = 0
        self.did_not_overlap = False
        self._cond = threading.Condition()
        self._next = 0
        self._serving = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        model = json.loads(request.content)["model"]
        with self._cond:
            self.arrivals.append(model)
            self._cond.notify_all()
            if self.barrier:
                end = time.monotonic() + self.barrier_cap_s
                while len(self.arrivals) < self.barrier:
                    remaining = end - time.monotonic()
                    if remaining <= 0:
                        self.did_not_overlap = True
                        break
                    self._cond.wait(remaining)
            ticket = self._next
            self._next += 1
            while ticket != self._serving:
                self._cond.wait()
            if self.served and self.served[-1] != model:
                self.changes += 1
            self.served.append(model)
        try:
            time.sleep(self.latency_s)
            return self.respond(model, request)
        finally:
            with self._cond:
                self._serving += 1
                self._cond.notify_all()


def count_changes(url: str, **options) -> ChangeCount:
    """Registra el POST de chat en modo «cuenta cambios» y devuelve el contador."""
    server = ChangeCount(**options)
    post(url).mock(side_effect=server)
    return server
