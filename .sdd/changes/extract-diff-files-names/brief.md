# Brief: local_extract: nombres de campo de ficheros y hunks de un diff por programa, sin null silencioso (#665)

## Problem

El #665 se reabrió: dos informes del 2026-11-16 (`local_extract` con `path` a un `.patch` grande y
troceado, campos `ficheros_y_hunks_con_lineas` y `ficheros_con_lineas`) volvieron con `null` en
todos los trozos. El log de uso de esta PC dice que hoy todas las llamadas corrieron la 0.52.0,
publicada antes del #676 (que no está en ninguna versión publicada). Con el código de `main`,
`ficheros_con_lineas` ya se responde por programa, también tras la cabecera de `git format-patch`;
pero siguen yendo al modelo, trozo a trozo: un campo que pide ficheros Y hunks
(`ficheros_y_hunks_con_lineas`, `files_and_hunks_with_lines`), `changed_files_with_lines` (la
palabra de recuento `changed` lo descarta como campo de líneas) y un `.patch` cuyo principio no
es una cabecera de parche (un preámbulo antes del primer `diff --git`).

## Desired outcome

Esos nombres y esas formas se responden por programa; si un `.patch` no se puede leer o un campo
de líneas sobre un diff troceado queda en `null`, un `warning` lo dice.

## In scope

- Predicado de nombres de ficheros + hunks; `changed/modified_files` como sujeto, no recuento.
- Rangos de cada hunk en líneas del parche.
- Detección de diff también por sufijo `.patch`/`.diff`.
- Avisos: `.patch` sin cabeceras de fichero; campo de líneas en `null` sobre un diff troceado.

## Out of scope

- `hunks_with_lines` a secas sigue siendo del modelo (test existente).
- Publicar versión, tocar el daemon o el PR #685.

## Constraints and risks

- Sin regex con backtracking; el recorrido del parche es lineal.
- Tests existentes intactos.

## Open questions

- Ninguna.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-16 Original request, verbatim:

  > Tarea: el issue #665, reabierto hoy. [...] Arregla la causa real: que el camino por programa
  > cubra esos nombres (un campo que pide ficheros + hunks debe dar fichero y rango de cada hunk
  > dentro del patch, o el rango por fichero con aviso), y que nunca vuelva un `null` silencioso
  > sobre un diff troceado: si no se puede, un `warning` que lo diga.

- L2 2026-11-16 Reproducido con backend doblado (`tests/test_extract_diff_files_names.py`): 15
  fallos con el código de `main` (control positivo); el caso de 6000 líneas con `format-patch`
  ya pasaba en `main`.
