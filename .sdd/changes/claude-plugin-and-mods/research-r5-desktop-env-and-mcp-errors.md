# R5 — Claude Desktop: qué entorno reciben los MCP y por qué fallan al abrir

Fecha: 2026-10-21 · Desktop MSIX 3.1623.0.0 (Windows 11) · Investigación en solo lectura: no se tocó ninguna config ni se reinició nada.

Etiquetas: **[PRUEBA]** medido en esta PC · **[DOC]** sale del código de la app o de documentación · **[INF]** deducción.

Copia del código de la app (solo los `.js`/`.json`, extraídos del `app.asar` con un lector propio, sin `npx`): carpeta de trabajo `scratchpad/r5/asar/.vite/build/`. Fichero principal: `index.chunk-7dsQFims.js` (los desplazamientos de abajo son posiciones en ese fichero).

---

## 1. Qué entorno pasa Desktop a los MCP que arranca

### 1.1 Lista blanca, no hereda `process.env` [DOC]

Los servidores de `claude_desktop_config.json` se lanzan así: `launchMcpServer` (≈4531694) lee `getMcpServersConfig()[name]` y llama a `_x(name, entry)` (≈2146766), que crea el transporte stdio con:

```js
env: ih(hat(), t.env, {PATH: f ? f.replace(/\$\{PATH\}/gi, () => d) : d})
```

- `hat()` = `ih(mat(), Wrt())` (≈1455778): **solo variables de sistema de una lista fija**.
  - `mat()` (≈1453191, es el `getDefaultEnvironment` del SDK): `APPDATA, HOMEDRIVE, HOMEPATH, LOCALAPPDATA, PATH, PROCESSOR_ARCHITECTURE, SYSTEMDRIVE, SYSTEMROOT, TEMP, USERNAME, USERPROFILE, PROGRAMFILES`.
  - `Wrt()` (≈1419480) añade `ComSpec, SystemRoot, windir, PATHEXT, TEMP, TMP, ALLUSERSPROFILE, ProgramData, ProgramFiles(x86), ProgramW6432, CommonProgramFiles*, PUBLIC, COMPUTERNAME, OS, NUMBER_OF_PROCESSORS, PROCESSOR_*`.
- Encima, el `env` literal de la entrada (`t.env`), mezclado sin distinguir mayúsculas (`ih`).
- `PATH` = PATH de la entrada (si lo hay, sustituyendo `${PATH}`) o, si no, el PATH ampliado de Desktop (rutas conocidas + PATH del shell de login + `process.env.PATH`; función `ph`, ≈1444642).

Todo lo demás del entorno de `claude.exe` **se descarta**, incluidas las variables de usuario como `LOCAL_DELEGATE_WEB_TOKEN`.

### 1.2 Comprobado por los procesos vivos [PRUEBA]

Con la sonda de nombres (`r2/env-name-probe.ps1`; solo imprime True/False), comparando `claude.exe` (60116) con la cadena de `local-delegate` (`cmd` 60672 → `node` npx 36380 → `node` mcp-remote 42220):

| Variable | claude.exe | hijos MCP |
|---|---|---|
| `APPDATA`, `ComSpec` (en la lista) | sí | sí |
| `PSModulePath`, `OneDrive` (fuera de la lista) | sí | **no** |
| `LOCAL_DELEGATE_WEB_TOKEN` | sí | **no** |
| `BRAVE_API_KEY` | sí | **no** |

Encaja exactamente con la lista blanca. `LOCAL_DELEGATE_WEB_TOKEN` está definida en el ámbito **Usuario** del registro (no en Máquina).

### 1.3 ¿Sustituye `${VAR}`? No, salvo `${PATH}` [DOC]

