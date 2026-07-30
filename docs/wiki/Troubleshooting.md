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

## `[local-delegate error] no se pudo conectar al endpoint`

El backend OpenAI-compatible no responde en `LOCAL_DELEGATE_BASE_URL`.

- Verifica que tu backend corre: `curl http://127.0.0.1:9292/v1/models`.
- Si usas llama-swap y quieres que el MCP lo arranque solo, activa el opt-in
  (`LOCAL_DELEGATE_AUTOSTART=1` + `LLAMASWAP_CONFIG`/`LLAMASWAP_EXE`). Ver
  [recipe de llama-swap](../recipes/llama-swap-blackwell.md).
- Otros backends (Ollama, LM Studio, vLLM) los arrancas tú; el auto-arranque es solo llama-swap.

Si el backend está en otra máquina:

- `Could not resolve host`: MagicDNS no está resolviendo; prueba primero `tailscale status` y
  `tailscale ping <PC>` desde la Mac.
- `Operation timed out`: DNS resolvió, pero falta ruta/grant o Tailscale Serve no está activo.
- `401`: la red funciona; carga la key desde Keychain y confirma el header Bearer.
- No cambies a MCP remoto completo para “arreglar” `path`: el MCP debe seguir local en la Mac.

Guía completa: [Backend remoto Mac → PC](Remote-backend.md).

## `[local-delegate error] <modelo> respondió 404` (o "model not found")

Los ids de modelo configurados no existen en tu backend. Ajusta
`LOCAL_DELEGATE_MODEL_MECHANICAL/_LONG/_CODE/_FAST` a los ids reales (p. ej. con Ollama,
`llama3.1`, `qwen2.5-coder:14b`…). Ver [Configuration](Configuration.md).

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

Si además responde a `curl` con **401**, no está caído: está arriba y **falta la credencial en ese
entorno**. Desde la 0.14.0 el `doctor` lo distingue y lo reporta como `[ -- ] … responde 401`, que
no cuenta como aviso. Exporta `LOCAL_DELEGATE_API_KEY` en la shell desde la que lo ejecutas.

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
