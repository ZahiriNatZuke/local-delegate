"""Utilidades stdlib para hooks consultivos de local-delegate.

La telemetria es opt-in y nunca escribe prompts, comandos ni paths: solo evento, categoria,
tamaño y banda. El log se activa con ``LD_HOOK_TELEMETRY_LOG``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path


def enabled() -> bool:
    """Interruptor del EXPERIMENTO, no el de encendido de un hook. La diferencia importa.

    `LD_HOOK_ENABLED=0` es lo que pone una sesion en rama baseline de un A/B: ni sugiere ni
    registra, para que el log de la rama piloto sea solo del piloto. Por eso apaga tambien la
    telemetria, que en cualquier otro contexto seria un error.

    **Solo puede apagar, nunca encender.** Que un hook este activo lo decide el registro
    (`settings.json`), y de ahi no se sale: cuando la unica puerta era una variable de entorno,
    `install --enable-read-hook` registro el script sin ponerla y el hook quedo instalado e
    inerte, en silencio. Esa es la historia que hay detras de `esta_encendido()` en
    `suggest_delegate_read.py`, y la razon de que ningun hook nuevo deba mirar aqui para saber
    si nacio encendido.
    """
    return os.environ.get("LD_HOOK_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def record(event: str, **metadata: object) -> None:
    if not enabled():
        return
    destination = os.environ.get("LD_HOOK_TELEMETRY_LOG", "").strip()
    if not destination:
        return
    payload = {"ts": datetime.now(UTC).isoformat(), "event": event, **metadata}
    try:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        # La telemetría es best-effort y corre dentro de un hook del agente: si el destino no se
        # puede crear o escribir (permisos, disco lleno, ruta inválida en LD_HOOK_TELEMETRY_LOG),
        # perder una línea de log es preferible a romperle la operación al usuario.
        pass


def emit(event: str, context: str, **metadata: object) -> None:
    """Camino CONSULTIVO: le pasa un texto al modelo y el modelo hace lo que quiera con el."""
    if not enabled():
        return
    record(event, suggested=True, **metadata)
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": context,
                }
            },
            ensure_ascii=False,
        )
    )


def emit_updated_input(
    event: str,
    updated_input: dict,
    *,
    context: str | None = None,
    **metadata: object,
) -> None:
    """Camino que CAMBIA lo que se va a ejecutar: reescribe `tool_input` antes de la llamada.

    Va separado de `emit()` a proposito, y no por gusto de simetria. `emit` sugiere y el modelo
    decide; esto sustituye la entrada de la tool, y el permiso del usuario **se evaluo sobre el
    comando original** —medido: con `--allowedTools "Bash(echo:*)"`, un hook que reescribio a un
    `python -c` lo ejecuto igual—. O sea que un fallo aqui no es un consejo malo: es un comando
    distinto del que se autorizo. De ahi tres cosas:

    - la reescritura que llegue debe ser minima y mecanica, y eso lo garantiza quien llama;
    - siempre deja huella en la telemetria, para que sea auditable a posteriori;
    - `context` es opcional: sirve para decirle al modelo que se reescribio y donde quedo la
      salida, que es lo que evita que la reescritura parezca magia.

    `updated_input` es el `tool_input` COMPLETO que se quiere en su lugar, no un parche.
    """
    if not enabled():
        return
    record(event, rewritten=True, **metadata)
    salida: dict = {"hookEventName": event, "updatedInput": updated_input}
    if context:
        salida["additionalContext"] = context
    print(json.dumps({"hookSpecificOutput": salida}, ensure_ascii=False))
