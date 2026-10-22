#!/usr/bin/env python3
"""Hook PreToolUse (matcher: Read) para local-delegate.

Es experimental y queda apagado por defecto tras el piloto A/B. Se enciende de dos formas
equivalentes: el argumento --enabled (que es como lo registra `install --enable-read-hook`) o
LD_HOOK_READ_ENABLED=1 en el entorno (para quien lo instale a mano siguiendo la recipe).

Que sean dos y no una tiene historia: antes SOLO valía la variable, y `--enable-read-hook`
registraba el script sin ponerla. Eran dos puertas y la bandera abría una, así que la opción no
hacía nada — y en silencio. Ahora el registro mismo enciende el hook, que es lo que hace que
`install`/`uninstall` sean la única fuente de si está activo o no.

Sólo avisa de lo que de verdad se puede delegar. Medido sobre 14 días de uso real (49 sesiones,
1 579 lecturas): la versión anterior avisaba en 572 de 852 lecturas y sólo 29 apuntaban a una
transformación global. Las otras eran código que hay que leer literal para editarlo, franjas
pedidas a propósito con offset/limit, y archivos medianos. Un aviso que acierta el 5 % enseña a
ignorarlo, y se lleva por delante los casos en que tenía razón — así que ahora se calla en los
tres casos y sube los umbrales.

Usa dos bandas: LD_HOOK_READ_SUGGEST_KB (default 8 KB) y LD_HOOK_READ_STRONG_KB (default 100 KB).

El umbral bajo era 32 KB hasta el 2026-09-08, y bajarlo salió de medir, no de opinar: de las 96
lecturas registradas desde que la telemetria guarda la extension, este hook callaba por tamaño 24
veces y LAS 24 eran `.md`, `.json` o `.txt` —ni una de codigo—, con 17 entre 8 y 16 KB. O sea que
la franja donde vive la documentacion de un repo quedaba muda, y lo que parecia desobediencia era
un aviso que nunca llegaba. La banda `strong` se deja en 100 KB a proposito: se cambia UNA cosa,
para que la proxima medicion sepa a que atribuir la diferencia.
**Desde F1 sí puede bloquear, y solo en un caso muy acotado.** Cuatro mediciones seguidas dieron
adopción cero —la última ya con el aviso acertando el tipo de fichero—, así que el problema dejó
de ser la puntería: sugerir no cambia la conducta. La regla bloquea la lectura COMPLETA de un
`.md` o un `.txt` grande, que es donde un resumen puede sustituir a la lectura, y para todo lo
demás sigue avisando como hasta ahora. Un `.json` o un `.log` se leen para encontrar un valor
exacto, y ahí el resumen no sirve.

Tres cosas apagan el bloqueo, y las tres son deliberadas:

- `LD_HOOK_READ_BLOCK=0`, que se lee **en cada invocación**: una sesión abierta hereda el entorno
  del lanzador, así que una variable que solo se mire al arrancar no serviría de freno.
- Que el backend local no responda: bloquear sin sitio a donde delegar deja al agente sin forma de
  leer el fichero.
- El interruptor general del experimento, `LD_HOOK_ENABLED=0`.

Sin dependencias (stdlib únicamente) y multiplataforma.

Instalar en settings.json (ver docs/recipes/claude-code-hooks.md):

  "hooks": {
    "PreToolUse": [
      {"matcher": "Read", "hooks": [
        {"type": "command", "command": "python /ruta/a/suggest_delegate_read.py --enabled"}
      ]}
    ]
  }
"""

from __future__ import annotations

import json
import os
import sys

import read_classifier
from hook_common import (
    backend_available,
    block_state,
    context_of,
    cooled_model,
    deny,
    emit,
    hook_text,
    mod_decision_fields,
    new_id,
    path_digest,
    record,
    record_block,
    summary_model,
)

TRUTHY = {"1", "true", "yes", "on"}
FALSY = {"0", "false", "no", "off"}

#: Prosa: lo que un resumen puede sustituir. Son las dos extensiones con volumen medido —`.md` 49
#: y `.txt` 15 de los 85 avisos del periodo— y las únicas que se bloquean.
PROSE_EXTENSIONS = frozenset({".md", ".txt", ".markdown", ".rst"})

#: Se leen para encontrar un valor exacto: un `package.json`, un `state.json`, la línea del error
#: en un log. Se avisa, pero no se bloquea, porque ahí el resumen no sustituye a la lectura. De
#: `.csv` y `.log` no hubo **ni un aviso** en el periodo medido, así que entrar a bloquearlos
#: habría sido inventar el caso.
DATA_EXTENSIONS = frozenset({".json", ".csv", ".log", ".yaml", ".yml", ".xml", ".toml"})

