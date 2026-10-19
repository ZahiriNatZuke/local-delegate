# Gate `quality` — `english-names-bilingual-output` (evidencia del 2026-10-18; aprobado el 2026-10-19)

Revisión evaluada: `main` en `b8ede29` (release v0.36.0, PR #330). Nota: `main` ya avanzó a
`c47a636` (`docs: drop retired code-index MCP from codex-config-local records`, solo docs, ajeno al
cambio); la evaluación es sobre `b8ede29`.

## Recomendación

**Aprobar.** CI entero en verde, incluidos los checks que no son workflows; 0 alertas abiertas de
code scanning y de Dependabot; la suite completa pasa en un worktree limpio en las dos variantes;
`ruff` limpio. Lo único que se ve es lo de siempre: 2 skipped y 2 avisos de deprecación de
`anyio.abc.BlockingPortal` que vienen de `starlette/testclient.py`, de terceros.

## CI

`gh pr checks 330`: **19 de 19 en `pass`**.

| Grupo | Checks |
| --- | --- |
| Workflows de CI | `lint`, `secrets`, `audit`, `install-smoke`, `test (ubuntu/macos/windows-latest)`, `test-lang-es`, `cli-python-matrix (3.11, 3.12, 3.13, 3.14, 3.15)`, `ci-gate` |
| Fuera de los workflows | `CodeQL`, `Analyze (python)`, `GitGuardian Security Checks`, `Socket Security: Project Report`, `Socket Security: Pull Request Alerts` |

`gh run list --branch main` tras la mezcla de `b8ede29`: CI, CodeQL, Pages, Vendor audit y Dependency
Graph en `success`. `Publish` del tag `v0.36.0` en `success` (39 s).

Alertas abiertas: `code-scanning/alerts?state=open` → **0**; `dependabot/alerts?state=open` → **0**.

## Suite en un worktree limpio

Worktree limpio en `b8ede29` (detached), `uv sync --group dev --group ui`, todo
con `pesado.sh` desde la tool Bash. Worktree borrado al acabar.

| Corrida | Comando | Resultado | Tiempo |
| --- | --- | --- | --- |
| Por defecto | `uv run pytest -q -n 2 --dist loadgroup -p no:cacheprovider` | **3196 passed, 2 skipped**, 2 warnings | 215 s |
| Como `test-lang-es` | lo mismo con `LANG=es_ES.UTF-8` | **3196 passed, 2 skipped**, 2 warnings | 187 s |

El job `test-lang-es` del CI no usa `LOCAL_DELEGATE_OUTPUT_LANGUAGE`: pone `LANG=es_ES.UTF-8`,
genera el locale y comprueba que ni `LC_ALL` ni `LC_MESSAGES` lo pisen (`.github/workflows/ci.yml:186-220`).
Se replicó con `LANG`. En Windows `LANG` no cambia el locale del sistema, así que esta corrida local
aporta poco frente al job de Ubuntu, que es el que vale (verde en #330). Además el fixture de sesión
de `tests/conftest.py:20-43` fija `LOCAL_DELEGATE_LANG=es` para toda la suite, que por eso da lo
mismo con cualquier locale (REQ-043). La rama de release ya había corrido la suite con
`LOCAL_DELEGATE_LANG=es` y `=en` (3196/2 en las dos: `evidence/live-036/suite-*.txt`).

Los dos resúmenes de `local_lint_summary` coinciden con la línea final del log: 0 fallos, 2 avisos de
deprecación (`starlette/testclient.py:53`, `anyio.abc.BlockingPortal`).

## Otras comprobaciones en la misma revisión

- `ruff check .` → «All checks passed!»; `ruff format --check .` → 266 ficheros ya formateados.
- Detector de nombres (REQ-016) con `rename-exceptions.md`: **0 fuera de la lista**, 849 nombres en
  español únicos, todos con su excepción; **111 palabras sin clasificar** (ver `conformance.md`,
  punto 1: no afecta a calidad, sí a la letra de REQ-044).
- Final de línea (REQ-042): de los 165 ficheros modificados o renombrados entre `8ec2f1d` (antes de
  A0) y `b8ede29`, 0 cambian de clase (LF, CRLF o mixto), comparando los blobs de las dos revisiones.

## Ficheros de esta revisión

Los logs completos de la corrida (`pytest`, `uv sync`, detector, `ruff`) se quedaron fuera del repo:
llevan rutas de la máquina. Sus cifras están arriba; el detector del cierre está en
`evidence/close/detector.txt`.

## Después de la 0.36.0 (2026-10-19)

Los PR mezclados hasta la 0.36.1 (#331–#339 y #341–#342) pasaron cada uno el CI completo (19 checks,
incluidos CodeQL, GitGuardian y Socket). En #341 el CI pilló dos cosas que se arreglaron antes de
mezclar: un nombre en español en un test y un título del panel que se cortaba con la fuente de
reserva de Linux. En #342, una alerta de CodeQL (`py/regex/unmatchable-dollar`) en un script de
medición, arreglada en el código. El PR de la release vuelve a pasar el CI completo.

**Decisión: aprobado** (2026-10-19).
