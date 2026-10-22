"""Puente MCP por stdio hacia el daemon HTTP, para el chat de Claude Desktop (REQ-012, solo Windows).

El chat de Desktop solo arranca MCP locales por stdio, no les pasa el entorno del usuario y no
expande `${VAR}` en su config (medido el 2026-10-21). La entrada que hasta ahora lo conectaba al
daemon (`npx mcp-remote … Bearer <token>`) llevaba el token escrito. Este puente la sustituye: lo
lanza Desktop como `local-delegate desktop-bridge`, lee el token del registro
(:mod:`token_source`) y reenvía cada mensaje JSON-RPC al `/mcp` del daemon.

Qué hace con el transporte *streamable HTTP* del daemon:

- Cada línea de stdin es un mensaje y va en un POST. La respuesta puede ser JSON o un flujo SSE;
  cada mensaje que traiga sale por stdout en una línea.
- Guarda el `Mcp-Session-Id` del `initialize` y la versión de protocolo, y los manda después.
- `initialize`, notificaciones y respuestas van en orden; las demás peticiones van en paralelo,
  para que una delegación larga no bloquee un `ping` o una cancelación.
- Un 401 hace releer el token una vez (pudo rotarse) y, si sigue, sale como error MCP que dice qué
  variable mirar. Daemon caído: error MCP con la URL. Sesión olvidada (el daemon se reinició): la
  rehace con el mismo `initialize` y repite la petición una vez.
- Desktop lanza cada servidor dos veces (chat y Cowork/Code): cada puente es un proceso con su
  sesión y no comparte nada en disco, así que dos a la vez no se estorban.

El token solo va en la cabecera `Authorization`: no se imprime, no se registra y no se escribe.
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import IO

import anyio
import httpx2

from . import config, i18n, json_state, token_source

# Igual que `daemon.MCP_PATH` (lo comprueba la suite). No se importa `daemon` porque arrastra el
# servidor MCP entero, y este proceso lo lanza Desktop dos veces en cada arranque.
MCP_PATH = "/mcp"

ERROR_PARSE = -32700
ERROR_DAEMON_DOWN = -32001
ERROR_TOKEN_REJECTED = -32002
ERROR_HTTP = -32003
ERROR_NO_ANSWER = -32004

_ACCEPT = "application/json, text/event-stream"
# Sin tope de lectura: una delegación a un modelo local puede tardar minutos con el SSE abierto.
_TIMEOUT = httpx2.Timeout(connect=5.0, read=None, write=30.0, pool=None)
_CLOSE_TIMEOUT = 2.0
_DETAIL_CHARS = 300

Write = Callable[[bytes], Awaitable[None]]


class _BridgeError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def daemon_url() -> str:
    """La URL de `/mcp` del daemon: la que dejó escrita él en `daemon.json`, o la configurada.

    `daemon.json` va primero porque Desktop no pasa el entorno: si el usuario cambió el puerto con
    una variable, este proceso no la ve, pero el daemon sí la vio al arrancar y la escribió ahí.
    """
    state = json_state.read_json(config.LOG_DIR / "daemon.json")
    host, port = state.get("host"), state.get("port")
    if not isinstance(host, str) or not isinstance(port, int) or isinstance(port, bool):
        host, port = config.WEB_HOST, config.WEB_PORT
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}{MCP_PATH}"


class Bridge:
    """Una conexión stdio de Desktop contra el daemon: una sesión MCP, un cliente HTTP."""

    def __init__(
        self,
        url: str,
        *,
        token_provider: Callable[[], str] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.url = url
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        self._provider = token_provider
        self._cached_token: str | None = None
        self._log = log or (lambda message: print(message, file=sys.stderr, flush=True))
        self._init_line: bytes | None = None
        self._write: Write | None = None
        self._client: httpx2.AsyncClient | None = None
        self._write_lock = anyio.Lock()
        self._session_lock = anyio.Lock()

    def _token(self, refresh: bool = False) -> str:
        if refresh or self._cached_token is None:
            # Sin proveedor se busca `token_source.web_token` al llamar, no al construir: así la
            # fuente es siempre la vigente (y la suite puede sustituirla).
            provider = self._provider or token_source.web_token
            self._cached_token = (provider() or "").strip()
        return self._cached_token

    def _headers(self, *, with_session: bool) -> dict[str, str]:
        headers = {"Accept": _ACCEPT, "Content-Type": "application/json"}
        token = self._token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if with_session and self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if with_session and self.protocol_version:
            headers["Mcp-Protocol-Version"] = self.protocol_version
        return headers

    async def run(self, lines: AsyncIterator[bytes], write: Write) -> None:
        """Lee mensajes de `lines` hasta agotarlas y escribe las respuestas con `write`."""
        self._write = write
        async with httpx2.AsyncClient(timeout=_TIMEOUT) as client:
            self._client = client
            try:
                async with anyio.create_task_group() as group:
                    async for raw in lines:
                        line = raw.strip()
                        if not line:
                            continue
                        try:
                            message = json.loads(line)
                        except ValueError:
                            await self._emit_error(None, ERROR_PARSE, i18n.t("bridge.error.parse"))
                            continue
                        if self._is_request(message) and message["method"] != "initialize":
                            group.start_soon(self._forward, line, message)
                        else:
                            await self._forward(line, message)
            finally:
                await self._close_session()

    @staticmethod
    def _is_request(message: object) -> bool:
        return isinstance(message, dict) and "method" in message and "id" in message

    async def _forward(self, line: bytes, message: object) -> None:
        is_request = self._is_request(message)
        request_id = message.get("id") if is_request else None  # type: ignore[union-attr]
        is_init = is_request and message.get("method") == "initialize"  # type: ignore[union-attr]
        if is_init:
            self._init_line = line
        try:
            answered = await self._post(line, is_init=is_init, request_id=request_id)
            if is_request and not answered:
                raise _BridgeError(ERROR_NO_ANSWER, i18n.t("bridge.error.no_answer"))
        except _BridgeError as error:
            if is_request:
                await self._emit_error(request_id, error.code, error.message)
            else:
                self._log(error.message)

    async def _post(self, line: bytes, *, is_init: bool, request_id: object) -> bool:
        """Manda `line` y entrega lo que vuelva. Devuelve si llegó la respuesta a `request_id`."""
        assert self._client is not None
        refreshed = recovered = False
        while True:
            session = self.session_id
            try:
                async with self._client.stream(
                    "POST", self.url, content=line, headers=self._headers(with_session=not is_init)
                ) as response:
                    status = response.status_code
                    if status == 401:
                        await response.aread()
                        if not refreshed:
                            refreshed = True
                            previous = self._token()
                            if self._token(refresh=True) != previous:
                                continue
                        raise _BridgeError(
                            ERROR_TOKEN_REJECTED,
                            i18n.t(
                                "bridge.error.token_rejected", variable=token_source.TOKEN_VARIABLE
                            ),
                        )
                    if status == 404 and session and not is_init and not recovered:
                        await response.aread()
                        recovered = True
                        await self._rebuild_session(session)
                        continue
                    if status >= 400:
                        body = (await response.aread()).decode("utf-8", "replace")
                        raise _BridgeError(
                            ERROR_HTTP,
                            i18n.t(
                                "bridge.error.http_status",
                                status=status,
                                url=self.url,
                                detail=body.strip()[:_DETAIL_CHARS],
                            ),
                        )
                    if is_init and response.headers.get("mcp-session-id"):
                        self.session_id = response.headers["mcp-session-id"]
                    return await self._read_body(response, is_init=is_init, request_id=request_id)
            except httpx2.HTTPError as exc:
                raise _BridgeError(
                    ERROR_DAEMON_DOWN,
                    i18n.t("bridge.error.daemon_down", url=self.url, detail=type(exc).__name__),
                ) from exc

    async def _read_body(
        self, response: httpx2.Response, *, is_init: bool, request_id: object
    ) -> bool:
        kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
        answered = False
        if kind == "text/event-stream":
            data: list[str] = []
            async for text in response.aiter_lines():
                if text == "":
                    if data:
                        answered |= await self._deliver("\n".join(data), is_init, request_id)
                        data = []
                    continue
                field, _, value = text.partition(":")
                if field == "data":
                    data.append(value.removeprefix(" "))
            if data:
                answered |= await self._deliver("\n".join(data), is_init, request_id)
        else:
            body = (await response.aread()).decode("utf-8", "replace")
            if body.strip():
                answered = await self._deliver(body, is_init, request_id)
        return answered

    async def _deliver(self, text: str, is_init: bool, request_id: object) -> bool:
        """Escribe un mensaje del daemon en stdout, en una línea. ¿Era la respuesta esperada?"""
        try:
            message = json.loads(text)
        except ValueError:
            self._log(i18n.t("bridge.error.parse"))
            return False
        if is_init and isinstance(message, dict):
            version = (message.get("result") or {}).get("protocolVersion")
            if isinstance(version, str):
                self.protocol_version = version
        await self._send(message)
        return (
            request_id is not None
            and isinstance(message, dict)
            and "method" not in message
            and message.get("id") == request_id
        )

    async def _send(self, message: object) -> None:
        assert self._write is not None
        data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        async with self._write_lock:
            await self._write(data)

    async def _emit_error(self, request_id: object, code: int, message: str) -> None:
        await self._send(
            {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
        )

    async def _rebuild_session(self, stale: str) -> None:
        """El daemon ya no conoce `stale`: repite el `initialize` del cliente y sigue con otra."""
        assert self._client is not None
        async with self._session_lock:
            if self.session_id != stale:
                return  # otra petición ya la rehízo
            if self._init_line is None:
                raise _BridgeError(ERROR_HTTP, i18n.t("bridge.error.session_lost"))
            response = await self._client.post(
                self.url, content=self._init_line, headers=self._headers(with_session=False)
            )
            new_session = response.headers.get("mcp-session-id")
            if response.status_code >= 400 or not new_session:
                raise _BridgeError(ERROR_HTTP, i18n.t("bridge.error.session_lost"))
            self.session_id = new_session
            await self._client.post(
                self.url,
                content=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                headers=self._headers(with_session=True),
            )
            self._log(i18n.t("bridge.log.session_recovered"))

    async def _close_session(self) -> None:
        """Avisa al daemon de que la sesión acabó, para que no la guarde. Sin insistir."""
        if not self.session_id or self._client is None:
            return
        try:
            with anyio.move_on_after(_CLOSE_TIMEOUT):
                await self._client.delete(self.url, headers=self._headers(with_session=True))
        except httpx2.HTTPError:
            # El daemon ya no está o no responde: la sesión morirá con él, no hay nada que hacer.
            pass


def main(
    argv: list[str] | None = None,
    *,
    stdin: IO[bytes] | None = None,
    stdout: IO[bytes] | None = None,
    stderr: IO[str] | None = None,
) -> int:
    """`local-delegate desktop-bridge [--url URL]`: puente stdio hasta que Desktop cierre stdin."""
    args = list(sys.argv[1:] if argv is None else argv)
    err = stderr or sys.stderr

    def log(message: str) -> None:
        print(message, file=err, flush=True)

    url = None
    if args[:1] == ["--url"] and len(args) == 2:
        url = args[1]
    elif args:
        log(i18n.t("bridge.error.usage"))
        return 2
    url = url or daemon_url()
    source_in = stdin or sys.stdin.buffer
    sink = stdout or sys.stdout.buffer

    bridge = Bridge(url, log=log)
    state = "bridge.log.token_present" if bridge._token() else "bridge.log.token_absent"
    log(i18n.t("bridge.log.started", url=url, token=i18n.t(state)))

    async def lines() -> AsyncIterator[bytes]:
        while True:
            line = await anyio.to_thread.run_sync(source_in.readline)
            if not line:
                return
            yield line

    async def write(data: bytes) -> None:
        sink.write(data + b"\n")
        sink.flush()

    try:
        anyio.run(bridge.run, lines(), write)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
