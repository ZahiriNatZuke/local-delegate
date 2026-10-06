# Troubleshooting

## `MCP error -32000: Connection closed` — el cliente no ve nada más

Ese mensaje es el **síntoma de un proceso muerto**, no la causa, y el cliente no enseña más. La
causa suele ser que el paquete **no importa**: una dependencia publicó un major incompatible y
`uvx` resolvió a él.

**El traceback real está en el `Server stderr` del log de tu cliente**, no en la ventana de chat.
En macOS, `~/Library/Caches/claude-cli-nodejs/<proyecto>/mcp-logs-local-delegate/`.

Pasó de verdad con la 0.12.1: el SDK `mcp` publicó 2.0.0, que eliminó `mcp.server.fastmcp`, y la
versión publicada declaraba `mcp>=1.2` sin techo. Toda instalación nueva moría. Por eso hoy las
dependencias del camino de arranque llevan techo de major (ver
[Configuración del repositorio](Repo-hardening.md)) y hay un job `install-smoke` que instala el
wheel con resolución libre y le exige un handshake.

**Si te pasa:** mira el stderr, y como parche inmediato acota la dependencia culpable
(`uvx --with "mcp<3" …`). Fijar una versión **vieja** del paquete no ayuda — al contrario: congela
rangos de dependencias aún más antiguos.

## El daemon responde `421 Misdirected Request`

Solo con el SDK `mcp` 2.x, y solo si publicaste el daemon fuera de loopback. `streamable_http_app`
activa por su cuenta la protección contra *DNS rebinding* cuando el host es de loopback, y entonces
**solo admite** `127.0.0.1:*`, `localhost:*` y `[::1]:*`: cualquier cliente que llegue por la IP de
la LAN recibe 421.

Se corrigió pasándole el host configurado, así que con `LOCAL_DELEGATE_WEB_HOST=0.0.0.0` la
protección no se activa y la LAN funciona. Si lo ves igualmente, comprueba que el cliente manda el
header `Host` que esperas y que el daemon corre una versión **0.13.0 o posterior**.

## El dashboard sigue enseñando los gráficos viejos tras actualizar

No es un fallo: el endpoint sirve Chart.js con `Cache-Control: public, max-age=86400`, así que tras
actualizar el paquete **el navegador sigue usando el de la caché hasta 24 h**. Fuerza la recarga
(Ctrl+F5) y se acabó. Despista mucho al verificar una actualización: `window.Chart.version` puede
seguir diciendo la versión vieja con el servidor sirviendo ya la nueva.

## `[local-delegate error] no se pudo conectar con el backend: …`

El backend OpenAI-compatible no responde en `LOCAL_DELEGATE_BASE_URL`. Detrás de los dos puntos va
la **causa**, la misma que enseñan el badge del panel, `local_status` y `doctor`, y que el log de
uso guarda en la clave `fallo_conexion` (las versiones anteriores a este cambio decían «no se pudo
conectar al endpoint» sin más).

| Causa (`fallo_conexion`) | Badge | Qué dice | Qué hacer |
|---|---|---|---|
| `dns` | caído · no resuelve | no se resuelve el nombre `<host>` (¿VPN o DNS?) | Revisa el nombre en `LOCAL_DELEGATE_BASE_URL`; con un backend remoto, `tailscale status` o usa la IP 100.x de la tailnet |
| `rechazada` | caído · nadie escucha | `<host>` rechaza la conexión: no hay nada escuchando en ese puerto | Arranca llama-swap (en local) o revisa el puerto; en otra máquina, arráncalo allí |
| `sin_ruta` | caído · sin ruta | no hay ruta de red hacia `<host>` | Revisa la red hacia ese host: VPN, cortafuegos, Tailscale |
| `timeout_conexion` | caído · no contesta | `<host>` no contesta a la conexión (ruta, cortafuegos o VPN) | Igual que `sin_ruta`; es el caso típico de una VPN que se come el tráfico |
| `credencial` | sin acceso (ámbar) | `<host>` responde `<N>`: está arriba pero rechaza la credencial | Falta o no vale `LOCAL_DELEGATE_API_KEY` en el entorno de quien llama (ver abajo) |
| `http_error` | responde con error (ámbar) | `<host>` responde HTTP `<N>` | Revisa `LOCAL_DELEGATE_BASE_URL` (¿falta `/v1`?) |
| `respuesta_invalida` | respuesta no válida (ámbar) | `<host>` responde a `<endpoint>`, pero con un cuerpo que no se entiende | Lo que escucha en ese puerto no es un backend OpenAI-compatible |
| `sin_respuesta` | no responde a tiempo (ámbar) | `<host>` acepta la conexión pero no responde a tiempo | El backend está colgado o saturado; revísalo en ese host |
| `url_invalida` | caído · URL no válida | la URL del backend no es válida: revisa LOCAL_DELEGATE_BASE_URL | Corrige la URL |
| `transporte` | caído · fallo de red | fallo de red con `<host>` | Sin pista específica: revisa el backend en ese host |
| `desconocida` | caído · fallo inesperado | fallo inesperado al sondear `<host>` | Igual; el tipo de excepción va entre paréntesis en el detalle |

