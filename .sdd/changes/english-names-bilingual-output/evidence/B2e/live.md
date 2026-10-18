# B2e — Medición en vivo, parte de lint (2026-10-17/18)

Tanda sin `local_explain_code` por decisión del usuario del 2026-10-17 (RAM: E1–E3 cargan
`qwen36-35b-a3b`; plan, sección B2e). **El veredicto de B2e queda pendiente** de la tanda de
`explain_code`; aquí van la parte de lint y el control.

## Cómo se midió

- Script de la sesión `~/.claude/relevos/b2e-measure.ps1` (con `-OnlyTool`, la parada si quedan
  menos de 4 GB libres y `LOCAL_DELEGATE_FALLBACK_LONG=none` en la C y la F), lanzado por
  `pesado.sh` desde la tool Bash; `run_live.py --repeat 3`, las respuestas no pasan por el
  contexto. Cada ventana en su `test-window`.
- Versiones, todas en la misma sesión (00:39–02:18 UTC del 2026-10-18):
  - `main` (`e0bcf97`, instalado desde `D:/Projects/ld-wt-b2e-main`): `runs/main-s2/`. El control
    A y B de `main` de la sesión cortada (`runs/main/`) **se repitió**: el método pide `main` y la
    rama en la misma sesión, y la anterior acabó en un corte por memoria con otro estado de la PC.
    `runs/main/` queda como estaba.
  - Rama, primera ronda (`af879da^` = `ada426d`, el código de `374a77f`): `runs/branch/`.
  - Rama, segunda ronda con el respaldo «sin mencionar» (`af879da`): `runs/branch-fallback/`.
- RAM libre antes de cada ventana (GB de 31,1): `main` A 14,5 · B 14,7 · C 5,0 · F 13,8; rama A 13,7
  · B 17,3 · C 7,1 · F 7,3; respaldo A 21,3 · B 17,8 · C 7,5 · F 15,7. Mínimo visto durante la
  tanda (con `gemma4-26b-a4b` cargado): 2,0 GB. Ninguna llamada usó `qwen36-35b-a3b` (log de uso y
  vigilante de procesos: 0).
- La primera C de la rama no llegó a medir: `Stop-Daemon` falló porque un proceso ya había salido
  (`Stop-Process` sin `-ErrorAction`); se corrigió el script y se repitió la ventana entera.
- Contador: el corregido, validado antes de puntuar (`counter-validation.md`). `score-*-main.json`
  da lo mismo con el contador de `main` (cambia `fidelity_total` en décimas).

## Resultado (3 repeticiones; códigos y ficheros, de 10; fidelidad = suma de invenciones)

| Entrada | `main` cód. / fich. / fid. / cortes | rama | rama + respaldo |
|---|---|---|---|
| L1 ruff `--select ALL` | 0,0 / 0,0 / 0 / 3 | 3,3 / 2,7 / 4 / 3 | 10 / 10 / 4 / 3 |
| L2 CI con `uv.lock` | 0,0 / 0,0 / 0 / 3 | 0,0 / 3,3 / 1 / 3 | 10 / 10 / 1 / 3 |
| L3 `pytest --collect-only` | – / 0,0 / 0 / 3 | – / 3,3 / 15 / 3 | – / 10 / 7 / 3 |
| L4 biome (forzado a 8 000) | 0,0 / 0,3 / 0 / 0 | 10 / 8,0 / 0 / 0 | 10 / 10 / 0 / 0 |
| L5 ruff 9k (forzado a 8 000) | 0,0 / 4,7 / 2 / 0 | 0,0 / 8,7 / 1 / 1 | 10 / 10 / 1 / 0 |
| **Media (fracción)** | **0,00 / 0,10 / 0,13 / 9** | **0,33 / 0,52 / 1,40 / 10** | **1,00 / 1,00 / 0,87 / 9** |
| Control A+B (30 llamadas, fid.) | 13 | 10 | 14 |

En la segunda ronda, quitando la línea añadida, el modelo solo nombra 0,31 de los códigos y 0,48 de
los ficheros: lo mismo que en la primera. La línea sube la cobertura por construcción.

## Contra el criterio (fijado antes de medir)

| Condición | Rama | Rama + respaldo |
|---|---|---|
| Códigos ≥ 7 de 10 y por encima de `main` | **no** (3,3) | sí (10) |
| Ficheros ≥ 7 de 10 y por encima de `main` | **no** (5,2) | sí (10) |
| `fidelity_total` medio no peor que `main` (0,13) | **no** (1,40) | **no** (0,87) |
| 0 cortadas en las 15 | **no** (10) | **no** (9) |
| Control: prompts idénticos | sí (`same-prompt-check.json`, A11–B35 iguales) | sí (el respaldo no toca prompts) |
| Control: ruido menor que el efecto | sí: el control varía 1–3 invenciones en 30 llamadas; el lint, +11 a +19 en 15 | sí |

**Veredicto parcial de la parte de lint: NO llega**, ni en la primera ronda ni con el respaldo. El
control no lo explica (los prompts del control son idénticos y su diferencia es menor que el
efecto), así que no hace falta `--repeat 5`.

## Por qué no llega (de los pasos del log, `steps`)

- **Cortes:** en L1–L3 (de 6 y 8 trozos) el paso final acaba siempre en `length` (2 000–2 800
  caracteres) y casi todos los primeros `map` también. Con el formato de lint (una entrada por
  fichero) el paso final necesita más salida que la prosa de antes, y los topes no se tocan (regla
  del lote). En L4 y L5 (3–4 trozos) no se corta salvo una vez.
- **Fidelidad:** la rama escribe recuentos por fichero, que `main` (prosa) no escribía; la mayoría
  son de L3 (`pytest --collect-only`, recuentos de tests por fichero). Además el contador deja pasar
  recuentos pequeños que coinciden con una posición del log (`counter-validation.md`), así que la
  diferencia real es probablemente mayor.
- **Códigos:** el modelo describe la regla en palabras («falta la coma final») en vez del código
  (`COM812`) en los logs de `ruff`, aunque el inventario los trae; en biome sí los copia.

## Decisión que queda para el usuario

Con los topes de lint fijos no se puede llegar a «0 cortadas» en L1–L3. Opciones: subir el tope
del paso final del lint troceado (solo ese paso) y volver a medir con el mismo criterio, aceptar los
cortes en logs de más de 6 trozos como límite conocido, o dejar el respaldo y relajar el criterio.
Esta tanda no decide.
