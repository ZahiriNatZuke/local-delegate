# Specification: local_summarize: el enfoque llega a la sección que lo trata, o avisa

## Summary

Issue #558: con `focus`, `local_summarize` sobre un Markdown de ~16 KB devolvió un resumen sin nada
de la sección cuyo título contiene el término del foco, sin aviso. Causa medida: el foco SÍ llega
al prompt de sistema de todas las pasadas (llamada única, cada trozo del map y el reduce; la entrada
de 16 KB cabe en una sola llamada del rol `long`, tope 48000), pero solo como cláusula genérica
«Prioriza este aspecto»; la lista de secciones y el reparto de palabras del mensaje de usuario
pesan más y el modelo resume la introducción y las secciones grandes. No hay preselección de
secciones. Arreglo: nombrar en el mensaje de usuario las secciones que tratan el foco y avisar
cuando el resumen no lo menciona aunque la entrada sí.

## Requirements

- **REQ-001** — Con `focus`, si el texto que se manda al modelo (la entrada entera o cada trozo)
  tiene títulos Markdown cuyo título o cuerpo contiene un término significativo del foco (palabra
  de 3 o más caracteres que no sea una palabra vacía es/en; sin distinguir mayúsculas ni acentos),
  el mensaje de usuario nombra esas secciones (hasta 8; si son más, no se nombran) como las que
  tratan el aspecto prioritario. Vale en el camino estructurado (llamada única y trozos) y en el de
  prosa (llamada única y map).
  - Request: "cuando la entrada tiene secciones Markdown cuyo título o cuerpo contiene palabras significativas del foco, darle prioridad a esas secciones"
  - Verify: test tests/test_summarize_focus_coverage.py
- **REQ-002** — Con `focus`, si algún término significativo del foco aparece en la entrada y
  ninguno aparece en el resumen del modelo (antes de reponer títulos que faltan), la salida lleva un
  aviso `[local-delegate warning: …]` (es/en) que nombra esos términos. Si el resumen menciona
  alguno, o ningún término está en la entrada, no hay aviso. Un error del backend no lleva aviso.
  Revisión del PR #561: un término solo se juzga si es literal (dígito, `_`, `.`, `/`, camelCase
  o mayúsculas en el foco) o si el idioma detectado de la entrada coincide con el del resumen; las
  líneas de título del resumen no cuentan como mención; los plurales ingleses en «-ies» casan con
  su singular; la búsqueda es una sola pasada sobre la entrada; la nota va solo al map, nunca al
  reagrupado de resúmenes parciales.
  - Request: "si ninguna palabra significativa del focus aparece en el resumen pero sí en la entrada, añadir un aviso"
  - Verify: test tests/test_summarize_focus_coverage.py
- **REQ-003** — Sin `focus` (o con un foco vacío o sin términos significativos) los prompts y la
  salida son los de antes, byte a byte.
  - Request: "No cambies el comportamiento sin focus"
  - Verify: test tests/test_summarize_focus_coverage.py
- **REQ-004** — El cambio queda en el CHANGELOG `[Unreleased]` → Fixed con (#558).
  - Request: "CHANGELOG: añade tu entrada en ## [Unreleased]"
  - Verify: review CHANGELOG.md

## Acceptance scenarios

### Scenario: el informe del issue

- **Given** un Markdown sintético de ~16 KB con introducción, varias secciones `###` (una con
  `cp1252` en el título) y una lista final larga
- **When** se llama a `local_summarize(path=…, focus="cp1252 / utf8 stdin")` con backend falso
- **Then** el mensaje de usuario nombra la sección de `cp1252`; si el modelo responde sin
  mencionarla, la salida lleva el aviso con `cp1252`

## Edge cases and failure behavior

- Términos que no están en la entrada (`utf8` frente a `UTF-8`) no cuentan ni para el aviso ni para
  las secciones.
- Un fichero de código (clase `code` por extensión) no recibe la nota: sus `## ` viven en cadenas
  y son datos (#539). El aviso sí aplica.
- Coincidencia por prefijo del término (sus primeros `max(4, n-2)` caracteres) al inicio de una
  palabra, para que «riesgos» case con «riesgo».

## Non-functional requirements

- Funciones puras en `sections`, sin red ni disco; coste lineal en el tamaño de la entrada.

## Non-goals

- Reordenar la entrada, cambiar la cláusula de sistema del foco o el reparto de palabras.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
