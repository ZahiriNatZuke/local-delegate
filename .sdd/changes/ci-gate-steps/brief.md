# Brief: Un gate que mire los steps para que el job fantasma de Windows no bloquee un merge

## Problem

`test (windows-latest)` se queda en `in_progress` **con sus ocho pasos terminados en `success`**
—incluido `Complete job`— y `completed_at: null`. El runner acabó (~86 s); quien no cierra el job es
el backend de GitHub. Como el ruleset exige ese contexto por nombre, **el merge queda bloqueado**
hasta que alguien cancela y relanza a mano.

Ocurrió **tres veces en dos días**: PR #77 (1954 s), PR #86 (651 s) y PR #88 (10+ min). Lo normal son
60–125 s.

Evidencia y lo ya descartado (`docs/wiki/Repo-hardening.md:20-66`):

- **No es nuestro código**: el cuelgue es posterior al runner.
- **No es un proceso huérfano** reteniendo handles, el fallo clásico en Windows: verificado por
  ejecución, la suite no deja procesos vivos.
- **`timeout-minutes` no rescata de esto**: lo aplica el runner sobre un job que sigue
  ejecutándose, y aquí el runner ya terminó. Medido en el PR #88: 10+ min con el límite en 8.
- Es un [problema conocido de GitHub sin solución oficial](https://github.com/orgs/community/discussions/161434);
  el [issue #2409 del runner](https://github.com/actions/runner/issues/2409) se cerró *not planned*.

## Desired outcome

Un run cuyos jobs **terminaron todos sus pasos en `success`** puede mergearse, aunque GitHub deje
uno de ellos sin cerrar. Y un run con un paso fallido **sigue bloqueando**, sin excepción.

## In scope

- Un job *gate* en `ci.yml` que consulte la API de Actions y decida por los **steps** de los demás
  jobs del run, no por su estado agregado.
- El cambio correspondiente en los *required status checks* del ruleset y en
  `scripts/setup_repo_security.sh`, que es quien lo aplica.
- Documentar el mecanismo y su modo de fallo en `docs/wiki/Repo-hardening.md`.

## Out of scope

- `Analyze (python)`: es de `codeql.yml`, otro workflow y otro run. Sigue siendo check propio.
- Arreglar la causa raíz en GitHub: no está a nuestro alcance.
- Quitar `timeout-minutes`: cubre **otro** modo de fallo (un job atascado ejecutando de verdad).

## Constraints and risks

- **Riesgo mayor: un gate mal escrito pasa en verde con jobs fallando.** Tiene que fallar por
  defecto, y en particular si no puede leer la API o si un job esperado no aparece.
- **`needs` + `always()` no sirve**: `needs` espera a que el job *termine*, que es justo lo que no
  pasa. El gate corre en paralelo y hace polling.
- **Un check requerido que nadie reporta bloquea el repo para siempre**: el ruleset y el nombre del
  job tienen que cambiar en el orden correcto y coincidir exactamente.
- La lista de jobs esperados no puede ser una **segunda fuente de verdad** frente a `ci.yml`.
- El gate corre en un runner y **puede ser víctima del mismo fallo**. Riesgo residual a documentar.

## Open questions

- ¿La API expone los steps ya concluidos mientras el job sigue `in_progress`? Confirmado en las tres
  ocurrencias por la sesión anterior; **se reconfirma en vivo** durante la verificación de este
  change.
- ¿Cómo sabe el gate qué jobs debe esperar sin duplicar la definición de `ci.yml`?
