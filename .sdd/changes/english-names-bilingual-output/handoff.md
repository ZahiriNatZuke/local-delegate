# Handoff: Renombrado a inglés de lo publicado y salidas en español e inglés

## Current state

- SDD status: `closed` (2026-10-19). Gates `spec`, `plan`, `quality`, `conformance` y `memory`
  aprobados; evidencia de los dos últimos de verificación en `evidence/gates/`.
- Last completed gate: `memory`.
- Current revision: release v0.36.1 (PR de release del 2026-10-19). El grueso salió en la v0.36.0
  (2026-10-18, PR #330, `b8ede29`); la 0.36.1 recoge los restos y los huecos del cierre.

## What changed

- **Frente A, renombrado (0.35.0 y olas A7–A10, cerrado el 2026-10-14):** CLI, variables, ficheros
  en disco, API del panel, ids de checks, módulos, identificadores, tests y scripts en inglés. Los
  nombres viejos siguen como alias con aviso (`doctor`, `local_status`, telemetría de hooks) y se
  leen para siempre los formatos viejos. Detector de nombres en español versionado en `scripts/`,
  a 0 fuera de la lista de excepciones y con 0 palabras sin clasificar.
- **Frente B, idioma (0.36.0):** todas las salidas en español y en inglés desde un único catálogo
  (`resources/i18n/{es,en}`). Regla única del idioma: variable `LOCAL_DELEGATE_LANG`, preferencia
  `language.json` que deja `install`, sistema, reserva en inglés. Selector ES/EN en el panel, por
  visitante. El modelo local responde en el idioma vigente o en `LOCAL_DELEGATE_OUTPUT_LANGUAGE`
  (issue #260); `local_commit_msg` no cambia. Contrato de las tools en inglés e igual en los dos
  idiomas (subclaves de `_local_delegate`, cambio que rompe y está anunciado).
- **Cierre y 0.36.1 (2026-10-19):**
  - #331: recuentos por código en el inventario de `local_lint_summary` y celda de afinidad de lint
    por idioma.
  - #332: lista de excepciones del detector en `scripts/data/`, 0 palabras sin clasificar
    (REQ-044) y nota de RAM con modelos grandes.
  - #333 y #341: tarjetas del panel de ancho fijo; la fila de KPIs casa con los dos paneles, las
    cifras grandes no invaden la columna vecina y los títulos se aprietan por igual antes del «…».
  - #338: el juez de idioma quita la línea «Sin mencionar (…)» / «Not mentioned (…)».
  - #339: muestras en vivo de REQ-028 en es/en/fr, 5 documentos × 3 repeticiones por tool.
  - #342: `local_lint_summary` con logs muy grandes: el paso final ya no se corta (7/12 → 0/12) y
    las cifras por fichero las pone el programa.
  - #334–#337: dependencias (ruff, pre-commit, playwright, filelock, fastapi, platformdirs).

## Decisions

- Los alias viven tres versiones menores y **se retiran en la 0.38.0** (ola R, fuera de este
  cambio); el test de horizonte (`tests/test_deprecations.py`) falla si se olvida.
- La lista de excepciones del detector y el léxico viven en `scripts/data/`
  (`name_exceptions.json`, `spanish_lexicon.json`); el guardián exige 0 fuera de la lista y 0 sin
  clasificar. Una palabra nueva se clasifica a mano y se anota en `spanish_lexicon.README.md`.
- El idioma de la respuesta del modelo se mide con el juez «solo prosa»
  (`scripts/judge_response_language.py`), no con el texto entero: los títulos que el formato copia
  tumbaban al detector.
- Las mediciones de lint se hacen con `--repeat 3` y la base re-medida en la misma sesión, con un
  criterio fijado antes sobre las llamadas cuyo prompt cambia.

## Next action

- **Ola R en la 0.38.0:** retirar los alias de nombres viejos (CLI, variables, claves); el test de
  horizonte avisa.
- **Backlog del vault §1.8 (parcial):** en el lint troceado de logs muy grandes, 10 de 12 respuestas
  aún tienen algún paso intermedio (`map`) cortado; el modelo no respeta la lista de ficheros
  (`evidence/lint-large-logs/live.md`).
- **Backlog del vault §1.11 (nuevo):** las cifras por fichero del rol mecánico en español se
  midieron en dos iteraciones y no se adoptaron; queda como límite conocido.
- La Mac sigue en la 0.34: al actualizarla, `LOCAL_DELEGATE_LANG=es local-delegate update`.

## Memory

- Canonical note: vault `projects/local-delegate/`, nota de la jornada del 2026-10-19.
- Indexes updated: `MEMORY.md` del proyecto y el índice de jornadas, con la nota de la jornada.
