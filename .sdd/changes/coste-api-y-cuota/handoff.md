# Handoff: Panel: coste equivalente a precio de API y % de cuota sin calibrar

## Current state

- SDD status: cerrado. Mezclado en `main` por los PR #232, #233, #235 y #238, sin versión
  publicada.
- Gates: spec, plan, quality, conformance y memory aprobados. T11 (ensayo real del vigilante en
  GitHub) hecho: ver la sección «T11» de `verification.md`.

## What changed

- Densidad de tokens de Claude por familia de tokenizador y por contenido (`densidad.json`).
- Atribución de cada delegación: `tool_use_id`, el hook `anotar_llamada.py` y el modelo del
  transcript (`atribucion.py`).
- Coste equivalente a precio de API (`precios.json`, `valoracion.py`), cuota «sin calibrar»
  (`cuota.py`), cobertura e imágenes aparte en el panel.
- `local-delegate recalcular-coste` (agregados de los transcripts) y el check `config.coste` (22).
- Vigilante semanal de precios y límites (`vigilante-precios.yml`).

## Durable decisions

- Recorded in the vault: `projects/local-delegate/jornada-2026-10-06-el-ahorro-que-se-contaba-a-medias.md`.
- El PR del vigilante queda `BLOCKED` con todo en verde; la salida es cerrarlo y reabrirlo desde la
  cuenta del dueño (documentado en `docs/wiki/Repo-hardening.md`). Se descartó una GitHub App o un
  token personal.

## Next steps

- La cuota se calibra sola cuando haya 3 puntos del statusline de ventanas distintas.
- Lanzar `local-delegate recalcular-coste` cada pocas semanas (lo avisa `doctor`).
