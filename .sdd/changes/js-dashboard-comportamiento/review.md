# Result review: El JS del panel se prueba ejecutandolo

## Verdict

`conforms-with-notes`

## Specification comparison

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 los seis presets | Sí | Sí | 5 tests |
| REQ-002 medianoche local | Sí | Sí, mutante | — |
| REQ-003 incluyen hoy | Sí | Sí, mutante | Parametrizado 7 y 30 |
| REQ-004 último día entero | Sí | Sí, mutante | — |
| REQ-005 preset desconocido | Sí | Test sí, mutante no aplicable | Patrón del mutante mal escrito |
| REQ-006 día local | Sí | Sí, mutante | Lo cazan **dos** tests |
| REQ-007 `byDay` | Sí | Sí, 2 mutantes | El del orden, tras arreglar el test |
| REQ-008 `agg` | Sí | Sí, 2 mutantes | — |
| REQ-009 `fmtHace` | Sí | Sí, mutante | Diez fronteras |
| REQ-010 zona fijada | Sí | Sí | Sin ella el mutante de UTC no caería |

## Findings

1. **Menor — un mutante no se pudo aplicar** (REQ-005), por un patrón mal escrito en el script de
   mutación, no por el test. El requisito tiene su test.
2. **Informativo — el pendiente daba por necesario Playwright y no lo era.** Las funciones que
   deciden qué se ve son puras o casi puras. Playwright seguiría haciendo falta para interacción
   real, y eso queda fuera con su razón.
3. **Informativo — el test de `byDay` no probaba el orden** hasta que un mutante lo destapó: los
   datos ya entraban ordenados. Cuarta aparición del mismo patrón en la sesión.
4. **Informativo — `subprocess` con entorno recortado mata a node en Windows.** Anotado en el
   código para que no se «limpie» más adelante.

## Required follow-up

- Ninguno para cerrar.
- Para el backlog, no para ahora: interacción real del panel (paginación, filtros en el DOM) si
  alguna vez compensa meter un navegador en el CI.