El badge rojo (con «caído») es para cuando no se llega al backend; el ámbar, para cuando **alguien
contesta** pero la respuesta no sirve. En el panel hacen falta dos sondeos fallidos seguidos para
pasar a «caído»; ver [Savings & metrics](Savings-and-metrics.md#estado-del-backend-y-de-los-modelos).

- Verifica que tu backend corre: `curl http://127.0.0.1:9292/v1/models`.
- Si usas llama-swap **en esta máquina** y quieres que el MCP lo arranque solo, activa el opt-in
  (`LOCAL_DELEGATE_AUTOSTART=1` + `LLAMASWAP_CONFIG`/`LLAMASWAP_EXE`). Ver
  [recipe de llama-swap](../recipes/llama-swap-blackwell.md).
- Otros backends (Ollama, LM Studio, vLLM) los arrancas tú; el auto-arranque es solo llama-swap.
- **Con un backend en otra máquina** el MCP no pregunta «¿Lo arranco?» ni intenta arrancarlo,
  tenga `LOCAL_DELEGATE_AUTOSTART` el valor que tenga: no puede arrancar nada fuera de esta máquina.
- **Una delegación se rinde a los 10 s si no puede conectar.** Ese plazo es solo el de
  **conexión**; la lectura sigue en `LOCAL_DELEGATE_TIMEOUT` (180 s por defecto), así que la
  espera mientras llama-swap carga un modelo no cambia. Antes, con una VPN que se comía el tráfico,
  cada delegación se quedaba colgada 75–95 s hasta que el sistema operativo agotaba la conexión.

Si el backend está en otra máquina:

- `dns` (o `Could not resolve host` con `curl`): MagicDNS no está resolviendo; prueba primero
  `tailscale status` y `tailscale ping <PC>` desde la Mac.
- `timeout_conexion` o `sin_ruta` (`Operation timed out` con `curl`): DNS resolvió, pero falta
  ruta/grant, Tailscale Serve no está activo o una VPN se come el tráfico.
- `credencial` (`401`): la red funciona; carga la key desde Keychain y confirma el header Bearer.
- No cambies a MCP remoto completo para “arreglar” `path`: el MCP debe seguir local en la Mac.

Guía completa: [Backend remoto Mac → PC](Remote-backend.md).

## `[local-delegate error] <modelo> respondió 404` (o "model not found")

Los ids de modelo configurados no existen en tu backend. Ajusta
`LOCAL_DELEGATE_MODEL_MECHANICAL/_LONG/_CODE/_FAST/_VISION` a los ids reales (p. ej. con Ollama,
`llama3.1`, `qwen2.5-coder:14b`…). Ver [Configuration](Configuration.md).

**Si empezó al actualizar a la 0.28.0:** los defaults de largo, código y visión pasaron a
`gemma4-26b-a4b`, `qwen36-35b-a3b` y `gemma4-12b`. Si tu `config.yaml` de llama-swap sigue con
`llama31-8b`, `qwen25-coder-14b` o `qwen3-vl-8b`, renómbralos allí o fija las variables a los ids
que tengas.

## `UserPromptSubmit operation blocked by hook` — Claude Code no te deja escribir

Síntoma exacto, en cada prompt:

```
UserPromptSubmit operation blocked by hook:
python.exe: can't open file 'C:\\UsersTuUsuario.claudehookslocal-delegatesuggest_delegate_prompt.py'
```

Fíjate en la ruta: **perdió las barras**. Las versiones **anteriores a la 0.14.0** registraban el
hook como `python C:\Users\...\hook.py` sin comillas, y el shell al que Claude Code entrega ese
comando interpreta cada `\` como escape y lo borra. Solo afecta a Windows, y con
`UserPromptSubmit` no degrada: bloquea.

Cómo salir:

1. Quita las entradas de local-delegate de `~/.claude/settings.json` (las que apuntan a
   `hooks/local-delegate/`) para poder volver a escribir.
2. Actualiza a **0.14.0 o posterior** y reinstala: `uvx local-delegate-mcp install`. Desde esa
   versión la ruta va citada y con barras `/`, que funciona en sh, cmd y PowerShell.
3. Comprueba con `local-delegate doctor` — «hooks registrados» debe salir `[ OK ]`.

## `doctor` dice que el backend está CAÍDO pero llama-swap está corriendo

Si responde a `curl` con **401**, no está caído: está arriba y **falta la credencial en ese
entorno**. Desde la 0.18.1 `doctor` ni siquiera llega ahí — le pregunta primero al daemon, que sí
tiene credencial, y solo prueba por su cuenta si no hay daemon. Si aun así lo ves, exporta
`LOCAL_DELEGATE_API_KEY` en la shell desde la que lo ejecutas.

Ahora `doctor` ya no lo llama «caído»: el check «backend» enseña el **detalle de la causa** (la
tabla de la sección anterior sobre «no se pudo conectar con el backend») y una pista que
depende de **quién** vio el fallo y de **dónde** está el backend:

- Un 401 visto por `doctor` en su propio sondeo sale `[ -- ]` (no se pudo comprobar) con la pista «exporta
  LOCAL_DELEGATE_API_KEY en este entorno»: lo que falta es la clave en **esta** consola.
- Un 401 que ve el **daemon** sale `[WARN]` con «la clave del daemon no vale: revisa
  LOCAL_DELEGATE_API_KEY en su lanzador».
- Con el backend en otra máquina, ninguna pista dice «arranca llama-swap» a secas: dice dónde
  («arranca llama-swap en `<host>` o revisa el puerto») o manda a revisar la red (VPN, cortafuegos,
  Tailscale).

`local_status` usa el mismo criterio en su línea `Backend:`: `arriba`, `SIN ACCESO: <detalle>`
(credencial), `RESPONDE CON ERROR: <detalle>` (alguien contesta, pero con error, con un cuerpo que
no se entiende o sin responder a tiempo) o `CAÍDO: <detalle>` (no se llega). Ni `doctor` ni
`local_status` esperan un segundo fallo como el panel: hacen una sola consulta y dicen lo que ven.
Los sondeos de estado se rinden a los 3 s si no pueden conectar y a los 2 s si no les llega la
respuesta, así que con el backend inalcanzable tardan como mucho eso.

## Las tools `local_*` responden `401` aunque `doctor` diga que el backend está bien

**Son dos caminos distintos al mismo backend, y solo uno lleva la credencial.** El daemon la recibe
de su lanzador (en Windows, descifrada con DPAPI); el proceso MCP en modo `stdio` lo arranca el
**cliente** y hereda el entorno del cliente, donde normalmente no está. Así que `doctor` puede
verlo todo bien mientras cada delegación falla.

Lo avisa el check **«credencial del backend»**:

```
[WARN] credencial del backend: el backend exige credencial y Claude Code habla por stdio
       sin ella: sus tools local_* responderán 401
       arréglalo con: local-delegate install --mcp-mode http
```

La salida es apuntar la entrada MCP al daemon, que ya tiene el secreto:

```bash
local-delegate install --clients claude --clients codex --no-hooks --no-skill --no-memory --mcp-mode http
```

Después **reinicia el cliente**, y comprueba que una tool responde de verdad — que `doctor` diga
`[ OK ]` no lo demuestra.

Ojo: `--api-key-env` **no** resuelve este caso. Reenvía `${LOCAL_DELEGATE_API_KEY}`, que sale del
mismo entorno que está vacío. Sirve cuando la variable sí existe y solo hay que propagarla.

## `uvx` no encuentra el comando / Claude no arranca el MCP

- Usa la ruta absoluta a `uvx` en `command` (Claude Desktop puede no heredar tu PATH),
  p. ej. `C:\Users\<tu>\.local\bin\uvx.exe`.
- El comando del paquete es `local-delegate-mcp` (o el alias `local-delegate`).

## La web no aparece en `http://127.0.0.1:9393`

- En modo daemon, verifica `GET http://127.0.0.1:9393/api/daemon` y arranca
  `local-delegate serve` si no responde.
- ¿`LOCAL_DELEGATE_WEB=0`? Quítalo.
- Si hay **otra instancia** de Claude (Code + Desktop) ya sirviendo el puerto, la segunda no monta
  una web embebida nueva. Migra los clientes al [daemon compartido](Daemon.md) para eliminar esa
  dependencia del ciclo de vida de `stdio`.

## El modelo tarda mucho en la primera llamada

Es el *cold-load* en VRAM (llama-swap carga el modelo al vuelo). Las siguientes van calientes.
Ajusta el `ttl` de llama-swap para el equilibrio VRAM/latencia — ver
[recipe · Descarga de VRAM](../recipes/llama-swap-blackwell.md#descarga-de-vram-ttl).

## El dashboard está vacío

No hay ningún `usage-YYYYMM.jsonl` todavía (se crea en la primera delegación tras arrancar
el MCP), o `LOCAL_DELEGATE_LOG_DIR`/`LOCAL_DELEGATE_LOG` apunta a otra ruta que la que lee
la web. El pie del dashboard muestra cuántos archivos leyó (`files_read`) — si es 0, es
justo esto.

## `doctor` da `[WARN] coste y relleno`

El check `config.coste` mira si la cifra de coste equivalente es de fiar y si se está perdiendo
histórico. No lee transcripts: lee lo que dejó `local-delegate recalcular-coste` en `LOG_DIR`. Da
`warn` por dos motivos, y si se cumplen los dos los dice juntos:

- **«N delegación(es) pendiente(s) de relleno, la más antigua de hace D días»**. Hay delegaciones
  sin modelo atribuido cuyo transcript está a menos de 10 días de borrarse (Claude Code los borra a
  los `cleanupPeriodDays` de `~/.claude/settings.json`, 30 si no está puesto). Lanza
  `local-delegate recalcular-coste`: las atribuye cruzando el log con los transcripts y el aviso
  desaparece. Una vez borrado el transcript, esa delegación se valora para siempre con el
  respaldo (ver [Configuration](Configuration.md#coste-equivalente)). Avisa aunque el comando no
  se haya lanzado nunca: lo que mira es la pendiente más antigua, no la fecha del último relleno.
- **«el último cotejo (…) no cuadra con lo que cobra Claude Code»**. La tabla de precios del
  paquete no reproduce el coste que Claude Code calcula en sus transcripts: falta un modelo (los
  nombra) o algún precio no casa. Mientras tanto, las delegaciones de un modelo sin precio no suman
  dólares y el panel las cuenta aparte. El arreglo es una tabla al día: actualiza el paquete (el
  vigilante semanal abre un PR cuando cambia la página de precios) y vuelve a lanzar el comando.

`unknown` («no hay cotejo guardado») no es un error: es una máquina sin transcripts de Claude Code
o en la que el comando no se ha lanzado. El check nunca da `missing`.

## El bloque de cuota dice «sin calibrar»

Es lo esperado. Para decir qué parte de una ventana de 5 h o de la semanal supone lo delegado,
hacen falta al menos **tres medidas del statusline de ventanas distintas** con una dispersión
menor del 25 %, y hasta entonces el panel no enseña ningún porcentaje. Esas medidas salen del
registro del statusline (`~/.claude/cuota-statusline.jsonl`), que solo existe si tu statusline lo
escribe; sin él, el bloque lo dice y no puede calibrar. Lanza `local-delegate recalcular-coste`
para incorporar las medidas nuevas. El bloque enseña además cuántas se descartaron y por qué
(`contaminado`, `delta_pequeno`, `solapado`…): una medida tomada mientras otra sesión que no está
en el registro gastaba cuota no sirve para calibrar. Si cambian los límites de uso (el vigilante
abre un PR con el texto nuevo), descarta la calibración vieja con
`local-delegate recalcular-coste --reiniciar-calibracion five_hour` (o `seven_day`).
