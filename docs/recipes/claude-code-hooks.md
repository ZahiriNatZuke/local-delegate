# Recipe: hooks de Claude Code para sugerir delegación

Tres hooks **opt-in y consultivos** sugieren las tools `local_*` antes de gastar contexto. No
bloquean la acción original ni envían el prompt a otro modelo.

Scripts en [`hooks/`](./hooks/): Python 3 puro, sin dependencias.

## Hooks

### `suggest_delegate_prompt.py` — `UserPromptSubmit`

Detecta intenciones mecánicas explícitas como resumir, extraer, clasificar, traducir o resumir
lint. Omite tareas con señales de arquitectura, investigación, seguridad, migración o acciones
de riesgo. Solo añade un recordatorio corto; Claude conserva la decisión final.

### `suggest_delegate_read.py` — `PreToolUse`, matcher `Read`

Usa dos bandas configurables:

- 8-32 KiB: sugerencia si se necesita una transformación global.
- más de 32 KiB: recomendación fuerte de `path`.

Aclara que una lectura directa sigue siendo correcta para líneas exactas usadas al razonar o editar.

### `suggest_lint_summary.py` — `PreToolUse`, matcher `Bash`

Detecta comandos `lint|test|tsc|build|pytest|clippy|biome` **antes** de ejecutarlos y recomienda
redirigir una salida previsiblemente larga a fichero. El hook anterior era `PostToolUse`; llegaba
demasiado tarde porque la salida ya había entrado al contexto.

## Instalación

Copia los cuatro archivos de `hooks/` (`hook_common.py` y los tres scripts) a
`~/.claude/hooks/` y añade, ajustando las rutas:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python",
            "args": ["/ruta/a/suggest_delegate_prompt.py"]
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [
          {
            "type": "command",
            "command": "python",
            "args": ["/ruta/a/suggest_delegate_read.py"]
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python",
            "args": ["/ruta/a/suggest_lint_summary.py"]
          }
        ]
      }
    ]
  }
}
```

En Windows, `command` puede ser `python` o `py`; en macOS/Linux, `python3`.

## Configuración

| Variable | Default | Efecto |
|---|---:|---|
| `LD_HOOK_ENABLED` | `1` | `0` apaga sugerencias y telemetría para una sesión A/B |
| `LD_HOOK_READ_SUGGEST_KB` | `8` | Inicio de sugerencia para Read |
| `LD_HOOK_READ_STRONG_KB` | `32` | Inicio de recomendación fuerte |
| `LD_HOOK_TELEMETRY_LOG` | vacío | JSONL agregado opt-in; vacío desactiva telemetría |

La telemetría solo guarda timestamp, evento, categoría, tamaño/banda y si hubo sugerencia. Nunca
guarda prompts, comandos o paths. Es una recipe de usuario; `local-delegate` no instala hooks solo.

Para comparar sesiones equivalentes sin editar `settings.json`, inicia Claude desde una terminal
con `LD_HOOK_ENABLED=0` para baseline y `LD_HOOK_ENABLED=1` para piloto.

## Verificación manual

1. Envía un prompt como “resume este archivo en cinco viñetas”: debe aparecer el recordatorio.
2. Pide leer un archivo de 10 KiB y otro de 40 KiB: deben aparecer bandas diferentes.
3. Ejecuta `pytest` o `npm test`: la sugerencia debe aparecer antes de la tool Bash.
4. Envía “investiga y diseña la arquitectura”: no debe sugerir delegación local.
