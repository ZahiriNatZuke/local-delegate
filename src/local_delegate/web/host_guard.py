"""Guarda del `Host` y el `Origin` del puerto del daemon: la defensa contra el DNS rebinding.

El ataque, medido en la revisión del 2026-10-23: una web cualquiera hace que su propio nombre
(`evil.example`) resuelva a `127.0.0.1`, y desde ese momento el navegador trata al daemon como si
fuera **del mismo origen** que la web atacante. Sin token —la configuración por defecto— eso lee
`/api/events`, `/api/status`, `/api/system` y `/api/hooks` enteros, y `POST /api/hook/classify`
sirve de oráculo para saber si existe cualquier fichero y cuánto pesa. Lo único que el navegador no
puede falsificar es la cabecera `Host`: lleva el nombre del atacante, no `127.0.0.1`.

El SDK de MCP ya hace esta comprobación, pero **solo en `/mcp`** (`streamable_http_app(host=…)`), y
el panel está montado en `/` fuera de su alcance. Esta guarda envuelve la raíz —igual que
`auth.protect`— para que una ruta nueva quede cubierta por existir, y le pasa al SDK la **misma**
lista (:func:`transport_security`), para que los dos sitios no puedan discrepar sobre qué host vale.

Qué se admite:

- Siempre `127.0.0.1`, `localhost` y `::1` (con cualquier puerto): el navegador local, los hooks,
  el mod, el puente de Claude Desktop y el MCP en modo http llegan por ahí.
- El propio ``LOCAL_DELEGATE_WEB_HOST`` cuando es una interfaz concreta: quien escucha en una IP
  la recibe como `Host`.
- Los de ``LOCAL_DELEGATE_WEB_ALLOWED_HOSTS`` (separados por comas): el nombre con el que llega un
  proxy delante, como `tailscale serve` (`own-pc.tailXXXX.ts.net`). ``*`` desactiva la guarda.

Cuándo no se aplica: si el daemon escucha en todas las interfaces (`0.0.0.0`, `::`) y no hay hosts
extra, porque entonces no hay forma de saber por qué nombre o IP llegarán los clientes de la LAN; es
lo mismo que hace el SDK en `/mcp`. Con hosts extra la guarda vuelve a aplicarse.

La guarda **no es control de acceso**: un cliente que no sea un navegador puede mandar el `Host`
que quiera. Para eso está el token (`LOCAL_DELEGATE_WEB_TOKEN`). Lo que cierra es la puerta que
solo tiene un navegador: el rebinding y, con el `Origin`, el POST de otra web contra `127.0.0.1`.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from .. import config

#: Hosts de loopback, siempre admitidos.
LOOPBACK_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")

#: Valores de ``LOCAL_DELEGATE_WEB_HOST`` que significan «todas las interfaces».
_WILDCARD_BINDS = frozenset({"", "0.0.0.0", "::", "[::]"})

#: El texto de la respuesta: el mismo del SDK más dónde se arregla. No dice qué hosts valen.
_HOST_MESSAGE = b"Invalid Host header (allowed hosts: LOCAL_DELEGATE_WEB_ALLOWED_HOSTS)\n"
_ORIGIN_MESSAGE = b"Invalid Origin header (allowed hosts: LOCAL_DELEGATE_WEB_ALLOWED_HOSTS)\n"


def _normalize(host: str) -> str:
    """Un nombre de host comparable: minúsculas, sin corchetes de IPv6 ni punto final."""
    host = host.strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host.rstrip(".")


def host_from_header(value: str) -> str:
    """El nombre de host de una cabecera `Host` (`nombre`, `nombre:puerto`, `[::1]:puerto`).

    El puerto se descarta a propósito: el ataque se distingue por el nombre, y un proxy delante
    (`tailscale serve`) puede publicar el daemon en otro puerto.
    """
    value = value.strip()
    if value.startswith("["):
        end = value.find("]")
        return _normalize(value[1:end]) if end != -1 else ""
    if value.count(":") == 1:
        value = value.split(":", 1)[0]
    return _normalize(value)


def allowed_hosts(
    bind_host: str | None = None, extra: Iterable[str] | None = None
) -> frozenset[str] | None:
    """Los hosts admitidos, o ``None`` si la guarda no se aplica.

    ``None`` en dos casos: ``*`` entre los hosts extra (desactivación explícita), o escucha en todas
    las interfaces sin hosts extra (no hay lista posible; mismo criterio que el SDK).
    """
    bind = config.WEB_HOST if bind_host is None else bind_host
    extras = [_normalize(h) for h in (config.WEB_ALLOWED_HOSTS if extra is None else extra)]
    extras = [h for h in extras if h]
    if "*" in extras:
        return None
    wildcard = _normalize(bind) in {_normalize(w) for w in _WILDCARD_BINDS}
    if wildcard and not extras:
        return None
    hosts = set(LOOPBACK_HOSTS) | set(extras)
    if not wildcard:
        hosts.add(_normalize(bind))
    return frozenset(hosts)


def transport_security(bind_host: str | None = None, extra: Iterable[str] | None = None):
    """Los ajustes del SDK de MCP para `/mcp`, sacados de la misma lista que la guarda."""
    from mcp.server.transport_security import TransportSecuritySettings

    hosts = allowed_hosts(bind_host, extra)
    if hosts is None:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    hostports: list[str] = []
    origins: list[str] = []
    for host in sorted(hosts):
        shown = f"[{host}]" if ":" in host else host
        hostports += [shown, f"{shown}:*"]
        for scheme in ("http", "https"):
            origins += [f"{scheme}://{shown}", f"{scheme}://{shown}:*"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hostports, allowed_origins=origins
    )


def _origin_allowed(origin: str, hosts: frozenset[str]) -> bool:
    """¿Viene de una página que el daemon admite?

    Solo puede atacar una página web, así que lo que se rechaza es lo que una página produce: un
    origen `http(s)` de otro host y `null` (iframe con sandbox, `data:`). Un origen de otro esquema
    (`app://`, `vscode-webview://`) no lo puede fabricar una web y se deja pasar, para no romper a
    un cliente embebido que no se conozca.
    """
    origin = origin.strip()
    if origin.lower() == "null":
        return False
    parts = urlsplit(origin)
    if parts.scheme.lower() not in ("http", "https"):
        return True
    return _normalize(parts.hostname or "") in hosts


class HostGuard:
    """Middleware ASGI puro: 421 a un `Host` ajeno y 403 a un `Origin` de otra web.

    Puro y no de Starlette por la misma razón que `auth.PortToken`: envuelve la raíz del daemon y
    cubre todo lo montado debajo sin depender de a qué app se añade.
    """

    def __init__(self, app, hosts: frozenset[str]):
        self.app = app
        self.hosts = hosts

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []
        }
        if host_from_header(headers.get("host", "")) not in self.hosts:
            await self._reject(scope, send, 421, _HOST_MESSAGE)
            return
        origin = headers.get("origin")
        if origin is not None and not _origin_allowed(origin, self.hosts):
            await self._reject(scope, send, 403, _ORIGIN_MESSAGE)
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(scope, send, status: int, body: bytes) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def protect(app, bind_host: str | None = None, extra: Iterable[str] | None = None):
    """Envuelve `app` con la guarda, o la devuelve tal cual si la guarda no se aplica."""
    hosts = allowed_hosts(bind_host, extra)
    return app if hosts is None else HostGuard(app, hosts)
