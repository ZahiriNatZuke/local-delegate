# Revisión del resultado (modo lite): acotar el job fantasma de Windows

## Veredicto

`conforms`

## Comparación contra la especificación

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | Los cuatro jobs declaran `timeout-minutes` (5 / 8 / 10 / 5), comprobado parseando el YAML. |
| REQ-002 | sí | sí | Cada valor lleva su razón y su duración observada en el propio fichero. |
| REQ-003 | sí | sí | `concurrency` por `github.ref`; observado en el PR, donde el segundo push generó un run nuevo. |
| REQ-004 | sí | sí | `cancel-in-progress` condicionado a que la ref **no** sea `main`. |
| REQ-005 | sí | sí | `Repo-hardening.md` recoge el síntoma, el `gh api` de los *steps* y el gotcha del retraso. |

## Hallazgos

1. **Ninguno bloqueante.**

2. **Un ajuste a la baja durante la implementación, y la objeción era correcta.** La primera
   versión ponía 15 min en `test`: un número elegido mirando el cuelgue y no la duración real. El
   usuario lo cuestionó y los datos le dieron la razón — el peor caso observado es **1 m 23 s**, y
   el reloj del `timeout` corre sobre la **ejecución** del job, no sobre la espera en cola. Bajó a
   8. Un timeout de más no protege mejor: alarga la espera cada vez que el job se cuelga.

3. **Límite honesto del cambio, y conviene no perderlo de vista:** esto **acota el daño, no cura
   la causa**. Si GitHub vuelve a dejar un job sin cerrar, seguirá ocurriendo — pero fallará en 8
   minutos en vez de bloquear hasta 6 horas.

## Seguimiento requerido

Ninguno. Si el patrón se repitiera con frecuencia, el paso siguiente sería abrir un caso a GitHub
con los identificadores de job, que es lo único que queda por hacer fuera del repo.
