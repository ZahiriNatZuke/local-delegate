# Implementation plan: Un gate que mire los steps para que el job fantasma no bloquee un merge

## Approach

Un script de `scripts/` con **solo stdlib** (precedente exacto: `check_vendor.py`, que habla con OSV
sin dependencias y por eso no obliga a un `uv sync` previo), y un job en `ci.yml` que lo llama.

La pieza que hace todo esto testeable es separar **veredicto** de **espera**:

- `veredicto_de_job(job) -> OK | FALLO | ESPERAR` es una **función pura** sobre el dict que devuelve
  la API. Todos los casos de la spec se prueban offline.
- El bucle de polling recibe un *fetcher* inyectable, así que los tests no tocan la red.

Es el mismo reparto que ya permitió probar los probes de `checks.py`.

## Ordered tasks

El orden no es cosmético: invertir 3 y 4 es exactamente cómo se bloquea un repo para siempre.

1. **T1 — `scripts/ci_gate.py`** (nuevo)
   - Files: `scripts/ci_gate.py`
   - Requirements: REQ-002, REQ-003, REQ-005, REQ-006, REQ-007
   - Contenido:
     - Docstring en español: el fallo, por qué `needs` no sirve, qué **no** cubre.
     - `JOBS_ESPERADOS`: los seis de `ci.yml`. `install-smoke` **incluido a propósito**, con el
       comentario de que eso lo vuelve bloqueante de hecho y que fue una decisión, no un descuido.
     - `veredicto_de_job(job)` con el orden de REQ-002. **El detalle que decide la corrección:** el
       caso *fantasma* exige que el **último step listado se llame `Complete job`** y esté en
       `success`. No se cuenta ni se compara `number` — está comprobado que la numeración salta
       (1-5, luego 9-11).
     - Bucle: cada 10 s hasta **25 min** (ver hallazgo B1: el plazo tiene que cubrir cola +
       ejecución, no solo ejecución). **FALLO inmediato** en cuanto un job da FALLO; no se espera al
       resto.
     - La consulta lleva **`?filter=latest&per_page=100`** explícitos (hallazgos B2 y B3).
     - Red: reintentos y, agotados, **fallo**. Ningún camino convierte un error en éxito.
     - Salida: una línea por job con su veredicto, los fantasmas nombrados, y el informe también a
       `GITHUB_STEP_SUMMARY` si está en el entorno, como `check_vendor.py`.
     - Salidas: `0` OK · `1` un job falló · `2` plazo agotado · `3` no se pudo leer la API.
   - Verification: T3.
   - Rollback: borrar el fichero; nadie depende de él todavía.

2. **T2 — Job `ci-gate` en `.github/workflows/ci.yml`**
   - Files: `.github/workflows/ci.yml`
   - Requirements: REQ-001
   - Contenido: **sin `needs`**, `runs-on: ubuntu-latest`, `timeout-minutes: 30` (por encima de los
     25 de espera, ver B1). `permissions: actions: read` **en el job**; el global sigue en `contents: read`,
     y `actions: write` no se concede en ningún sitio. Un solo paso,
     `python scripts/ci_gate.py`, con `GITHUB_TOKEN`, `GITHUB_REPOSITORY` y `GITHUB_RUN_ID`: sin
     `setup-uv`, porque es stdlib y el runner ya trae Python. Comentario con la historia —las tres
     ocurrencias, por qué `timeout-minutes` no rescata, por qué `needs` no sirve y qué pasa si el
     gate mismo se cuelga—.
   - Verification: el job aparece y reporta en el run del PR.
   - Rollback: quitar el job.

3. **T3 — `tests/test_ci_gate.py`** (nuevo)
   - Files: `tests/test_ci_gate.py`
   - Requirements: REQ-004 y cobertura de REQ-002/005/006

     | Caso | Espera |
     | --- | --- |
     | job `success` | OK |
     | fantasma: `in_progress`, `completed_at` nulo, steps OK, último `Complete job` | OK |
     | `in_progress`, steps OK pero el último **no** es `Complete job` | ESPERAR |
     | `in_progress` con un step en `failure` | FALLO |
     | `conclusion: failure` | FALLO |
     | `cancelled` | FALLO |
     | `skipped` | OK |
     | un job esperado nunca aparece → plazo agotado | salida ≠ 0 |
     | la API lanza en todos los intentos | salida ≠ 0 |
     | **REQ-004:** `JOBS_ESPERADOS` vs los jobs de `ci.yml` (PyYAML, matriz expandida) | **conjuntos iguales** |

   - **Verificar los tests al revés** (regla del repo): relajando el criterio de fantasma a «todos
     los steps en success» —sin exigir `Complete job`—, el caso «a medias» tiene que **fallar**. Si
     no falla, el test no prueba nada. Se comprueba a mano y se anota en `verification.md`.
   - Rollback: n/a.

4. **T4 — `scripts/setup_repo_security.sh`**
   - Files: `scripts/setup_repo_security.sh`
   - Requirements: REQ-009
   - En `REQUIRED_CHECKS`: `test (windows-latest)` sale, `ci-gate` entra. Los otros cinco **no se
     tocan**, `secrets` incluido. Comentario de por qué Windows ya no está y quién lo cubre.
   - Verification: `--dry-run` enseña la lista nueva.
   - Rollback: es idempotente; se devuelve la línea.

5. **T5 — `docs/wiki/Repo-hardening.md`**
   - Files: `docs/wiki/Repo-hardening.md`
   - Requirements: REQ-010
   - La sección del job fantasma pasa de «vía por explorar» a mecanismo implementado, conservando lo
     aprendido (`needs` no sirve; `timeout-minutes` no rescata y sigue por otra razón). **Y dice qué
     deja de estar cubierto:** `test (windows-latest)` ya no se exige por nombre e `install-smoke`
     pasa a bloquear de hecho, con su pero (depende de PyPI en vivo).

