# Afinidad de `local_lint_summary` por idioma (2026-10-18)

Escrito ANTES de medir. Backlog del vault §1.9; diseño en la sección B2-affinity de `plan.md`.

## Por qué no basta con re-medir lo de hoy

La celda (`local_lint_summary → gemma4-26b-a4b`, rol comparado `gemma3-4b`) se mide forzando el
modelo del rol mecánico (`LOCAL_DELEGATE_MODEL_MECHANICAL`), porque la afinidad sustituye el modelo
del rol **con el prompt del rol mecánico**. Ese prompt no ha cambiado desde B2-affinity (B2f y la
ola lint-counts solo tocan el del rol largo; el mecánico va byte a byte, con test). Re-medirlo tal
cual repetiría la medición de esta misma mañana (26B en `es`: 0 códigos en 9 de 9; rechazada en
los dos idiomas). No es una iteración: no cambia ninguna entrada.

## Iteración 1 (la palanca)

El inventario de B2f con los recuentos de lint-counts va también en la llamada única del rol
mecánico. Es lo que en B2f devolvió los códigos al 26B en el rol largo (H: 0,17 → 0,96 en `es`). El
precio: cambia el prompt de `gemma3-4b` en producción, así que se mide también su no-regresión.

## Método

- Afinidad: `B2-affinity/run_affinity_live.py` (copia de su `b2affinity-measure.ps1` con este
  árbol), los 4 casos `resume-ruff-*` del corpus congelado, 3 modelos (`gemma3-4b` rol,
  `qwen35-2b` control débil, `gemma4-26b-a4b` alternativo) × 2 idiomas, `--repeat 3`, una ventana
  de prueba por (modelo, idioma). Resultados en
  `benchmarks/afinidad-2026-10/reevaluation-lint-counts/results/`, veredicto con
  `B2-affinity/evaluate_reevaluation.py --scorer v2` (la v3) hacia
  `reevaluation-lint-counts/verdict.json` y `verdict.md` aquí.
- No-regresión de `gemma3-4b`: las ventanas M/ME de `lint-counts` (rol mecánico, 6 logs pequeños,
  `--repeat 3`) con este candidato frente al candidato de lint-counts (cuyo prompt mecánico es el de
  `main`), en la misma sesión.

## Criterio (fijado antes de medir)

1. **Celda por idioma:** aprobada si `evaluate_mechanical_cell` da `approved` en cada una de las 3
   repeticiones (igual que B2-affinity), y la revisión a mano del sentido de la comparación rol/26B
   en los casos que decidan el criterio de calidad no la contradice.
2. **No-regresión del rol mecánico (M/ME):** `codes` y `files` no por debajo del candidato de
   lint-counts − 0,05, invenciones por respuesta no por encima + 0,15 (el ruido medido en B2f fue
   0,11–0,12), cortadas no más de +1.
3. Se adopta solo lo que pase 1 **y** 2: si la celda pasa en un idioma y no en el otro, se queda la
   que pasa (campo `language` de `matrix.Cell`). Si 2 falla, la palanca no se adopta aunque 1 pase.
4. Si no pasa en ninguna iteración (la 2 sería tocar una vez la redacción del inventario), se
   documenta el límite: sin afinidad de lint, y el campo `language` no entra (sin celda no hay
   quien lo use).

## Decisión sobre el puntuador

La v3 se usa tal cual para decidir (continuidad con B2-affinity). No se lleva a
`analyze_benchmark.py` en esta ola: hoy apareció otro fallo de lectura (en una frase con varios
códigos y la cifra delante, «6 errores de … (D101) y 3 errores de … (D102)», la v3 da a D101 el 3
de D102; `lint-counts/count-scorer-check.md`), y su control contra revisión a mano quedó en 14 de
16. Llevarla al producto exige antes ese arreglo y re-puntuar T6 con revisión a mano.
