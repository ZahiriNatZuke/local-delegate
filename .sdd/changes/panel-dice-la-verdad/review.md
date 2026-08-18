# Plan review (adversarial)

## Hallazgos

### H1 — `by_client` puede convertirse en la correlación que el panel evita (mitigado)

El panel tiene una línea roja escrita: no cruzar sugerencias con delegaciones. Un desglose por
cliente es tentador de leer como «claude-code delegó poco, luego ignora las sugerencias», que es
exactamente esa correlación por la puerta de atrás.

**Mitigación:** el desglose responde «quién pidió esto», no «cuántas sugerencias se siguieron», y
el pie de la tarjeta de hooks debe seguir diciendo que la conversión no se mide. Se añade al texto
de T4 en vez de dejarlo al criterio de quien lo pinte.

### H2 — Mezclar categorías en el desglose por motivo daría un denominador falso (incorporado)

`motivo` sólo lo escribe el hook de lectura. Si el agregado recorre todos los eventos, los de
`lint` y `summarize` caerían en «desconocido» y la tarjeta diría que el hook descarta sin motivo
la mitad de las veces. El plan ya lo acota a `category == "read"`; se deja anotado porque es un
fallo silencioso, de los que se leen bien y significan otra cosa.

### H3 — El control anti-vacío del end-to-end no está definido (corregido)

«Levantar el daemon y mirar la línea» pasa igual si el `client` viene de un default escrito a
mano en el test. El control es un **segundo cliente con otro nombre**: si las dos llamadas
producen la misma firma, la identidad no se está propagando y se está leyendo una constante.
Se añade a T5.

### H4 — `ext` en el panel es dato nuevo en una interfaz que se publica (aceptado)

La captura del README se regenera desde el panel real, y ya hubo un incidente por publicar el log
de quien la capturaba. `ext` no identifica un archivo, pero la lista de extensiones de trabajo de
alguien es información. **Se acepta**: `tests/test_captura.py` mockea `/api/hooks` desde el PR de
la 0.22.1, así que la captura no lleva datos reales. Hay que confirmar que el mock sigue cubriendo
el endpoint después de añadirle claves.

### H5 — El `ContextVar` fuera de una petición (ya en el plan)

`_log_event` se llama desde `benchmark` y desde caminos de arranque. Un `ContextVar` con default
`None` no lanza fuera de contexto, así que el riesgo es teórico — pero el plan ya obliga a
comprobarlo y no cuesta nada.

## Veredicto

Sin hallazgo bloqueante. H1, H2 y H3 se incorporan; H4 añade una comprobación a T5.
