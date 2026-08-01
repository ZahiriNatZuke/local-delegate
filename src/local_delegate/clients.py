"""Observador de clientes MCP: qué capabilities declara cada uno y qué protocolo negoció.

Hasta ahora el daemon no sabía con qué hablaba: ni una ocurrencia de `capabilities` en el paquete.
El log de uso anota el coste de cada llamada, pero su campo `source` dice de dónde salió el
contenido ("path"/"inline"), no quién llamó.

Se engancha como `ServerMiddleware` del SDK, que corre en TODO mensaje inbound. Ojo con la pieza:
no es el `Extension`/`intercept_tool_call` (SEP-2133), que este repo descartó para telemetría
porque el coste real vive en los caminos al backend y no en el borde MCP. Aquí es al revés — la
identidad del cliente SOLO existe en el borde—, así que el sitio correcto es justo este.

Tres cosas medidas contra el SDK instalado, no leídas de la documentación (traza en
`.sdd/changes/observador-capabilities-cliente/research.md`):

1. Durante `initialize` no hay nada que leer: el middleware corre ANTES del commit del handshake y
   ve `client_capabilities` y `client_params` en None. El primer mensaje útil es
   `notifications/initialized`.
2. La revisión negociada no la predicen las constantes del SDK: con `LATEST_PROTOCOL_VERSION` en
   2026-07-28 y `DEFAULT_NEGOTIATED_VERSION` en 2025-03-26, lo negociado fue **2025-11-25**. Por eso
   el dato se mide en vez de deducirse.
3. Desde la revisión 2026-07-28 las capabilities viajan en el envelope de cada petición y el
   `client_info` es opcional: puede haber capabilities SIN identidad. Por eso las dos cosas se leen
   por separado y el nombre puede faltar.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import config

# Nombre del fichero dentro de LOG_DIR. Separado de usage.jsonl a propósito: aquel es contabilidad
# por llamada y este es identidad por cliente; mezclarlos obligaría a filtrar en todo el que lea.
LOG_FILENAME = "clients.jsonl"

# Techo y sufijo del rotado. Medido: el registro crece ~144 B por arranque de proceso MCP —una
# línea por identidad nueva, no por mensaje—, así que harían falta unos 1800 arranques para llegar
# a este techo. Es a propósito un número que no se alcanza en uso normal: la rotación existe para
# que el fichero no crezca **sin límite**, no para recortarlo cada semana.
#
# Se rota por tamaño y NO por mes, y la diferencia importa: lo que este fichero responde es «¿qué
# clientes se han visto?», y un corte mensual haría desaparecer del diagnóstico a un cliente visto
# en enero por el simple hecho de que llegó febrero. Eso sería peor que el problema que arregla.
MAX_BYTES = 256 * 1024
SUFIJO_ROTADO = ".1"

# Claves EXACTAS de una línea del registro. Las fija aquí y no en el punto de escritura para que el
# test pueda aseverar el conjunto completo: así un campo colado por descuido —una cabecera, una
# ruta— rompe el test en vez de acabar en disco.
CAMPOS = ("ts", "client", "version", "protocol", "caps")


@dataclass(frozen=True)
class _Identidad:
    """Lo que distingue a un cliente. Congelada porque es la clave del registro."""

    client: str | None
    version: str | None
    protocol: str
    caps: tuple[str, ...]


# El registro vivo de esta ejecución del daemon. Lo lee /api/status, que en FastAPI es un endpoint
# SÍNCRONO y por tanto corre en el threadpool de uvicorn: la concurrencia aquí es de hilos, no de
# corrutinas, así que el lock no es decorativo.
_VISTOS: dict[_Identidad, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def nombres_capabilities(caps: Any) -> tuple[str, ...]:
    """Los nombres de las capabilities declaradas, ordenados.

    Distingue tres casos que no son el mismo: no haber declarado nada (None), haber declarado el
    objeto vacío (tupla vacía) y haber declarado alguna. Un campo en None dentro del objeto es una
    capability NO declarada, así que no cuenta.
    """
    if caps is None:
        return ()
    try:
        datos = caps.model_dump(exclude_none=True)
    except AttributeError:  # no es un modelo del SDK; no se inventa nada
        return ()
    return tuple(sorted(k for k, v in datos.items() if v is not None))


def _rotar_si_toca(destino: Path) -> None:
    """Aparta el registro cuando pasa del techo, conservando UNA generación.

    Rotar y no truncar: quien lee el registro pregunta «¿qué clientes se han visto?», y truncar
    respondería «ninguno» sobre una máquina donde sí se vieron. Con la generación apartada, el
    diagnóstico sigue encontrándolos —ver :func:`rutas_para_leer`.

    `os.replace` es atómico y sobreescribe la generación anterior en los tres sistemas; con
    `Path.rename` esto fallaría en Windows en cuanto existiera un `.1`.

    Best-effort como todo lo que escribe este módulo: si no se puede rotar, se sigue anexando. Un
    fichero grande es un inconveniente; una excepción aquí sube por el middleware y afecta a la
    respuesta que se le da al cliente MCP.
    """
    try:
        if destino.stat().st_size < MAX_BYTES:
            return
        os.replace(destino, destino.with_name(destino.name + SUFIJO_ROTADO))
    except OSError:
        # No se pudo mirar el tamaño o no se pudo renombrar (fichero abierto por otro proceso en
        # Windows, disco lleno, permisos). Se sigue anexando a propósito: un registro que crece de
        # más es un inconveniente, y una excepción aquí sube por el middleware MCP y afecta a la
        # respuesta que se le da al cliente. Observar nunca puede empeorar la conversación.
        pass


def _escribir_linea(destino: Path, linea: str) -> None:
    """Anexa una línea al registro. Punto único de E/S, para que el test pueda doblarlo.

    Se dobla ESTA función en las pruebas en vez de jugar con permisos del sistema de ficheros:
    en Windows `chmod` no los aplica como en POSIX y el test mediría una cosa distinta en cada
    runner.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    _rotar_si_toca(destino)
    with destino.open("a", encoding="utf-8") as f:
        f.write(linea)