#: Extensiones que se leen para editarlas, no para transformarlas. Es una constante de módulo y no
#: una lista dentro de la decisión para que ampliarla no obligue a tocar la lógica —y para que un
#: test pueda leerla. Deja fuera a propósito `.md`, `.json`, `.txt`, `.csv` y `.log`, que son los
#: formatos donde un resumen o una extracción sí sustituyen a la lectura entera.
CODE_EXTENSIONS = frozenset(
    {
        ".c",
        ".cpp",
        ".cs",
        ".css",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".php",
        ".prisma",
        ".ps1",
        ".py",
        ".rb",
        ".rs",
        ".scss",
        ".sh",
        ".sql",
        ".svelte",
        ".swift",
        ".toml",
        ".ts",
        ".tsx",
        ".vue",
        ".yaml",
        ".yml",
    }
)

#: Tope de la extensión que va a la telemetría. Una extensión propietaria y larga podría decir algo
#: del trabajo de quien la usa; el log no guarda rutas ni nombres y esto evita que se cuele uno por
#: la puerta de atrás.
MAX_EXT = 12


def is_enabled(argv: list[str] | None = None) -> bool:
    """¿Debe hacer algo este hook? Por el argumento del registro o por el entorno.

    Cualquiera de las dos basta. `argv` se puede inyectar para poder probar la decisión sin
    montar un proceso.
    """
    args = sys.argv[1:] if argv is None else argv
    if "--enabled" in args:
        return True
    return os.environ.get("LD_HOOK_READ_ENABLED", "0").strip().lower() in TRUTHY


