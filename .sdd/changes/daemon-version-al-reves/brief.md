# Brief: El check del daemon compara versiones por desigualdad, no por cuál es más nueva

## Problem

`_probe_daemon` (`checks.py:674`) compara así:

```python
if installed and version != "?" and version != installed:
    return Result(WARN, f"... la versión instalada es {installed}: el daemon sirve la vieja",
                  RESTART_HINT)
```

Es una **desigualdad**, no una comparación de orden. Así que siempre que las dos versiones difieran
dice «el daemon sirve la vieja» y manda reiniciar el daemon, **también cuando el daemon sirve la
NUEVA**.

Encontrado en producción por el usuario el 2026-07-31, justo tras publicar la 0.18.0:

```
[WARN] daemon: local-delegate 0.18.0 · pid 32660 — pero la versión instalada es 0.17.0:
       el daemon sirve la vieja
       arréglalo con: reinicia el daemon para que sirva la versión instalada
```

El daemon corre del venv editable del repo (**0.18.0**) y el CLI está instalado con `uv tool`
(**0.17.0**). El mensaje dice justo lo contrario de lo que pasa, y **el arreglo que ofrece no
arregla nada**: reiniciar el daemon lo dejaría igual en 0.18.0, porque el atrasado es el CLI.

Es la misma clase de defecto que `cli.published` ya resuelve bien —compara con `_compare_versions`,
no con `!=`—, pero ahí nadie lo aplicó.

## Desired outcome

Cuando las versiones difieren, `doctor` dice **cuál de las dos está atrasada** y ofrece el comando
que arregla **esa**:

- daemon más viejo que la instalada → «el daemon sirve la vieja» + reiniciar.
- daemon más nuevo que la instalada → «el CLI instalado está atrasado» + el comando de upgrade que
  corresponda a esta instalación.

## In scope

- `_probe_daemon`: comparar con `_compare_versions` y distinguir los dos sentidos.
- El `fix_hint` de cada caso, tomado de lo que ya existe (`RESTART_HINT` y `_upgrade_hint()`).
- Tests de los dos sentidos y del caso no comparable.

## Out of scope

- Que `update` actualice el CLI de `uv tool`: está **descartado con motivo** (hacerlo desde el
  propio entorno destruye la instalación en Windows). Este change solo arregla el diagnóstico.
- Tocar `cli.published`, que ya compara bien.

## Constraints and risks

- El estado sigue siendo `WARN` en los dos sentidos: difieran como difieran, hay algo que atender,
  así que el exit code no cambia.
- **`_upgrade_hint()` importa `update`, que importa `checks`**: el import ya es diferido dentro de
  la función. No introducir uno a nivel superior.
- Dos versiones que no se puedan comparar (formato raro) no deben empeorar el mensaje: se avisa de
  que difieren, **sin** ofrecer un arreglo que podría ser el equivocado.

## Open questions

Ninguna. El caso está reproducido en producción y el patrón correcto ya existe en el mismo módulo.
