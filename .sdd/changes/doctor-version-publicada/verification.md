# Verification: doctor compara la version instalada contra la publicada en PyPI

## Environment

- **Revisión:** rama `feat/doctor-version-publicada`, sobre `main` en `52861fc`.
- **Máquina:** Windows 11, Python 3.11 (uv), CLI y daemon en 0.17.0, llama-swap arriba (backend
  en 401, el caso conocido de la key DPAPI que no cruza al shell del agente).
- **Suite:** 429 tests, 1 skipped (417 al empezar; **+12**).

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | Entrada en el registro, grupo y posición | OK | `cli.published` sale entre `cli.path` y `client.presence` en la salida real de `doctor` |
| REQ-002 (WARN) | Instalada por detrás | OK | ejecución real: `[WARN] instalada 0.17.0, publicada 0.99.0: la instalación está atrasada` + `fix_hint` no vacío |
| REQ-002 (OK =) | Al día | OK | `doctor` real en esta máquina: `[ OK ] versión publicada: 0.17.0 (la última publicada)` |
| REQ-002 (OK >) | Repo por delante | OK | ejecución real: `[ OK ] instalada 0.17.0, por delante de la publicada 0.1.0` |
| REQ-002 (UNKNOWN) | Sin red / sin versión instalada / consulta deshabilitada | OK | ejecución real: `[ -- ] instalada 0.17.0; no se pudo consultar PyPI (URLError)`; tests `test_sin_red_...` y `test_sin_version_instalada_...` |
| REQ-003 | Orden numérico | OK | `test_las_versiones_se_comparan_como_numeros_y_no_como_texto` (`0.9.0` vs `0.11.0` → WARN) |
| REQ-004 | El probe no tumba el diagnóstico | OK | `test_una_consulta_que_revienta_no_tumba_el_diagnostico`: con `latest_release` lanzando, `run_all` devuelve los 13 y `cli.published` queda `UNKNOWN` |
| REQ-005 | No escribe | OK | el probe no toca el sistema de ficheros; el test de árbol byte a byte del registro sigue verde |
| REQ-006 | cp1252 | OK | `test_el_detalle_y_la_pista_caben_en_la_consola_de_windows` + `.encode("cp1252")` sobre los tres desenlaces en ejecución real |
| REQ-007 | Una sola definición de «última publicada» | OK | `_default_latest_release` llama a `update.latest_version`; no hay segunda implementación (`grep` de `pypi.org/simple` da un solo sitio) |
| REQ-008 | Colaborador inyectable | OK | `Context.latest_release`; los 4 sitios de test lo doblan y la suite corre sin red |
| REQ-009 | Timeout como constante | OK | `checks.PYPI_TIMEOUT = 2.0` |
| REQ-010 | `install` no consulta PyPI | OK | `test_install_no_consulta_pypi_al_reportar_el_andamiaje` (espía con contador) **+ ejecución real** contra HOME simulado: `[ -- ] versión publicada: instalada 0.17.0; no se consulta PyPI en este comando` |
| REQ-011 | `update` no duplica la consulta | OK | `test_pypi_se_consulta_una_sola_vez_en_todo_el_comando`: cuenta 1, no 2 |
| REQ-012 | `--online` intacto | OK | `doctor.py` no se tocó (`git diff --stat` no lo lista); los 6 tests de `run_doctor` siguen verdes |
| REQ-013 | Los cuatro textos del tamaño | OK | `test_el_docstring_dice_cuantos_checks_hay_de_verdad` verde con `len(CHECKS) == 13` |
| REQ-014 | CHANGELOG bajo `Unreleased` y CRLF | OK | entrada añadida; `CRLF=890, LF sueltos=0`; `git diff --stat` = 8 insertions, 0 deletions |
| REQ-015 | Documentación | OK | `docs/wiki/Integration-install.md`: «doce piezas» → «trece», fila nueva en la tabla, nota de qué comprobación sale a la red y cuál no, y `[ -- ]` incluye «no hay red» |

### Escenarios de aceptación

