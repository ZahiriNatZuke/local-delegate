# B2e — Validación del contador de fidelidad, antes de puntuar (2026-10-17)

Regla de B2d-4: el contador corregido (`scripts/score_lint_fidelity.py`, commit `374a77f`) solo se
usa para medir si, contra una revisión a mano de **cifras nuevas** (no las 18 de
`evidence/B2d-4/counter-validation.md`), no suelta ninguna cifra inventada que el de `main`
(`score_lint_fidelity_main.py`) sí cuente. Hecha ANTES de correr `score_b2e.py`.

## Material

- Respuestas troceadas de la base de B2e: `runs/main-s2/L1…L5-r1…r3` (15 respuestas, `main` en la
  sesión de esta tanda) y `evidence/B2d-2/live-answers/C43.txt` y `C44.txt` (sin una sola cifra:
  solo nombres de fichero, que los dos contadores aceptan).
- Para tener casos de recuentos por fichero, que la base casi no trae, también las respuestas
  de la rama de la ventana F: `runs/branch/L4-r1…r3` y `L5-r1…r3`.
- Las cifras y su contexto las saca `validate_counter.py` (los dos contadores); el veredicto «a
  mano» es contra el log, contando las líneas de diagnóstico por fichero y código (`awk`/`grep`
  sobre el log, no a ojo).

## Tabla (una fila por cifra distinta y su sitio; 28 cifras)

| Respuesta | Cifra y contexto | Log | A mano | `main` | Corregido |
|---|---|---|---|---|---|
| main L1 | «Found 1991 errors» | línea final `Found 1991 errors.` | real | acepta | acepta |
| main L2 | «resolver 61 paquetes» | `Resolved 61 packages` | real | acepta | acepta |
| main L2 | «auditar 58 paquetes» | `Audited 58 packages` | real | acepta | acepta |
| main L2 | «Found 1299 errors» | `Found 1299 errors.` | real | acepta | acepta |
| main L3 | «2617 tests collected» | línea final | real | acepta | acepta |
| main L3 | «0» de «0.74s» | línea final | real | acepta | acepta |
| main L4 | «Found 3 errors» | `Found 3 errors.` | real | acepta | acepta |
| main L4 | «Found 51 warnings» | `Found 51 warnings.` | real | acepta | acepta |
| main L4 | «Found 192 infos» | `Found 192 infos.` | real | acepta | acepta |
| main L5 r1 | «derechos de autor: 4» | CPY001 sale 5 veces | **inventada** | acepta | acepta |
| main L5 r1 | «cadena de documentación: 20» | D101–D107 suman 24 | **inventada** | cuenta | cuenta |
| main L5 r1 | «coma final: 8» | COM812 sale 16 veces | **inventada** | acepta | acepta |
| main L5 r1 | «excepciones: 12» | TRY003+EM102+EM101+TRY301 = 17 | **inventada** | acepta | acepta |
| main L5 r1 | «`subprocess`: 2» | S603 sale 2 veces | real | acepta | acepta |
| main L5 r1 | «otros errores: 23» | sin base en el log | **inventada** | acepta | acepta |
| main L5 r2 | «Found 84 errors» | el log no tiene línea `Found`; 96 diagnósticos | **inventada** | cuenta | cuenta |
| rama L4 r1 | `package.json`, noRestrictedDependencies: 1 | 1 | real | acepta | acepta |
| rama L4 r1 | `env.schema.ts`, useNamingConvention: 6 | 6 | real | acepta | acepta |
| rama L4 r1 | `geocode.dto.ts`, noMagicNumbers: 5 | 4 | **inventada** | acepta | acepta |
| rama L4 r1 | `validate.dto.ts`, noMagicNumbers: 5 | 5 | real | acepta | acepta |
| rama L4 r1 | `validate.dto.ts`, useNamingConvention: 4 | 4 | real | acepta | acepta |
| rama L4 r1 | `repo-root.ts`, useBlockStatements: 3 | 2 | **inventada** | acepta | acepta |
| rama L4 r1 | `geocode.controller.ts`, useImportType: 2 | 2 | real | acepta | acepta |
| rama L5 r2 | `benchmark.py`, «coma final»: 6 | COM812 en ese fichero: 15 | **inventada** | acepta | acepta |
| rama L5 r2 | `benchmark.py`, «método público» (D102): 7 | 7 | real | acepta | acepta |
| rama L5 r2 | `benchmark.py`, «`__init__`» (D107): 4 | 5 | **inventada** | acepta | acepta |
| rama L5 r3 | `benchmark.py`, «problemas por archivo»: 66 | 86 diagnósticos | **inventada** | cuenta | cuenta |
| rama L5 r3 | `agents.py`, «problemas por archivo»: 5 | 5 | real | acepta | acepta |

Resumen: 28 cifras, 16 reales y 12 inventadas a mano. Los dos contadores dan **el mismo
veredicto en las 28**: aceptan las 16 reales y cuentan 3 de las 12 inventadas (20, 84 y 66). Las
otras 9 inventadas son recuentos pequeños (2–23) que el log escribe en otro sitio como línea o
columna (`benchmark.py:12:…`), y ninguno de los dos los ve: es el límite conocido del contador
(una cifra presente en el log, aunque sea como posición, respalda una cifra en dígitos; B2e solo
lo cerró para las cifras en palabras). No lo crea el cambio de `374a77f` ni lo empeora.

## Control negativo y casos del arreglo, sobre logs reales (`counter_controls.py`)

Salida en `counter-controls.json` (8 casos, los 8 como se esperaba):

| Caso | Log | `main` | Corregido | Esperado del corregido |
|---|---|---|---|---|
| negativo: «Found 7777 errors» añadido a la respuesta de L2 | L2 | cuenta | cuenta | cuenta |
| negativo: «4321 paquetes» añadido | L2 | cuenta | cuenta | cuenta |
| negativo: fichero `scripts/no_such_file.py` añadido | L2 | cuenta | cuenta | cuenta |
| negativo: «doce avisos» sin un 12 en el log | una línea | cuenta | cuenta | cuenta |
| arreglo: `scripts/build\_corpus.py` (escape de Markdown) | L2 | cuenta (falso) | acepta | acepta |
| arreglo: posición de `tsc` `(52,24)` | una línea `tsc` | cuenta (falso) | acepta | acepta |
| arreglo: versión `v255` | una línea | cuenta (falso) | acepta | acepta |
| arreglo: «nine T201» apoyado solo en una columna `:9:` | L5 | acepta (falso) | cuenta | cuenta |

## Veredicto

El contador corregido **no suelta ninguna cifra inventada** que el de `main` cuente (0 de 12
casos), acepta lo mismo que `main` en las 16 reales, y el control negativo da los cuatro inventos
añadidos. Los cuatro arreglos de `374a77f` se confirman en sus casos y **ninguno se revierte**. Se
usa el corregido para puntuar; `score_b2e.py --counter main` se corre también para comparar.

Límite que queda (no es de B2e): los recuentos en dígitos que coinciden con una posición del log
pasan los dos contadores. En esta tanda son 9 de 12 inventadas, así que `fidelity_total` subestima
las invenciones de las respuestas con recuentos por fichero (más frecuentes en la rama, que pide
el formato de lint). Se informa con el veredicto.
