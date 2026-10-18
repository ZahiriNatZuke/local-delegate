# B2-affinity — re-evaluación en vivo de la celda de lint (2026-10-18)

Método, criterio y reglas de desvío: `plan.md`, sección «B2-affinity», escritos antes de cada tanda.

## Qué se midió

- Rama `sdd/english-names-bilingual-output` en `db384c3` (B2e), instalada en el daemon con
  `uv tool install --force --reinstall --no-cache ".[llamaswap]"` (el `server.py` instalado es el de
  la rama, comprobado con `diff`). Huella del prompt de lint: `es` `0b070d5d…`, `en` `2c9a0a31…`; la
  de T6 era `5202980b…`.
- Los 4 casos de lint del corpus congelado (`resume-ruff-*`, `sha256` de cada fuente comprobado),
  por `local_lint_summary` del daemon con `path` y `max_words` 200. Una ventana de prueba por
  (modelo, idioma), con el lanzador modificado por `C:\Users\Yohan\.claude\relevos\b2affinity-measure.ps1`
  (`LOCAL_DELEGATE_MODEL_MECHANICAL`, `LOCAL_DELEGATE_FALLBACK=0` y, en `en`,
  `LOCAL_DELEGATE_LANG=en`): calentamiento descartado y 3 repeticiones.
- Cada ventana: 13 llamadas y 13 líneas del log de uso, todas `local_lint_summary`, servidas por el
  modelo pedido, sin `routing` ni respaldo. **Ajenas: 0** en las 14 ventanas.
- Ventanas de prueba (todas cerradas por id): primera tanda `w-20261018T062708Z`,
  `…T062755Z`, `…T062834Z`, `…T062904Z`, `…T062946Z`, `…T063055Z`; segunda `w-20261018T063835Z`,
  `…T063914Z`, `…T063950Z`, `…T064016Z`, `…T064049Z`, `…T064202Z`; regla (1)
  `w-20261018T064601Z`, `…T064725Z`.
- RAM: ≥ 4 GB libres antes de cada carga (mínimo 5,3 GB antes de `qwen36` en `en`); mínimo durante
  una ventana, 4,8 GB (vigilante a 1,5 GB, no saltó).
- Carga en frío mediana del rol (`gemma3-4b`), copia nueva de `metrics.db`: 3,27 s (T6: 3,27 s).

## Primera tanda — la flecha no discriminaba

`first-run/verdict-v1.md`: con el puntuador de T6 el rol saca 0 en 2–3 de 4 casos. Motivo y
ajuste: plan y `scorer-v2-check.md`. Puntuada con la v3, solo como referencia,
`first-run/verdict-v3.md`: rechazada en los dos idiomas, como la segunda.

## Segunda tanda (decide) — puntuador v3 + revisión a mano del sentido

`verdict.md` y `benchmarks/afinidad-2026-10/reevaluation-0.36.0/verdict.json`.

| Alternativo | Idioma | Rep. 1 | Rep. 2 | Rep. 3 | Veredicto | Latencia mediana alt. / rol (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| gemma4-26b-a4b | es | calidad | calidad | calidad | **rechazada** | 3 059–3 330 / 1 488–1 616 |
| gemma4-26b-a4b | en | calidad | calidad | aprobada | **rechazada** | 3 474–3 764 / 1 563–1 792 |
| qwen36-35b-a3b | es | calidad, verbosidad | calidad | calidad | **rechazada** | 3 868–4 484 / 1 488–1 616 |
| qwen36-35b-a3b | en | calidad | calidad | calidad | **rechazada** | 3 223–4 346 / 1 563–1 792 |

La latencia cumple en todas (alternativo ≤ rol + 3,27 s). Criterio 1 (el corpus discrimina) en
todas. Respuestas distintas de 12: rol 11–12, 2B 12, 26B 10 (`es`) y 7 (`en`), Qwen 12: las
repeticiones midieron ruido.

**Revisión a mano del sentido de la comparación** (lo que decide el criterio 2):

- `es`, 26B: en tres-reglas, docstrings y cinco-reglas **no nombra ningún código de regla en 9 de 9
  respuestas** (traduce el nombre de la regla: «Línea demasiado larga: 2 errores»); las cifras son
  correctas. El rol nombra los códigos con cifras válidas (0,50–1,00). Coincide con la v3: peor.
- `en`, 26B: en un-solo-archivo r1 y r2 no da cifras («Multiple instances», «Several lines»); el rol,
  0,67 a mano en r1 y r2 (la v3 le da 0,33 en r2 porque no cuenta «a single»: no cambia el sentido).
  Coincide: peor. En el resto el 26B saca 1,00, mejor que el rol.
- `qwen36-35b-a3b`, los dos idiomas: escribe prosa sin códigos («Se identificaron errores de estilo
  y formato…», «Two instances of the Line too long rule») en la mayoría de casos. Coincide: peor.

Ningún desacuerdo de sentido entre la v3 y la revisión a mano. **Veredicto: ninguna celda de lint
llega al criterio; regla (3): la celda sale de `CELLS`.**

## Lo que esto dice del producto (fuera de la afinidad)

Con la orden de idioma endurecida (B2d, B2d-fix: «redacta cada frase… sin copiar frases del
contenido», «también van en {idioma} las etiquetas… y los nombres de cada chequeo»), los modelos
grandes dejan de copiar los códigos de regla del log y los sustituyen por su descripción traducida,
o escriben prosa sin cifras. La orden dice que los códigos «se quedan tal cual», pero no pide
nombrarlos. Afecta también al rol largo (`gemma4-26b-a4b` resume los logs grandes); B2e ya vio que
el modelo solo nombra el 57 % de los códigos en los logs troceados. Nota en `backlog-note.md`.
