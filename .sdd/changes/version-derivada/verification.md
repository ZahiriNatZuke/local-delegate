# Verification: __version__ deja de ser un literal clavado y sale de la metadata del paquete

## Environment

- Revisión base: `3b20fb3` (`main`, 0.19.0 publicada); rama `fix/version-derivada`.
- Windows 11, PowerShell 7, `uv run` sobre el venv del repo (Python 3.11+).
- `pyproject.toml [project].version` = `0.19.0`; el paquete instalado en el venv declara lo mismo,
  así que el test corrió su assert y **no** se saltó por la guarda del entorno desincronizado.

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | `pytest tests/test_release_metadata.py` con el entorno sincronizado | ✅ | `5 passed`, **0 skipped** — el assert se ejecutó de verdad |
| REQ-002 | Contrato heredado de `server._get_version()`: captura `PackageNotFoundError` y devuelve `"0.0.0"` | ✅ | `server.py:43-50`; no se añade política nueva |
| REQ-003 | **Mutante:** restaurar `__version__ = "0.10.0"` en `__init__.py` y correr `-k "version or metadata"` | ✅ | `1 failed, 47 passed`. Cayó **solo** `test_el_paquete_no_declara_su_version_a_mano`, con `AssertionError: local_delegate.__version__ dice '0.10.0' y pyproject.toml '0.19.0'. Mira src/local_delegate/__init__.py: …` |
| REQ-004 | `__version__` sigue siendo `str` y exportado | ✅ | Suite completa en verde; `__all__` sin tocar |

**Lo que demuestra el mutante, y es el punto:** de los 48 tests que la selección ejecutó, cayó
**uno**, y es el nuevo. O sea que antes de este change **ningún** test cazaba el defecto — el
atributo podía mentir nueve versiones sin que la suite se enterara, que es exactamente lo que
pasó. Y falló por el mensaje que le corresponde, no por una guarda ajena.

## Quality checks

- [x] `uv run pytest -q` → **570 passed, 1 skipped** (569 antes del change: el nuevo suma uno).
- [x] `uv run ruff check .` → `All checks passed!`
- [x] `uv run ruff format --check .` → `61 files already formatted`
- [x] `uv run python scripts/extract_dashboard_js.py <salida>` + `node --check` → OK (39.395 chars)
- [x] Sin secretos: el change no toca credenciales, entornos ni configuración. `gitleaks` corre en
      el pre-commit.
- [x] Sin cambios ajenos: el diff son 3 ficheros — `__init__.py`, `test_release_metadata.py` y
      `CHANGELOG.md` — más la traza SDD.

## Deviations and residual risk

- **El escenario «paquete sin instalar» no se ejerció por ejecución.** Se apoya en el contrato ya
  probado de `server._get_version()`, que no es código nuevo de este change. Montar un intérprete
  sin la metadata para comprobar un `except` que ya existía y ya está en uso costaría más de lo
  que aporta.
- **El test puede saltarse solo** si alguien bumpea `pyproject.toml` sin reinstalar el editable.
  Es deliberado: un fallo ahí acusaría a `__init__.py` de un problema del entorno. El `skip` dice
  cuál de los dos casos es. Riesgo: en un entorno permanentemente desincronizado el test dejaría
  de proteger en silencio — mitigado porque el CI parte de un `uv sync` limpio, donde la condición
  del skip no puede darse.
