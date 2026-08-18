# Plan review (adversarial)

## Hallazgos

### H1 — Excluir todo el código mata también el caso de `local_explain_code` (aceptado)

`local_explain_code(path=…)` existe precisamente para código, y REQ-002 lo deja sin ningún aviso
que lo recuerde. Es una pérdida real, no un efecto colateral invisible.

**Se acepta a conciencia.** Los números mandan: 562 lecturas de código en 14 días contra 8 llamadas
históricas a `local_explain_code` en todo el proyecto. Un aviso que acierta menos de una vez cada
setenta se lleva por delante su propio caso bueno. Si más adelante hace falta, el sitio es el hook
de prompt (`suggest_delegate_prompt`), que ve la intención del usuario —"explícame este
archivo"— en vez del tamaño en disco, que no la ve.

### H2 — `ext` podría identificar en un caso de borde (mitigado)

Una extensión propietaria y rara (`.contratoacme`) diría algo sobre el trabajo del usuario. El
riesgo es bajo pero el coste de acotarlo es una línea: limitar `ext` a 12 caracteres y descartar
lo que no sea alfanumérico. Se añade a T4.

### H3 — `test_install.py:141` no se rompe, pero su comentario miente (corregido en T6)

Usa 40 000 bytes = 39 KB y sólo verifica que haya `additionalContext`, así que con el umbral nuevo
de 32 KB sigue pasando. Pero el comentario dice "por encima de la banda «strong»" y con
`strong=100 KB` deja de ser cierto. Un comentario falso al lado de un número mágico es cómo se
fabrica el próximo diagnóstico equivocado. Se corrige el comentario en la misma tarea.

### H4 — La verificación por simulación tiene que importar el módulo real (ya está en el plan)

Reimplementar las reglas en el script de simulación mediría el script, no el hook. El plan ya
exige importar del módulo real; se deja anotado porque es el fallo más fácil de cometer aquí.

### H5 — `.html` en la lista de código es discutible (aceptado)

Un `.html` grande puede ser un informe generado, no una plantilla. Se deja dentro de la lista: en
los datos medidos, las 34 lecturas de `.html` eran plantillas de componentes. Si aparece el otro
caso, la lista es una constante de módulo (T1) y se saca de ahí.

## Veredicto

Sin hallazgo bloqueante. H2 y H3 se incorporan al plan.
