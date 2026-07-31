# Research: Check de doctor sobre los clientes MCP observados

Todo lo de aquí está **medido por ejecución** en esta máquina el 2026-07-31, no leído de la
documentación ni de los comentarios del repo.

## Current behavior

`checks.CHECKS` (`src/local_delegate/checks.py:604-619`) tiene **catorce** comprobaciones y ninguna
mira los clientes MCP observados. La más parecida por nombre, `client.presence`
(`checks.py:231-239`), es otra cosa: comprueba si existen los directorios `~/.claude` y `~/.codex`,
o sea qué clientes están **instalados**, no con cuáles se ha **hablado**.

El dato de los clientes observados existe desde el PR #95 (`clients.py`) y hoy solo lo consume
`/api/status`. `doctor` no lo ve.

## R1 — La premisa de entrada era medio falsa

La instrucción de la sesión decía: *«El dato ya se registra en `clients.jsonl` (`LOG_DIR`) y en
`GET /api/status` bajo `clients`»*. En el **código** sí; en **esta máquina** no:

```
> Invoke-RestMethod http://127.0.0.1:9393/api/status
version: 0.17.0
tiene clients: False
```

```
> uv run python -c "from local_delegate import config; ..."
LOG_DIR: C:\Users\Yohan\AppData\Local\local-delegate
existe: False        # clients.jsonl
```

El daemon en producción sirve la **0.17.0**, anterior a `clients.py` (que está en `Unreleased`).
Consecuencia práctica: **el caso normal del check, hoy y hasta que se publique, es «sin datos»**.
Eso lo convierte en el camino principal a diseñar, no en un borde.

## R2 — `/api/status` NO sirve como fuente para `doctor`

`web/metrics.py:514` expone `"clients": clients.snapshot()`, y `snapshot()` (`clients.py:152-160`)
devuelve copia de `_VISTOS`, que es **un dict en memoria del proceso**. El propio comentario del
endpoint lo dice: *«Clientes MCP observados en ESTA ejecución del daemon (el histórico está en
clients.jsonl)»*.

Dos razones independientes para descartarlo:

1. **`doctor` es otro proceso.** Nunca comparte esa memoria; tendría que ir por HTTP al 9393.
2. **El daemon no ve a los clientes que importan.** Claude Code y Codex hablan por **stdio**: cada
   uno lanza su propio proceso de `local-delegate`. Sus observaciones **no pasan** por el daemon del
   9393, así que `/api/status` sería sistemáticamente ciego justo para los dos clientes reales.

**Fuente elegida: `clients.jsonl`.** Es la única que ve a todos los procesos, no depende de que el
daemon esté arriba, y leerla no escribe nada.

## R3 — El registro duplica una línea por arranque de proceso

La deduplicación de `registrar()` es **intra-proceso**: se apoya en `_VISTOS`, que arranca vacío.
Verificado simulando el reinicio con `clients.reset()`:

```
p1 primera      : True
p1 repetida     : False      <- dedup dentro del proceso: funciona
p2 tras reinicio: True       <- MISMA identidad, línea nueva
p3 otro cliente : True
--- lineas en disco: 3
```

Con Claude Code en stdio arrancando varias veces al día, `clients.jsonl` acumula líneas idénticas
sin fin. **El check tiene que deduplicar al leer**, o su salida sería una lista repetida.

Además, la identidad incluye la **versión**: cada actualización del cliente crea una identidad
nueva, así que con el tiempo habría `claude-code 2.1.219`, `2.1.220`, … acumuladas. Por eso la
agrupación correcta es **por nombre de cliente, quedándose con el avistamiento más reciente**.

## R4 — Un cliente real sí escribe la línea (end-to-end)

Con `LOCAL_DELEGATE_LOG_DIR` apuntando a un directorio de pruebas y Claude Code lanzado por stdio
contra el repo:

```
claude -p "Llama a la tool local_status..." --mcp-config <fichero> --strict-mcp-config \
       --allowedTools "mcp__local-delegate__local_status"
```

`clients.jsonl` quedó con exactamente una línea:

