# Prueba con Codex real en la PC: qué tienes que hacer tú (#669, #670, #671)

Escrito el 2026-11-23. Lo demás ya está hecho: los cuatro hooks están en `~\.codex\hooks.json`
(`doctor`: «configurados 4 de 4; aprobados 0 de 4»), tus hooks de antes siguen intactos y la entrada
MCP de Codex (http a `127.0.0.1:9393/mcp`) no se tocó. Copia de antes en la carpeta `codex-backup`
del scratchpad de la sesión. Tiempo estimado: unos 45 min.

## 0. Antes de empezar (1 min)

```powershell
local-delegate test-window start --label codex-real-669-670-671   # apunta el id que imprime
local-delegate doctor | Select-String "Codex"
```

## 1. Aprobar los hooks (#669, 2 min)

1. Abre Codex (`codex`) en cualquier carpeta y escribe `/hooks`.
2. Aprueba los cuatro: `codex-prompt`, `codex-subagent-start`, `codex-tool-guard`, `codex-mcp-call`.
   No toques los tuyos (`advise_delegate_read`, `pre-tool-use.mjs`, `advise_lint_summary`, relevo).
3. Sal de Codex y corre `local-delegate doctor`: debe decir «aprobados en /hooks: 4 de 4». Si dice
   «0 de 4» tras aprobarlos, para aquí y avísame: es un fallo.

## 2. Delegaciones atribuidas por sesión (#669, 10 min)

En **una sola sesión nueva** de Codex, abierta en `D:\Projects\local-delegate`, pide en orden:

1. Hilo principal: `resume README.md con local_summarize en cinco viñetas`.
2. Subagente: `lanza un subagente que resuma docs/wiki/Tools.md con local_summarize y te dé el resultado`.
3. Code mode (si lo tienes encendido): `desde código, llama a local_extract sobre CHANGELOG.md con el campo version`.
4. Un prompt mecánico sin nombrar la tool: `extrae las versiones que aparecen en CHANGELOG.md`
   (debe salir el aviso de `codex-prompt` a favor de `local_extract`).

Apunta la hora (Uruguay) del primer y del último prompt. No cierres la sesión hasta el paso 3.

## 3. Resumen de lecturas y guard de escritura (#670, 15 min)

Crea el centinela fuera del repo (prosa de unos 12 KB con una palabra rara solo a mitad):

```powershell
$d = "$env:TEMP\ld-centinela"; New-Item -ItemType Directory -Force $d | Out-Null
$p = 1..60 | ForEach-Object { "Párrafo $_ de prueba: el inventario del almacén se revisa cada semana y las diferencias se anotan en el registro general para la auditoría del trimestre." }
$p[30] = $p[30] + " La clave interna de este documento es ZEBRA-4417."
Set-Content -Path "$d\centinela.md" -Value ($p -join "`n`n") -Encoding utf8
(Get-Item "$d\centinela.md").Length   # debe pasar de 8192
```

Abre **otra** sesión de Codex en esa carpeta (`cd $env:TEMP\ld-centinela; codex`) y pide:

1. `lee centinela.md con cat y dime de qué trata`. Debe contestar con el resumen; en pantalla, el
   aviso de que el hook bloqueó la orden.
2. `¿qué palabra rara o clave aparece a mitad del fichero?` No debe saber `ZEBRA-4417` (si la dice,
   el original entró al contexto: fallo).
3. `cambia la primera línea de centinela.md por "Título de prueba"`. El `apply_patch` debe
   **rechazarse** con el aviso de leer un tramo literal.
4. `lee las primeras 40 líneas con Get-Content -TotalCount 40 y vuelve a intentar el cambio`. Ahora
   el cambio **pasa**.
5. Daemon parado (la lectura debe pasar tal cual). En otra consola:

   ```powershell
   $pid9393 = (Get-NetTCPConnection -LocalPort 9393 -State Listen).OwningProcess
   schtasks /End /TN LocalDelegateDaemon; Stop-Process -Id $pid9393 -Force
   ```

   En la sesión del centinela pide de nuevo `lee centinela.md con cat`: ahora Codex lee el fichero
   entero. Vuelve a arrancar el daemon: `schtasks /Run /TN LocalDelegateDaemon` y comprueba
   `local-delegate doctor` (backend conectado).

## 4. Tools directas sin `tool_search` (#671, 10 min)

```powershell
local-delegate install --clients codex --mcp-mode http --codex-direct-tools --no-hooks --no-memory --no-skill --dry-run
```

Debe enseñar la misma entrada (`url = "http://127.0.0.1:9393/mcp"`, tu `bearer_token_env_var`) más
`omit_tools_from = ["deferred"]`. Si es así, repítelo sin `--dry-run` y acepta reemplazar la entrada
puesta a mano (deja `config.toml.bak`). Abre una sesión nueva de Codex y pide
`resume docs/wiki/Codex-capabilities.md en cinco viñetas`: el modelo debe llamar a
`local_summarize` **sin** pasar antes por `tool_search`. Repite ese mismo prompt en **Codex Desktop**
si lo tienes en la PC (si solo está en la Mac, dilo y queda para allí). Vuelta atrás, si no lo
quieres encendido: el mismo comando con `--no-codex-direct-tools`.

## 5. Al terminar

```powershell
local-delegate test-window stop <id del paso 0>
local-delegate doctor | Select-String "Codex"
```

Dime: el id de la ventana, las horas de los pasos 2 y 3, si en el paso 3 Codex supo la palabra
rara, si el `apply_patch` se rechazó y luego pasó, y si en el paso 4 hubo `tool_search`.

## Qué miro yo después en el log (no hace falta que lo mires tú)

- `usage-202611.jsonl` del `LOG_DIR`, filas de la ventana con `client: codex-mcp-client`: llevan
  `tool_use_id` (el de code mode empieza por `exec-`), `caller_session_key` (la misma en las tres
  delegaciones del paso 2, también la del subagente), `caller_src: codex-hook`, `caller_model` (el
  de Codex), `caller_kind` `main`/`subagent` y `caller_agent_type` en la del subagente. Sin
  `tool_use_id` o sin `caller_session_key`: el `_meta` no llega como se supuso. Con `tool_use_id`
  pero sin `caller_src`: el hook no despachó (miro `codex-hooks-seen.json` y el `tool_name` real).
- Filas con `client: local-delegate-codex-read` en el paso 3.1 (el resumen del centinela) y ninguna
  en el 3.5 (daemon parado).
- `<datos>\codex-read\<session_id>.jsonl` de la sesión del centinela: solo rutas, tramos y marcas,
  nunca texto; el transcript de esa sesión en `~\.codex\sessions\…` no contiene `ZEBRA-4417`
  antes del paso 3.5.
- Forma real del `command` de PowerShell que Codex pasa al hook en Windows (para cerrar la duda de
  `verification.md` de #670).
- Panel: «Quién delegó» con la columna «Codex»; `/api/stats?session=<id>` solo con esa sesión.
- Con eso: puerta `conformance` y cierre de `codex-session-attribution` y
  `codex-read-summary-write-guard`, comentario de evidencia en #669, #670 y #671 y cierre de los tres.
