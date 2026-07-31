# Specification: Un gate que mire los steps para que el job fantasma de Windows no bloquee un merge

## Summary

Un run cuyos jobs **acabaron todos sus pasos** puede mergearse, aunque GitHub deje uno sin cerrar.
Un run con un paso fallido **sigue bloqueando**.

Lo consigue un job nuevo, `ci-gate`, que corre en paralelo con los demás y decide mirando los
**steps** de cada job por la API de Actions, no su estado agregado. En el ruleset,
`test (windows-latest)` deja de exigirse por nombre y pasa a exigirse `ci-gate`.

**La premisa está verificada, no supuesta:** `GET /actions/runs/{id}/jobs` devuelve cada job con sus
steps y su `conclusion`, y en las tres ocurrencias del fallo el job colgado mostraba los ocho en
`success` incluido `Complete job`.

## Requirements

- **REQ-001:** `ci.yml` declara un job `ci-gate` **sin `needs`**, que arranca a la vez que los demás.
  (`needs` esperaría a que el job termine, que es justo lo que no pasa.)
- **REQ-002:** `ci-gate` obtiene el veredicto de cada job esperado por este orden:
  1. `conclusion == "success"` o `"skipped"` → **OK**.
  2. `conclusion` con cualquier otro valor (`failure`, `cancelled`, `timed_out`, …) → **FALLO
     inmediato**, sin esperar al resto.
  3. `conclusion` nulo (el job sigue abierto):
     - algún step con `conclusion` distinta de `success`/`skipped` → **FALLO inmediato**;
     - el **último step listado se llama `Complete job` y concluyó en `success`** → **OK**, y se
       registra en la salida como *job fantasma*;
     - en cualquier otro caso → **seguir esperando**.
- **REQ-003:** La lista de jobs esperados es **explícita**, y son los seis de `ci.yml`:
  `lint`, `test (ubuntu-latest)`, `test (windows-latest)`, `test (macos-latest)`, `secrets` e
  `install-smoke`. El gate **no** se incluye a sí mismo.
- **REQ-004:** Un test compara esa lista con los jobs que declara `ci.yml` —expandiendo la matriz—
  **por conjuntos iguales, no por inclusión**, y falla si sobra o falta un nombre.
- **REQ-005:** `ci-gate` **falla** si se agota su plazo de espera con algún job esperado sin
  veredicto, incluido el caso de un job que nunca aparece en la API.
- **REQ-006:** `ci-gate` **falla** si no consigue leer la API tras sus reintentos. No hay ningún
  camino en que un error de lectura se interprete como éxito.
- **REQ-007:** La salida del gate dice, por cada job, qué veredicto le dio y por qué, y nombra
  explícitamente los que pasaron por la vía del *job fantasma*.
- **REQ-008:** El ruleset `protect-main` exige `ci-gate` y **deja de exigir**
  `test (windows-latest)`. Los otros cuatro contextos (`lint`, `test (ubuntu-latest)`,
  `test (macos-latest)`, `secrets`, `Analyze (python)`) **no se tocan**.
- **REQ-009:** `scripts/setup_repo_security.sh` lleva esa misma lista, de modo que reaplicarlo
  reproduce el estado y no lo revierte.
- **REQ-010:** `docs/wiki/Repo-hardening.md` documenta el mecanismo, por qué `needs` no sirve, y
  **qué deja de estar cubierto**.

## Acceptance scenarios

### Scenario: el job fantasma ya no bloquea

- **Given** un run donde `test (windows-latest)` está `in_progress`, con `completed_at: null` y sus
  steps en `success` incluido `Complete job`, y los otros cinco jobs en `success`
- **When** corre `ci-gate`
- **Then** termina en **éxito**, y su salida nombra `test (windows-latest)` como job fantasma

### Scenario: un fallo real sigue bloqueando

- **Given** un run donde `test (ubuntu-latest)` acaba en `failure`
- **When** corre `ci-gate`
- **Then** termina en **fallo**, nombrando el job culpable, sin esperar a los demás

