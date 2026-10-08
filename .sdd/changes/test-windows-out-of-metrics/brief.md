# Brief: Las pruebas fuera de las métricas: ventanas de prueba y una sola regla de exclusión en todo el panel

## Problem

Las pruebas en vivo contra el MCP o el daemon escriben en el mismo log de uso que el trabajo real y
ensucian el panel, `local_status` y las mediciones de P-4 y F1. Hoy solo el coste aparta las pruebas
(cliente `mcp` y bancos), y los medidores dependen de `--excluir` a mano.

## Desired outcome

Una regla común de «es una prueba» que aplican el panel entero, `local_status`, el coste, el
recálculo y los medidores; un fichero `test-windows.json` con ventanas UTC gestionado con
`local-delegate test-window`; un interruptor en el panel para verlas. El log no se reescribe.

## In scope

Ver `spec.md`, REQ-001 a REQ-026 (REQ-026 condicionado a D7).

## Out of scope

Ver `spec.md`, «Non-goals».

## Constraints and risks

Código en inglés y textos en español; el panel es un dashboard; sin variables de entorno nuevas;
comandos pesados con `bash ~/.claude/scripts/pesado.sh`; otro agente cambia `web/metrics.py` en
paralelo (T0 rebasa). Riesgos en `research.md` y `plan.md`.

## Open questions

D1 a D7 en `spec.md`, «Decisiones abiertas», con recomendación.
