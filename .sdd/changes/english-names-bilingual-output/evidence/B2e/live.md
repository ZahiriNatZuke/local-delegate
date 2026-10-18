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

# B2e — Tanda del 2026-10-18: `explain_code` y lint con el tope nuevo del paso final

Decisiones del usuario del 2026-10-17/18 (plan, sección B2e): medir E1–E3 con la PC libre, subir
SOLO el tope del paso final del lint troceado y, si una parte no llega tras iterar, documentar el
límite conocido y adoptar la mejor versión medida. Todo en una sesión (02:59–05:43 UTC), con el
mismo script (`-OnlyTool`, parada con menos de 4 GB, ahora con `-Repeat`), `run_live.py`, ventanas
de prueba y `LOCAL_DELEGATE_FALLBACK_LONG=none` en C y F. Contador: el corregido.

- RAM: libre antes de cada ventana entre 9,0 y 22,9 GB de 31,1; mínimo visto durante toda la tanda
  4,04 GB (03:02 UTC, `main`, al cargar `qwen36-35b-a3b` para E1). El vigilante (umbral 1,5 GB,
  cada 3 s) no paró nada.
- Versiones: `main` (`e0bcf97`, árbol aparte): `runs/main-s3/` (E ×3, A, B, C-lint, F) y
  `runs/main-e5/` (E ×5). Rama: `runs/branch-explain/` (`af879da`, E ×3), y con `742341f` (tope
  nuevo y respaldo de `explain_code`) `runs/branch-explain2/` (E ×3), `runs/branch-cap/` (A, B,
  C-lint, F) y `runs/branch-e5/` (E ×5). Puntuación: `score-<tag>-new.json`.

## `explain_code` (E1–E3)

| Versión | E1 nombra `doctor` y `benchmark` | Registrados E1+E2 | Solo el modelo (sin la línea) | E3 primer nivel |
|---|---|---|---|---|
| `main` ×3 | 0 de 3 | 0,56 | 0,56 | 0,077 |
| rama `af879da` ×3 (inventario) | 0 de 3 | 0,81 | 0,81 | 0,044 |
| rama `742341f` ×3 (+ respaldo) | 3 de 3 | 1,00 | 0,71 | 0,029 |
| `main` ×5 | 0 de 5 | 0,44 | 0,44 | 0,055 |
| rama `742341f` ×5 | 5 de 5 | 1,00 | 0,80 | 0,062 |

- **Primera tanda (`af879da`): NO llega.** El reduce no se corta en E1 (`steps`: todo `stop`): el
  inventario llega al prompt y el modelo omite nombres (`start`, `stop`, `add`, `list`, `doctor`,
  `benchmark`…). De ahí el candidato 1: el respaldo «sin mencionar» de la decisión 3, con los
  nombres registrados.
- **Con el respaldo, ×3:** E1 y la media de registrados pasan (por construcción: la línea los
  añade), pero E3 da 0,029 frente a 0,077. E3 no tiene registros: su prompt es el de `main` byte a
  byte (test `test_a_file_without_registrations_keeps_the_inventory_of_today_byte_for_byte`) y no
  lleva línea, así que la diferencia es ruido del modelo (en `main` ×3 una sola repetición dio 0,15
  y las otras 0,03–0,04). Apliqué la regla de ruido del plan (repetir con `--repeat 5` sin cambiar
  el criterio) a este control, que es el único de `explain_code`.
- **×5, misma sesión: LLEGA.** E1 5 de 5; registrados 1,00 (≥ 0,9 y > 0,44); E3 0,062 ≥ 0,055.
  Sin maquillar: la cobertura pasa por la línea del programa; el modelo solo nombra 0,80 (frente a
  0,44 de `main`). E2 y E3 se cortan en un `map` (el trozo 3 de E2 y el 1 de E3) en todas las
  versiones, `main` incluido: no entra en el criterio de `explain_code` y se anota como límite.

## Lint (L1–L5) con el tope nuevo del paso final

Tope fijado antes de medir: reduce y reagrupado `3·(3·w+96)` = 2 088 tokens (antes 696); map y
llamada única sin tocar (plan, «Fijado antes de la segunda tanda»).

