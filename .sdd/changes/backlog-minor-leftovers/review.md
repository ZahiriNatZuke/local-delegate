# Revisión del resultado: restos menores

## Veredicto

`conforms-with-notes`

## Comparación con la spec

| REQ | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 | Sí (#385) | Test + captura | — |
| REQ-002 | Sí (#385) | node + Playwright + mutante | Sin JS queda `data-theme="dark"` de reserva |
| REQ-003 | Sí (#383) | Test + mutante | El código ya cumplía; solo faltaba el test |
| REQ-004 | Sí (#387) | Medición en vivo | Mínimo 4096; sin razonamiento también 15/15 y ~6× más rápido |
| REQ-005–011 | Sí (#386) | Tests + mutantes + prueba con HOME vacío | `created_ancestors` opcional: manifiestos 0.38.0 siguen válidos |
| REQ-012–013 | Sí (#384) | Tests + mutantes + `doctor --home` es/en | Check nuevo `config.claude_settings`; 27 checks |

## Hallazgos

- Menor: `tests/test_doctor_backend_params.py` dice «the 26 checks» en un docstring (no comprueba el
  número).
- Nota de producto: en esta PC `doctor` dará WARN por la `.bak` real hasta que el usuario la borre.

## Seguimiento

- Ninguno bloqueante. Docstring del contador: corregir de paso en el próximo cambio que toque ese
  fichero.
