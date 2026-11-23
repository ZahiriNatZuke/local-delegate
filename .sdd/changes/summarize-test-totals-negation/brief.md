# Brief: local_summarize: aviso cuando el resumen niega una categoria que el runner de tests conto

## Problem

`local_summarize` sobre una salida corta de `pytest -q` (1616 caracteres, última línea
`750 passed, 2 skipped in 81.33s`, rol `mechanical`) devolvió «completó con éxito 750 casos,
omitiendo 2 … No se reportaron fallos ni saltos», sin aviso (#684). La cifra está en la entrada,
así que la revisión de datos inventados (#630, `grounding.py`) no tiene nada que marcar.

## Desired outcome

Que quien llama sepa, sin releer la fuente, que una frase del resumen niega una categoría que el
runner contó: un aviso `[local-delegate warning: …]` al final, en la línea de los de #630.

## In scope

- Leer por programa la línea de totales de pytest, jest, `cargo test` y `go test -v`.
- Buscar en el resumen una negación de una categoría (fallos/errores, saltos) con recuento > 0,
  en español y en inglés.
- Aviso es/en que cita la frase y la línea del runner y sugiere `local_lint_summary`.
- CHANGELOG, `docs/wiki/Tools.md`.

## Out of scope

- Cambiar el prompt (no se puede probar en vivo desde el agente: el backend da 401).
- Reescribir el resumen.
- Otros runners (vitest, mocha, unittest) y recuentos contradictorios sin negación.

## Log

- L1 2026-11-16 Original request, verbatim:

  > Tarea: arreglar el issue #684 [...]: `local_summarize` sobre una salida corta de `pytest -q`
  > que termina en `750 passed, 2 skipped` dijo «omitiendo 2» y luego «No se reportaron fallos ni
  > saltos», sin aviso. [...] el remedio fiable es por programa, no solo por prompt [...] detectar
  > en la fuente los totales de un runner de tests (pytest `N passed, M skipped/failed/errors`, y
  > si es barato jest/cargo/go) y, si el resumen niega una categoría con recuento > 0
  > («sin/no se reportaron … saltos/fallos», también en inglés), avisar con un warning claro o
  > enderezarlo [...] Sin regex con backtracking catastrófico. [...] Tests: casos positivo,
  > negativo (resumen que dice bien «2 saltados» no avisa) y un control que demuestre que el test
  > falla sin el fix. Los tests existentes deben seguir intactos.
- 2026-11-16 Cambio de entrega de la sesión principal: sin PR propio; push de la rama, los cuatro
  issues abiertos van en un PR conjunto que abre la sesión principal.
- 2026-11-16 Detector `runner_totals.py` y aviso en `local_summarize`; solo aviso, el resumen no
  cambia.
