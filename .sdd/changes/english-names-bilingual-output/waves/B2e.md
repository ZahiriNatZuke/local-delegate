# Ola B2e: lo que se pierde al combinar los trozos (`local_explain_code` y `local_lint_summary`)

Rama `sdd/english-names-b2e` desde `main` (`e0bcf97`). Ejecuta el lote «B2e» de `plan.md`. Sin
push ni PR. **Estado: medido entero. `explain_code` LLEGA (con el respaldo «sin mencionar», ×5);
el lint troceado NO llega con ninguna versión y queda como límite conocido, con la versión de la
rama adoptada** (regla del usuario del 2026-10-18; plan, sección B2e).

## Commits

| Commit | Qué |
|---|---|
| `aa45bec` docs | sección del lote en el plan |
| `374a77f` fix(i18n) | inventario de nombres registrados de `explain_code`, reduce propio del lint troceado con inventario, `steps` en el log de uso, volcado de notas, `lint_patterns`, cuatro casos del contador; 17 tests y 8 mutantes |
| `e725417` docs | decisiones del usuario y conjunto de medición congelado |
| `1e84ba6` docs | primera medición, cortada por falta de RAM en E1 |
| `ada426d` docs | decisión de separar `explain_code`, `--only-tool`, primera ronda de lint (`main` y rama en la misma sesión) y validación del contador |
| `af879da` fix(i18n) | respaldo «sin mencionar» en el lint troceado; 4 tests y el mutante 9 |
| `6a3f593` docs | segunda ronda de lint, `live.md`, CHANGELOG, suite, corpus y este registro |
| `742341f` fix(i18n) | tope propio del paso final del lint troceado (2 088 tokens) y respaldo «sin mencionar» en `explain_code`; decisiones del 2026-10-18 en el plan; 6 tests y los mutantes 10 y 11 |
| (siguiente) docs | tanda del 2026-10-18, test de B2d-2 ajustado al tope nuevo, `live.md`, plan, CHANGELOG y este registro |

## Medición

Detalle en `evidence/B2e/live.md`.

**Parte de lint, primera y segunda ronda (sesión del 2026-10-17/18).** Medias de L1–L5 con 3
repeticiones (códigos y ficheros, fracción de los 10 más nombrados; fidelidad, invenciones por
respuesta):

| Versión | Códigos | Ficheros | Fidelidad | Cortadas |
|---|---|---|---|---|
| `main` | 0,00 | 0,10 | 0,13 | 9 de 15 |
| rama | 0,33 | 0,52 | 1,40 | 10 de 15 |
| rama + respaldo | 1,00 | 1,00 | 0,87 | 9 de 15 |

**Tanda del 2026-10-18 (otra sesión; `main` re-medido en ella).**

| `explain_code` | E1 `doctor` y `benchmark` | Registrados E1+E2 | Solo el modelo | E3 |
|---|---|---|---|---|
| `main` ×3 / ×5 | 0 de 3 / 0 de 5 | 0,56 / 0,44 | 0,56 / 0,44 | 0,077 / 0,055 |
| rama `af879da` ×3 | 0 de 3 | 0,81 | 0,81 | 0,044 |
| rama `742341f` ×3 / ×5 | 3 de 3 / 5 de 5 | 1,00 / 1,00 | 0,71 / 0,80 | 0,029 / 0,062 |

| Lint (L1–L5) | Códigos | Ficheros | Solo el modelo | Fidelidad | Cortadas | Paso final cortado |
|---|---|---|---|---|---|---|
| `main` | 0,00 | 0,09 | 0,00 / 0,09 | 0,00 | 9 de 15 | – |
| rama, tope 2 088 | 1,00 | 1,00 | 0,57 / 0,65 | 1,40 | 9 de 15 | 7 de 15 |

- `explain_code`: con ×3 el control E3 (prompt idéntico en las dos versiones) bajó por ruido; se
  repitió con `--repeat 5` sin cambiar el criterio y pasa entero. La cobertura la da la línea.
- Lint: no llega en fidelidad ni en cortes; el control (A+B) varía 7 invenciones (12 frente a 5),
  menos que el efecto (+21). Límite conocido y versión adoptada: `live.md`, «Veredicto».
- RAM mínima vista: 4,04 GB (al cargar `qwen36-35b-a3b`); ninguna parada.

## Validación del contador

`evidence/B2e/counter-validation.md`: 28 cifras nuevas a mano (16 reales, 12 inventadas). El
contador corregido da el mismo veredicto que el de `main` en las 28 y no suelta ninguna inventada;
el control negativo y los cuatro arreglos (`counter_controls.py`) salen como se esperaba. No se
revierte nada de `374a77f`. Límite conocido: 9 de las 12 inventadas pasan los dos contadores
(recuentos pequeños que el log escribe como línea o columna).

## Mutantes

`evidence/B2e/mutants.json`, re-corridos al final: los 11 casan (ninguno «no muta») y en cada uno
salta el assert que nombra, no un guardián. El 9 se ajustó para que siga mutando (la línea
`postprocess=_add_not_mentioned` aparece ahora en dos tools). El 10 (tope viejo) hace saltar
`caps["reduce"] == {2088}`; el 11 (sin respaldo en `explain_code`), la búsqueda de la línea.

## Verificación

- Suite completa: `evidence/B2e/suite-es.txt` (`LANG=es_ES.UTF-8`) y `suite-en.txt`
  (`LANG=en_US.UTF-8`), `-n 2`: 3066 passed y 2 skipped en las dos, 0 fallos. Un test de B2d-2
  (`test_every_step_of_the_chunked_lint_asks_for_the_new_cap`) fijaba el mismo tope en todos los
  pasos: ahora fija el de los `map` y el nuevo del paso final; su mutante sigue saltando.
- `ruff check .` y `ruff format --check .` limpios (244 ficheros).
- Corpus: `evidence/B2e/corpus-f2-check.txt` y `corpus-affinity-check.txt`, `ok`, iguales línea a
  línea a los anteriores (la frontera de la 0.36.0 ya cubría `local_lint_summary` y
  `local_explain_code`).
- Al terminar: `restore` del lanzador (huella `c96f022a…a69f69a`), el daemon con el código final
  de la rama instalado y `D:/Projects/ld-wt-b2e-main` borrado.

## Lo que queda

- La mejora del lint troceado en logs de 6 trozos o más: nota en el backlog del vault
  (`projects/local-delegate/backlog.md`, §1.8).

## Llamadas `local_*`

| # | Llamada | Para qué | Resultado |
|---|---|---|---|
| 1 | `local_status` | comprobar backend, roles y cadenas de respaldo antes de medir | vio que la cadena de `long` acaba en `qwen36-35b-a3b`: de ahí `LOCAL_DELEGATE_FALLBACK_LONG=none` |
| 2 | `local_summarize(path=evidence/B2d-4/counter-validation.md)` | el método de la validación a mano | útil a medias (genérico) |
| 3 | `local_summarize(path=evidence/B2e/research.md)` | qué trae `374a77f` | cortado por `max_tokens`; se completó con `git show --stat` |

Tanda del 2026-10-18: 0. El MCP no estaba en la sesión del agente (ECONNREFUSED al empezar y
tampoco tras la reconexión del usuario: un subagente no recupera el MCP), y después medir exige
reiniciar el daemon, que lo tumba. Las respuestas se puntuaron por programa (`score_b2e.py` y
scripts de la sesión), sin pasar por el contexto; pytest, ruff y corpus, por su línea final.
