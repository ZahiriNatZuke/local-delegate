# Specification: local_summarize respeta la estructura del documento (resumen por secciones)

## Summary

Cuando el texto que se resume tiene títulos Markdown, `local_summarize` devuelve un resumen que
**sigue la estructura del documento**: nombra cada sección en orden, con su título tal cual, y
resume lo que dice. Claude puede decidir qué leer con calma sin releer para orientarse. El texto
sin títulos se resume como hoy, byte a byte el mismo prompt. Un parámetro opcional `focus` permite
pedir que el resumen conserve lo que interesa (cifras, decisiones, riesgos…).

Evidencia en `research.md`: en el piloto de T5 la tool nombró entre el 0 % y el 27 % de los títulos
aunque Claude pidió 450–600 palabras, y la causa es el prompt («prosa clara», «nada fuera del
formato»).

## Requirements

- **REQ-201 (resumen estructurado, siempre que se pueda):** si el texto tiene **al menos dos
  títulos Markdown del mismo nivel** —de estilo ATX (`#`…`######`) o setext (subrayados con `===`
  para el nivel 1 y `---` para el 2)— **fuera de bloques de código**, sin que nadie lo pida, el
  resumen lista las secciones del **nivel estructural** (el nivel más alto con al menos dos
  títulos) **en el orden del documento**, cada una con su título literal y un resumen breve de su contenido. No inventa
  secciones ni omite ninguna de ese nivel.
  **Enmienda v3:** las subsecciones del nivel siguiente se nombran dentro de su sección; el texto
  anterior a la primera sección, si tiene contenido, es una sección «Introducción»; y el presupuesto
  se reparte según el tamaño de cada sección.
- **REQ-202 (presupuesto):** `max_words` sigue siendo el tope del texto de los resúmenes; los
  títulos no cuentan para él. `max_tokens` deja margen para los títulos y el formato, de modo que
  una salida estructurada no se corte por `length` en los documentos del banco. Si hay más
  secciones de las que caben con al menos una frase cada una, se nombran todas y las que no caben
  llevan solo el título, con un aviso final que dice cuántas.
- **REQ-203 (documentos largos):** por encima del tope del rol, el troceado ya corta por títulos;
  la fusión conserva las secciones en orden con el mismo formato de REQ-201, en lugar del «único
  resumen global en prosa». La nota «(resumido de N partes…)» se mantiene.
- **REQ-204 (sin títulos, sin cambios):** con menos de dos títulos, el prompt, el formato de la
  salida y el enrutado son **idénticos** a los de `main`, para no mover los benchmarks ni el corpus
  que copian el prompt.
- **REQ-205 (enfoque):** parámetro opcional `focus: str | None = None`. Si viene, el resumen
  prioriza ese aspecto y conserva los datos concretos que pida (cifras, nombres, decisiones), en
  formato estructurado o en prosa según REQ-201/REQ-204. Vacío o solo espacios cuenta como ausente.
  Sin `focus`, nada cambia respecto a REQ-201/REQ-204.
- **REQ-206 (modelo y contabilidad):** el rol se sigue eligiendo por el tamaño del documento entero,
  así que `hook_common.modelo_del_resumen` no se desfasa. Una llamada a la tool escribe **un solo
  evento** de uso, aunque haga varias llamadas al backend (`chunks: N`, como hoy). El evento añade,
  solo cuando aplica, `secciones: <n>` y `focus: true`; nunca el texto del enfoque.
- **REQ-207 (descripción y docs):** la descripción de la tool dice que conserva la estructura y
  documenta `focus`. CHANGELOG, README, `docs/wiki/Tools.md` y la skill `delegacion-local` se
  actualizan en la release (regla de las tres superficies).
