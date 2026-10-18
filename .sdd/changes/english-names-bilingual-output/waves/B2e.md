# Ola B2e: lo que se pierde al combinar los trozos (`local_explain_code` y `local_lint_summary`)

Rama `sdd/english-names-b2e` desde `main` (`e0bcf97`). Ejecuta el lote «B2e» de `plan.md`. Sin
push ni PR. **Estado: parte de lint medida y NO llega al criterio; parte de `explain_code`
pendiente de su tanda** (decisión del usuario del 2026-10-17: no cabe en RAM con la PC en uso).

## Commits

| Commit | Qué |
|---|---|
| `aa45bec` docs | sección del lote en el plan |
| `374a77f` fix(i18n) | inventario de nombres registrados de `explain_code`, reduce propio del lint troceado con inventario, `steps` en el log de uso, volcado de notas, `lint_patterns`, cuatro casos del contador; 17 tests y 8 mutantes |
| `e725417` docs | decisiones del usuario y conjunto de medición congelado |
| `1e84ba6` docs | primera medición, cortada por falta de RAM en E1 |
| `ada426d` docs | decisión de separar `explain_code`, `--only-tool`, primera ronda de lint (`main` y rama en la misma sesión) y validación del contador |
| `af879da` fix(i18n) | respaldo «sin mencionar» en el lint troceado; 4 tests y el mutante 9 |
| (siguiente) docs | segunda ronda, `live.md`, CHANGELOG, suite, corpus y este registro |

## Medición (parte de lint)

Detalle en `evidence/B2e/live.md`. Medias de L1–L5 con 3 repeticiones (códigos y ficheros como
fracción de los 10 más nombrados; fidelidad, invenciones por respuesta):

| Versión | Códigos | Ficheros | Fidelidad | Cortadas |
|---|---|---|---|---|
| `main` | 0,00 | 0,10 | 0,13 | 9 de 15 |
| rama | 0,33 | 0,52 | 1,40 | 10 de 15 |
| rama + respaldo | 1,00 | 1,00 | 0,87 | 9 de 15 |

No llega: con el respaldo, la cobertura pasa por construcción, pero la fidelidad es peor que la de
`main` y el paso final de los logs de 6 y 8 trozos se corta siempre con los topes de hoy (que no se
tocan). El control (A y B, 30 llamadas, prompts idénticos) varía 1–3 invenciones entre versiones:
menos que el efecto.

## Validación del contador

`evidence/B2e/counter-validation.md`: 28 cifras nuevas a mano (16 reales, 12 inventadas). El
contador corregido da el mismo veredicto que el de `main` en las 28 y no suelta ninguna inventada;
el control negativo y los cuatro arreglos (`counter_controls.py`) salen como se esperaba. No se
revierte nada de `374a77f`. Límite conocido: 9 de las 12 inventadas pasan los dos contadores
(recuentos pequeños que el log escribe como línea o columna).

## Mutantes

`evidence/B2e/mutants.json`, re-corridos tras el `ruff format` de `server.py`: los 9 casan
(ninguno «no muta») y en cada uno salta el assert que nombra, no un guardián.

## Verificación

- Suite completa: `evidence/B2e/suite-es.txt` (`LANG=es_ES.UTF-8`) y `suite-en.txt`
  (`LANG=en_US.UTF-8`), `-n 2`: 3060 passed y 2 skipped en las dos, 0 fallos.
- `ruff check .` y `ruff format --check .` limpios (244 ficheros).
- Corpus: `evidence/B2e/corpus-f2-check.txt` y `corpus-affinity-check.txt`, `ok`, iguales línea a
  línea a los de B2d-4 (la frontera de la 0.36.0 ya cubría `local_lint_summary` y
  `local_explain_code`; su motivo lo anotó `1e84ba6` en `PROMPT_BOUNDARIES`). El respaldo no toca
  prompts: `same-prompt-check.json` sigue igual.
- Al terminar: `restore` del lanzador (huella `c96f022a…a69f69a`, coincide) y el daemon con el
  código de la rama (`af879da`) instalado. `D:/Projects/ld-wt-b2e-main` se conserva para la tanda
  de `explain_code`.

## Lo que falta

1. La tanda de `explain_code` (E1–E3, `main` y rama en la misma sesión), cuando el usuario avise.
2. La decisión del usuario sobre el lint (tope del paso final, límite conocido o criterio): ver
   `live.md`, «Decisión que queda para el usuario».

## Llamadas `local_*`

| # | Llamada | Para qué | Resultado |
|---|---|---|---|
| 1 | `local_status` | comprobar backend, roles y cadenas de respaldo antes de medir | vio que la cadena de `long` acaba en `qwen36-35b-a3b`: de ahí `LOCAL_DELEGATE_FALLBACK_LONG=none` |
| 2 | `local_summarize(path=evidence/B2d-4/counter-validation.md)` | el método de la validación a mano | útil a medias (genérico) |
| 3 | `local_summarize(path=evidence/B2e/research.md)` | qué trae `374a77f` | cortado por `max_tokens`; se completó con `git show --stat` |

Después, 0: reiniciar el daemon para medir tumba el MCP de la sesión y no vuelve. La salida de
pytest, ruff y corpus se leyó por su línea final; las respuestas medidas, por programa
(`score_b2e.py`, `validate_counter.py`), salvo las que la validación a mano pedía leer.
