# Verification: La wiki nativa se sincroniza sola desde docs/wiki

## Environment

- Base `9c6cb47` (`main`, tras el PR #107); rama `feat/sync-wiki-nativa`.
- Windows 11, PowerShell 7, `uv run`. La wiki se clonó de verdad para comparar.

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | `paths` del workflow | ✅ | `test_el_workflow_se_dispara_*` + mutante que lo apunta a otra carpeta |
| REQ-002 | `find -delete` antes de copiar | ✅ | revisión del workflow (no ejercitable en local) |
| REQ-003 | script sobre `docs/wiki/` real | ✅ | **18 enlaces convertidos**, y `grep '](\.\.'` sobre la salida da **0** |
| REQ-004 | idem | ✅ | **18 enlaces internos** conservados relativos; mutante que los convierte cae |
| REQ-005 | conversión con ancla | ✅ | `…/llama-swap-blackwell.md#descarga-de-vram-ttl` |
| REQ-006 | `git diff --cached --quiet` | ✅ | revisión del workflow |
| REQ-007 | índice | ✅ | `test_ninguna_pagina_queda_huerfana_del_indice` |

### La medición que motivó el change

Clonando `local-delegate.wiki.git` y comparando con `docs/wiki/`: **los 11 ficheros divergidos**,
último commit del 2026-07-28, con 0.18.0, 0.18.1 y 0.19.0 publicadas encima.

Tras generar con el script, el diff contra la wiki publicada sigue siendo de las 11 páginas — o
sea, el primer push las pondrá todas al día de una vez.

### Verificación al revés: 5 mutantes, 5 cazados

| Mutante | Quién lo caza |
| --- | --- |
| convierte **todos** los enlaces, hermanas incluidas | `test_los_enlaces_entre_paginas_NO_se_convierten` |
| no convierte nada (vuelve al `cp`) | `test_lo_que_sale_del_directorio_se_convierte_*` |
| pierde el ancla | `test_la_conversion_conserva_el_ancla` |
| inventa una URL para un enlace que sale del repo | `test_un_enlace_que_sale_del_repo_se_deja_como_esta` |
| el workflow deja de mirar `docs/wiki` | `test_el_workflow_se_dispara_*` |

**El primero se escapó en la primera pasada**, y por un fallo del test, no del código: comprobaba
la condición sobre el enlace **ya convertido**, donde el `/` de la URL hacía que nunca entrara en
la rama del `if`. Reescrito para preguntar por los enlaces del original, y con un contador que
falla si no llegó a comprobar ninguno — un test que no prueba nada se parece demasiado a uno que
pasa.

## Quality checks

- [x] `uv run pytest -q` → **620 passed, 1 skipped** (611 antes del change).
- [x] `uv run ruff check .` → `All checks passed!`
- [x] `uv run ruff format --check .` → `65 files already formatted`
- [x] `extract_dashboard_js.py` + `node --check` → OK
- [x] Sin secretos: el token va por `secrets.GITHUB_TOKEN` en la URL del clone.
- [x] Sin cambios ajenos: `release.py` y los `docs/wiki/*.md` (salvo `Publishing.md`) no se tocan.

## Deviations and residual risk

- **El push real a la wiki no se puede ejercitar antes del merge.** Que el `GITHUB_TOKEN` empuje a
  `<repo>.wiki.git` es el comportamiento documentado de GitHub, pero **no está medido en este
  repo**. Si fallara, el job saldría rojo con el error del `git push`: fallo visible, no silencioso.
  **Se comprobará en el primer push a `main` tras el merge**, y ahí sí queda medido.
- **REQ-002 (el borrado) se verifica por revisión, no por ejecución.** Ejercitarlo exigiría
  escribir en la wiki real.
- **El primer commit de la wiki será grande** (las once páginas más 18 conversiones). Es el
  resultado buscado, no una anomalía.
