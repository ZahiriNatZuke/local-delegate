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

**Subagentes:**
- **Al lanzar uno**, su prompt lleva como paso 1 una delegación concreta (tool, `path` y
  pregunta) y la carga de las tools con `ToolSearch("select:mcp__local-delegate__local_extract,mcp__local-delegate__local_explain_code")`.
  Nada de «si te conviene»: un condicional se lee como permiso para no delegar.
- **Si eres un subagente**, ante un archivo grande localiza primero: pide a
  `local_extract` o `local_explain_code` (con `path`) las líneas que necesitas y lee solo
  ese rango con `offset`/`limit`. Citar o editar líneas exactas justifica leer el rango, no
  el archivo entero.

Detalle completo y catálogo de tools en la skill `local-delegation`; diagnóstico del
backend con `local_status`; panel de ahorro en `http://127.0.0.1:9393`.
