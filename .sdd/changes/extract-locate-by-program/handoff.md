# Handoff: local_extract: las líneas las calcula el programa y el esquema tiene tipos por campo (#692, #694, #696, #697, #698)

## Current state

- SDD status: `plan-review`, listo para pasar a `implementing`.
- Last completed gate: plan (spec y plan aprobadas el 2026-11-23 tras dos pasadas de revisión).
- Current revision: `origin/main` en `ce09fc5a` (incluye #709, rechazo de binarios); sin cambios de código.

## What changed

- Solo artefactos SDD: `research.md` (promesas de los cerrados e inventario de tests), `spec.md`
  (REQ-001..REQ-022, forma nueva del valor, decisiones D1..D6) y `plan.md` (contrato de interfaz,
  T1..T11 en dos frentes).

## Decisions

- D1 siempre lista `{name, start, end}` (+`hunks`); D2 entrada sin numerar en extract; D3 sin
  interruptor de compatibilidad, 0.54.0 incompatible; D4 el nombre solo decide si hace falta el
  modelo; D5 ancla exacta; D6 se retiran `lines_unverified`, `outline_copies`, `diff_files` de extract.
- Desviación anotada (REQ-015): el booleano se quita de `list` y `location`, y se mantiene en
  `scalar` para no romper campos de sí/no con nombre libre.

## Next action

- Fase 0: el frente A hace T1 (`locate.py`, tipos y `classify_field`); después A (T2-T4) y B
  (T5-T7) en paralelo, B integra (T8), A limpia `line_check.py` (T9), B documenta (T10), T11 cierra.
- Máximo 2 agentes con código; pytest con `pesado.sh`. Prueba en vivo solo al final, con
  `test-window` y ≥ 8 GB libres (mide la fidelidad de las anclas y el `enum` de llama-server).

## Memory

- Canonical note: pendiente (al cerrar, nota del vault de la jornada con la decisión de forma del valor).
- Indexes updated: no.