def ruta_registro() -> Path:
    """Dónde vive el registro. Pública porque el diagnóstico también lo lee.

    `checks.py` la consume en vez de recomponer la ruta por su cuenta: el nombre del fichero y su
    directorio se saben en UN solo sitio, que es este. Dos fuentes para el mismo dato es la clase
    de defecto que este repo ya tuvo que arreglar tres veces.
    """
    # `config.LOG_DIR` se lee AQUÍ, en tiempo de llamada, y no como default de módulo: un default
    # capturado en el import no se dobla con monkeypatch.
    return config.LOG_DIR / LOG_FILENAME


def rutas_para_leer() -> list[Path]:
    """Los ficheros del registro que hay que leer, **del más viejo al más nuevo**.

    Función aparte de :func:`ruta_registro` porque son dos preguntas distintas: aquella responde
    «¿dónde escribo?» y esta «¿dónde está todo lo anotado?». Desde que el registro rota, la
    segunda ya no es la primera, y quien lea solo la primera perdería de vista a un cliente por
    haber rotado — el mismo defecto que la rotación pretendía evitar, girado del revés.

    Devuelve solo las que existen: la ausencia de la generación rotada es lo normal.
    """
    viva = ruta_registro()
    rotada = viva.with_name(viva.name + SUFIJO_ROTADO)
    return [p for p in (rotada, viva) if p.is_file()]


def registrar(caps: Any, client_info: Any, protocol: str) -> bool:
    """Anota esta identidad si es la primera vez que se ve. Devuelve si escribió línea.

    El lock cubre comprobar + escribir + añadir como UNA operación. Separarlo dejaría que dos
    mensajes concurrentes comprobaran antes de que ninguno añadiera, y escribirían dos líneas para
    la misma identidad. Sí, eso hace una escritura a disco con el lock tomado: es aceptable porque
    ocurre una vez por identidad, no por mensaje.
    """
    nombres = nombres_capabilities(caps)
    nombre = getattr(client_info, "name", None) if client_info is not None else None
    version = getattr(client_info, "version", None) if client_info is not None else None

    # Ni capabilities ni identidad: no hay nada que informar, y una línea vacía contaminaría la
    # lectura del registro (que es justo para decidir si algún cliente soporta elicitation).
    if caps is None and client_info is None:
        return False

    ident = _Identidad(client=nombre, version=version, protocol=protocol, caps=nombres)
    ahora = _utcnow().isoformat(timespec="seconds")

    with _LOCK:
        previo = _VISTOS.get(ident)
        if previo is not None:
            previo["last_seen"] = ahora
            previo["messages"] += 1
            return False

        _VISTOS[ident] = {
            "client": nombre,
            "version": version,
            "protocol": protocol,
            "caps": list(nombres),
            "first_seen": ahora,
            "last_seen": ahora,
            "messages": 1,
        }
        linea = json.dumps(
            {
                "ts": ahora,
                "client": nombre,
                "version": version,
                "protocol": protocol,
                "caps": list(nombres),
            },
            ensure_ascii=False,
        )
        _escribir_linea(ruta_registro(), linea + "\n")
        return True


def snapshot() -> list[dict[str, Any]]:
    """Los clientes vistos en esta ejecución, como estructura nueva y desligada.

    La copia se arma DENTRO del lock. Devolver los dicts internos dejaría que el serializador JSON
    de /api/status los recorriera desde el threadpool mientras el middleware los muta desde el loop
    del MCP: un fallo intermitente en el endpoint que alimenta el panel.
    """
    with _LOCK:
        return [dict(v) for v in _VISTOS.values()]


def reset() -> None:
    """Vacía el registro en memoria. Para las pruebas; el daemon nunca lo llama."""
    with _LOCK:
        _VISTOS.clear()


async def observar_cliente(ctx: Any, call_next: Any) -> Any:
    """Middleware: observa y sigue. Nunca altera la petición ni la rompe.

    Se salta `initialize` por lo medido —ahí todavía no hay datos— y porque es la zona donde el SDK
    avisa de que hablarle al cliente bloquea la conexión: quien toque esto después, que no meta
    aquí una llamada al cliente.
    """
    if ctx.method != "initialize":
        try:
            sesion = ctx.session
            registrar(
                sesion.client_capabilities,
                getattr(sesion.client_params, "client_info", None),
                ctx.protocol_version,
            )
        except Exception:
            pass  # observar es best-effort; jamás propaga a la respuesta del cliente
    return await call_next(ctx)
