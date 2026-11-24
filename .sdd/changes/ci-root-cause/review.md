# Result review: Ruido del CI arreglado de raíz: gate, tests de coste, E/S real, huellas y CodeQL

## Review level

- Level: deep
- Judges: result-reviewer-1, result-reviewer-2
- Security reviewer: yes
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | perdón del cancelado sin runner limitado a las patas `(macos-latest)` tras la revisión |
| REQ-002 | yes | yes | paso paralelo con `-m "not perf and not real_io"`, paso `real_io` en serie, job `perf` |
| REQ-003 | yes | yes | `tests/perf.py`; control cuadrático falla |
| REQ-004 | yes | yes | `linear_cost.py` borrado; migraciones con el helper |
| REQ-005 | yes | yes | guardián AST y prohibición de `process_time` |
| REQ-006 | yes | yes | 109 tests `real_io` en serie con reintento |
| REQ-007 | yes | yes | sonda sin el entorno del producto, solo con la firma del crash de la imagen |
| REQ-008 | yes | yes | `check_local.py` en pre-commit; bump con `uv sync --inexact` y comprobación de manifiestos |
| REQ-009 | yes | yes | `ci_retry.sh`, peor caso 240 s |
| REQ-010 | yes | yes | `check_main.py`, probado contra GitHub |
| REQ-011 | yes | yes | CHANGELOG `[Unreleased]` |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F-1 | El bump capturaba con la versión vieja (dist-info sin reinstalar) | found | confirmed fix | confirmed | `uv sync --inexact` antes y `BumpError` si un manifiesto no dice la versión nueva |
| F-2 | El gate perdonaba un cancelado sin runner en Ubuntu o Windows | found | confirmed fix | confirmed | solo `(macos-latest)`; controles para el resto |
| F-3 | La sonda de pwsh usaba `powershell_env` del producto y perdonaba cualquier fallo | found | confirmed fix | confirmed | `os.environ` y solo exit -6/134 o `FileLoadException` |
| F-4 | `str(longrepr)` escapa comillas y la guarda no avisaba | found | list case | confirmed | se lee `longrepr[2]` de tupla o lista |
| F-5 | Los pasos del job `test` sumaban 24 min con el job en 20 | — | found | suspected | job a 25 (firma 30:00) y test que exige suma + 1 ≤ job |
| F-6 | El ruleset exige `test (macos-latest)` por nombre: el perdón del gate no desbloquea el merge | — | found | escalated | decisión del dueño: quitar ese contexto del ruleset y dejar que `ci-gate` mande |
| F-7 | CodeQL «Empty except» (alerta 232) | — | — | confirmed | el `except` registra el tipo de error en la versión; hilo resuelto |

## Required follow-up

- F-6: decidir si se quita `test (macos-latest)` de los checks exigidos del ruleset (ver `docs/wiki/Repo-hardening.md`).
- Actualizar la memoria `ci-pytest-xdist.md`: firma 30:00, macOS sin runner = aviso, marcadores `perf` y `real_io`.