- **REQ-208 (medición en dos etapas, criterio escrito antes de medir):**
  - **Etapa 1, sin cuota:** la tool contra el backend real, con los tres documentos del piloto
    (README, `Integration-install.md`, `Daemon.md`) y el CHANGELOG, `max_words` 500. **Pasa** si
    en los tres primeros la cobertura de títulos **en la salida de la tool** es ≥ 0,9, cada sección
    nombrada lleva al menos una frase de contenido, y **un juicio humano** (el usuario) acepta que
    los resúmenes son fieles en al menos 2 de 3. En el CHANGELOG, cobertura ≥ 0,9 **sin contar las
    secciones completadas por el servidor**, cada versión emparejada con contenido, y sin corte por
    `length`. En el documento corto (modelo mecánico) se aplica el mismo umbral de 0,9; si no lo
    alcanza, el modo estructurado se limita al rol `long` y el texto corto va en prosa como hoy. Si no pasa, no se gasta cuota: se vuelve al plan.
  - **Etapa 2, con cuota:** `scripts/experimento_adopcion.py --piloto` con 3 repeticiones por
    tarea (9 corridas, unos 3,6 USD), con los hooks de siempre y copias de los documentos fijadas
    en el commit `95a65ee`. Línea base de T5: **2 de 9 correctas** (V0: 0 de 3) y **7 con el
    contenido en el contexto**. «Correcta» ya exige que el contenido no entrara al contexto, así
    que la regla se decide solo por correctas: **se queda** con al menos 6 de 9, **se retira** (el
    interruptor del modo estructurado pasa a apagado por defecto en una release, el código se
    conserva para medir de nuevo; `focus` se queda) con 3 o menos, y entre medias no es
    concluyente y se decide con el usuario. Las corridas con el contenido en el contexto se
    informan aparte, con la misma definición que en T5.
  - **Amenazas a la validez, escritas antes de medir:** la línea base se midió con tres variantes
    de oferta distintas (hoy retiradas) y con los hooks anteriores al PR #220 (el Shell no ofrecía
    la ruta absoluta); con una corrida por casilla. El salto de 2/9 a 6/9 es grande para que el
    ruido lo explique, pero una mejora menor no se atribuye al cambio.

## Acceptance scenarios

### Scenario: documento con secciones
- **Given** un Markdown con 9 títulos `##` y un título `#`
- **When** Claude llama `local_summarize(path=..., max_words=500)`
- **Then** la respuesta nombra los 9 títulos `##` en el orden del documento, cada uno con al menos
  una frase de resumen, y termina con la coletilla de ahorro de siempre.

### Scenario: texto sin títulos
- **Given** un log o un texto sin títulos Markdown
- **When** se resume sin `focus`
- **Then** el prompt enviado al backend es byte a byte el de `main`.

### Scenario: título dentro de un bloque de código
- **Given** un Markdown cuyo bloque ```` ```bash ```` contiene `# instala las dependencias`
- **When** se resume
- **Then** esa línea no cuenta como título ni aparece como sección.

### Scenario: enfoque
- **Given** un documento con cifras de configuración repartidas por secciones
- **When** se llama con `focus="cifras de configuración"`
- **Then** el resumen conserva esas cifras, y el log registra `focus: true` sin el texto.

### Scenario: documento largo
- **Given** un Markdown de más de 48 000 caracteres con títulos `##`
- **When** se resume
- **Then** hay un solo evento de uso con `chunks: N`, y la salida lista las secciones en orden.

## Edge cases and failure behavior

- Un solo título, o ninguno: REQ-204.
- Muchas secciones (el CHANGELOG tiene 46): REQ-202, se nombran todas.
- Títulos duplicados: se listan en su orden, las dos veces.
- Títulos setext: cuentan (REQ-201). Una línea `---` bajo un párrafo vacío es una regla horizontal,
  no un título; y el bloque de metadatos YAML inicial (`---` … `---`) no cuenta.
- El backend falla o corta: el comportamiento de error, respaldo y aviso de truncado no cambia.
- `focus` muy largo: se recorta a 200 caracteres antes de inyectarlo.

## Non-functional requirements

- **Compatibilidad:** `focus` es opcional; los clientes con el schema en caché siguen funcionando.
- **Rendimiento:** con los documentos del banco, una sola llamada al backend, como hoy. No se
  añaden llamadas por sección.
- **Privacidad:** el log no guarda el enfoque, el título de las secciones ni la salida.
- **Pruebas:** hay tests que fijan el prompt estructurado, el de `main` para texto sin títulos, la
  detección de títulos fuera de bloques de código y el evento de uso; con mutantes que los hacen
  fallar.

## Non-goals

- Llamadas al backend por sección (quedan como alternativa si la etapa 1 falla con una pasada).
- Cambiar modelos, roles o topes (`LONG_INPUT_CHARS`, `MAX_CHARS`).
- Otras tools (`local_extract`, `local_translate`…).
- El texto de los hooks.
- Formatos no Markdown (PDF, HTML, reStructuredText, código).

## Traceability

| Requisito | Plan | Verificación |
| --- | --- | --- |
| REQ-201, REQ-204 | T1, T2 | tests de detección y de payload + etapa 1 |
| REQ-202 | T2, T4 | tests de `max_tokens` y de completitud + etapa 1 (palabras sin títulos) |
| REQ-203 | T4 | tests del modo por secciones en map-reduce + CHANGELOG en la etapa 1 |
| REQ-205 | T3 | tests del prompt con `focus` + etapa 1 con el escenario de cifras |
| REQ-206 | T5 | tests del evento de uso y de `modelo_del_resumen` |
| REQ-207 | T9 | revisión de la release |
| REQ-208 | T6, T7, T8 | informe en `verification.md` |
