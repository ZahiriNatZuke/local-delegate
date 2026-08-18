# Implementation plan: la puntería del hook de lectura

## Ficheros

| Fichero | Qué cambia |
|---|---|
| `src/local_delegate/resources/hooks/suggest_delegate_read.py` | Las tres exclusiones, los umbrales nuevos, `ext` en los dos caminos de registro |
| `tests/test_hook_recipes.py` | Un test por escenario de la spec, más el control anti-vacío |
| `CHANGELOG.md` | Entrada en `Unreleased` |
| `docs/recipes/claude-code-hooks.md` | Umbrales y exclusiones documentados, si los menciona |

No se toca `hook_common.py`: `record()` ya acepta metadata arbitraria por `**metadata`, así que
`ext` entra sin cambiar la utilidad.

## Tareas

### T1 — decidir dónde vive la lista de extensiones

`EXTENSIONES_DE_CODIGO` como constante de módulo (REQ-002), para que un test pueda leerla y para
que ampliarla no obligue a tocar la función de decisión.

### T2 — extraer la decisión a una función pura

Hoy `main()` mezcla leer stdin, decidir y emitir. Sacar `decidir(file_path, tool_input, tamaño_kb)`
que devuelva `("descartar"|"suggest"|"strong", motivo)` permite probar los cuatro escenarios sin
montar stdin ni tocar el disco. `main()` queda como el que lee, mide y emite.

**Riesgo:** probar sólo `decidir()` es probar la pieza, no el uso. Los tests de escenario van
contra `main()` con stdin real y archivos reales en `tmp_path`; `decidir()` se prueba aparte para
los casos de borde.

### T3 — las tres exclusiones y los umbrales

Orden de las guardas en `main()`, de más barata a más cara:

1. sin `file_path` → salir (ya está)
2. `offset` o `limit` presentes → registrar `suggested: false`, salir (REQ-001)
3. extensión en `EXTENSIONES_DE_CODIGO` → registrar `suggested: false`, salir (REQ-002)
4. `getsize` falla → salir sin registrar (ya está)
5. `size_kb <= suggest_kb` → registrar `suggested: false` (ya está, con umbral nuevo)
6. emitir, banda según `strong_kb`

Los defaults pasan a `32` y `100` (REQ-003). Las guardas 2 y 3 registran en vez de callarse
(REQ-005), porque sin denominador no hay puntería que medir.

### T4 — `ext` en la telemetría

Calcular `ext = os.path.splitext(file_path)[1].lower()` una vez y pasarlo a `record()` y `emit()`
en todos los caminos que registran (REQ-004). Nunca el nombre ni la ruta.

### T5 — tests

Uno por escenario de la spec, más:

- **control anti-vacío:** el `.md` de 120 KB debe seguir emitiendo `strong`. Si alguien rompe el
  hook para que nunca sugiera, los cinco tests de "no sugiere" pasarían igual y sólo este falla.
- **test de privacidad:** extender el que ya existe para verificar que `ext` está y que un nombre
  de archivo distintivo no aparece en el log.

### T6 — CHANGELOG y docs

## Verificación

- `uv run pytest` completo (no sólo el fichero tocado: el hook lo tocan también `test_install.py`
  y `test_install_clients.py`).
- `uv run ruff check` y `ruff format --check`.
- Re-correr la simulación de `research.md` con la lógica nueva importada del módulo real —no
  reimplementada en el script— y comprobar que da ~29 sobre las 852 lecturas.

## Lo que puede salir mal

- **`test_install.py` verifica el comportamiento del hook end-to-end** con un archivo de prueba;
  si ese archivo pesa entre 8 y 32 KB, el cambio de umbral lo rompe. Hay que mirarlo antes de
  tocar nada, no después.
- El hook instalado en `~/.claude/hooks/` es una copia de la 0.24.0; el cambio no llega a esta
  máquina hasta reinstalar. La verificación de que funciona en vivo es aparte del `pytest`.
