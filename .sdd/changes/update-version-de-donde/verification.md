# Verification: update dice de donde saco la version publicada y como saltarse la cache

## Environment

- **Revisión:** rama `feat/update-version-de-donde`, sobre `main` en `f05b4e2`.
- **Máquina:** Windows 11, Python 3.11 (uv), instalación **editable** desde
  `D:\Projects\local-delegate`, CLI y daemon en 0.17.0.
- **Suite:** 438 tests, 1 skipped (429 al empezar el change; **+9**).

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | `--version` no se presenta como «la última publicada» | OK | ejecución real: `Versión pedida con --version: 0.99.0`; test que asevera que ninguna línea contiene «publicada» |
| REQ-002 | La fuente aparece nombrada | OK | ejecución real: `Última versión publicada: 0.17.0 (índice simple de PyPI, que se sirve con caché)` |
| REQ-003 | Sin red se conserva el comportamiento | OK | `test_sin_red_se_conserva_el_aviso_de_siempre`: motivo + «sin tocar los pines» |
| REQ-004 | Todo sale por `out` | OK | `run_update` solo usa `out(line)`; los tests capturan con `out=lista.append` y ven las líneas |
| REQ-005 | Se detecta instalada > publicada | OK | **ejecución real** con la publicada forzada a `0.16.0`: `Ojo: la instalada (0.17.0) es MÁS NUEVA que la que anuncia PyPI.` |
| REQ-006 | El recordatorio lleva la versión sustituida | OK | ejecución real: `Si es la que quieres fijar: local-delegate update --version 0.17.0`; el test exige `--version 0.17.0` literal |
| REQ-007 | No cambia el plan ni el exit code | OK | `test_el_aviso_de_desfase_no_cambia_el_plan_ni_el_exit_code`: mismo exit code, y quitadas **las líneas exactas** del aviso las dos salidas son idénticas |
| REQ-008 | Sin segunda comparación de versiones | OK | se llama a `checks._compare_versions`; `grep` no encuentra otra implementación en `update.py` |
| REQ-009 | El dato medido, escrito | OK | docstring de `latest_version()`: 600 s vs 900 s y por qué cambiar de endpoint empeoraría |
| REQ-010 | CHANGELOG bajo `Unreleased`, CRLF | OK | `CRLF=896, LF sueltos=0` |
| REQ-011 | cp1252 | OK | `test_las_lineas_caben_en_la_consola_de_windows` sobre los tres desenlaces |

### Escenarios de aceptación

| Escenario | Cómo se verificó | Resultado |
| --- | --- | --- |
| AC-1 acabas de publicar | **ejecución real** con `latest_version` forzada a `0.16.0` | las tres líneas del aviso, con `--version 0.17.0` ya sustituida |
| AC-2 versión pedida a mano | **ejecución real** `update --dry-run --version 0.99.0` | `Versión pedida con --version: 0.99.0`, sin la frase de «última publicada» |
| AC-3 caso normal | **ejecución real** `update --dry-run` contra PyPI de verdad | fuente nombrada, sin aviso de desfase |
| AC-4 sin red | test con motivo de fallo | mensaje de siempre, sin aviso |
| Bordes | versión instalada `None` y sin dígitos | sin aviso (`test_sin_con_que_comparar_se_calla`, parametrizado) |

### Verificación al revés (obligatoria)

Sustituida la condición del aviso por `if False:`, **fallan exactamente los dos tests que lo
protegen** y ninguno más:

```
FAILED tests/test_update.py::test_instalada_mas_nueva_que_la_publicada_avisa_y_recuerda_el_flag
FAILED tests/test_update.py::test_el_aviso_de_desfase_no_cambia_el_plan_ni_el_exit_code
2 failed, 49 passed
```

## Quality checks

- [x] **Tests:** `uv run pytest -q` → **438 passed, 1 skipped**.
- [x] **Lint:** `uv run ruff check .` → *All checks passed!*
- [x] **Formato:** `uv run ruff format --check .` → *53 files already formatted*
- [x] **Secretos:** el cambio es de texto de salida. Sin credenciales, sin peticiones nuevas (el
      número de llamadas a PyPI por ejecución no cambia) y sin dependencias.
- [x] **Sin cambios ajenos:** `update.py`, `tests/test_update.py`, `CHANGELOG.md` y la traza SDD.

## Deviations and residual risk

- **La causa raíz sigue abierta a propósito.** Distinguir «PyPI sirvió caché stale» de «la
  publicación aún no había terminado» exige medir durante una publicación real, y publicar
  requiere confirmación explícita del usuario. Este cambio no la resuelve: hace que la próxima
  publicación **deje constancia en pantalla** de si el desfase ocurrió, que es lo que permitirá
  zanjarla sin adivinar.
- **El aviso saldrá en cada `update` de esta máquina** mientras el repo vaya por delante de PyPI
  (hallazgo P-1 de la revisión del plan). Se acepta: la afirmación es cierta, es informativa, y
  suprimirlo en instalaciones editables lo apagaría justo en la máquina desde la que se publica
  —que es donde ocurre el síntoma—. Verificado en la ejecución real de AC-3: hoy, con el repo y
  PyPI los dos en 0.17.0, **no** aparece.
- **Lo que se descartó con dato, no con opinión:** cambiar al endpoint JSON, que era el arreglo
  que proponía el backlog. Se sirve con `max-age=900` frente a los `600` del índice simple, así
  que habría empeorado el síntoma. Queda escrito en el docstring de `latest_version()` para que
  no haya que volver a medirlo.
