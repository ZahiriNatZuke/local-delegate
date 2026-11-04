# Handoff: local_summarize corta el resumen a mitad de frase con el max_words por defecto (#580)

## Current state

- SDD status: closed (PR de cierre `chore/close-sdd-2026-11-04-tarde`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `e85c0519` (PR #581)

## What changed

- `server.py`: `_summary_max_tokens(words) = 3w + 64` (514 con `max_words=150`, antes 364 = 2w+64); lo usan la llamada única de `local_summarize` y cada paso de su map/reduce (`max_tokens_for`).
- `sections.py`: `trim_to_last_sentence`; `_chat` acepta `trim_cut` y, si la llamada única acaba en `length`, recorta hasta la última frase completa (o la última línea completa) y quita bloques de código abiertos y títulos o etiquetas colgando. Aviso nuevo es/en `mcp.warning.output_trimmed`, que conserva la frase del aviso viejo.
- Ajustes de la revisión antes de mezclar: una línea entera en negrita que es frase se conserva, los finales `。！？` de chino y japonés cuentan sin espacio detrás y una fila de tabla cortada se quita entera.
- Tests existentes cambiados solo en el número del tope (`test_structured_summary.py`, `test_lossless_summary_output.py`, `test_request_body_compat.py` con `_CHANGED_MAX_TOKENS`), en un commit aparte.

## Decisions

- El recorte es solo de la llamada única: el reduce del map/reduce no se recorta y mantiene el aviso de siempre.
- No se toca el resumen por secciones (ya usa 3w), `local_describe_image` (2w+64, sin cortes en 3 meses de log) ni los topes propios de lint, commit, explain_code o extract.
- Reintento con la orden de acortar: descartado por duplicar la latencia en los casos largos.
- Límite conocido y documentado: una abreviatura («p. ej.», «EE. UU.») cuenta como final de frase.

## Next action

- Ninguna. Entra en la próxima versión publicada.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-04-seis-arreglos-y-el-vigilante-de-precios.md`
- Indexes updated: índice de jornadas de `projects/local-delegate` (sesión principal)
