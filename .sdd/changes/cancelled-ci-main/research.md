# Research: El cancelled del CI en main tiene causa conocida y firma reconocible

## Current behavior

Consultado con `gh run list --workflow ci.yml --branch main --limit 40`:

| Conclusión | Runs |
| --- | --- |
| `success` | 36 |
| `cancelled` | **3** |
| `failure` | 1 |

Los tres `cancelled`, con `gh api .../jobs`:

| Run | Job de Windows | Estado interno al morir | Duración |
| --- | --- | --- | --- |
| `30652987094` | `cancelled` | `Tests (pytest)` **in_progress** | 17:53:57 → 18:06:57 = **13:00** |
| `30654961990` | `cancelled` | **todos** los pasos `success`, `Complete job` incluido | 18:23:33 → 18:36:33 = **13:00** |
| `30660878897` | `cancelled` | `Tests (pytest)` **in_progress** | 19:54:43 → 20:07:43 = **13:00** |

En los tres, los otros seis jobs en `success` y `ci-gate` incluido.

### Lo que descarta las explicaciones fáciles

- **No es la concurrencia.** `ci.yml:18` declara
  `cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}` — o sea **false en `main`**.
- **No es una persona.** Trece minutos clavados al segundo en tres runs distintos no lo hace nadie
  a mano.
- **No es un estado interno concreto**: dos murieron con el paso corriendo y uno con todo
  terminado. El temporizador cuenta desde el inicio del **job**, no desde el paso.

### La explicación que encaja

`timeout-minutes: 8` (`ci.yml:90`) más los **5 minutos de gracia** que GitHub concede al runner
para atender la cancelación antes de matarlo: **8 + 5 = 13**. Y explica por qué la conclusión es
`cancelled` y no `timed_out`.

## Impact map

| Área | Responsabilidad actual | Impacto esperado | Evidencia |
| --- | --- | --- | --- |
| `.github/workflows/ci.yml` | Comentario con el diagnóstico falso | Se corrige con lo medido | `ci.yml:71-74` |
| `.github/workflows/ci.yml` (paso) | `Tests (pytest)` sin límite propio | Recibe `timeout-minutes: 5` | `ci.yml:102-103` |
| `scripts/ci_gate.py` | Repite el diagnóstico en su docstring | Se corrige | docstring, sección `timeout-minutes` |
| `docs/wiki/Repo-hardening.md` | Sección «`timeout-minutes` NO rescata» | Se reescribe con la firma | líneas 46-57 |
| `tests/test_ci_gate.py` | Ata `JOBS_ESPERADOS` a `ci.yml` | Recibe dos tests de números | líneas 280-292 |

## Existing conventions

- **Un dato que puede desfasarse se ata con un test.** El precedente vivo es
  `test_los_jobs_esperados_son_exactamente_los_de_ci_yml`, que compara **por conjuntos iguales** y
  no por inclusión.
- **Los comentarios explican el porqué y la historia**, incluido lo que se intentó y falló. Por eso
  la corrección se escribe como corrección —diciendo qué ponía antes y por qué era falso— en vez de
  borrar y reescribir: el error tiene valor.
- **`ci_gate.py` y `ci.yml` comparten constantes** para no tener dos fuentes del mismo dato.

## Dependencies and integrations

- La API de Actions, ya usada por `ci_gate.py`.
- El periodo de gracia de 5 minutos es **comportamiento de GitHub**, no configurable. La evidencia
  de que son 5 es la aritmética de los tres runs, no la documentación.

## Risks and unknowns

- **Confirmado por ejecución:** las tres duraciones, los estados internos, `cancel-in-progress`
  false en main, y que `ci-gate` dio `success` en el run cuyos pasos terminaron.
- **Inferido, no medido directamente:** que la gracia sean exactamente 5 minutos. Lo que está
  medido es el total de 13:00 con el límite en 8. Si GitHub cambiara la gracia, la firma cambiaría
  — por eso el test ata el número al texto, para que se corrija junto.
- **No se puede saber por qué pytest se cuelga en Windows:** el runner no subió log
  (`BlobNotFound`) en ninguno de los casos.
