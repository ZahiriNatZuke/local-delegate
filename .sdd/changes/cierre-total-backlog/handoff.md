# Traspaso — cierre total del backlog

## Qué quedó hecho

**0.21.0 publicada** (PyPI + registro MCP `isLatest: true`) y el **backlog sin ningún punto
abierto**. Cinco PRs: #116, #117, #118, #119, #120.

Del backlog: `CTRL_BREAK` arreglado con su diagnóstico, panel probado interactuado, `clients.jsonl`
con techo, instalador ejercido en los tres sistemas, brazo B desbloqueado y encendido. El chunking,
Codex-con-token, la UI de `elicitation` y las ideas de la sección 4 quedan como **decisiones
escritas**, no como pendientes.

Nuevos, encontrados en la auditoría: `--version` inexistente, `--enable-read-hook` como no-op
silencioso, Playwright sin declarar, el mensaje del lock que engañaba, y un **ciclo de importación
real** con seis alertas de CodeQL.

## Estado de la máquina

- CLI y daemon en **0.21.0 desde el paquete publicado** (`uv tool`), no del venv del repo.
- Entradas MCP en **`http`** contra el daemon del 9393.
- **Brazo B encendido**: el hook de Read registrado con `--enabled`, verificado ejecutándolo tal
  cual quedó en el `settings.json` real, con el entorno limpio.

## Lo que la próxima sesión debe saber

1. **`install` sin `--mcp-mode http` vuelve al default `stdio`**, que en esta máquina deja las
   tools en 401. Se pisó en esta sesión y se corrigió en el acto. Pasarlo **siempre**.
2. **El brazo B necesita días de datos.** Al medirlo, no usar la tasa global: el 17 % del brazo A
   salía entero de dos categorías.
3. **Propuesta abierta, no deuda**: el proyecto no tiene comprobador de tipos. Decidir si entra.
4. `uv tool upgrade` puede no actualizar por caché del índice → `uv tool install --force --refresh`.
5. Tras rebasar el CHANGELOG, comprobar que `git diff origin/main` da **cero líneas borradas**: un
   fusionador ingenuo con CRLF borró 1011 líneas en esta sesión.

## Sin secretos

Ningún artefacto de este cambio contiene credenciales, tokens ni datos personales. El diagnóstico
imprime **nombres** de variables, nunca valores.
