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

Usa dos bandas: LD_HOOK_READ_SUGGEST_KB (default 32 KB) y LD_HOOK_READ_STRONG_KB (default 100 KB).
NUNCA bloquea la tool: no emite `permissionDecision`, sólo contexto. Sin dependencias (stdlib
únicamente) y multiplataforma.

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

from hook_common import emit, record

VERDADEROS = {"1", "true", "yes", "on"}

#: Extensiones que se leen para editarlas, no para transformarlas. Es una constante de módulo y no
#: una lista dentro de la decisión para que ampliarla no obligue a tocar la lógica —y para que un
#: test pueda leerla. Deja fuera a propósito `.md`, `.json`, `.txt`, `.csv` y `.log`, que son los
#: formatos donde un resumen o una extracción sí sustituyen a la lectura entera.
EXTENSIONES_DE_CODIGO = frozenset(
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


def esta_encendido(argv: list[str] | None = None) -> bool:
    """¿Debe hacer algo este hook? Por el argumento del registro o por el entorno.

    Cualquiera de las dos basta. `argv` se puede inyectar para poder probar la decisión sin
    montar un proceso.
    """
    args = sys.argv[1:] if argv is None else argv
    if "--enabled" in args:
        return True
    return os.environ.get("LD_HOOK_READ_ENABLED", "0").strip().lower() in VERDADEROS


def extension_de(file_path: str) -> str:
    """La extensión en minúsculas, acotada y sin nada que identifique al archivo.

    Devuelve `""` cuando no hay extensión, cuando pasa de `MAX_EXT` o cuando trae algo que no sea
    alfanumérico: en esos casos el dato ya no sirve para medir puntería y sí podría decir de más.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if not ext or len(ext) > MAX_EXT or not ext[1:].isalnum():
        return ""
    return ext


def es_lectura_acotada(tool_input: dict) -> bool:
    """Una franja pedida con offset/limit es intencionada: el modelo ya sabe qué parte quiere."""
    return tool_input.get("offset") is not None or tool_input.get("limit") is not None


def main() -> None:
    if not esta_encendido():
        return

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path:
        return

    ext = extension_de(file_path)

    # Las dos guardas siguientes registran en vez de callarse: sin denominador no hay puntería que
    # medir, y no poder medirla es lo que dejó a este hook tres semanas apuntando a código.
    if es_lectura_acotada(tool_input):
        record("PreToolUse", suggested=False, category="read", ext=ext, motivo="acotada")
        return

    if ext in EXTENSIONES_DE_CODIGO:
        record("PreToolUse", suggested=False, category="read", ext=ext, motivo="codigo")
        return

    try:
        suggest_kb = float(os.environ.get("LD_HOOK_READ_SUGGEST_KB", "32"))
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
            motivo="pequeno",
        )
        return

    band = "strong" if size_kb > strong_kb else "suggest"
    strength = "Recomendacion fuerte" if band == "strong" else "Sugerencia"
    emit(
        "PreToolUse",
        f"{strength}: este archivo pesa {size_kb:.0f} KB. Si necesitas una transformacion "
        "global (resumen, campos, traduccion o explicacion), usa la tool local_* con path para "
        "que no entre al contexto. Leelo directamente si necesitas lineas exactas para razonar o editar.",
        category="read",
        band=band,
        ext=ext,
        size_kb=round(size_kb, 1),
    )


if __name__ == "__main__":
    main()
