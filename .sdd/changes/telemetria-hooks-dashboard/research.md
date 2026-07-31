# Research: El dashboard lee la telemetria de los hooks

## Current behavior

- `resources/hooks/hook_common.py:24-37` escribe JSONL a la ruta de `LD_HOOK_TELEMETRY_LOG`, y su
  docstring declara el contrato: *«nunca escribe prompts, comandos ni paths: solo evento,
  categoria, tamaño y banda»*.
- La variable **sí está definida** (bloque `env` de `~/.claude/settings.json`), y el log de la
  máquina de referencia tiene **1817 líneas**.
- Forma de cada evento: `ts`, `event`, `suggested`, `category`, y `command_chars` o `prompt_chars`.
- `metrics.py` no menciona `telemetry` ni `hook`.

Composición real medida (rango 2026-07-01 en adelante):

| | |
| --- | --- |
| Total | 1817 |
| Sugeridas | 308 (**17,0 %**) |
| Por evento | `PreToolUse` 1679 (283 sug.), `UserPromptSubmit` 138 (25 sug.) |
| Por categoría | `bash` 1396 / **0 sug.**, `lint` 283 / **283 sug.**, `sin categoría` 113 / 0, `summarize` 25 / 25 |

**El desglose por categoría dice mucho más que el total:** la tasa global sale entera de `lint` y
`summarize`; `bash` no sugiere nunca.

## Impact map

| Área | Responsabilidad actual | Impacto esperado | Evidencia |
| --- | --- | --- | --- |
| `config.py` | Configuración por entorno | Añade `HOOK_TELEMETRY_LOG` | patrón de `LOG_DIR` |
| `web/metrics.py` | Endpoints y panel | `_aggregate_hooks` + `/api/hooks` + tarjeta | `_aggregate` como molde |
| `web/metrics.py` (JS) | Render del panel | `renderHooks` y `escHooks`, y un fetch más en `fetchData` | `fetchData:1244` |
| `docs/wiki/Savings-and-metrics.md` | Documenta las APIs | Fila nueva y sección | tabla de APIs |

## Existing conventions

- **`_read_file_cached` lee JSONL tolerando líneas corruptas y cachea por `(mtime, size)`**. Se
  reutiliza tal cual: el log de hooks es otro JSONL escrito por procesos que pueden morir a medias.
- **`_resolve_range` gobierna el rango de todos los endpoints**, y el panel manda `from`/`to` a
  todos. Una tarjeta con otro rango se leería como una contradicción de los KPIs.
- **Las cuentas viven en Python, no en el cliente** (`Savings-and-metrics.md:69`): una sola
  implementación. Por eso el agregado es una función pura y el JS solo pinta.
- **Los tests que prueban JS lo ejecutan con node**, no lo buscan por grep
  (`test_metrics.py:641`, paridad de `acct()`); `_extraer_funcion_js` es el ayudante.
- El resto del panel interpola sin escapar porque pinta datos propios.

## Dependencies and integrations

- Ninguna nueva. `_read_file_cached`, `_parse_ts` y `_resolve_range` ya existen.
- `node` para dos tests; se saltan con `pytest.skip` si no está, como el de paridad.

## Risks and unknowns

- **Confirmado por ejecución:** el endpoint contra el log real devuelve los 1817 eventos con el
  desglose correcto por evento, categoría y día.
- **Confirmado:** el escapado, ejecutado con node.
- **Decisión, no incógnita:** el endpoint devuelve la **ruta** del log en `log`. Es consistente con
  `/api/status`, que ya expone `log_dir`, y con que el panel sea local.
- **Riesgo vivo, de interpretación:** que alguien lea la tasa como «lo que se delegó». Se mitiga
  con texto en la propia tarjeta y un test que falla si ese texto desaparece; **no** con código.
