# Recipe: hooks de Claude Code para sugerir delegación

Dos hooks **opt-in** que sugieren usar las tools `local_*` en el momento justo, sin
forzar nada: ninguno de los dos bloquea la acción original de Claude, solo le añaden
contexto adicional (`additionalContext`) para que decida.

Scripts en [`hooks/`](./hooks/): Python 3 puro (sin dependencias), multiplataforma.

## Qué hace cada uno

### `suggest_delegate_read.py` — `PreToolUse`, matcher `Read`

Si el archivo que Claude va a abrir con `Read` pesa más de `LD_HOOK_READ_KB` (default
**50 KB**), añade una sugerencia de usar `local_summarize(path=...)` o
`local_extract(path=...)` en vez de leerlo entero. Nunca bloquea: siempre devuelve
`permissionDecision: "allow"`.

### `suggest_lint_summary.py` — `PostToolUse`, matcher `Bash`

Si el comando ejecutado matchea `lint|test|tsc|build|pytest|clippy|biome` y su stdout
supera `LD_HOOK_BASH_LINES` líneas (default **120**), sugiere volcar la salida a
fichero y usar `local_lint_summary(path=...)`. El tool ya se ejecutó: esto es solo
feedback, no hay nada que bloquear.

## Instalación

Copia los dos scripts a donde prefieras (por ejemplo `~/.claude/hooks/`) y añade este
bloque a tu `settings.json` (global `~/.claude/settings.json` o de proyecto
`.claude/settings.json`), ajustando las rutas:

```json
{
  "hooks": {
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
      }
    ],
    "PostToolUse": [
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

En Windows, `command` puede ser `python` o `py`; en macOS/Linux, `python3`. Verifica
cuál resuelve en tu `PATH` antes de instalar.

## Configuración (env)

| Variable | Default | Efecto |
|---|---|---|
| `LD_HOOK_READ_KB` | `50` | Umbral en KB para que `suggest_delegate_read.py` sugiera delegar |
| `LD_HOOK_BASH_LINES` | `120` | Nº de líneas de stdout para que `suggest_lint_summary.py` sugiera resumir |

## Por qué opt-in

Estos hooks son una **recipe**, no algo que `local-delegate` instale solo: cada usuario
decide si los quiere y con qué umbrales. Si prefieres que Claude decida caso a caso sin
un hook determinista, la [skill `delegacion-local`](../../README.md) ya cubre la regla
de decisión — los hooks son un empujón adicional, no un reemplazo.

## Verificación manual

Con los hooks instalados, pide a Claude que lea (con `Read`) un archivo de más de 50 KB
del repo: debería aparecer la sugerencia de `local_summarize`/`local_extract` como
contexto adicional antes de que Claude decida. Para el segundo hook, corre un comando
de test/lint con salida larga (`npm test`, `pytest`, `cargo clippy`, …) y verifica que
aparece la sugerencia de `local_lint_summary` tras la ejecución.
