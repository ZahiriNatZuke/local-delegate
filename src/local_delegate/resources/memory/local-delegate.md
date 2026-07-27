## Delegación a modelos locales (MCP `local-delegate`)

Hay un MCP `local-delegate` que expone modelos locales como tools `local_*`. Delegar en
ellas conserva cuota de la suscripción.

**Regla:** si el paso cabe en UNA frase con formato de salida explícito (resumir,
clasificar, extraer campos, boilerplate, traducir, mensaje de commit desde un diff,
resumir lint/tests, explicar código, describir una imagen), **delégalo** a la tool
`local_*` correspondiente. Si necesita criterio, arquitectura, razonamiento encadenado o
varias fuentes, **hazlo tú**.

**El ahorro real está en `path`:** para archivos grandes pasa `path` en vez de leerlos
primero — el MCP los lee del lado del servidor y el contenido nunca entra al contexto.

Detalle completo y catálogo de tools en la skill `delegacion-local`; diagnóstico del
backend con `local_status`; panel de ahorro en `http://127.0.0.1:9393`.
