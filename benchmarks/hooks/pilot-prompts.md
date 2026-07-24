# Piloto A/B de hooks de Claude Code

Ejecuta estos prompts, en orden y sin decirle a Claude qué tool debe usar, primero con hooks
apagados (A) y después en una sesión nueva con hooks activos (B).

1. `Resume el archivo README.md en cinco viñetas. No cambies archivos.`
2. `Extrae de pyproject.toml el nombre, la versión y las dependencias como JSON. No cambies archivos.`
3. `Clasifica este texto como exito, fallo o incierto: "La suite terminó con 157 pruebas aprobadas".`
4. `Traduce al inglés: "El backend remoto respondió correctamente".`
5. `Ejecuta uv run pytest -q. Si la salida es larga, guárdala y devuelve solamente un resumen.`
6. `Genera el boilerplate de una función Python que valide una URL terminada en /v1. No escribas archivos.`
7. `Investiga las versiones más recientes de FastMCP y decide si conviene actualizar. No cambies archivos.`
8. `Diseña la arquitectura para añadir OAuth al backend remoto. No cambies archivos.`
9. `Revisa los riesgos de seguridad de la autenticación remota. No cambies archivos.`
10. `Planifica una migración del almacenamiento de métricas. No cambies archivos.`

Los prompts 1-6 son oportunidades mecánicas elegibles. Los prompts 7-10 deben permanecer en
Claude y sirven para detectar falsos positivos.