- En las entradas de `claude_desktop_config.json` **no hay ninguna expansión**: `getMcpServersConfig` (`PX`/`wui`, `yui`) copia `command`, `args` y `env` tal cual. El único reemplazo es `${PATH}` dentro del valor de `PATH`. No se expanden `$VAR` ni `%VAR%`.
- Para los **plugins** (`Y_n`, ≈2785646) sí se expanden `${VAR}` y `${VAR:-defecto}`, pero **solo** con `CLAUDE_PLUGIN_ROOT` y las variables de la lista blanca. Si no, deja el texto tal cual y avisa: *«config uses environment variables the desktop does not fill in for plugin servers … Only CLAUDE_PLUGIN_ROOT and the variables every local server receives (such as PATH, TEMP and APPDATA) are filled in.»*
- En las **extensiones (.mcpb/DXT)** se sustituye `${user_config.X}` con lo que el usuario rellena en la ficha de la extensión (≈1571344, ≈2786743). Es el único mecanismo con secretos que tiene Desktop.
- Los mensajes «Replacing ${…» o «Environment variable … not found» que citaba la nota antigua **no existen** en esta versión (0 apariciones en el asar) ni en los logs viejos de `%APPDATA%\Claude\logs` [PRUEBA]. Esa nota está desfasada.

## 2. Forma correcta de que el token llegue a `mcp-remote` sin escribirlo literal

- `"env": {"LOCAL_DELEGATE_WEB_TOKEN": "${LOCAL_DELEGATE_WEB_TOKEN}"}` **no funciona**: Desktop pasaría el texto literal `${LOCAL_DELEGATE_WEB_TOKEN}` [DOC, por 1.3].
- El truco del README de `mcp-remote` (`--header "Authorization:${AUTH_HEADER}"` con `"env": {"AUTH_HEADER": "Bearer …"}`) solo evita el problema de los espacios en Windows. El secreto sigue literal en `env` [DOC, README de mcp-remote; no lo pude verificar en el código porque la caché de `npx` de la versión que corre ya no está en disco].
- **Estado real hoy** [PRUEBA]: la entrada `local-delegate` de Desktop lleva `--header Authorization:Bearer <token literal>` (56 caracteres, sin `$` ni `%`). Por eso conecta (sesión de las 18:07: `Connected … StreamableHTTPClientTransport`, respuestas a `tools/list`). Las 4 entradas de DigitalOcean están igual, y `brave-search`, `github`, `whisper-transcribe` y `google-analytics` tienen claves literales en `env`.

Opciones que sí sirven sin literal [INF]:

1. **Lanzador que lea la variable de Usuario del registro** (el proceso hijo puede leer `HKCU\Environment` aunque Desktop no se la pase). Por ejemplo, `command` = `powershell.exe` con un `.ps1` que haga `$env:LOCAL_DELEGATE_WEB_TOKEN = [Environment]::GetEnvironmentVariable('LOCAL_DELEGATE_WEB_TOKEN','User')` y luego ejecute `mcp-remote … --header "Authorization:Bearer ${LOCAL_DELEGATE_WEB_TOKEN}"` (mcp-remote expande `${VAR}` de su propio entorno). Funciona, pero las comillas en Windows son frágiles.
2. **Mejor para el producto**: un subcomando de `local-delegate` que haga de puente stdio→HTTP contra el daemon (por ejemplo, `local-delegate bridge`) y saque el token por su cuenta: de la variable de Usuario del registro o del fichero de config de local-delegate. `install --desktop` escribiría `command` = ruta absoluta del ejecutable, sin `npx`, sin `mcp-remote` y sin secreto en el JSON.
3. **Extensión .mcpb** con `user_config` `{token: {type: "string", sensitive: true}}` y `${user_config.token}` en `env`/`args`: el mecanismo oficial de Desktop para secretos (el usuario lo pega una vez en la ficha de la extensión).

Confirmar la opción 1 o 2 en vivo exige añadir una entrada de prueba y **reiniciar Desktop**. No lo hice. Pasos: añadir `ld-probe` con el lanzador, reiniciar Desktop, mirar `mcp-server-ld-probe.log` (debe salir `Connected` y no 401) y ejecutar la sonda de nombres sobre el `node` de mcp-remote.

## 3. Por qué salen errores al abrir Desktop

Sesión actual: Desktop arrancó a las 18:07:01 hora local (21:07Z en `mcp.log`). Los logs vivos están en `%LOCALAPPDATA%\Claude\Logs\`.

**Chat y «Cowork/Code»** [DOC + PRUEBA]: Desktop arranca cada servidor de `claude_desktop_config.json` **dos veces**. Una copia es para el chat (errores «Server disconnected», aviso «X couldn't start»/«stopped running»). La otra es la **reserva compartida** (*shared pool*) que se ofrece a las sesiones de Cowork y de Code (errores «Couldn't start for Cowork and Code sessions», contexto `shared-pool`, aviso `mcp_shared_pool_error`; código ≈4514624 y ≈4527693). Los servidores de `~/.claude.json` **no** aparecen en estos logs: la pestaña Code los carga con su propio Claude Code y no deja rastro en `mcp.log` ni `main.log` [PRUEBA: 0 menciones en los errores y avisos de `main.log` de la sesión].

De 25 servidores, **fallan 4**. Los otros 21 conectan, `local-delegate` incluido [PRUEBA, `mcp.log`; resumen local cruzado]:

- **pycharm / webstorm**: `mcp-remote@0.14.3` contra `127.0.0.1:65287` y `127.0.0.1:64438` da `ECONNREFUSED` porque los IDE no están abiertos (ni `pycharm64` ni `webstorm64` corren, y los puertos no escuchan) [PRUEBA]. Fallan en chat y en la reserva compartida (3–4 reintentos cada uno). En el CLI pasa lo mismo (esta sesión de Claude Code también reporta `pycharm ECONNREFUSED`). Además, el puerto de JetBrains puede cambiar al reabrir el IDE [INF].
- **markitdown**: arranca y muere a los 10 s con `ImportError: cannot import name 'eval_type_backport' from 'pydantic._internal._typing_extra'`, lanzado desde `mcp\server\fastmcp\utilities\func_metadata.py` [PRUEBA]. La entrada de Desktop añade `--with "mcp<2"`; la del CLI no (`uvx --from markitdown-mcp --with markitdown[all] markitdown-mcp`) y en el CLI funciona. El `mcp` 1.x que fuerza `mcp<2` importa un símbolo interno que el pydantic reciente ya quitó [INF].
- **MCP_DOCKER**: arranca bien (42 tools) y se cae a las 18:08:55 («transport closed unexpectedly»). Los procesos de Docker Desktop tienen hora de inicio 18:09, así que Docker Desktop se (re)inició justo entonces y tumbó el `docker mcp gateway run`. Desktop no lo relanza: ahora mismo no queda ningún proceso de gateway [PRUEBA]. Aviso aparte, no fatal: `secrets engine is not available: dial unix …sock: An invalid argument was supplied`.

Lo que **no** es la causa de ningún fallo de esta sesión: el PATH (todos encuentran `npx.cmd` en `C:\nvm4w\nodejs` y `uvx.exe` en `~\.local\bin`) y el OAuth de `mcp-remote` (DigitalOcean y betterstack conectan; betterstack tuvo un `AbortError` puntual y luego siguió). El filtrado del entorno tampoco rompe nada **hoy**, porque todas las entradas de Desktop llevan los secretos literales. Rompería cualquier entrada copiada del CLI con `${VAR}` [INF].

## 4. Por qué hay dos (en realidad cuatro) `mcp-remote` por servidor [PRUEBA]

Árbol de procesos (todo creado por el `claude.exe` actual, pid 60116, hijo de explorer, 18:07):

```
claude.exe 60116 ─ cmd 60672 ─ node 36380 (npx-cli)  ─ cmd 9452 ─ node 42220 (mcp-remote proxy.js)   18:07:10  ← chat
                 └ cmd 38412 ─ node 62192 (npx-cli)  ─ cmd 5720 ─ node 17492 (mcp-remote proxy.js)   18:07:32  ← reserva Cowork/Code
```

Lo mismo para las 4 de DigitalOcean y betterstack: un lanzamiento a las 18:07:0x (chat) y otro a las 18:07:2x–3x (reserva compartida). Cada uno son 2 `node`: el envoltorio de `npx` más el `mcp-remote` real. **No hay huérfanos** de arranques anteriores.

## 5. Recomendación (sin aplicar)

1. **markitdown**: igualarla al CLI quitando `--with "mcp<2"`. Si hiciera falta mantener `mcp` 1.x, añadir `--with "pydantic<2.12"` [INF: falta confirmar la versión exacta de pydantic que quitó el símbolo].
2. **pycharm / webstorm**: sacarlas de `claude_desktop_config.json` (son por proyecto y dependen del IDE abierto) o asumir el aviso cuando el IDE esté cerrado. Si se quieren en Desktop, que las gestione la integración de JetBrains con Claude Desktop, que reescribe el puerto.
3. **MCP_DOCKER**: abrir Docker Desktop antes que Claude, o relanzar el servidor desde Ajustes → Desarrollador cuando Docker termine de arrancar. Si no se usa en el chat, quitarlo.
4. **Higiene de secretos**: los tokens literales en `claude_desktop_config.json` funcionan, pero el fichero tiene en claro tokens de local-delegate, DigitalOcean, GitHub, Brave y OpenAI, más credenciales de Postgres dentro de las URL de conexión. Para lo que se pueda, mejor pasar a extensiones .mcpb con `user_config` sensible.
5. **Qué implica para `install --desktop` de local-delegate** (hoy `install.py` no tiene modo Desktop: `mcp_entry` solo genera entradas para Claude Code):
   - **No** reutilizar `mcp_entry` tal cual: el `Bearer ${LOCAL_DELEGATE_WEB_TOKEN}` del modo HTTP y el `${LOCAL_DELEGATE_API_KEY}` del modo stdio llegarían **literales**. Lo mismo con cualquier variable `LOCAL_DELEGATE_*` que se espere heredar: Desktop las filtra.
   - Desktop solo acepta stdio en su config: hace falta un puente (`mcp-remote` o uno propio).
   - Camino recomendado: un puente propio (opción 2 del apartado 2) que lea el token del registro o de la config de local-delegate, con ruta absoluta en `command`. A falta de eso, la extensión .mcpb (opción 3). Escribir el token literal solo con aviso explícito al usuario.
   - `doctor` debería avisar si una entrada de Desktop contiene `${…}` (salvo `${PATH}` dentro de `PATH`): Desktop no la expande.
   - Contar con el doble lanzamiento (chat + reserva compartida): cada entrada de Desktop crea dos clientes contra el daemon.

## Tabla resumen

| Servidor | Error (sesión 18:07) | Causa | Arreglo |
|---|---|---|---|
| pycharm | `ECONNREFUSED 127.0.0.1:65287` (chat + reserva Cowork/Code) | PyCharm cerrado; puerto sin escuchar (también falla en el CLI) | Quitar de Desktop o abrir el IDE antes; si se quiere, que lo gestione la integración del IDE |
| webstorm | `ECONNREFUSED 127.0.0.1:64438` (chat + reserva) | WebStorm cerrado | Igual que pycharm |
| markitdown | `ImportError … eval_type_backport` → «Connection closed» | `--with "mcp<2"` (solo en Desktop) junta un `mcp` 1.x con un pydantic nuevo | Quitar `--with "mcp<2"` (como en el CLI) o fijar `pydantic<2.12` |
| MCP_DOCKER | Conecta y se cae a las 18:08:55 (transport closed) | Docker Desktop se (re)inició a las 18:09 y mató el gateway; Desktop no lo relanza | Abrir Docker antes que Claude o relanzar desde Ajustes; quitarlo si no se usa |
| local-delegate | Sin error | Funciona porque el token va **literal** en `--header` | Para quitar el literal: puente propio o .mcpb (`${…}` no se expande en Desktop) |
| DigitalOcean ×4, betterstack | Sin error (un `AbortError` puntual en betterstack) | — | — |
| Resto (17) | Sin error | — | — |
