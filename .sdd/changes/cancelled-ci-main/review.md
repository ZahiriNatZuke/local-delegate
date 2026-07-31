# Result review: El cancelled del CI en main tiene causa conocida y firma reconocible

## Verdict

`conforms-with-notes`

## Specification comparison

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 corregir el diagnóstico | Sí, en los 3 sitios | Sí | Escrito como corrección, no como reemplazo |
| REQ-002 límite del paso | Sí, `5` frente a `8` | Sí | Menor que el del job, si no no actuaría |
| REQ-003 test del límite del job | Sí | Sí, mutante | — |
| REQ-004 test del límite del paso | Sí | Sí, 2 mutantes | — |
| REQ-005 clasificar un `cancelled` | Sí | Sí | Tabla con los tres casos |

## Findings

1. **Menor — la gracia de 5 minutos es inferida.** Lo medido es el total de 13:00 con el límite en
   8. Si GitHub la cambiara, el test no lo vería: mide contra el repo, no contra GitHub. Queda
   escrito en `verification.md`.
2. **Menor — el efecto del límite del paso no está ejercitado**, porque el cuelgue no se reproduce
   a demanda. Se apoya en que dos de los tres casos tenían el paso corriendo.
3. **Informativo — el pendiente pedía elegir remedio y la respuesta fue que ya estaba puesto.** El
   trabajo real era corregir un diagnóstico que el repo repetía en tres sitios. Es el mismo patrón
   que la auditoría del backlog midió: la observación estaba bien y la causa era inventada.
4. **Informativo — se deja explícitamente sin diagnosticar** por qué pytest se cuelga en Windows.
   Sin log, cualquier causa sería inventada.

## Required follow-up

- Ninguno para cerrar.
- Para vigilar, no para hacer: si aparece un `cancelled` cuya duración **no** sea ~13:00, la firma
  dejó de valer y hay que volver a medir.
