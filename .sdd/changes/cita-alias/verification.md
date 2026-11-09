# Verification: El verificador de citas acepta un alias o una constante del nombre citado (#616)

## Environment

- Revision: rama `fix/cita-alias` sobre `origin/main` 26a14cb9
- Relevant runtime and tool versions: Windows 11, `.venv` propio del worktree (`uv sync --locked`)

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_a_citation_through_an_alias_holds` (constante JS del #616, constante Python con tipo, `import as`) | pass | sin el arreglo fallan los 3; mutante «sin alias» (`names += []`): fallan los 3 |
| REQ-002 | `test_an_alias_does_not_cover_a_wrong_citation`, `test_a_comparison_or_a_call_is_not_an_alias` (5 casos), `test_a_name_bound_mid_statement_is_not_an_alias` (3 casos) | pass | la línea sin nombre ni alias sigue en `["14"]`; mutante sin el ancla de fin de expresión: falla el caso `'…' + suffix`; la guarda `MODE = '…'` falla sin el arreglo; mutantes con coma final, con `search` en vez de `fullmatch` y sin exigir `import`: falla cada uno su caso |
| REQ-003 | `test_the_review_cases` y `test_at_most_two_false_warnings_and_every_real_error` | pass | 26 correctas y 5 errores, igual que antes |
| REQ-004 | `test_the_alias_search_is_linear` | pass | líneas de 50 000 espacios, 5 000 nombres y 5 000 `as` que contienen el nombre, en menos de 1 s |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `uv run --locked pytest` (como `.venv/Scripts/python -m pytest -q -n 2`, por `pesado.sh`) | yes | pass | 6689 passed, 30 skipped (tras renombrar `ALIASED_JS`, que `test_detect_spanish_names` rechazaba) |
| `ruff check .` y `ruff format --check .` | yes | pass | All checks passed; 450 files already formatted |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Solo un nivel de alias; una llamada indirecta (tabla de despacho, `getattr`) sigue pudiendo dar un aviso falso.
- Un alias de un nombre muy repetido puede confirmar una cita cercana a cualquier uso de ese alias; con tope de 5 alias por nombre.