### Scenario: un job abierto a mitad de camino no se da por bueno

- **Given** un job `in_progress` cuyos steps listados están todos en `success` pero **el último no es
  `Complete job`** (el runner va por la mitad y los steps futuros aún no se listan)
- **When** `ci-gate` lo evalúa
- **Then** **sigue esperando**; no lo cuenta como terminado

### Scenario: un job esperado que nunca aparece

- **Given** un run en el que un job esperado no llega a crearse
- **When** se agota el plazo de espera de `ci-gate`
- **Then** termina en **fallo**, nombrando el job que faltó

## Edge cases and failure behavior

- **La API no responde o devuelve error:** reintentos con espera; agotados, **fallo**.
- **Job `skipped` por un `if`:** cuenta como OK. Hoy ningún job de `ci.yml` tiene `if`, pero el
  criterio queda definido.
- **Job cancelado** (por `concurrency` o a mano): `conclusion: cancelled` → fallo. Correcto: un run
  cancelado no debe habilitar un merge.
- **La numeración de steps salta** (comprobado: 1-5 y luego 9-11), así que **el criterio es el
  nombre del último step, nunca contar**.
- **`Complete job` es un nombre que pone GitHub**, no nosotros: es una dependencia externa y va
  anotada como tal. Si GitHub lo renombrara, el gate dejaría de reconocer al fantasma y **volvería a
  esperar hasta fallar por plazo** — degrada al comportamiento de hoy, no a un falso verde.

## Non-functional requirements

- **Seguridad:** el gate solo **lee**. Pide `actions: read` en el propio job; el workflow mantiene
  `contents: read` global. **No** se concede `actions: write` en ningún sitio.
- **Sin dependencias:** el script usa solo la biblioteca estándar, como `check_vendor.py`, para no
  necesitar `uv sync` antes de correr.
- **Coste:** el repo es público, así que los minutos del polling no se facturan.
- **Compatibilidad:** funciona con el `GITHUB_TOKEN` de solo lectura de un PR desde un fork.

## Non-goals

- **`Analyze (python)`** vive en `codeql.yml`, otro run: el gate no lo ve y sigue siendo check propio.
- **No se arregla la causa raíz**, que está en el backend de GitHub y no es alcanzable.
- **No se quita `timeout-minutes`** de `ci.yml`: cubre el otro modo de fallo, un job que se atasca
  ejecutando de verdad.
- **No se automatiza `cancel` + `rerun`**: exigiría `actions: write` (descartado en el research).

## Consecuencia aceptada explícitamente

Con REQ-003, **`install-smoke` pasa a bloquear un merge de hecho**, cosa que hoy no hacía. Es una
decisión tomada en esta sesión, no un efecto colateral, y tiene su pero: ese job depende de PyPI en
vivo, así que un índice degradado bloqueará PRs sin que nada del repo esté roto. Queda documentado
en la wiki.

## Traceability

| Requisito | Trabajo previsto | Evidencia de verificación |
| --- | --- | --- |
| REQ-001 | job `ci-gate` en `ci.yml` | el job aparece y arranca a la vez que los demás en el run del PR |
| REQ-002 | veredicto en `scripts/ci_gate.py` | tests por caso + run real |
| REQ-003 | lista explícita en el script | test |
| REQ-004 | test que parsea `ci.yml` con PyYAML | el test falla si se toca un nombre |
| REQ-005 | plazo de espera y salida distinta de cero | test con job ausente |
| REQ-006 | manejo de error de la API | test con la API fallando |
| REQ-007 | salida del gate | log del run real |
| REQ-008 | `gh api` sobre el ruleset | consulta posterior al ruleset |
| REQ-009 | `scripts/setup_repo_security.sh` | `--dry-run` enseña la lista nueva |
| REQ-010 | `docs/wiki/Repo-hardening.md` | revisión del texto |
