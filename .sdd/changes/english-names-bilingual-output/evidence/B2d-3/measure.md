# B2d-3: medición en vivo de la regla de la cantidad (método de 2026-10-17; base, 1 y 1b medidos; 1c pendiente)

Fijada el 2026-10-17, ANTES de las llamadas con este método. La ejecuta la sesión principal: hay
que reinstalar el daemon con cada versión, y eso tira el MCP de la sesión (pedir `/mcp`).

## Qué cambió respecto a la primera medición del paso 1

La primera medición del paso 1 (n=1, ventanas `w-20261017T145849Z` y `w-20261017T145949Z`) está en
`live-answers/`, `live-runs.json`, `live-score-answers.json` (contador de entonces) y `live.md`. Se
conserva **de referencia**: no cuenta para el criterio. `recount-n1.json` la vuelve a contar, junto
con la de B2d-2, con el contador y el control nuevos. Tres cambios de método (`../../plan.md`, B2d-3):

1. `check_controls.py` acepta «57.» al final de frase (antes lo rechazaba) y lee carpetas de
   repeticiones (`--answers-dir NOMBRE=DIR`, una por versión).
2. `scripts/score_lint_fidelity.py` cuenta también las cifras de cero a veinte en palabras (inglés y
   español; sin «one/un/una/uno» ni «once») y no cuenta como repetida la misma frase bajo dos
   encabezados de fichero distintos.
3. Tres repeticiones por log y versión: `run_live.py --answers-dir DIR --repeat 3`.

## Qué se mide

Los 10 logs del conjunto 3 (`../B2d-2/fidelity-set.json`, **sin tocar**), con `local_lint_summary` y
sus argumentos por defecto, en las dos tandas de siempre, con el mismo `manifest.json`:

| Tanda | Variables del daemon | Llamadas |
|---|---|---|
| A | `LOCAL_DELEGATE_OUTPUT_LANGUAGE=en` (producto `es`) | A11–A15 |
| B | `LOCAL_DELEGATE_LANG=en`, `LOCAL_DELEGATE_OUTPUT_LANGUAGE=es` | B31–B35 |

10 llamadas × 3 repeticiones = **30 respuestas por versión**, 90 en total. Cada versión va a su
carpeta:

| Versión | Commit | Carpeta |
|---|---|---|
| base | `7a17941` (`main`) | `runs/base/` |
| paso 1 | `8999bce` | `runs/step1/` |
| paso 1b | el commit del paso 1b (rama `sdd/english-names-b2d-3`) | `runs/step1b/` |

Las respuestas se llaman `<id>-r<k>.txt` (k = 1, 2, 3) y cada carpeta lleva su `live-runs.json` con
el inicio y el fin de cada tanda y repetición (`A-r1`, …). La temperatura de lint es 0.2: las
repeticiones sí varían. `run_live.py` comprueba los `sha256` antes de llamar.

## Pasos, por versión

Con `E=.sdd/changes/english-names-bilingual-output/evidence`, desde la raíz del repo y con `V` =
`base`, `step1` o `step1b`:

1. Poner el código de la versión (`git checkout <commit>` en un árbol aparte, o la rama) e
   instalarlo en el daemon: `uv tool install --force --reinstall --no-cache ".[llamaswap]"` y
   reiniciarlo (como en `../B2d-2/live-plan.md`). Comprobar con `local_status` que corre esa versión.
   **Los scripts de medición se ejecutan siempre desde la rama** (los de `7a17941` no tienen
   `--answers-dir`): solo cambia el código instalado en el daemon.
2. Tanda A: poner en el daemon las variables de `windows.A.env` y reiniciarlo.
   - `local-delegate test-window start --label "B2d-3 V tanda A es + output en (lint, conjunto 3, 3 rep.)"`
     (anotar el id).
   - `uv run python $E/B2d-2/run_live.py --window A --manifest $E/B2d-3/manifest.json --answers-dir $E/B2d-3/runs/V --repeat 3`
   - `local-delegate test-window stop <id>`
3. Tanda B: lo mismo con `windows.B.env`, `--window B` y la etiqueta `"B2d-3 V tanda B en + output
   es (lint, conjunto 3, 3 rep.)"`.
4. Quitar las variables y reiniciar el daemon.

Orden: base, paso 1, paso 1b. Al acabar, dejar instalada la última versión de la rama.

## Recuento (desde la rama, con las tres carpetas llenas)

```
for V in base step1 step1b; do
  uv run python $E/B2d-2/score_live.py answers --manifest $E/B2d-3/manifest.json --answers-dir $E/B2d-3/runs/$V > $E/B2d-3/runs/$V/score-answers.json
done
uv run python $E/B2d-3/check_controls.py --answers-dir base=$E/B2d-3/runs/base --answers-dir step1=$E/B2d-3/runs/step1 --answers-dir step1b=$E/B2d-3/runs/step1b > $E/B2d-3/runs/controls.json
uv run python $E/B2d-2/score_live.py log --usage-log "<log de uso del daemon>" --since <inicio A-r1 de base> --until <fin B-r3 de step1b> > $E/B2d-3/runs/score-log.json
```

