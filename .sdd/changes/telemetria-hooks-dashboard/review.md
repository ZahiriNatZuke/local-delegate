# Result review: El dashboard lee la telemetria de los hooks

## Verdict

`conforms-with-notes`

## Specification comparison

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 agregados con rango | Sí | Sí, unit + e2e real | 1817 eventos |
| REQ-002 `suggested` ausente = no | Sí | Sí, mutante | — |
| REQ-003 `enabled: false` | Sí | Sí, mutante | Con motivo legible |
| REQ-004 tasa 0 sin datos | Sí | Sí | Sin división por cero |
| REQ-005 línea corrupta | Sí, heredado | Sí | `_read_file_cached` |
| REQ-006 no filtra contenido | Sí | Sí | Test con campo inyectado |
| REQ-007 tarjeta escondida | Sí | Sí, node + navegador | 4 escenarios |
| REQ-008 avisa que son sugerencias | Sí | Sí, mutante | Reescrito tras verlo en pantalla |
| REQ-009 escapado | Sí | Sí, node | Mutante cazado tras arreglar el test |
| REQ-010 orden de las listas | Sí | Sí, mutante | — |

## Findings

1. **Menor — el riesgo de interpretación no se cierra con código.** Alguien puede leer «17 %» como
   «lo que se delegó». Se mitiga con el texto de la tarjeta y un test que lo exige, pero nada
   impide malinterpretar un número.
2. **Menor — el endpoint expone la ruta del log** en `log`, consistente con `log_dir` de
   `/api/status`. Con el token del puerto ya disponible, ese puerto puede exigir credencial.
3. **Informativo — verlo en un navegador real cambió el texto.** El aviso decía «nada que **una
   una** sugerencia con una delegación»: correcto en español y muy difícil de leer. No lo habría
   detectado ningún test.
4. **Informativo — el desglose por categoría resultó más útil que el total.** Con 17 % global,
   `bash` acumula 1396 eventos y cero sugerencias. Un KPI suelto habría escondido eso.

## Required follow-up

- Ninguno para cerrar.
