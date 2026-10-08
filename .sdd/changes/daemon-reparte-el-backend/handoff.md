# Handoff: Daemon: no se pelea por el modelo, aprovecha el cargado, avisa de la lentitud y deja la residencia configurable

## Current state

- SDD status: `implementing`, con la verificación final (T17) hecha. Falta cerrar el gate
  `memory` y pasar el cambio a cerrado; eso lo hace la sesión principal.
- Gates: `spec` (reaprobado por el usuario el 2026-10-08T01:44:25Z) y `plan`, aprobados;
  `quality` y `conformance`, aprobados con la evidencia de T17; `memory`, pendiente.
- Current revision: rama `feat/daemon-reparte-el-backend`, último commit `1aa7c7a` más los cambios
  de cierre sin commitear (`verification.md`, este fichero, `state.json`, `evidencias/T17.md` y las
  claves falsas de `tests/test_llamaswap_api.py` y `tests/test_metrics.py`).

## What changed

- **Turno en el daemon:** el daemon calcula qué modelos chocan en llama-swap (misma regla que v255)
  y les da turno, para que dos tools no se quiten el modelo una a otra. Sin topología se comporta
  como antes.
- **Afinidad:** si ya está cargado un modelo con una celda aprobada (`local_translate` con el 26B o
  Qwen3.6, `local_lint_summary` y `local_delegate` con el 26B), la llamada lo usa en vez de cargar
  el del rol.
- **Cadenas sin residente:** el paso `residente` pasa a `loaded`; `residente` sigue aceptado como
  sinónimo.
- **Espera frente a lentitud:** el log separa espera e inferencia y marca «lento» frente a la
  mediana del modelo; el panel lo enseña.
- **CLI `llamaswap residency`:** muestra, quita (`--none`), fija (`--pin`, con `--vram-model`),
  cambia TTL (`--ttl`) y restaura (`--restore`), siempre con copia fechada y vigilando la recarga.
  `doctor` tiene dos checks nuevos (residencia y turno).
- **Medición de afinidad:** corpus, tanda, hoja a ciegas y veredicto por programa
  (`benchmarks/afinidad-2026-10/`); idioma del mensaje de commit fijado.
- **Documentación:** CHANGELOG (`[Unreleased]`), README y wiki.

## Decisions

- La afinidad de `local_commit_msg` no se implementa (decisión del usuario), aunque el veredicto la
  hubiera aprobado.
- Con afinidad, un fallo de capacidad del alternativo vuelve al modelo del rol (decisión 6 del
  usuario, en la tabla de aclaraciones de `spec.md`).
- El código de la rama va en inglés; los textos de salida, en español.
- Las pruebas en vivo que ensucian las métricas se tratan en un SDD propio, no aquí.

## How to verify

- `bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q -rs -p no:cacheprovider` (en T17:
  `2245 passed, 2 skipped`), `uv run ruff check .` y `uv run ruff format --check .`.
- Evidencia completa en `verification.md`, sección «Ola 11», y en `evidencias/T17.md`.
- Ventanas que P-4 y F1 deben excluir: `2026-10-08T01:20:05.255Z`–`01:22:31.544Z` y
  `2026-10-08T01:24:10.521Z`–`01:24:39.452Z`.

## Risks

- `--pin` exige `--vram-model` porque el estimador no está validado.
- `install`/`update` no conservan el plazo de los clientes MCP.
- Calidad de `local_summarize` y `local_lint_summary` (truncado y resumen pobre en T17).
- Las pruebas en vivo quedan en el log de uso y en el panel.
- Lista completa en `verification.md`, «Deviations and residual risk».

## Next action

1. Commit del cierre y PR contra `main` (commits firmados; revisar `gh pr checks`, CodeQL incluido,
   y resolver los hilos de revisión).
2. Publicar una versión lo decide el usuario; el daemon de esta PC sigue en la 0.32.0 publicada.
3. SDD aparte para renombrar a inglés lo que ya está publicado (variables, campos, comandos).
4. SDD aparte para que las pruebas no cuenten en las métricas.

## Memory

- Canonical note: pendiente; la escribe la sesión principal al cerrar el gate `memory`.
- Indexes updated: pendiente.
