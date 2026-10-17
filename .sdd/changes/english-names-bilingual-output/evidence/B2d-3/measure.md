# B2d-3, paso 1: medición en vivo de la regla de la cantidad (preparada, sin ejecutar)

Fijada el 2026-10-17, ANTES de cualquier llamada de medición. La ejecuta la sesión principal: hay
que reinstalar el daemon con el código de la rama, y eso tira el MCP de la sesión (pedir `/mcp`).

## Qué se mide

Los 10 logs del conjunto 3 (`../B2d-2/fidelity-set.json`, **sin tocar**), con `local_lint_summary` y
sus argumentos por defecto, en las dos tandas de B2d-2:

| Tanda | Variables del daemon | Llamadas |
|---|---|---|
| A | `LOCAL_DELEGATE_OUTPUT_LANGUAGE=en` (producto `es`) | A11–A15 |
| B | `LOCAL_DELEGATE_LANG=en`, `LOCAL_DELEGATE_OUTPUT_LANGUAGE=es` | B31–B35 |

`manifest.json` de esta carpeta son esas 10 llamadas copiadas del manifiesto de B2d-2 (mismos
documentos y `sha256`), con las respuestas en `live-answers/` de aquí. `run_live.py` comprueba los
`sha256` antes de llamar y no llama si alguno cambió.

## Pasos

Con `E=.sdd/changes/english-names-bilingual-output/evidence` y desde la raíz del repo:

1. Reinstalar el daemon con el código de la rama: `uv tool install --force --reinstall --no-cache
   ".[llamaswap]"` y reiniciarlo (como en `../B2d-2/live-plan.md`). Comprobar con `local_status`
   que corre la versión de la rama.
2. Tanda A: poner en el daemon las variables de `windows.A.env` y reiniciarlo.
   - `local-delegate test-window start --label "B2d-3 tanda A es + output en (solo lint, conjunto 3)"`
     (anotar el id).
   - `uv run python $E/B2d-2/run_live.py --window A --manifest $E/B2d-3/manifest.json`
   - `local-delegate test-window stop <id>`
3. Tanda B: lo mismo con `windows.B.env`, la etiqueta de `windows.B.label` y `--window B`.
4. Quitar las variables y reiniciar el daemon. `live-runs.json` (aquí) guarda el inicio y el fin de
   cada tanda.

## Recuento

```
uv run python $E/B2d-2/score_live.py answers --manifest $E/B2d-3/manifest.json > $E/B2d-3/live-score-answers.json
uv run python $E/B2d-2/score_live.py log --usage-log "<log de uso del daemon>" --since <inicio A> --until <fin B> > $E/B2d-3/live-score-log.json
uv run python $E/B2d-3/check_controls.py > $E/B2d-3/controls.json
```

- `answers` aplica `scripts/score_lint_fidelity.py` (`count_inventions`) a cada respuesta contra su
  log congelado: da `fidelity_total` y el detalle por respuesta.
- `log` da, por tool y modelo, las llamadas con `finish_reason=length` (respuestas cortadas).
- `check_controls.py` mira que las cifras reales de los logs que las traen sigan en la respuesta:
  A14 (125/551/653), A15 (10), B31 (57 passed), B32 (7).

## Criterio de hecho

- `fidelity_total` = **0** sobre las 10 respuestas. Nunca por encima de **9** (la base, código
  `32d8612`); B2d-2 dio 12. Si sale entre 1 y 9, el paso 1 no basta: se pasa al paso 2 del plan
  (revisión por programa) y se mide otra vez con este mismo manifiesto.
- Control: `controls_ok` = `true` (las cifras reales siguen ahí). Una regla que quitara todos los
  números bajaría la fidelidad a 0 y suspendería aquí.
- Una respuesta cortada (`finish_reason=length` en el log) se anota y **no** se juzga su fidelidad;
  el tope de lint no se toca (0 cortadas en B2d-2).
- La revisión a mano de atribuciones (cifra o fichero real puesto donde no va), que el contador no
  ve, va en la columna manual de `live.md`, como en B2d-2.
