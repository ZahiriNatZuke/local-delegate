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