```json
{"ts": "2026-07-31T17:15:52+00:00", "client": "claude-code", "version": "2.1.220",
 "protocol": "2025-11-25", "caps": ["elicitation", "roots"]}
```

Coincide con lo medido en la séptima tanda. **Es el dato que faltaba para decidir qué es fallo.**

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `src/local_delegate/checks.py` | registro único de 14 comprobaciones | +1 probe, +1 entrada en `CHECKS`, +1 colaborador en `Context`, 5 frases de tamaño | `checks.py:604-619`, `147-163` |
| `src/local_delegate/clients.py` | escribe y expone el registro | **solo lectura**: se le pide una función que lea el JSONL; sin cambios de formato | `clients.py:96-99` |
| `src/local_delegate/update.py` | mapea check → reparación | el check nuevo **no** se repara; entra en el comentario de no reparables | `update.py:138-141` |
| `src/local_delegate/doctor.py` | recorre e imprime | ninguno: imprime por grupo, el check nuevo sale solo | `doctor.py:302-310` |
| `tests/test_checks.py` | ata el tamaño declarado al real | `_NUMERO` necesita `15: "quince"` | `test_checks.py:617-641` |
| `docs/wiki/Integration-install.md` | documenta `doctor` | dice «las catorce piezas» | `Integration-install.md:133` |

## Existing conventions

De `checks.py:36-64` y su docstring:

| Estado | Significado | ¿Cuenta para el exit code? |
| --- | --- | --- |
| `ok` | está y como debe estar | no |
| `warn` | está, pero **no como debería** | **sí** (`is_warning`) |
| `missing` | falta y **se puede arreglar** | **sí** |
| `unknown` | no se pudo comprobar / no aplica / **sin datos** | no |

- `probe` nunca escribe (`test_no_probe_writes_anything` compara el árbol byte a byte).
- Los colaboradores se **inyectan** en `Context` con un default que delega en el módulo real
  (`daemon_status`, `backend_models`, `version_of`, `latest_release`). Los tres últimos devuelven
  **`(valor, motivo)`**, que es el patrón para distinguir «no hay» de «no pude».
- `doctor._print_group` imprime **una sola línea** por check: `[ OK ] {title}: {detail}`.
- Sin caracteres fuera de cp1252 en la salida (la flecha `→` mata el doctor en Windows).
- `read_text`/`read_json` distinguen «no existe» `(None, None)` de «no se pudo leer»
  `(None, motivo)`.

## Dependencies and integrations

- `config.LOG_DIR` sale de `LOCAL_DELEGATE_LOG_DIR` o del dir de datos (`config.py:132-133`):
  **no depende de `HOME`**, así que `doctor --home <árbol>` no lo aísla. Mismo comportamiento que
  ya tienen `service.daemon` y `service.backend`; hay que dejarlo escrito para que nadie lo
  confunda con el defecto del change C.
- `clients.py` no importa `checks.py` ni al revés hoy; el import nuevo (`checks` → `clients`) no
  crea ciclo: `clients` solo importa `config`.
- Sin dependencias nuevas: `json` y `pathlib` ya están.

## Risks and unknowns

**Hechos confirmados** (todos medidos arriba): la fuente correcta es el JSONL, el fichero duplica
por proceso, hoy no existe, un cliente real lo escribe, y el test del tamaño se rompe.

**Riesgos:**

- *Dato engañoso por acumulación* — mitigado agrupando por nombre y quedándose con lo más reciente.
- *JSONL parcialmente corrupto* — una línea a medio escribir (proceso muerto durante el `write`)
  no debe tumbar el diagnóstico: se salta y se sigue.
- *`detail` largo* — con varios clientes la línea crece. Aceptable: `_print_group` no la corta y el
  formato es compacto.

**Asunción que queda por validar en implementación** (no bloquea la spec): que el `ts` en formato
ISO-8601 con offset ordena bien como cadena para escoger «el más reciente». Todas las líneas las
escribe el mismo código con `timespec="seconds"` en UTC, así que el prefijo es homogéneo; aun así
el plan lo ordena parseando la fecha, no comparando texto.
