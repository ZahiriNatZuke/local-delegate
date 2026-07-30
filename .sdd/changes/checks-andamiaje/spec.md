# Especificación — Registro único de comprobaciones y `doctor` completo

## Summary

Nace **una sola definición de «estar a punto»**: un registro de comprobaciones donde cada elemento
del andamiaje sabe cómo verificarse. `doctor` pasa a consumirlo y por primera vez ve el sistema
entero —clientes, skill, hooks, memoria, entradas MCP, daemon y backend— en vez de solo el backend.

Este es el **change A** de tres. Deja la base que después consumirán **B** (`update`) y **C**
(`install --clients auto`). Aquí **no** se toca `install` ni se escribe nada: `doctor` sigue siendo
solo de lectura.

## Requirements

### El registro

- **REQ-001:** Existe `src/local_delegate/checks.py` con un registro de comprobaciones. Cada una
  declara: `id` estable, `group`, descripción corta, y una función `probe(ctx)` que **no escribe
  nada**.
- **REQ-002:** `probe(ctx)` devuelve uno de cuatro estados: `ok`, `missing` (falta y se puede
  arreglar), `warn` (está pero no como debería) y `unknown` (no se pudo comprobar), cada uno con un
  detalle legible de una línea.
- **REQ-003:** Un check que no aplica a la máquina —el cliente no está instalado, no hay
  `config.yaml` de llama-swap— se reporta como `unknown` con el motivo, y **nunca** como `missing`.
  Un error de permisos también es `unknown`, no `missing`.
- **REQ-004:** El registro cubre los **once** elementos del andamiaje: hooks copiados, hooks
  registrados, skill, memoria (Claude y Codex), MCP en Claude, MCP en Codex, daemon, backend
  `/models`, `llama-swap`, `llama-server` y presencia de clientes.
- **REQ-005:** El check de hooks registrados distingue **los nuestros** de los del usuario reusando
  `install._is_ours`, no un criterio propio.
- **REQ-006:** Ningún `probe` exige red para dar un resultado útil: sin internet, los que consultan
  red devuelven `unknown` con el motivo y el resto sigue funcionando.
- **REQ-007:** Cada `probe` que habla por red o lanza un proceso tiene timeout acotado, y el
  diagnóstico completo termina en un tiempo comparable al `doctor` de hoy.

### El `doctor`

- **REQ-008:** `local-delegate doctor` reporta los once checks agrupados, conservando el estilo
  actual de salida (`[ ok ]`, `[warn]`, `[ -- ]`) y su semántica de exit code: **0** si no hay
  avisos, **1** si hay al menos uno.
- **REQ-009:** Un `missing` cuenta como aviso a efectos del exit code; un `unknown` **no**.
- **REQ-010:** Se conserva todo lo que el doctor ya hacía: `--config`, `--online`, la comparación
  contra `RECOMMENDED_VERSIONS` y los issues de GitHub. Ninguna salida existente desaparece.
- **REQ-011:** `--home DIR` permite diagnosticar contra un HOME simulado, sin tocar el real.
- **REQ-012:** Cuando un check está en `missing`, la salida dice **qué comando lo arregla**
  (típicamente `local-delegate install`), sin ejecutarlo.

### Límites

- **REQ-013:** `doctor` **no escribe nada** en disco ni en la configuración de ningún cliente. Se
  verifica comparando el árbol del HOME simulado antes y después, byte a byte.
- **REQ-014:** `install` y su comportamiento actual no cambian en este change.

## Acceptance scenarios

### Escenario: máquina completa (esta PC)

- **Dado** el andamiaje instalado y el daemon vivo en el 9393
- **Cuando** se ejecuta `local-delegate doctor`
- **Entonces** los checks de skill, hooks, memoria, MCP y daemon salen `ok`, el daemon muestra su
  versión y pid, y el exit code es 0 si el backend también está sano

### Escenario: HOME limpio

- **Dado** un HOME simulado vacío
- **Cuando** se ejecuta `local-delegate doctor --home <tmp>`
- **Entonces** los checks del andamiaje salen `missing` indicando `local-delegate install`, los de
  cliente salen `unknown` («no hay ~/.claude»), el exit code es 1, y **el HOME simulado queda
  exactamente igual que antes**

### Escenario: hook ajeno presente

- **Dado** un `settings.json` con un hook del usuario que no es nuestro
- **Cuando** se ejecuta el check de hooks registrados
- **Entonces** el hook ajeno no se cuenta como nuestro ni se reporta como problema

### Escenario: sin red

- **Dado** que PyPI y GitHub no responden
- **Cuando** se ejecuta `local-delegate doctor --online`
- **Entonces** los checks de red salen `unknown` con el motivo, los locales dan su resultado real, y
  el comando **no falla**

### Escenario: daemon caído

- **Dado** que nadie escucha en el 9393 pero la entrada MCP es de tipo HTTP
- **Cuando** se ejecuta `doctor`
- **Entonces** el check del daemon sale `missing` diciendo cómo levantarlo, y el exit code es 1

## Edge cases and failure behavior

- **Puerto ocupado por otro servicio:** `query_daemon` ya distingue «es nuestro daemon» de «alguien
  escucha»; el check debe reportar `warn` («el 9393 lo tiene otro proceso»), no `ok` ni `missing`.
- **Fichero ilegible por permisos:** `unknown` con el motivo (REQ-003).
- **`config.yaml` de llama-swap ausente:** `unknown`, como ya hace hoy `detect_llamaserver_version`.
- **Versión distinta de la probada:** `warn`, no `missing`: funciona, pero no es lo verificado.
- **Bloque de memoria editado a mano por el usuario:** si los marcadores están, es `ok`; el
  contenido de dentro no se compara literalmente, para no pelear con ediciones legítimas.

## Non-functional requirements

- **Sin dependencias nuevas.**
- **Simplicidad:** once checks son una lista de objetos con dos funciones, **no** un framework de
  plugins. Si aparece un registro dinámico o carga por entry points, el diseño se fue de las manos.
- **Seguridad:** ningún `probe` lee API keys ni secretos, ni los imprime. El diagnóstico no debe
  volcar rutas de credenciales ni contenido de `auth.json`.
- **Cobertura:** tests con `tmp_path` como HOME y dobles para red y procesos; ningún test lanza
  procesos reales ni sale a internet.

## Non-goals

- **No** se toca `install` (change C) ni se crea `update` (change B).
- **No** se arregla nada automáticamente: `doctor` solo mira. Los `fix` se declaran en el registro
  pero los consumen B y C.
- **No** se añaden clientes nuevos: hoy Claude Code y Codex.
- **No** se cambia `RECOMMENDED_VERSIONS` ni la política de versiones del backend.

## Traceability

| Req | Trabajo previsto | Verificación |
|---|---|---|
| REQ-001..007 | `checks.py`: registro y `probe`s | tests unitarios por check, con dobles |
| REQ-008..012 | `doctor.py`: consume el registro | ejecución real en esta PC y contra HOME simulado |
| REQ-013 | disciplina de solo lectura | comparación byte a byte del HOME simulado antes/después |
| REQ-014 | no tocar `install` | `tests/test_install.py` sigue verde sin cambios |
