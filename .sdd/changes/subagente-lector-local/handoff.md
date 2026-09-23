# Handoff — subagente-lector-local (spec v2, plan v4.1)

Estado 2026-09-23 (tarde): **T5 cerrada con el piloto**. Las variantes no se distinguen (V0 0/3,
V1 1/3, V2 1/3; las 9 delegaron y 7 releyeron porque el resumen local no sigue la estructura).
REQ-102 se cierra por «nadie gana»; V1/V2 retiradas (decisión del usuario), y se conservan la ruta
absoluta del hook de Shell, la telemetría del prompt y los scripts. Detalle en `verification.md`.
Pendiente: reinstalar los hooks en la PC (siguen los de T4), commit firmado, gates
quality/conformance/memory y la palanca real: que `local_summarize` respete la estructura
(backlog §4.1).

## Estado anterior (antes del piloto)

Estado 2026-09-23: fase `implementing`; T0–T4 hechas (ver `verification.md`), sin commitear en
`feat/oferta-tool-directa`. Siguiente: **piloto de T5 aprobado por el usuario** — 3 tareas × 3
variantes (9 corridas) con resúmenes SIN pedir datos concretos; corrección por los títulos de
sección del documento, no por un hecho plantado. Si las variantes no se distinguen, se cierra
REQ-102 con ese resultado (sin las 72 corridas). Base del script del control: `control_t4.py`.
Jornada: vault `projects/local-delegate/jornada-2026-09-22-el-subagente-que-reescribia.md`.
