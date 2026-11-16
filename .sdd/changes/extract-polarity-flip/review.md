# Result review: local_extract: aviso cuando un valor invierte la negacion de la fuente

## Review level

- Level: standard
- Judges: result-reviewer-1 (agente revisor de resultado, solo lectura), result-reviewer-2 (revisión de la sesión que implementó, con mutantes)
- Security reviewer: no aplica (sin entrada externa nueva; el detector solo lee la entrada y la respuesta que ya llegan, con tope de tamaño, presupuesto y frontera que traga excepciones)
- Verdict: conforms-with-notes (primera pasada «does-not-conform» con 12 hallazgos; los aplicables, arreglados con test y con mutante que lo mata)

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | el valor vuelve palabra por palabra con `text` y con `path` más campo de ubicación; una entrada de 3219 caracteres es una sola llamada sin `chunked` |
| REQ-002 | sí | sí | seis inversiones: añadida y quitada, en español, en inglés, traducida y conjugada |
| REQ-003 | sí | sí | 17 casos fieles, corte de línea en cada palabra, 177 respuestas guardadas y cada frase de la wiki y del CHANGELOG contra su fichero: 0 avisos |
| REQ-004 | sí | sí | aviso tardío tras `cross_filled_keys`; es y en; fuente enorme o vacía, excepción y presupuesto sin aviso; campos de ubicación fuera |
| REQ-005 | sí | sí | CHANGELOG, wiki, docstring; suite completa en `verification.md` |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| P1 | copia literal marcada si la fuente corta la línea entre la negación y su verbo | sí | sí | confirmed | bloques por línea en blanco, lista, encabezado o celda; test que corta en cada palabra; mutante `no-line-join` muerto |
| P2 | «X, no Y» traducido como «X and not Y» marcado | sí | sí | confirmed | la palabra negada no puede estar en una cláusula negada de la misma oración; caso `x-and-not-y` |
| P3 | fila entera de tabla copiada marcada | sí | sí | confirmed | el valor se corta con los mismos separadores; casos `markdown-row-copied` y `html-row-copied` |
| P4 | negación de un encabezado o del nombre del campo ignorada | sí | sí | confirmed | alcance desde encabezado y línea `...:` negados; claves con prohibición no se comprueban; casos y test propios |
| P5 | dos raíces compartidas con negación sobre otro objeto | sí | sí | confirmed | la raíz de la palabra negada no cuenta entre las compartidas; caso `negation-about-another-object` |
| P6 | coste cuadrático al buscar la palabra negada | sí | sí | confirmed | una pasada de derecha a izquierda; test de tiempo con 400 000 caracteres de negaciones |
| P7 | verification y review en plantilla | sí | sí | confirmed | rellenados |
| P8 | dos casos fieles que no discriminaban | sí | sí | confirmed | `negation-scoping-a-list` rehecho (lo mata el mutante `no-forward-scope`); el de frase corta renombrado, la exclusión de la palabra negada ya lo cubre |
| P9 | sin test de que la entrada del issue no se trocea | sí | sí | confirmed | `test_an_input_of_the_issue_size_is_one_call` |
| P10 | casos no detectados | sí | sí | confirmed | añadidos `ningun`, `nadie`, `none`, `nothing`, `nobody`; la rama de quitada sigue mirando solo la negación propia de la cláusula fuente (con el alcance heredado saltaría con «no toques X, pero revisa Y»); frases unidas por el modelo, límite documentado en la wiki |
| P11 | doble negación marcada como quitada | sí | sí | confirmed | `sin`/`without` tras la negación la anula; caso `double-negation` |
| P12 | redacción de REQ-004 y límites en la wiki | sí | sí | confirmed | REQ-004 y wiki ajustados |

## Required follow-up

- Ninguno antes de cerrar. La entrada real del issue no se publicó; si aparece otro caso con su
  forma, se suma como caso de test.