- `answers --answers-dir` da, por versión: `fidelity_totals` (uno por repetición),
  `fidelity_total_mean`, `parenthesized_invented` (cifras inventadas entre paréntesis, por
  repetición), `per_call` (total por llamada y repetición), `identical_in_every_repetition` y el
  detalle completo en `by_repetition`.
- `check_controls.py` da, por versión y caso, qué cifras reales conserva cada repetición,
  `kept_reps`, `ok` (2 de 3) y `cases_kept`.
- `log` da las respuestas cortadas (`finish_reason=length`) por tool y modelo; para saber de qué
  versión es cada una, cruzar su hora con los `live-runs.json` de cada carpeta.

## Criterio de hecho (fijado antes de medir; el mismo que `plan.md`, B2d-3)

El «paso final» es la versión que se publica: 1b, o 1 si 1b empeora.

- **Fidelidad:** `fidelity_total_mean` del paso final **≤ el de la base** y **≤ 4,0**.
- **Paréntesis:** `parenthesized_invented` = **0** en las 3 repeticiones del paso final.
- **Control:** `cases_kept` del paso final incluye **todos** los de la base. Si la base no conserva
  A14, A14 no distingue: se anota y no se juzga.
- Una respuesta cortada se anota y **no** se juzga; el tope de lint no se toca.
- Si `identical_in_every_repetition` recoge las 10 llamadas de una versión, sus repeticiones no miden
  ruido: se anota y se mira por qué antes de concluir.
- Si ningún paso cumple, se reabre el paso 2 del plan (revisión por programa).
- La revisión a mano de atribuciones (cifra o fichero real puesto donde no va), que el contador no
  ve, va en la columna manual de `live.md`, como en B2d-2.

Resultado (2026-10-17, en `live.md`): el paso 1b cumple los tres criterios (media 3,67; paréntesis
0, 0, 0; controles A14, A15, B31 y B32 ⊇ A15, B31 y B32 de la base), pero B35 sale cortado en las 3
repeticiones (`gemma4-26b-a4b`, `finish_reason=length`): repite el mismo texto por cada elemento.

## Paso 1c (fijado el 2026-10-17, ANTES de medirlo)

Decisión del usuario: probar un paso 1c que mantiene la regla del total del 1b y añade que los
elementos con el mismo problema vayan en una sola línea que los nombre juntos, en vez de repetir el
mismo texto por cada uno. Commit: el del paso 1c en la rama `sdd/english-names-b2d-3` (el último).

| Versión | Commit | Carpeta |
|---|---|---|
| paso 1c | el commit del paso 1c (rama `sdd/english-names-b2d-3`) | `runs/step1c/` |

Mismos pasos que arriba con `V` = `step1c` (etiquetas `"B2d-3 step1c tanda A es + output en (lint,
conjunto 3, 3 rep.)"` y `"B2d-3 step1c tanda B en + output es (lint, conjunto 3, 3 rep.)"`):

```
uv run python $E/B2d-2/run_live.py --window A --manifest $E/B2d-3/manifest.json --answers-dir $E/B2d-3/runs/step1c --repeat 3
uv run python $E/B2d-2/run_live.py --window B --manifest $E/B2d-3/manifest.json --answers-dir $E/B2d-3/runs/step1c --repeat 3
```

Recuento, desde la rama:

```
uv run python $E/B2d-2/score_live.py answers --manifest $E/B2d-3/manifest.json --answers-dir $E/B2d-3/runs/step1c > $E/B2d-3/runs/step1c/score-answers.json
uv run python $E/B2d-3/check_controls.py --answers-dir base=$E/B2d-3/runs/base --answers-dir step1=$E/B2d-3/runs/step1 --answers-dir step1b=$E/B2d-3/runs/step1b --answers-dir step1c=$E/B2d-3/runs/step1c > $E/B2d-3/runs/controls-1c.json
uv run python $E/B2d-2/score_live.py log --usage-log "<log de uso del daemon>" --since <inicio A-r1 de step1c> --until <fin B-r3 de step1c> > $E/B2d-3/runs/score-log-1c.json
```

(`controls.json` y `score-log.json` de las tres primeras versiones no se sobrescriben.)

**Criterio del 1c.** Se adopta si cumple los mismos tres criterios que el 1b **y** no corta nada:

- *Fidelidad:* `fidelity_total_mean` ≤ 11,67 (la base) y ≤ 4,0.
- *Paréntesis:* `parenthesized_invented` = 0 en las 3 repeticiones.
- *Control:* `cases_kept` incluye A15, B31 y B32 (los de la base).
- *Cortadas:* **0** respuestas con `finish_reason=length` en las 30 llamadas.

Si no cumple alguno, **se queda el 1b** (se revierte el commit del 1c) y el corte de B35 se anota
como deuda. `identical_in_every_repetition` se anota como en las demás versiones.
