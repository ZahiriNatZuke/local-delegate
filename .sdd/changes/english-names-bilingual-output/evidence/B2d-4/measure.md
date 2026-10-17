# B2d-4: medición en vivo del compactado de líneas iguales (fijada el 2026-10-17, ANTES de medir)

El cambio y su porqué están en `../../plan.md` (B2d-4, «Decisión»). Método: el de
`../B2d-3/measure.md`, sin cambios: los 10 logs del conjunto 3 (A11–A15 y B31–B35, mismos
documentos y `sha256`; `manifest.json` copiado del de B2d-3 con las etiquetas de B2d-4), tandas A y
B, **3 repeticiones**, ventanas de prueba (`local-delegate test-window start/stop`).

| Tanda | Variables del daemon | Llamadas |
|---|---|---|
| A | `LOCAL_DELEGATE_OUTPUT_LANGUAGE=en` (producto `es`) | A11–A15 |
| B | `LOCAL_DELEGATE_LANG=en`, `LOCAL_DELEGATE_OUTPUT_LANGUAGE=es` | B31–B35 |

| Versión | Commit | Carpeta |
|---|---|---|
| base (B2d-3) | `7a17941` | `../B2d-3/runs/base/` (ya medida con este método; no se repite) |
| paso 1b (B2d-3, `main`) | `20faa5e` / `5a5a7c0` | `../B2d-3/runs/step1b/` (ídem) |
| compactado | el commit del cambio en `sdd/english-names-b2d-4` | `runs/compact/` |

## Pasos

Script de la sesión: `~/.claude/relevos/b2d4-measure.ps1` (copia del de B2d-3 apuntando a este
manifiesto y a `runs/<tag>`; restaura el lanzador y comprueba su huella `c96f022a…`):

1. `b2d4-measure.ps1 -Step stop`; instalar la rama desde la tool Bash:
   `bash ~/.claude/scripts/pesado.sh uv tool install --force --reinstall --no-cache ".[llamaswap]"`.
2. `b2d4-measure.ps1 -Step A -Tag compact` y `-Step B -Tag compact` (cada uno abre y cierra su
   ventana de prueba).
3. `b2d4-measure.ps1 -Step restore` (lanzador original, daemon con la rama).

## Recuento (desde la rama)

```
E=.sdd/changes/english-names-bilingual-output/evidence
for V in base step1b; do
  uv run python $E/B2d-2/score_live.py answers --manifest $E/B2d-3/manifest.json --answers-dir $E/B2d-3/runs/$V > $E/B2d-4/runs/rescore-$V.json
done
uv run python $E/B2d-2/score_live.py answers --manifest $E/B2d-4/manifest.json --answers-dir $E/B2d-4/runs/compact > $E/B2d-4/runs/compact/score-answers.json
uv run python $E/B2d-3/check_controls.py --answers-dir base=$E/B2d-3/runs/base --answers-dir step1b=$E/B2d-3/runs/step1b --answers-dir compact=$E/B2d-4/runs/compact > $E/B2d-4/runs/controls.json
uv run python $E/B2d-2/score_live.py log --usage-log "<log de uso>" --since <inicio A-r1> --until <fin B-r3> > $E/B2d-4/runs/score-log.json
```

La base y el 1b se **re-cuentan** con el contador de esta rama (que acepta el N del bloque
compactado), sin llamadas nuevas: así las tres versiones se miden con la misma vara.

## Criterio de hecho (el de `../../plan.md`, B2d-4)

- **Cortadas:** **0** respuestas con `finish_reason=length` en las 30 llamadas.
- **Fidelidad:** `fidelity_total_mean` ≤ la de la base (11,67 con el contador de B2d-3; se anota
  también la re-contada) y ≤ 4,0.
- **Paréntesis:** `parenthesized_invented` = 0 en las 3 repeticiones.
- **Control:** `cases_kept` ⊇ A15, B31 y B32 (los de la base).
- `identical_in_every_repetition` se anota; si recoge las 10 llamadas, se mira por qué.

Si no cumple, no se adopta: se conserva la evidencia, se anota el veredicto en `live.md` y se
propone el siguiente candidato.

## Añadido durante la medición

Para tener una base del mismo día, el paso 1b de `main` (`5a5a7c0`) se re-midió en la misma
sesión con el mismo método (instalado desde `D:/Projects/ld-wt-b2d4-main`; tag `main-remeasure`,
carpeta `runs/main-remeasure/`). No cambia el criterio fijado arriba; se anota al lado.
Resultado y veredicto: `live.md`.