6. **T6 — `CHANGELOG.md`**
   - Files: `CHANGELOG.md`. Entrada en `Unreleased`. **Es CRLF**: se edita con la herramienta de
     edición o con Python y `newline=""`, nunca con here-strings de PowerShell.

7. **T7 — Aplicar el ruleset (operativo, DESPUÉS del merge)**
   - Requirements: REQ-008
   - `./scripts/setup_repo_security.sh --dry-run` y luego sin `--dry-run`. El propio script se niega
     si nadie reporta un check pedido (`verify_checks`), que es la red de seguridad de este orden.
   - Verification: releer `gh api .../rulesets/19859628`.
   - Rollback: reaplicar con la lista anterior.

## Test strategy

- **Unit:** T3, offline, sobre la función pura y sobre el bucle con *fetcher* inyectado.
- **Integration:** el run del propio PR — el gate corriendo de verdad contra la API.
- **End-to-end o manual, y esto cierra las dos incógnitas del research:** con el run del PR en
  marcha, consultar `runs/<id>/jobs` y comprobar **(a)** si los seis jobs aparecen desde el arranque
  o van apareciendo, y **(b)** que un job `in_progress` muestra sus steps ya concluidos. Se anota el
  resultado real en `verification.md`, salga lo que salga.
- **Antes del push:** `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run pytest -q --basetemp=...`, y `extract_dashboard_js.py` + `node --check`.
- **Security:** el gate solo lee; `gitleaks` corre en el CI y en `pre-commit`. No se añade ningún
  secreto ni se amplía un permiso más allá de `actions: read`.

## Migration and compatibility

- Ningún cambio en el paquete publicado: `scripts/` no viaja en el wheel.
- El único cambio de configuración externa es el ruleset (T7), reversible y con rollback escrito.
- Compatible con el `GITHUB_TOKEN` de solo lectura de un PR desde un fork.

## Riesgos y cómo los ataca este plan

| Riesgo | Mitigación |
| --- | --- |
| **Falso verde**: el gate pasa con jobs sin terminar | lista de jobs **explícita** (no «los que haya»), criterio `Complete job`, y test del caso «a medias» |
| **Falso verde por error de lectura** | los tres caminos de error salen ≠ 0; test con la API lanzando |
| **Check requerido que nadie reporta** | orden 1-2-3-4 y `verify_checks` del propio script |
| **Desproteger de golpe** | el ruleset **solo** pierde `test (windows-latest)`; los otros cuatro siguen |
| **El gate se cuelga igual** | corre en `ubuntu-latest`, donde no se ha visto; si pasa, el remedio es el de hoy (`cancel` + `rerun`): no se empeora nada |
| **Dos fuentes de verdad** (lista vs `ci.yml`) | test por **conjuntos iguales**, el mismo patrón que ata `SKILL.md` a `list_tools()` |
| **`Complete job` lo nombra GitHub** | anotado como dependencia externa; si cambia, degrada a esperar-y-fallar, nunca a falso verde |

## Plan review

Revisión adversarial hecha en esta sesión **sin subagente** (el usuario pidió no lanzar agentes).
Los hallazgos bloqueantes ya están aplicados arriba; se dejan escritos porque cada uno era un modo
de fallo real del plan anterior.

### Bloqueantes, corregidos

- **B1 — El plazo de espera medía lo que no era.** El plan decía «12 min porque los jobs más lentos
  declaran `timeout-minutes: 10`». Falso razonamiento: **`timeout-minutes` corre sobre la ejecución
  del job, no sobre su espera en cola** — está escrito en el propio `ci.yml:80-81`. Un
  `install-smoke` que espere 5 min por un runner y ejecute 10 suma 15, y el gate lo habría declarado
  fallo con todo en orden. Convertir un bloqueo ocasional en **falsos rojos** es empeorar el
  problema que se viene a resolver. Espera a **25 min**, `timeout-minutes: 30`; en repo público no
  cuesta dinero y el caso normal sale en segundos.
- **B2 — Faltaba `filter=latest`.** `GET /runs/{id}/jobs` acepta `filter=all`, que devuelve los jobs
  de **todos los intentos**. Si algún día se pasara `all` —o si cambiara el default—, tras un
  `rerun` el gate vería el intento fallido anterior y **fallaría para siempre** en ese run. Se pone
  explícito en vez de confiar en el default.
- **B3 — Faltaba `per_page`.** El endpoint pagina a 30. Hoy hay 7 jobs, pero con la lista de
  esperados explícita, un job que caiga fuera de la página **no aparece nunca** y el gate se agota
  esperando. `per_page=100`.

### No bloqueantes, anotados para la implementación

- **El parser del test (T3) tiene que fallar ruidosamente** ante una `strategy.matrix` que no sepa
  expandir (más de una clave, `include`/`exclude`), en vez de devolver un conjunto incompleto en
  silencio. Un parser que calla convierte el test de conjuntos en decoración.
- **La comparación de T3 excluye al propio gate**, y su nombre sale de la misma constante que usa el
  script: si se renombra el job, no hay dos sitios que actualizar.
- **Verificado que el orden de REQ-002 es el correcto**: un job con un step en `failure` y el
  `Complete job` en `success` da **FALLO**, porque la comprobación de steps malos va antes que la
  del fantasma. Es un caso real —cuando un step falla, GitHub cierra el job igual— y sin ese orden
  el gate sería un falso verde de manual.

### Checklist

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
