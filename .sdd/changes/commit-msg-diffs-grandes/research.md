# Research: local_commit_msg deja de truncar diffs grandes

Todo lo de aquí está medido por ejecución el 2026-08-04, con el backend local arriba
(`local_status`: `http://127.0.0.1:9292/v1 — arriba`, rol `code` = `qwen25-coder-14b`,
`max_chars=20000`).

## Reproducción del fallo

Caso de referencia: `git diff 6a7959e HEAD` de este repo, volcado a fichero.

```
chars totales: 164585
archivos: 44
archivos dentro de los primeros 20k: 7
ultimo archivo visible en 20k: .sdd/changes/aislar-entorno-en-tests/state.json
```

Los 7 archivos que sobreviven al truncado son todos de `.sdd/` — metadato de proceso. Se pierden
`CHANGELOG.md`, `docs/`, `src/local_delegate/web/auth.py` (+157 líneas), toda la suite de tests y
`uv.lock`.

`local_commit_msg(path=...)` sobre ese fichero devuelve:

```
[local-delegate: entrada truncada — procesados 20027 de 164585 chars]
chore: update GitHub Actions pages artifact version
```

Mismo síntoma que el reportado desde la Mac (`docs: update angular agents documentation` para un
refactor de `paycorr-core` de 71k chars). El mensaje describe el **primer archivo por orden
alfabético de rutas**, que es lo único que el modelo llegó a ver.

## Control positivo: ¿es el modelo o es lo que le llega?

`git diff --stat` del mismo rango son **2 987 chars** — cabe entero, sin truncar. Pasado a la misma
tool, con el mismo modelo:

```
feat: agregar cambios y pruebas para aislar entorno en tests y codeql alertas abiertas
```

No es perfecto (dice `feat` donde tocaría `chore`, y mezcla dos cosas porque el rango son seis PRs),
pero nombra el cambio real. **El modelo puede; lo que no llega es la entrada.** Este control es lo
que justifica la pieza C: 2 987 chars bien elegidos valen más que 20 027 chars del principio.

## El chunking actual no sirve para diffs

`_chunk_text(diff, 16000)` — el presupuesto que usaría `_chat_map_reduce` para el rol `code`:

```
trozos con el splitter ACTUAL: 11
trozos que empiezan en frontera de archivo: 1 / 11
invariante join==t: True
```

`_SPLITTERS` (`server.py:744`) es headers Markdown → párrafos → líneas. Un diff no tiene headers
`# `, así que cae a párrafos y corta a mitad de hunk:

```
trozo 2 empieza: '+  el brief y medido (la suite pasa con esas variables definidas).\n+\n+## Non-fun'
trozo 3 empieza: '+correcta: arreglo cuando el c digo mejora, descarte razonado cuando la herramie'
```

Líneas `+` huérfanas: el trozo no dice de qué archivo son. Enchufar map-reduce **sin** arreglar
esto daría parciales que no saben qué están resumiendo.

## Origen del defecto

Las otras dos tools reductoras ya se arreglaron y a esta no le tocó:

| Tool | Lectura | Camino largo |
| --- | --- | --- |
| `local_summarize` (`server.py:1150`) | `_NO_TRUNCATE` | `_chat_map_reduce` |
| `local_lint_summary` (`server.py:1422`) | `_NO_TRUNCATE` | `_chat_map_reduce` |
| `local_commit_msg` (`server.py:1474`) | `max_chars_for(MODEL_CODE)` | **ninguno** |

El comentario de `_chat_map_reduce` (`server.py:930`) ya describe este defecto textualmente:
«Hasta ahora estas tools simplemente *truncaban* la entrada y avisaban, que en un documento grande
significa resumir el principio e ignorar el resto en silencio útil».

## Restricción encontrada para el plan

`_chat_map_reduce` tiene el prompt del reduce cableado (`server.py:965-968`):

```python
reduce_system = _guard(
    "un ÚNICO resumen global en prosa clara, sin repetir ni enumerar los fragmentos",
    max_words,
)
```

y el texto del reduce dice «Estos son resúmenes parciales… Redacta un único resumen global»
(`server.py:988`). Para commit hace falta parametrizar ambos: un mensaje de commit no es prosa
clara ni admite `max_words` como tope principal.

## Reproducir

```powershell
git diff 6a7959e HEAD > $env:TEMP\diff-grande.txt
git diff --stat 6a7959e HEAD > $env:TEMP\diffstat.txt
# y llamar local_commit_msg con cada path
uv run python -c "from local_delegate.server import _chunk_text; ..."
```
