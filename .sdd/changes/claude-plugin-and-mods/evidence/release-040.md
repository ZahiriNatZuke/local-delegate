# Evidencia — release-040 (preparación de la 0.40.0, sin publicar)

Rama `feat/release-040` desde `main` en `be61ff1` (#405). Fecha: 2026-10-22. Nada publicado: ni
PyPI, ni tag, ni GitHub Release, ni `release.py` en modo real; nada instalado en la PC.

## Compromisos fechados «para la 0.40»

`grep -rn -E "\b0\.40\b|0\.40\.0"` en todo el repo (sin `.git`, `.venv`, `uv.lock`, `benchmarks/`).

| Compromiso | Dónde | Qué se hizo |
|---|---|---|
| Nota «bajar a la 0.39 exige `uninstall` antes» y su coste con la vía B | `plan.md` (release-040), `review-spec.md:151`, `plan.md` «Bajar de versión» | Hecho: `CHANGELOG.md` «Lo que rompe y cómo actualizar» y wiki `Claude-plugin.md#bajar-a-la-039` |
| `README.md` y `docs/wiki/` | `plan.md` (release-040) | Hecho (ver abajo) |
| Socket del paquete frente a la 0.39.0 | `plan.md` (release-040) | Hecho (ver abajo) |
| La PR de release sella `UNRELEASED` en `deprecations.py` | `deprecations.py:60` | No hay entradas `UNRELEASED`; `bump_version.py` no tuvo nada que sellar |
| Captura del README atada a la versión | `docs/wiki/Publishing.md`, `tests/test_capture.py` | Regenerada contra la app de métricas del árbol (`/api/status` = 0.40.0) |
| Nombres retirados «avisan hasta la 0.40.x» | `deprecations.py`, `name_exceptions.json`, README, wiki | No toca en esta release: es el horizonte; la retirada va en la ola 4 (`overdue("0.41.0")`) |
| Sobrecarga de los hooks (+150 ms mediana / +300 ms p95) o se estrechan filtros «antes de la release» | `plan.md` (medición en vivo de F2) | Cumplido según F2-live (#406): +80 ms de mediana con la capa de lectura apagada y +125 ms encendida (tope +150); no hay que estrechar filtros. Rebasado sobre `main` y la cifra va a la wiki `Claude-plugin.md` |
| `measure_plugin_adoption.py --install <instante de la 0.40.0>` | `F2-attribution.md:67` | Queda para después de publicar e instalar (la sesión principal fija el instante) |

## `bump_version.py`

`uv run python scripts/bump_version.py 0.40.0 --dry-run > dryrun.txt` (rc 0; igual en consola):

```
pyproject.toml → 0.40.0
server.json → 0.40.0
src/local_delegate/resources/claude-plugin/local-delegate/.claude-plugin/plugin.json → 0.40.0
src/local_delegate/resources/claude-plugin/.claude-plugin/marketplace.json → 0.40.0
.claude-plugin/marketplace.json → 0.40.0
(dry-run) versiones actuales: ['0.39.0']
(dry-run) uv.lock se regeneraría con `uv lock`
```

`bash pesado.sh uv run python scripts/bump_version.py 0.40.0 --boundaries > bump.txt` (rc 0):

```
Updated local-delegate-mcp v0.39.0 -> v0.40.0
OK: scripts/data/hook_hashes_after.json con 5 huellas de 3 hooks
(los mismos cinco ficheros → 0.40.0)
OK: versión 0.40.0 en todos los archivos
```

`--boundaries` no añadió huellas: `hook_hashes_after.json` no cambia. `--check`: «OK: todos los
archivos declaran 0.40.0».

**Desviación**: el `uv lock` local (uv 0.10.12) reescribió además los marcadores de `httpcore2`
(`h11`, `truststore`), que no tienen que ver con la release; el CI corre `uv lock --check` con el
uv de `setup-uv@v7`, que es el que dejó el lock de `main`. Se descartó ese cambio y en `uv.lock`
solo cambia la línea de la versión de `local-delegate-mcp`, como en la 0.39.0 (#388).

## Simulación del CHANGELOG

`scratchpad/rel040/sim_changelog.py` aplica a una copia la cabecera `## [0.40.0] - 2026-10-22` y
extrae la sección con la misma regex de `release.py::_changelog_notes`. Redirigida a fichero y en
consola: rc 0, 9234 caracteres y 20 líneas de notas, sin error de codificación (cp1252 solo
desfigura los acentos en consola). El CHANGELOG real sigue el patrón de la 0.39.0: `[Unreleased]`
vacío, `## [0.40.0] - 2026-10-22` con párrafo de cabecera, y enlaces de comparación
`[Unreleased]` → `v0.40.0...HEAD` y `[0.40.0]` → `v0.39.0...v0.40.0`.

## Documentación

- `CHANGELOG.md`: párrafo de la 0.40.0, «Lo que rompe y cómo actualizar» (migración por `update`,
  vuelta a settings respetada, bajar a la 0.39 con `uninstall` antes y su coste: cada hook carga el
  paquete de la 0.39, 0,7–1,2 s medidos en F2-live, y sale con código 1 sin bloquear) y una línea de documentación.
- `docs/wiki/Claude-plugin.md`: sección «Bajar a la 0.39».
- `docs/wiki/Savings-and-metrics.md`: `mod_calls` en la fila de `/api/stats` y sección
  «Delegaciones del mod y adopción del plugin» con `scripts/measure_plugin_adoption.py`.
- `plan.md:479` y «Vuelta atrás» del final: `update` respeta `install --claude-delivery settings`
  (#404).
- `README.md`: fila de hooks con el plugin, `--disable-read-hook`, y subsección «Plugin de Claude
  Code, comandos del mod y Claude Desktop» que enlaza a la wiki.
- `docs/wiki/Home.md`: enlaza las 13 páginas de la wiki (todas menos ella misma); sin cambios.
- `docs/assets/dashboard.png` y `dashboard.json`: captura regenerada (v0.40.0, 390 eventos de
  ejemplo), revisada a ojo. App de métricas del worktree en el 9494 y Playwright del venv del
  checkout principal (1.63.0, navegadores ya en caché): no se instaló nada.

## Socket (`depscore`)

`local-delegate-mcp@0.39.0`: supplyChain **89** (la referencia). La 0.40.0 no está publicada y no
se puede puntuar. Dependencias directas sin cambios desde la 0.39.0 (`pyproject.toml` solo cambia
la versión); en el lock solo cambió `virtualenv` (dev, #397).

| Paquete | supplyChain | Otras |
|---|---|---|
| mcp 2.3.0 | 98 | 100 |
| httpx2 2.13.1 / httpcore2 2.13.1 | 100 / 99 | 100 |
| platformdirs 4.13.3 | 99 | 100 |
| fastapi 0.143.2 | 100 | 100 |
| uvicorn 0.54.0 | 97 | 100 |
| filelock 4.2.0 | 98 | 100 |
| anyio 4.15.1 | 96 | 100 |
| pyyaml 6.0.3 (extra `llamaswap`) | 100 | 100 |
| starlette 1.3.1 / sse-starlette 3.4.5 | 99 / 100 | 100 |
| pydantic 2.13.4 / truststore 0.10.4 | 99 / 100 | 100 |
| virtualenv 21.14.9 (dev) | 97 | licencia 80 |

Ninguna por debajo de 0,7. No hay dependencias nuevas.

## Calidad

- `bash pesado.sh uv run pytest -n 2 -q`: **4374 passed, 28 skipped**, 0 fallos.
- `ruff check .` y `ruff format --check .`: limpios.
- `git ls-files --eol` de los tocados: igual que en `main` (README y `pyproject.toml` CRLF; el resto LF).

## Llamadas `local_*`

- `local_summarize(path=docs/wiki/Publishing.md)`: pasos de la release.
- `local_summarize(path=evidence/F2-attribution.md)`: `mod_calls` y la medición de adopción.
- `local_summarize(path=evidence/T0.md)`: vía B y conducta con un `ld_bin` de la 0.39.
- `local_lint_summary`: no hizo falta, la suite salió limpia (se leyeron las 3 últimas líneas).
- `local_commit_msg(path=<diff>)`: borrador del commit.
