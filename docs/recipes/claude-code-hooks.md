# Recipe: hooks de Claude Code para sugerir delegación

Queda **un** hook consultivo recomendado, `UserPromptSubmit`. El de `PreToolUse/Read` se
conserva como experimento y está apagado por defecto porque produjo avisos ruidosos en tareas de
arquitectura; el de `PreToolUse/Bash` se **retiró** el 2026-09-08 por puntería (ver abajo).
Ninguno bloquea la acción original ni envía el prompt a otro modelo.

Los scripts se distribuyen **dentro del paquete**
([`src/local_delegate/resources/hooks/`](../../src/local_delegate/resources/hooks)): Python 3 puro,
sin dependencias. La forma soportada de instalarlos es `local-delegate install` (ver abajo).

## Hooks

### `suggest_delegate_prompt.py` — `UserPromptSubmit`

Detecta intenciones mecánicas explícitas como resumir, extraer, clasificar, traducir o resumir
lint. Omite tareas con señales de arquitectura, investigación, seguridad, migración o acciones
de riesgo. Solo añade un recordatorio corto; Claude conserva la decisión final.

### `suggest_delegate_read.py` — `PreToolUse`, matcher `Read`

Está apagado por defecto. Se enciende de **dos formas equivalentes**, y basta con una:

- `local-delegate install --enable-read-hook`, que lo registra ya encendido (le pasa `--enabled`
  al script). Es la recomendada: `uninstall` lo retira, así que el registro es la única fuente de
  si está activo o no.
- `LD_HOOK_READ_ENABLED=1` en el entorno, para quien lo instale a mano con esta recipe.

> Antes solo valía la variable, y `--enable-read-hook` registraba el script **sin** ponerla: eran
> dos puertas, la bandera abría una y la opción no hacía nada, en silencio. Corregido.

Encendido, usa dos bandas configurables:

- 8-32 KiB: sugerencia si se necesita una transformación global.
- más de 32 KiB: recomendación fuerte de `path`.

Aclara que una lectura directa sigue siendo correcta para líneas exactas usadas al razonar o editar.

### `suggest_lint_summary.py` — retirado el 2026-09-08

Detectaba comandos `lint|test|tsc|build|pytest|clippy|biome` antes de ejecutarlos y recomendaba
redirigir la salida a fichero. **Ya no se instala**, y `install` retira la entrada y el fichero de
las instalaciones que lo tuvieran.

Se retiró por puntería, medida sobre 21 días de uso real: **366 disparos y 1 acierto** (0,3 %),
con la mediana de salida en 402 bytes. Decidía con una regex sobre el *comando*, antes de
ejecutarlo, y lo que de verdad la activaba eran las palabras `test` y `build` dentro de rutas. Un
aviso que casi nunca tiene razón enseña a ignorar todos los avisos, incluidos los que la tienen.

Ampliar la lista de comandos no lo salvaba: ningún ejecutable del corpus superaba el umbral de
tamaño en más del 9 % de sus ejecuciones, así que el techo alcanzable seguía siendo un aviso que
se aprende a ignorar. La sustitución está en estudio y se decide con datos, no con una regex
mejor.

## Instalación

```bash
local-delegate install --dry-run    # muestra exactamente qué tocaría
local-delegate install              # hooks + skill + memoria + entrada MCP
local-delegate install --no-skill --no-memory --no-mcp   # solo los hooks
```

El comando copia los scripts a `~/.claude/hooks/local-delegate/` y registra en
`~/.claude/settings.json` los que van encendidos. Es idempotente (reinstalar no duplica entradas),
no toca hooks ajenos y se revierte con `local-delegate uninstall`. El hook de `Read` solo se
registra con `--enable-read-hook`, así que **por defecto solo queda registrado el de
`UserPromptSubmit`**.

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
| `LD_HOOK_READ_ENABLED` | `0` | `1` activa el hook experimental de Read (equivale a registrarlo con `--enabled`) |
| `LD_HOOK_READ_SUGGEST_KB` | `8` | Inicio de sugerencia para Read (era `32` hasta el 2026-09-08; ver abajo) |
| `LD_HOOK_READ_STRONG_KB` | `100` | Inicio de recomendación fuerte |
| `LD_HOOK_TELEMETRY_LOG` | vacío | JSONL agregado opt-in; vacío desactiva telemetría |

> **Por qué el umbral bajo pasó de 32 KB a 8 KB (2026-09-08).** Salió de medir la propia
> telemetría, no de opinar. Sobre las **96 lecturas** registradas desde que el log guarda la
> extensión, el hook callaba por tamaño **24 veces, y las 24 eran `.md`, `.json` o `.txt`** —ni una
> de código—, con **17 entre 8 y 16 KB**. Es decir: la franja donde vive la documentación de un
> repo quedaba muda, y lo que parecía el modelo ignorando el aviso era un aviso que **nunca
> llegaba**. La banda `strong` se deja en 100 KB **a propósito**: se cambia una sola cosa, para que
> la siguiente medición sepa a qué atribuir la diferencia.

La telemetría solo guarda timestamp, evento, categoría, tamaño/banda, la **extensión** del archivo,
el motivo del descarte y si hubo sugerencia. Nunca guarda prompts, comandos o paths. La extensión
se acota a 12 caracteres alfanuméricos y se descarta si no lo es, para que una extensión
propietaria y larga no diga por la puerta de atrás lo que la ausencia del path calla. Los hooks siguen siendo **opt-in**: el paquete no los activa
por su cuenta, solo `local-delegate install` los registra cuando tú lo pides.

Para comparar sesiones equivalentes sin editar `settings.json`, inicia Claude desde una terminal
con `LD_HOOK_ENABLED=0` para baseline y `LD_HOOK_ENABLED=1` para piloto.

## Verificación manual

1. Envía un prompt como “resume este archivo en cinco viñetas”: debe aparecer el recordatorio.
2. Solo si pruebas el experimento Read (instalado con `--enable-read-hook`, o con
   `LD_HOOK_READ_ENABLED=1`), pide leer tres archivos **que no sean código**: uno de 5 KiB (no debe
   decir nada), otro de 20 KiB (`Sugerencia`) y otro de 120 KiB (`Recomendacion fuerte`). Con el
   umbral anterior de 32 KB los dos primeros callaban, que es justo lo que se cambió.
3. Ejecuta `pytest` o `npm test`: **no** debe aparecer ninguna sugerencia. El hook que la
   emitía está retirado, y comprobar su ausencia es lo que detecta una copia vieja que siguiera
   registrada de una instalación anterior.
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
