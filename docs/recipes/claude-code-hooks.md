# Recipe: hooks de Claude Code para sugerir delegación

Dos hooks **opt-in y consultivos** quedaron recomendados después del piloto A/B:
`UserPromptSubmit` y `PreToolUse/Bash`. El hook `PreToolUse/Read` se conserva como experimento,
pero está apagado por defecto porque produjo avisos ruidosos en tareas de arquitectura. Ninguno
bloquea la acción original ni envía el prompt a otro modelo.

Los scripts se distribuyen **dentro del paquete**
([`src/local_delegate/resources/hooks/`](../../src/local_delegate/resources/hooks)): Python 3 puro,
sin dependencias. La forma soportada de instalarlos es `local-delegate install` (ver abajo).

## Hooks

### `suggest_delegate_prompt.py` — `UserPromptSubmit`

Detecta intenciones mecánicas explícitas como resumir, extraer, clasificar, traducir o resumir
lint. Omite tareas con señales de arquitectura, investigación, seguridad, migración o acciones
de riesgo. Solo añade un recordatorio corto; Claude conserva la decisión final.

### `suggest_delegate_read.py` — `PreToolUse`, matcher `Read`

Está apagado por defecto. Si se activa con `LD_HOOK_READ_ENABLED=1`, usa dos bandas configurables:

- 8-32 KiB: sugerencia si se necesita una transformación global.
- más de 32 KiB: recomendación fuerte de `path`.

Aclara que una lectura directa sigue siendo correcta para líneas exactas usadas al razonar o editar.

### `suggest_lint_summary.py` — `PreToolUse`, matcher `Bash`

Detecta comandos `lint|test|tsc|build|pytest|clippy|biome` **antes** de ejecutarlos y recomienda
redirigir una salida previsiblemente larga a fichero. El hook anterior era `PostToolUse`; llegaba
demasiado tarde porque la salida ya había entrado al contexto.

## Instalación

```bash
local-delegate install --dry-run    # muestra exactamente qué tocaría
local-delegate install              # hooks + skill + memoria + entrada MCP
local-delegate install --no-skill --no-memory --no-mcp   # solo los hooks
```

El comando copia los cuatro archivos (`hook_common.py` y los tres scripts) a
`~/.claude/hooks/local-delegate/` y los registra en `~/.claude/settings.json`. Es idempotente
(reinstalar no duplica entradas), no toca hooks ajenos y se revierte con
`local-delegate uninstall`. El hook de `Read` solo se registra con `--enable-read-hook`.

El resultado en `settings.json` tiene esta forma:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /Users/tu-usuario/.claude/hooks/local-delegate/suggest_delegate_prompt.py"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /Users/tu-usuario/.claude/hooks/local-delegate/suggest_lint_summary.py"
          }
        ]
      }
    ]
  }
}
```

`command` es **un único string de shell**: Claude Code no acepta un campo `args` separado (una
entrada con `args` deja el hook registrado pero sin ejecutar el script). El intérprete por
defecto es `python3` (`python` en Windows) y se cambia con `--python`; no se usa el intérprete
actual porque bajo `uvx` vive en un entorno efímero que desaparece al terminar el comando.

## Configuración

| Variable | Default | Efecto |
|---|---:|---|
| `LD_HOOK_ENABLED` | `1` | `0` apaga sugerencias y telemetría para una sesión A/B |
| `LD_HOOK_READ_ENABLED` | `0` | `1` activa el hook experimental de Read |
| `LD_HOOK_READ_SUGGEST_KB` | `8` | Inicio de sugerencia para Read |
| `LD_HOOK_READ_STRONG_KB` | `32` | Inicio de recomendación fuerte |
| `LD_HOOK_TELEMETRY_LOG` | vacío | JSONL agregado opt-in; vacío desactiva telemetría |

La telemetría solo guarda timestamp, evento, categoría, tamaño/banda y si hubo sugerencia. Nunca
guarda prompts, comandos o paths. Los hooks siguen siendo **opt-in**: el paquete no los activa
por su cuenta, solo `local-delegate install` los registra cuando tú lo pides.

Para comparar sesiones equivalentes sin editar `settings.json`, inicia Claude desde una terminal
con `LD_HOOK_ENABLED=0` para baseline y `LD_HOOK_ENABLED=1` para piloto.

## Verificación manual

1. Envía un prompt como “resume este archivo en cinco viñetas”: debe aparecer el recordatorio.
2. Solo si pruebas el experimento Read, usa `LD_HOOK_READ_ENABLED=1` y pide leer un archivo de
   10 KiB y otro de 40 KiB: deben aparecer bandas diferentes.
3. Ejecuta `pytest` o `npm test`: la sugerencia debe aparecer antes de la tool Bash.
4. Envía “investiga y diseña la arquitectura”: no debe sugerir delegación local.

## Piloto A/B

Usa la suite versionada [`benchmarks/hooks/pilot-prompts.md`](../../benchmarks/hooks/pilot-prompts.md)
en dos sesiones limpias y equivalentes. La sesión A usa `LD_HOOK_ENABLED=0`; la B usa `1`. Registra
los timestamps de inicio/fin y calcula llamadas `local_*` por oportunidad, adopción y falsos
positivos. Gate: adopción >=40%, falsos positivos <=10% y cero bloqueos automáticos.

### Resultado del piloto de 2026-07-23

- A, hooks apagados: 5/6 oportunidades adoptadas (83,3%).
- B, hooks activos: 6/6 (100%); mejora absoluta +16,7 puntos y relativa +20%.
- `UserPromptSubmit`: 6/6 sugerencias correctas y 0/4 falsos positivos.
- `PreToolUse/Read`: cinco sugerencias dentro de dos de las cuatro tareas negativas; 50% de
  falsos positivos por tarea. Por eso queda `ITERATE` y apagado por defecto.
- Configuración adoptada (`UserPromptSubmit` + Bash; Read apagado): 0/4 falsos positivos y cero
  bloqueos. La corrida B mantuvo fuera del contexto 13.387 caracteres por `path`; el ahorro neto
  incremental observado fue pequeño (aprox. 70 tokens) porque la línea base ya delegaba 5/6.

La telemetría de `pytest` incluyó filas sintéticas de sus propios tests. Esas filas se excluyeron
del KPI usando sus marcadores de fixture/latencia cero; no se contaron como adopción real.