| Escenario | Cómo se verificó | Resultado |
| --- | --- | --- |
| AC-1 instalación vieja | ejecución real con la publicada forzada a `0.99.0` | `[WARN]`, `fix_hint` presente, `is_warning == True` (aporta al exit 1) |
| AC-2 al día | `local-delegate doctor` real | `[ OK ] versión publicada: 0.17.0 (la última publicada)` |
| AC-3 repo por delante | ejecución real con la publicada forzada a `0.1.0` | `[ OK ] … por delante de la publicada 0.1.0` |
| AC-4 sin red | ejecución real con motivo de fallo | `[ -- ]`, `is_warning == False`, el resto del diagnóstico entero |
| AC-5 `install` no sale a internet | test con espía **y** `local-delegate install --home <sim>` real | 0 consultas; línea `[ -- ]` con el motivo |
| AC-6 `update` no duplica | test con espía que cuenta | exactamente 1 consulta |

### Verificación al revés (obligatoria)

Revertida la inyección de `SKIP_PYPI` en `cli.py` y `update.py`, los dos tests que la protegen
**fallan**:

```
FAILED tests/test_install_clients.py::test_install_no_consulta_pypi_al_reportar_el_andamiaje
FAILED tests/test_update.py::test_pypi_se_consulta_una_sola_vez_en_todo_el_comando
E       assert 2 == 1
E        +  where 2 = len([2.0, 0.0])
```

El `2.0` es la consulta del check (con `PYPI_TIMEOUT`) y el `0.0` la legítima de `run_update`: la
salida del fallo **nombra las dos llamadas**, así que el test no solo detecta el defecto, lo
explica. Restaurada la inyección, los dos pasan.

### El HOME real no se tocó

`sha256` de `~/.claude.json` antes y después de `local-delegate install --home <sim>`:
`5d493a7a18d21952` en los dos casos — **idéntico**.

## Quality checks

- [x] **Tests del proyecto:** `uv run pytest -q` → **429 passed, 1 skipped**.
- [x] **Lint:** `uv run ruff check .` → *All checks passed!*
- [x] **Formato:** `uv run ruff format --check .` → *53 files already formatted*
- [x] **JS del dashboard:** `extract_dashboard_js.py` + `node --check` → OK (39 395 chars).
- [x] **Secretos:** el cambio no introduce credenciales ni datos personales. La única petición de
      red es al índice simple público de PyPI, sin cabeceras de autenticación — la misma que
      `update` ya hacía. Sin dependencias nuevas: `urllib` es stdlib.
- [x] **Sin cambios ajenos:** el diff toca `checks.py`, `cli.py`, `update.py`, cuatro ficheros de
      test, la wiki y el CHANGELOG. Nada más.

## Deviations and residual risk

- **Hallazgo durante la implementación (no estaba en el plan):** el plan decía doblar
  `checks._default_latest_release` con monkeypatch en `test_doctor.py`. **No habría funcionado**:
  el dataclass captura la referencia a la función en el momento de definir el campo, así que
  reasignar el atributo del módulo no cambia el default. Se dobla `update.latest_version`, que es
  el destino real — y es además lo que ya hacía `_stub_environment` con `daemon.query_daemon` y
  `doctor.backend_probe`. Encontrado escribiendo el test, no leyendo el plan.
- **Segundo hallazgo, cazado por un test que falló:** el primer intento metió `latest_release` en
  la lista de colaboradores prohibidos de `test_filtrar_por_grupo_no_toca_la_red_ni_el_backend`, y
  el test falló con razón: `cli.published` vive en `entorno`, así que el filtro por grupos **no**
  lo excluye ni debe hacerlo. Quien lo frena es `SKIP_PYPI`, que es otro mecanismo. Los dos
  quedan probados por separado, y el test lo dice en su docstring para que nadie los vuelva a
  mezclar.
- **Riesgo residual asumido:** `doctor` deja de ser un diagnóstico puramente local. Es la decisión
  explícita del usuario, con el coste medido (0.08 s y 0.07 s en dos consultas seguidas) y el
  peor caso acotado por `PYPI_TIMEOUT = 2.0`.
- **Ruido aceptado (R-4):** el reporte de `install` mostrará siempre `[ -- ] versión publicada:
  … no se consulta PyPI en este comando`. Se prefiere a añadir un mecanismo de exclusión por
  check en `run_all`, que sería la primera grieta hacia el framework que la regla 3 del módulo
  prohíbe.
- **No verificado en macOS ni Linux:** como el resto del repo, queda para el CI del PR (los tests
  corren en los tres sistemas). El código no usa nada específico de plataforma.
