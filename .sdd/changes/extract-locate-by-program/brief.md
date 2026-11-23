# Brief: local_extract: las líneas las calcula el programa y el esquema tiene tipos por campo (#692, #694, #696, #697, #698)

## Problem

`local_extract` pide al modelo que escriba números de línea y después intenta adivinar con
heurísticas de palabras si acertó; el esquema JSON no tiene tipos por campo y la salida tiene un
tope fijo de 512 tokens. Resultado: líneas equivocadas sin aviso y rangos correctos marcados como
dudosos (#694, #696), null en patches con un nombre de campo no previsto (#697), JSON cortado o
rangos sin nombre en `.ts` grandes (#698) y `true` en un campo de lista (#692). Detalle y evidencia:
`.sdd/changes/text-tools-common-cause/research.md` (causas C1, C2, C3, C4, C6; arreglos R1 y R2).

## Desired outcome

Las líneas de todo campo de ubicación las calcula el programa (índice por tipo de fichero o ancla
literal comprobada de forma exacta), con una forma de valor única; cada campo tiene su tipo en el
esquema, con un reintento si no cuadra y un tope de salida a su medida. Ver `spec.md`.

## In scope

- Índices de Python, TS/JS, Markdown, diff e ids; anclas; clasificación de campos por presencia.
- Esquema con tipos por campo, validación con un reintento, tope de salida a la medida.
- Rol `code`/`long` para campos de ubicación; forma nueva del valor; docs y versión.

## Out of scope

- `local_explain_code` (fase 2), binarios y `local_lint_summary` (SDD `text-tools-binary-and-lint-paths`),
  R5, R6 y el resto de R7. Pruebas en vivo (se hacen al final, aparte).

## Constraints and risks

- Cambio de contrato visible e incompatible (D3 del spec); versión 0.54.0.
- Sin dependencias nuevas; regex lineales; entrada no confiable.
- Máximo 2 agentes con código a la vez; comandos pesados con `pesado.sh`, de uno en uno.
- Riesgo alto: es el núcleo de #568, #594, #633, #665 y #666; inventario de tests en `research.md`.

## Open questions

- ¿llama-server acepta `enum` en `items` del esquema? Si no, REQ-010 cae a cadena libre (previsto).
  Se confirma en la prueba en vivo final; no cambia el spec.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-23 Original request, verbatim:

  > Rediseño de la localización de líneas de local_extract (R1 del análisis de causa común) junto con el esquema JSON con tipos por campo (R2). Principio: las líneas siempre las calcula el programa; índice por tipo de fichero (Python, TS/JS, Markdown, diff, ids REQ-NNN) sin modelo; en el resto el modelo copia un trozo literal y el programa calcula las líneas exactas, o null con aviso; nunca un número del modelo. Campos de líneas a los roles long o code, nunca al de 4B. Esquema con tipos por campo (listas, booleanos solo para preguntas), reintento si el tipo no cuadra, tope de salida a la medida del campo. Reconocer campos de líneas sin lista de palabras frágil (#697). Cierra #692, #694, #696, #697, #698.

- L2 2026-11-23 Spec y plan escritos (nivel standard por riesgo alto: cambio de contrato y núcleo
  de cinco arreglos previos). Queda: revisión independiente de spec y plan, después implementar
  con dos frentes según `plan.md`.
