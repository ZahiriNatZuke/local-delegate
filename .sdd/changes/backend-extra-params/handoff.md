# Handoff: Parámetros extra por petición al backend (reasoning effort y extra body)

## Current state

- SDD status: `closed` cuando se mezcle la PR de cierre (`feat/backend-params-close`). Los cinco
  gates están aprobados: spec, plan, quality, conformance y memory.
- Todo está implementado y mezclado en `main`: olas 1–6, PR #345–#356 (la #349 es el arreglo de
  `test_corpus`).
- No hay release: la versión sigue en 0.36.1 y la release queda fuera del plan (§7). El daemon de
  la PC corre el código de `main` instalado con `uv tool install`, y `backend-params.json` está vacío.

## What changed

- Parámetros por rol: el fichero `backend-params.json` y la variable `LOCAL_DELEGATE_BACKEND_PARAMS`
  aceptan una lista cerrada de muestreo y razonamiento. Hay un subcomando
  `local-delegate backend-params show|set|unset|reset`, y `doctor` y `local_status` muestran líneas
  sobre los parámetros.
- Cada petición fusiona los parámetros del rol, y el presupuesto de razonamiento se suma a
  `max_tokens`. Si el backend responde 400, se reintenta una sola vez por operación sin
  parámetros; si el razonamiento no cabe en el contexto, la llamada va sin él.
- El log tiene campos nuevos (`backend_params`, `reasoning_chars`, `backend_params_rejected`,
  `reasoning_skipped`) y el panel enseña marcas de esos estados.
- El benchmark tiene `--reasoning-effort` y `--reasoning-budget`. La documentación va en
  `docs/wiki/Configuration.md`, el README y el CHANGELOG.
- Evidencia:
  - `verification.md`: decisiones de cada lote, la prueba en vivo T19 y los checks de calidad;
  - `review.md`: las revisiones de spec, plan y conformidad;
  - `evidence/`: el benchmark, los eventos del log y cuatro capturas del panel.

## Decisions

- Las decisiones 1–12 del usuario, en `brief.md`.
- Medido en vivo: `low` y `high` no se distinguen. Lo que enciende y acota el razonamiento es
  `enable_thinking` con su presupuesto.
- Qwen3.6 con un presupuesto de 256 en `code` corta la respuesta por `max_tokens`. Cumple la spec,
  pero es un mal uso; la wiki avisa de que hay que vigilar `truncated_out`.
- Comportamientos aceptados en la revisión de conformidad: la excepción de `local_delegate.model`
  y el reintento que falla sin un 400. Están en `spec.md`, sección «Cambios tras la revisión».

## Next action

- Restos menores en el backlog del vault, §1.13:
  - medir un presupuesto recomendable para `code`;
  - un test de «resolver una vez por operación»;
  - booleanos `on`/`off` en el panel;
  - que el panel siga el tema del sistema.
- Siguiente trabajo: el autocompletado de la CLI (backlog §1.12, punto 1b) y, si el usuario lo
  pide, una release con este cambio.
- Contexto: vault `projects/local-delegate/jornada-2026-10-20-cierre-backend-params.md`.
