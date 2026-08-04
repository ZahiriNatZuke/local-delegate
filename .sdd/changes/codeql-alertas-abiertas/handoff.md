# Handoff: Cerrar las 10 alertas abiertas de CodeQL: 6 arreglos y 4 descartes

## Current state

- SDD status: `closed` (modo lite).
- Last completed gate: `memory`.
- Current revision: `main` @ `d087b1c` (squash de la PR #133).

## What changed

Las diez alertas abiertas de code scanning quedaron a cero: seis cerradas como `fixed` por el
código y cuatro como `dismissed` con motivo y comentario en GitHub.

- **Arreglos:** patrón del extractor del JS del dashboard (`py/bad-tag-filter`); comentario
  explicativo en los tres `except` vacíos; test de tipografías web buscando la hoja completa con
  esquema y ruta; test de concurrencia comprobando que el semáforo devuelve sus dos slots.
- **Descartes:** `#19` (falso positivo intraprocedural en `sysinfo.py`), `#13` (el `BaseException`
  del canario de macOS es deliberado), `#11` y `#12` (imports perezosos de `ctypes` bajo guarda
  `win32`, que no se pueden unificar porque `ctypes.wintypes` hay que importarlo aparte).

## Decisions

- **El criterio de reparto fue: se arregla si el código queda mejor; se descarta si el único
  beneficio sería que la herramienta calle.** Por eso `#11`/`#12` y `#13` se descartan aunque sean
  técnicamente "arreglables": tocar código Windows-only o el manejo de un hilo lector por una regla
  de estilo mete más riesgo que beneficio.
- **`codeql.yml` se queda con la suite `security-and-quality`**, aunque sea la fuente del ruido de
  reglas de estilo: de ahí salieron también las 15 alertas legítimas ya cerradas.
- **La escalera de `py/bad-tag-filter` se acepta hasta tres vueltas**, con el límite fijado de
  antemano: a la cuarta objeción la alerta pasaba a descarte por inaplicable (el fondo de esa regla
  es «no parsees HTML con regex»). No hizo falta.

## Next action

Nada pendiente de este cambio. Lo único que dejó abierto, para tratar aparte y sin urgencia:
**`tests/test_daemon.py` no aísla `LOCAL_DELEGATE_WEB_TOKEN`**, así que da cuatro `401 == 200` en
cualquier máquina que la tenga definida (esta, desde la 0.22.1). En CI no se ve porque allí no
existe. Se arregla con un `monkeypatch.delenv` o una fixture de entorno limpio.

## Memory

- Canonical note: `obsidian-vault/projects/local-delegate/jornada-2026-08-03-las-alertas-de-codeql.md`.
- Indexes updated: los tres.
  - Memoria del proyecto (Claude Code): jornada nueva, gancho del gotcha de `LOCAL_DELEGATE_WEB_TOKEN`,
    y **actualización de dos memorias existentes en vez de duplicarlas** —
    `feedback-verify-full-ci-before-done` (ahora dice que `gh run list` no ve todos los checks) y
    `control-positivo-no-es-opcional` (ahora exige mirar *qué* assert dispara el mutante).
  - Índice global de Claude Code: dos punteros transversales (`gh run list` ≠ CI en verde; el mutante
    que no prueba nada).
  - Índice de Codex: bloque `Task Group` con nota canónica, conocimiento reutilizable y fallos.
- Sin secretos ni datos personales en ninguno de los artefactos.
