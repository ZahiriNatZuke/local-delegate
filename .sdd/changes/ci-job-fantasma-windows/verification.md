# Verificación (modo lite): acotar el job fantasma de Windows

## Entorno

- Rama `ci/acotar-job-fantasma`, sobre `main` tras el merge del PR #86.
- Verificación en el propio PR **#87**, que es donde se puede observar.

## Evidencia

| Requisito | Comprobación | Resultado |
| --- | --- | --- |
| REQ-001 | `yaml.safe_load` de `ci.yml` | los **cuatro** jobs declaran `timeout-minutes`: `lint` 5, `test` 8, `install-smoke` 10, `secrets` 5 |
| REQ-002 | Comentarios del propio fichero | cada valor lleva su razón y la duración observada; el de `test` explica por qué 8 y no más |
| REQ-003 · REQ-004 | `concurrency` en `ci.yml` | `group: ci-${{ github.ref }}` con `cancel-in-progress` condicionado a que la ref **no** sea `main` |
| REQ-001 | Ejecución real en el PR | los seis jobs pasan; `test (windows-latest)` en **1 m 12 s** contra un límite de 8 min |
| REQ-003 | Ejecución real | el segundo push generó un run nuevo (`30634271697`) sin dejar el anterior ocupando |
| REQ-005 | `docs/wiki/Repo-hardening.md` | sección nueva con el síntoma, el comando de `gh api` para mirar los *steps* y el gotcha del retraso del estado |

## Comprobaciones de calidad

- [x] **YAML validado antes de cada push.** No es trámite: una expresión mal puesta en
      `concurrency` no rompe un job, rompe el workflow entero.
- [x] `uv run pytest -q` → 481 pasan, 1 skip. `ruff check` y `ruff format --check` limpios.
- [x] `CHANGELOG.md` sigue CRLF puro (963 CRLF, 0 LF sueltos).
- [x] Sin cambios ajenos: el diff toca `ci.yml`, `Repo-hardening.md` y el `CHANGELOG`.

## Ajuste durante la implementación

Los valores se **bajaron** tras una objeción del usuario: 15 minutos para `test` eran 10x la
duración real. Se corrigieron con dos datos: el peor caso observado en Windows es **1 m 23 s**, y
el reloj del `timeout` corre sobre la **ejecución** del job, no sobre la espera en cola. Un
timeout de más no protege mejor — solo alarga la espera cada vez que el job se cuelga, que es
justo lo que este cambio ataca.

## Desviaciones y riesgo residual

- **La causa raíz sigue viva y no es nuestra.** Esto acota el daño, no lo cura. Si el cuelgue se
  repite, ahora falla en 8 minutos y se relanza con `gh run rerun`.
- **Riesgo asumido:** un día excepcionalmente lento en el runner podría rozar los 8 minutos y dar
  un rojo que no es del código. Se acepta porque el margen es de ~5,5x y porque el fallo sería
  visible y explicable; si ocurriera, lo correcto es subir el número **con el dato nuevo**, no a
  ojo.
- **No se añadió reintento automático**, a propósito: escondería el problema en vez de acotarlo.
