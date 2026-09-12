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

- `LD_HOOK_READ_BLOQUEAR=0`, que se lee **en cada invocación**: una sesión abierta hereda el
  entorno del lanzador, así que una variable que solo se mire al arrancar no serviría de freno.
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

from hook_common import (
    anotar_bloqueo,
    backend_disponible,
    contexto_de,
    deny,
    emit,
    huella_de_ruta,
    nuevo_id,
    record,
)

VERDADEROS = {"1", "true", "yes", "on"}
FALSOS = {"0", "false", "no", "off"}

#: Prosa: lo que un resumen puede sustituir. Son las dos extensiones con volumen medido —`.md` 49
#: y `.txt` 15 de los 85 avisos del periodo— y las únicas que se bloquean.
EXTENSIONES_DE_PROSA = frozenset({".md", ".txt", ".markdown", ".rst"})

#: Se leen para encontrar un valor exacto: un `package.json`, un `state.json`, la línea del error
#: en un log. Se avisa, pero no se bloquea, porque ahí el resumen no sustituye a la lectura. De
#: `.csv` y `.log` no hubo **ni un aviso** en el periodo medido, así que entrar a bloquearlos
#: habría sido inventar el caso.
EXTENSIONES_DE_DATOS = frozenset({".json", ".csv", ".log", ".yaml", ".yml", ".xml", ".toml"})

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


def bloqueo_encendido() -> bool:
    """Si la regla puede rechazar una lectura. Se consulta EN CADA invocación, a propósito.

    Nace apagado: se enciende cuando esté escrito el criterio de la quinta medición, incluido el
    resultado que lo retira. Y se apaga sin cerrar la sesión, porque una sesión abierta hereda el
    entorno del lanzador —medido: catorce lecturas se comportaron con el umbral viejo después de
    cambiarlo— y un freno que exige reiniciar no es un freno.
    """
    return os.environ.get("LD_HOOK_READ_BLOQUEAR", "0").strip().lower() in VERDADEROS


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
    # La HUELLA de la ruta, nunca la ruta. Sin ella no se puede agrupar por fichero, y esa es la
    # pregunta que la guarda de «acotada» tiene pendiente: de las 277 lecturas por franjas
    # registradas, cuantas eran de un fichero que acabo leyendose entero de todas formas. La
    # telemetria sigue sin poder decir QUE fichero era.
    huella = {"path_sha": huella_de_ruta(file_path), **contexto_de(payload, __file__)}

    # Las dos guardas siguientes registran en vez de callarse: sin denominador no hay puntería que
    # medir, y no poder medirla es lo que dejó a este hook tres semanas apuntando a código.
    if es_lectura_acotada(tool_input):
        record(
            "PreToolUse",
            suggested=False,
            category="read",
            ext=ext,
            motivo="acotada",
            **huella,
        )
        return

    if ext in EXTENSIONES_DE_CODIGO:
        record("PreToolUse", suggested=False, category="read", ext=ext, motivo="codigo", **huella)
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
            motivo="pequeno",
            **huella,
        )
        return

    band = "strong" if size_kb > strong_kb else "suggest"
    comun = {
        "category": "read",
        "band": band,
        "ext": ext,
        "size_kb": round(size_kb, 1),
        "id": nuevo_id(),
        **huella,
    }

    # Solo la prosa se bloquea, y solo si hay a donde delegar. Cada una de las tres guardas
    # siguientes registra su motivo: si la regla se equivoca a menudo, tiene que verse en el dato
    # y no en la irritacion del usuario.
    if ext in EXTENSIONES_DE_PROSA and bloqueo_encendido():
        if backend_disponible():
            # La nota va ANTES del bloqueo: si el agente delega acto seguido, el servidor tiene
            # que encontrarla ya escrita.
            anotar_bloqueo(comun["id"], file_path)
            deny(
                "PreToolUse",
                f"Este archivo pesa {size_kb:.0f} KB y es prosa. Pasalo por una tool local con "
                f'`path="{file_path}"`: `local_summarize` para el contenido, `local_extract` '
                "para campos concretos, `local_translate` o `local_explain_code`. Asi no entra al "
                "contexto.\n\n"
                "Si de verdad necesitas el texto literal —lineas exactas para citar o editar—, "
                "leelo por franjas con `offset` y `limit`, que no se bloquean.",
                motivo="prosa_grande",
                **comun,
            )
            return
        record("PreToolUse", suggested=False, motivo="backend_ausente", **comun)

    strength = "Recomendacion fuerte" if band == "strong" else "Sugerencia"
    destino = (
        "una tool local_* con path"
        if ext not in EXTENSIONES_DE_DATOS
        else "local_extract con path, si lo que buscas son campos concretos"
    )
    emit(
        "PreToolUse",
        f"{strength}: este archivo pesa {size_kb:.0f} KB. Si necesitas una transformacion "
        f"global (resumen, campos, traduccion o explicacion), usa {destino} para "
        "que no entre al contexto. Leelo directamente si necesitas lineas exactas para razonar o editar.",
        **comun,
    )


if __name__ == "__main__":
    main()
