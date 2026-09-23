# Brief: local_summarize respeta la estructura del documento (resumen por secciones)

## Problem

La adopción de la delegación ya no es el cuello de botella; lo es la **fidelidad del resumen**.
En el piloto de T5 del SDD `subagente-lector-local` (2026-09-23, `verification.md`) las 9 corridas
de `claude -p` delegaron la lectura en `local_summarize`/`local_extract` con `path`, con cualquier
texto de oferta de los hooks (V0 incluida). Pero **7 de 9 releyeron después el fichero por
franjas**, y pagaron dos veces: el resumen local no sigue la estructura del documento. Según el
propio modelo, «se saltaba» secciones y «mezclaba temas y no seguía el orden». En T4, con
preguntas de «todas las cifras», pasó lo mismo: el resumen perdía los datos concretos.

Las dos corridas que salieron bien hicieron a mano lo que le falta a la tool. Una se apoyó en
`local_extract`. La otra partió el fichero por secciones con PowerShell y pidió un
`local_summarize` por sección.

Evidencia: `.sdd/changes/subagente-lector-local/verification.md` (T4 y T5); vault
`projects/local-delegate/jornada-2026-09-23-la-oferta-que-ya-se-aceptaba.md`; backlog §4.1,
entrada 0.

## Desired outcome

Cuando Claude delega el resumen de un documento estructurado (Markdown con títulos), la respuesta
de `local_summarize` conserva su estructura: nombra cada sección en orden y resume lo que dice.
Así Claude puede decidir qué leer con calma sin releer para orientarse. Se verifica con el banco
existente (`scripts/experimento_adopcion.py --piloto`, criterio de títulos `##` y contenido fuera
del contexto) contra la línea base de hoy: 2 correctas de 9, y 7 relecturas.

## In scope

- El comportamiento de `local_summarize` con documentos que tienen estructura de títulos:
  resumir por secciones, sin que Claude tenga que pedirlo ni partir el fichero.
- Si hace falta, un parámetro opcional de enfoque («qué me interesa»), entrada 0 del backlog §4.1.
- Cómo se combina con el troceado que ya existe (`MAX_CHARS` por modelo, `CHUNK_CHARS`) y con la
  contabilidad de ahorro.
- La descripción de la tool que ve el modelo, si el comportamiento cambia.
- Medición antes/después con el banco, con criterio escrito antes de medir.

## Out of scope

- El texto de las ofertas de los hooks (cerrado en `subagente-lector-local`).
- Cambiar los modelos o los roles (`mechanical`, `long`, `code`, `vision`).
- Otras tools (`local_extract`, `local_translate`…), salvo que la investigación muestre que
  comparten el mismo camino de código.
- Estructura de formatos que no sean Markdown/texto (PDF, HTML, código), salvo decisión expresa.

## Constraints and risks

- **Cuota:** la medición gasta cuota de la suscripción; cada tanda pide confirmación y no se corre
  nada hasta aprobar el plan. El piloto de hoy costó unos 3,6 USD por 9 corridas.
- **Contexto del modelo local:** un resumen por secciones puede ser más largo; hay que respetar
  `max_words` o justificar el cambio. El presupuesto de troceado está en caracteres y el límite
  del modelo en tokens (memoria `presupuesto-en-chars-limite-en-tokens`).
- **Latencia:** una llamada por sección multiplica las llamadas al backend; hay que medirlo en una
  PC compartida (memoria `config-para-maquina-compartida`).
- **Compatibilidad:** la firma de la tool es parte de su contrato con clientes que cachean el
  schema; un parámetro nuevo tiene que ser opcional. Una suite verde puede no ver un breaking
  change en una tool sin tests (memoria `probar-la-pieza-no-es-probar-el-uso`).
- **Métrica:** el criterio de títulos ≥ 80 % es fácil de pasar poniendo los títulos sin contenido.
  Hay que validar la métrica contra un juicio humano antes de fiarse de ella (memoria
  `si-no-es-el-indio-es-la-flecha`).
- **Ruido:** con una corrida por casilla, 1 contra 0 es ruido; el plan tiene que fijar las
  repeticiones.

## Open questions

- ¿Dónde se pierde la estructura hoy: en el prompt del resumen, en el troceado (cortes a mitad de
  sección) o en la fusión de trozos?
- ¿Resumen por secciones siempre que haya títulos, o solo bajo parámetro? ¿Qué pasa con
  documentos de muchas secciones pequeñas (el CHANGELOG tiene 46)?
- ¿Una llamada al modelo por sección o una sola llamada con instrucciones de estructura?
- ¿Hace falta el parámetro de enfoque, o basta con la estructura?
- ¿Cómo se cuenta el ahorro si una delegación hace N llamadas al backend?
