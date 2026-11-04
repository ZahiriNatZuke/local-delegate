# Implementation plan: local_extract: marcadores de sin dato a null y cuentas de listas vacías

## Approach

Todo en `server.py`, junto a `_normalize_extract_keys`: una función pura `_is_no_data_marker`
sobre una lista cerrada, `_null_placeholders(data, fields)` aplicada antes de normalizar las claves
(el relleno desde parciales de #473 también se salta los marcadores), y `_recount_lists(data,
fields, content)` tras la normalización. El prompt suma una cláusula fija `_EXTRACT_NO_DATA_CLAUSE`
al `system` (de ahí la heredan mapa y reduce). Avisos nuevos en i18n es/en. Las fixtures congeladas
de extract se actualizan solo en el texto del prompt. `local_extract` no tiene celda de afinidad
(`matrix.CELLS`), así que cambiar su prompt no deja ninguna celda sin base.

## Ordered tasks

- [x] T1 — Marcadores a null, `placeholder_keys`, `missing_keys` y aviso (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: src/local_delegate/server.py, src/local_delegate/resources/i18n/{es,en}/mcp.json
  - Verification: tests unitarios y con backend falso
  - Depends on: none
- [x] T2 — Cláusula del prompt: aplazada y escalada (REQ-005)
  - Files or modules: ninguno en este PR (ver REQ-005 en la spec)
  - Verification: review de verification.md
  - Depends on: none
- [x] T3 — Recuento de listas de primer nivel (REQ-006)
  - Files or modules: src/local_delegate/server.py, i18n
  - Verification: tests con backend falso, casos positivos y negativos
  - Depends on: T1
- [x] T4 — CHANGELOG, wiki, docstring y suite completa (REQ-007, REQ-008)
  - Files or modules: CHANGELOG.md, docs/wiki/Tools.md, tests/data/uncatalogued_exceptions.json, scripts/data/spanish_lexicon.json
  - Verification: pytest -n 2 con pesado.sh; ruff
  - Depends on: T1, T2, T3

## Test strategy

- Unit: `_is_no_data_marker` con marcadores y valores legítimos.
- Integration: `local_extract` con `_run_chat` doblado (patrón de test_extract_normalize_keys.py),
  modos schema y libre, llamada única y troceada.
- End-to-end or manual: la prueba en vivo con el backend real la hace la sesión principal.
- Control positivo: mutantes que anulan la normalización, el recuento y la cláusula; anotar qué
  assert dispara.
- Security and secret scanning: sin secretos; personal-security-check antes del commit.

## Migration and compatibility

- Claves nuevas opcionales en `_local_delegate` (`placeholder_keys`, `recounted_keys`); un valor
  marcador que antes llegaba como cadena ahora llega `null`. Rollback: revertir el PR.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
