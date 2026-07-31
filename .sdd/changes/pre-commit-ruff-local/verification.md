# Verification: El hook de ruff usa el del proyecto y gitleaks sube a la ultima

## Environment

- **Revisión:** rama `chore/pre-commit-ruff-local`, sobre `main` en `ac9a736`.
- **Máquina:** Windows 11, `uv run ruff --version` → **0.16.0** (el mismo que fija `uv.lock`).
- **Suite:** 463 tests, 1 skipped (sin cambio: este change no toca código).

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | Los hooks usan el ruff del entorno | OK | `entry: uv run ruff …` con `language: system`; la ejecución los nombra «ruff (del entorno del proyecto)» |
| REQ-002 | Sin versión de ruff en el config | OK | no queda ningún `rev` de ruff; `uv.lock` es la única fuente |
| REQ-003 | Mismas operaciones que antes | OK | `check --fix` y `format`, con `types_or: [python, pyi]` — el mismo alcance que declara `ruff-pre-commit` |
| REQ-004 | gitleaks al día | OK | `v8.18.4` → `v8.30.1`; el hook se instaló y pasó |
| REQ-005 | El porqué queda escrito | OK | comentario en el fichero con el bug que lo originó y el aviso de no devolverlo al repo remoto |
| REQ-006 | El repo queda sin cambios | OK | ver abajo |

### AC-1 — `pre-commit run --all-files`

```
Detect hardcoded secrets.................................................Passed
ruff (del entorno del proyecto)..........................................Passed
ruff-format (del entorno del proyecto)...................................Passed
```

Y `git status` después: **ningún fichero Python reformateado**. Los únicos modificados son los
que se editaron a mano (el propio config y la traza SDD). Esta es la comprobación de fondo: si el
hook y el CI estuvieran desalineados, se vería exactamente aquí.

### AC-2 — es el ruff del proyecto

`uv run ruff --version` → `0.16.0`, que es literalmente el binario que invoca el `entry` del hook.
No hay un segundo ruff descargado por `pre-commit` con el que pueda discrepar.

### AC-3 — un commit real

El commit de este mismo change pasó por los tres hooks y se completó, dejando `git status`
**limpio**. Es el camino que fallaba —y el que `run --all-files` **no** cubre, porque ahí se pasan
todos los ficheros y en un commit solo los staged (hallazgo R-3 del plan).

### Los cuatro pasos del CI

- `uv run ruff check .` → *All checks passed!*
- `uv run ruff format --check .` → *53 files already formatted*
- `uv run pytest -q` → **463 passed, 1 skipped**
- `extract_dashboard_js.py` + `node --check` → OK

`CHANGELOG.md` con CRLF intacto (**919 CRLF, 0 LF sueltos**).

## Quality checks

- [x] **Tests del proyecto:** pasan (no se tocó código; se corren igual para descartar efectos).
- [x] **Lint y formato:** pasan, y ahora con la garantía de que el hook usa el mismo binario.
- [x] **Escaneo de secretos:** `gitleaks v8.30.1` corrió sobre **todo el repositorio** y pasó. La
      versión nueva no destapó nada que la vieja ocultara.
- [x] **Sin cambios ajenos:** `.pre-commit-config.yaml`, `CHANGELOG.md` y la traza SDD.

## Deviations and residual risk

- **Verificación al revés:** no aplica en su forma habitual —no hay rama de código que romper—,
  pero tiene equivalente y no es una formalidad: el `git status` limpio tras `run --all-files` es
  justamente lo que fallaba antes de este cambio, y es la prueba de que el arreglo funciona.
- **`uv run` en un hook de git depende del PATH** (hallazgo R-1). Aceptable en este repositorio,
  que se trabaja desde terminal; y si fallara, diría «uv: command not found», que explica el
  problema — a diferencia del fallo anterior, que reformateaba en silencio y abortaba el commit
  sin decir por qué.
- **El entorno cacheado del ruff viejo** queda huérfano en `~/.cache/pre-commit`. Inofensivo; lo
  limpia `pre-commit gc`.
- **No verificado en macOS ni Linux:** `language: system` con `uv run` no tiene nada específico de
  plataforma, y el CI no usa `pre-commit` (corre ruff directamente), así que el riesgo se limita a
  la máquina de quien commitee.
