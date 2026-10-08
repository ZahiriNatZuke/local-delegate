# Verification: Las pruebas fuera de las métricas: ventanas de prueba y una sola regla de exclusión en todo el panel

## Environment

- Revision: rama `sdd/test-windows-out-of-metrics` rebasada sobre `origin/main` `415d14d` (incluye
  #242 y #243); commits de T0 a T9 encima.
- Windows 11, Python 3.11 (uv), node del PATH, Playwright del grupo `ui`
  (`uv sync --all-extras --group ui`).

## Evidence

Detalle por tarea, con los controles positivos y el assert que dispara cada uno, en `evidencias/T0.md`
a `evidencias/T9.md`.

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | forma del fichero tras `start`/`stop`/`add`, ids con sufijo | pasa | `tests/test_test_windows.py`, T1 |
| REQ-002 | los cinco instantes del borde; abierta hasta `now`; solapadas; mutantes `<`, `ceil`, cadenas y descarte rápido | pasa; los 4 mutantes fallan | T1 |
| REQ-003 | sin fichero, JSON roto, `version: 2`, entradas ilegibles, caché | pasa | T1 |
| REQ-004 | `test_reason` con `mcp`, banco en relleno y en fila, `test_window`, Codex y Claude | pasa; mutantes fallan | T2 |
| REQ-005 | `fundir` estampa en la copia; hash del log igual | pasa | T2 |
| REQ-006 a REQ-009 | CLI `start`, `stop` (0/1/2 abiertas), `add` (zonas, ms, repetido, fechas malas), `list`/`--json` | pasa; mutante de `stop` falla | T3 |
| REQ-010 | no pisa fichero ilegible; cerrojo ocupado; dos procesos | pasa; mutante sin `FileLock` falla | T1, T3 |
| REQ-011 | paridad de conjunto `events`/`stats` con y sin `include_tests` | pasa; mutante «solo stats» falla en `meta.count` | T4 |
| REQ-012 | `excluded_tests`, `tests_in_range` | pasa | T4 |
| REQ-013 | `/api/hooks` aparta ventanas y cuenta `excluded_tests` | pasa | T4 |
| REQ-014 | `coste` y `cuota` iguales con y sin interruptor; cuota calibrada (guarda) | pasa; mutante de `bloque_coste` falla; el de `_bloque_cuota` es **equivalente** (ver T4) | T4 |
| REQ-015 | agregados de `N` sin la fila en ventana (y con ella sin ventana) | pasa; mutante falla | T2 |
| REQ-016 | botón, `buildQuery`, tres peticiones con la misma query, ⓘ con el número, `localStorage`, guardián de tipografía sobre la barra | pasa; mutantes de query, fuente y punto fallan; capturas en claro y oscuro | T5 |
| REQ-017 | `_last_event` e `/api/inflight` enseñan la fila en ventana | pasa | T4 |
| REQ-018 | `local_status` 4 eventos, «(2 de pruebas fuera)», ventana abierta | pasa; mutante falla | T6 |
| REQ-019 | `metrics.test_windows`: sin fichero, cerradas, 13 h, 1 h, roto, ignoradas; tabla de la wiki | pasa; mutante de 24 h falla | T6 |
| REQ-020 | `main()` de verdad; P-4 con ventana = `--include-tests --excluir`; `--excluir` por instantes; `--include-tests` no quita `--excluir` | pasa; 3 mutantes fallan | T7 |
| REQ-021 | bloqueo y delegación en ventana fuera; `mcp` y banco fuera (fundiendo); `--include-tests` | pasa; mutantes «ignora el fichero» y «sin fundir» fallan | T7 |
| REQ-022 | `directorio_de_logs() == config.LOG_DIR` con y sin variable; los dos scripts importan `test_windows` | pasa | T7 |
| REQ-023 | siembra en el `LOG_DIR` real | **pendiente**: preparada y probada en un `LOG_DIR` temporal (57 ventanas, idempotente); no se ejecutó en la PC por las reglas del encargo | T9 |
| REQ-024 | CHANGELOG, README, wiki (sección nueva, tabla de APIs, tabla del doctor) | hecho; `tests/test_wiki.py` verde | T6, T8 |
| REQ-025 | nombres en inglés y textos en español; ninguna variable nueva | `tests/test_aislamiento_entorno.py` verde sin tocarlo; ninguna dependencia nueva | T10 |
| REQ-026 | `open_test_windows` en `/api/stats`; punto en el botón; orden en el ⓘ | pasa; mutante del punto falla | T4, T5 |
| No funcional: coste de lectura | `stats()` 6000 filas, 0 vs 60 ventanas, mediana de 5 | +10,0 / −0,7 / −0,6 / +1,5 / +1,3 % tras indexar `find` (la versión lineal daba +270 %) | T4 |

## Quality checks

- [x] Project-native tests pass: `pesado.sh uv run pytest -q -rs` → `2381 passed, 2 skipped` (los
  dos omitidos: `chmod` en Windows y uno que solo aplica al CI).
- [x] Lint, formatting: `uv run ruff check .` → «All checks passed!»; `uv run ruff format --check .`
  → «184 files already formatted»; `node --check` del JS extraído del panel → correcto.
- [x] Secret scanning: `gitleaks git --log-opts="origin/main..HEAD"` → «no leaks found».
- [x] No unrelated changes are present.

## Deviations and residual risk

- **T9 sin ejecutar** (REQ-023 y la comprobación en vivo): ni siembra real, ni cifras de
  `medir_adopcion.py` antes y después, ni daemon. Pasos exactos en `evidencias/T9.md`.
- **Medición de rendimiento con log sintético**: leer el log real lo bloqueó el clasificador.
- **Mutante de `_bloque_cuota` equivalente**: la propiedad de REQ-014 para la cuota se cumple por
  construcción; ningún test puede distinguir ese mutante (T4).
- **`medir_enfriamiento.py` aplica solo las ventanas**, no la regla común entera; `medir_adopcion.py`
  sí la aplica al log de uso (T7). Interpretación para cumplir el escenario de P-4 del spec.
- **D8 aprobada por el usuario (2026-10-08)**: `medir_enfriamiento.py` aplica solo las ventanas.
- **`find` optimizado**: `Window.contains` se quitó y la regla vive solo en `Windows.find`; los
  controles de T1 se repitieron sobre el código nuevo.