def extension_of(file_path: str) -> str:
    """La extensión en minúsculas, acotada y sin nada que identifique al archivo.

    Devuelve `""` cuando no hay extensión, cuando pasa de `MAX_EXT` o cuando trae algo que no sea
    alfanumérico: en esos casos el dato ya no sirve para medir puntería y sí podría decir de más.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if not ext or len(ext) > MAX_EXT or not ext[1:].isalnum():
        return ""
    return ext


def block_on() -> bool:
    """Si la regla puede rechazar una lectura. Se consulta EN CADA invocación, a propósito.

    Nace apagado: se enciende con `LD_HOOK_READ_BLOCK=1`, y se apaga en caliente con el fichero
    de `hook_common.switch_path()`, que gana a la variable. La variable sola no servía de
    freno: una sesión abierta hereda el entorno del lanzador —medido: catorce lecturas con el umbral
    viejo después de cambiarlo— (REQ-F1-11).
    """
    return block_state() == "on"


#: Máximo del nombre de tool que va a la telemetría.
MAX_TOOL = 80


def via_fields(access: read_classifier.Access | None) -> dict:
    """La vía y el alcance que decide el clasificador (REQ-019), para la telemetría por vía."""
    if access is None:
        return {"via": "none", "scope": "unclassifiable"}
    return {"via": access.via, "scope": access.scope}


def record_mcp_read(tool_name: str, tool_input: dict, payload: dict) -> None:
    """Una lectura por la tool de OTRO MCP: se cuenta y nunca se bloquea ni se sugiere (P-6).

    Sin este registro el denominador de la medición no incluye el camino de al lado, y una subida
    de la adopción no distinguiría «se delegó» de «se leyó por otro sitio» (REQ-F1-9).
    """
    paths = tool_input.get("paths")
    if not isinstance(paths, list):
        paths = [tool_input.get("path") or tool_input.get("file_path")]
    paths = [item for item in paths if isinstance(item, str) and item]
    access = read_classifier.classify_tool(tool_name, tool_input)
    fields: dict = {
        "category": "read",
        "route": "mcp",
        "reason": "foreign_mcp",
        "tool": tool_name[:MAX_TOOL],
        "paths": len(paths),
        "block": block_state(),
        **context_of(payload, __file__),
        **via_fields(access),
    }
    if paths:
        fields["path_sha"] = path_digest(paths[0])
        fields["ext"] = extension_of(paths[0])
        try:
            fields["size_kb"] = round(os.path.getsize(paths[0]) / 1024, 1)
        except OSError:
            # El tamaño es un dato extra: si la ruta no existe o no se puede leer (otro MCP puede
            # leer rutas remotas o relativas a su propia raíz), el evento se registra sin él. Perder
            # la lectura del usuario por un `getsize` sería mucho peor que un evento incompleto.
            pass
    record("PreToolUse", suggested=False, **fields)


def main() -> None:
    if not is_enabled():
        return

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    tool_input = payload.get("tool_input") or {}
    tool_name = str(payload.get("tool_name") or "")
    if tool_name.startswith("mcp__"):
        record_mcp_read(tool_name, tool_input, payload)
        return

    access = read_classifier.classify_tool("Read", tool_input)
    if access is None or not access.path:
        return
    file_path = access.path

    ext = extension_of(file_path)
    # La HUELLA de la ruta, nunca la ruta. Sin ella no se puede agrupar por fichero, y esa es la
    # pregunta que la guarda de «acotada» tiene pendiente: de las 277 lecturas por franjas
    # registradas, cuantas eran de un fichero que acabo leyendose entero de todas formas. La
    # telemetria sigue sin poder decir QUE fichero era.
    base_fields = {
        "path_sha": path_digest(file_path),
        "block": block_state(),
        **context_of(payload, __file__),
        **via_fields(access),
    }

    # Las dos guardas siguientes registran en vez de callarse: sin denominador no hay puntería que
    # medir, y no poder medirla es lo que dejó a este hook tres semanas apuntando a código.
    if access.scope == "range":
        record(
            "PreToolUse",
            suggested=False,
            category="read",
            ext=ext,
            reason="bounded",
            **base_fields,
        )
        return

    if ext in CODE_EXTENSIONS:
        record(
            "PreToolUse", suggested=False, category="read", ext=ext, reason="code", **base_fields
        )
        return

    try:
        suggest_kb = float(os.environ.get("LD_HOOK_READ_SUGGEST_KB", "8"))
        strong_kb = float(os.environ.get("LD_HOOK_READ_STRONG_KB", "100"))
        size_kb = os.path.getsize(file_path) / 1024
    except (OSError, ValueError):
        return

    if size_kb <= suggest_kb:
        record(
            "PreToolUse",
            suggested=False,
            category="read",
            ext=ext,
            size_kb=round(size_kb, 1),
            reason="small",
            **base_fields,
        )
        return

    band = "strong" if size_kb > strong_kb else "suggest"
    common = {
        "category": "read",
        "band": band,
        "ext": ext,
        "size_kb": round(size_kb, 1),
        "id": new_id(),
        **base_fields,
    }

    # Solo la prosa se bloquea, y solo si hay a donde delegar. Cada una de las tres guardas
    # siguientes registra su motivo: si la regla se equivoca a menudo, tiene que verse en el dato
    # y no en la irritacion del usuario.
    if ext in PROSE_EXTENSIONS and block_on():
        if not backend_available():
            record("PreToolUse", suggested=False, reason="backend_missing", **common)
        elif cooled_model(summary_model(int(size_kb * 1024))):
            # El servidor no llamaria a ese modelo: bloquear mandaria al agente a un destino que
            # no esta vivo (REQ-F1-10).
            record("PreToolUse", suggested=False, reason="model_cooled", **common)
        else:
            # La nota va ANTES del bloqueo: si el agente delega acto seguido, el servidor tiene
            # que encontrarla ya escrita.
            record_block(common["id"], file_path)
            deny(
                "PreToolUse",
                hook_text("read.block", size_kb=f"{size_kb:.0f}", path=file_path),
                reason="large_prose",
                **common,
            )
            return

    strength = hook_text(f"read.strength.{band}")
    target = hook_text("read.target.data" if ext in DATA_EXTENSIONS else "read.target.any")
    emit(
        "PreToolUse",
        hook_text("read.suggest", strength=strength, size_kb=f"{size_kb:.0f}", target=target),
        **common,
    )


def record_decision(entry: dict) -> None:
    """`hook record-read` de una vía de `Read`, `Grep` o de otro MCP: la línea que habría escrito
    este hook, con la decisión del mod (`hook_common.mod_decision_fields`)."""
    via = str(entry.get("via") or "none")
    path = entry.get("path") if isinstance(entry.get("path"), str) else None
    payload = {"session_id": entry.get("session_id")}
    fields: dict = {
        "category": "read",
        "block": block_state(),
        **context_of(payload, __file__),
        "via": via,
        "scope": str(entry.get("scope") or "unclassifiable"),
        **mod_decision_fields(entry.get("decision")),
    }
    if via.startswith("mcp_"):
        fields["route"] = "mcp"
        fields["tool"] = str(entry.get("tool_name") or via)[:MAX_TOOL]
        fields["paths"] = 1 if path else 0
    elif via == "grep_tool":
        fields["route"] = "grep"
    if path:
        fields["path_sha"] = path_digest(path)
        fields["ext"] = extension_of(path)
        size = entry.get("bytes")
        if isinstance(size, int):
            size_kb = size / 1024
            fields["size_kb"] = round(size_kb, 1)
            if not via.startswith("mcp_"):
                try:
                    strong_kb = float(os.environ.get("LD_HOOK_READ_STRONG_KB", "100"))
                except ValueError:
                    strong_kb = 100.0
                fields["band"] = "strong" if size_kb > strong_kb else "suggest"
    if fields.get("blocked") and path:
        fields["id"] = new_id()
        record_block(fields["id"], path)
    record("PreToolUse", **fields)


if __name__ == "__main__":
    main()
