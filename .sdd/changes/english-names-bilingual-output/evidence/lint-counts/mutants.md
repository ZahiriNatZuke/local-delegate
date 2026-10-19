# Mutantes de los tests de la ola lint-counts (2026-10-19)

`tests/test_lint_single_long.py`, corridos a mano sobre el código de `f5ea72c`:

| Mutante | Qué falla | Qué no falla |
|---|---|---|
| `_lint_single_user` llama a `_lint_inventory(..., with_counts=False)` | los asserts `"CPY001: 4, D401: 4, S603: 4" in head` (es y en) y `"D101: 5, E501: 2, F401: 1"` | las guardas de una llamada, rol largo y tope |
| `code_counts` devuelve 1 para cada código | los mismos tres asserts | ídem |

3 fallos y 5 pasan en los dos casos: dispara el assert de las cifras, no una guarda.