| Versión (misma sesión) | Códigos | Ficheros | Solo el modelo (cód./fich.) | Fidelidad por respuesta | Cortadas (cualquier paso) | Paso final cortado |
|---|---|---|---|---|---|---|
| `main` (`runs/main-s3`) | 0,00 | 0,09 | 0,00 / 0,09 | 0,00 | 9 de 15 | (sin `steps`) |
| rama con el tope (`runs/branch-cap`) | 1,00 | 1,00 | 0,57 / 0,65 | 1,40 | 9 de 15 | 7 de 15 |
| *referencia, sesión anterior:* rama + respaldo, tope 696 | 1,00 | 1,00 | 0,31 / 0,48 | 0,87 | 9 de 15 | 9 de 15 |

| Entrada | `main` cód./fich./fid./cortes | rama con el tope | caracteres del paso final (rama) | `map` cortados (rama) |
|---|---|---|---|---|
| L1 | 0,0 / 0,3 / 0 / 3 | 10 / 10 / 1 / 3 | 6 457, 6 075, 6 270 | 5, 4, 4 de 5 |
| L2 | 0,0 / 0,0 / 0 / 3 | 10 / 10 / 1 / 3 | 6 668, 6 215, 7 020 | 3 de 5 |
| L3 | – / 0,0 / 0 / 3 | – / 10 / 18 / 3 | 7 815, 7 958, 3 326 | 2 de 7 |
| L4 | 0,0 / 3,0 / 0 / 0 | 10 / 10 / 0 / 0 | ~1 400 | 0 |
| L5 | 0,0 / 1,3 / 0 / 0 | 10 / 10 / 1 / 0 | 3 063, 1 945, 2 922 | 0 |

- **Control (A y B, 30 llamadas, prompts sin tocar):** `main` 12 invenciones, rama 5 (contador de
  `main`: 15 y 12); 0 cortadas en las dos. Diferencia 7, menor que el efecto en las llamadas tocadas
  (+21 invenciones en 15), así que el control no explica el resultado y no hace falta `--repeat 5`.
- **Contra el criterio: NO llega.** Códigos y ficheros ≥ 7 y por encima de `main`: sí (por la
  línea; el modelo solo, 5,7 y 6,5). Fidelidad no peor que `main`: **no** (1,40 frente a 0,00).
  0 cortadas: **no** (9 de 15).
- **Por qué:** con 2 088 tokens el paso final escribe 6 000–8 000 caracteres (una entrada por
  fichero de logs con 40–109 ficheros) y aun así acaba en `length` en 7 de las 9 llamadas L1–L3;
  además, en L1–L3 se cortan 2–5 `map` por llamada, cuyo tope no se toca, así que «0 cortadas» no
  es alcanzable solo con el paso final (lo avisó el plan antes de medir). La fidelidad empeora casi
  toda por L3 (`pytest --collect-only`): el modelo escribe recuentos de tests por fichero que el log
  no da (18 de las 21 invenciones); fuera de L3, 3 en 12 respuestas.
- **Coste:** L1–L3 tardan ~35 s más por llamada (~+25 %: 175–197 s frente a 142–169 s con el tope
  de 696) y gastan ~1 400 tokens más de salida.

## Veredicto de B2e y versión adoptada

- `explain_code`: **llega** con el respaldo (×5, misma sesión), con la salvedad de que la cobertura
  de los nombres registrados la garantiza el programa.
- Lint troceado: **no llega** con ninguna de las tres versiones (sin respaldo, con respaldo, con el
  tope nuevo). Límite conocido: en logs de 6 trozos o más, el formato de lint (una entrada por
  fichero) no cabe ni en el paso final ni en los `map`, y los recuentos por fichero que el modelo
  escribe en logs sin recuentos (`pytest --collect-only`) son inventados.
- **Versión adoptada: la de la rama (`742341f`)**, tope nuevo incluido. Frente a `main` es mucho más
  útil (nombra los códigos y ficheros, `main` no nombra ninguno) y no rompe nada medido: la llamada
  única y el control no cambian (prompts y topes iguales), suite verde. Frente al tope de 696, el
  modelo nombra más por sí solo (0,57/0,65 frente a 0,31/0,48) y el paso final se corta menos (7
  frente a 9); a cambio, más latencia y más recuentos inventados en L3. Lo que no llega queda
  documentado y va al backlog del vault (`projects/local-delegate/backlog.md`, §1.8).
