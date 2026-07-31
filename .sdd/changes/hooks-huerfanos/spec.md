# Specification: Detectar y retirar los scripts de hooks huerfanos de instalaciones anteriores

## Summary

Las instalaciones anteriores dejaban los scripts de hooks sueltos en `~/.claude/hooks/`; la actual
los pone en `~/.claude/hooks/local-delegate/` y **nunca limpia los viejos**. `doctor` pasa a
detectarlos e `install` a retirarlos, con borrado **quirúrgico por nombre exacto**: nada más de esa
carpeta se toca.

## Requirements

### El check

- **REQ-001:** El registro `checks.CHECKS` incluye una comprobación con `id` `scaffold.hook_orphans`
  y `group` `andamiaje`.
- **REQ-002:** Reporta `WARN` con `fix_hint` no vacío si hay al menos un script **nuestro** suelto
  en la raíz de `~/.claude/hooks/`; `OK` si no hay ninguno; y `UNKNOWN` si Claude Code no está
  instalado o el directorio no se puede listar.
- **REQ-003:** El detalle dice **cuántos** son y **dónde** están.
- **REQ-004:** «Nuestro» se define como el conjunto de ficheros `.py` del directorio de recursos
  empaquetado (`resources/hooks/`), que es la definición de qué instalamos. **No** una lista
  paralela escrita a mano.
- **REQ-005:** El probe **no escribe** nada, como el resto del registro.
- **REQ-006:** Solo mira la **raíz** de `~/.claude/hooks/`: nunca el contenido de
  `hooks/local-delegate/`, que es la instalación buena.

### El retirado

- **REQ-007:** `install` planifica una acción que **borra únicamente** los ficheros nuestros
  sueltos en esa raíz, uno a uno y por nombre exacto.
- **REQ-008:** No se borra nada más: ni `telemetry.jsonl`, ni `__pycache__`, ni ficheros de
  terceros, ni el directorio `hooks/` ni el subdirectorio `local-delegate/`.
- **REQ-009:** La acción respeta `--dry-run`: con él **no se borra nada** y se anuncia lo que se
  haría.
- **REQ-010:** Si no hay huérfanos, **no se planifica ninguna acción** (idempotencia: reinstalar
  dos veces no genera trabajo la segunda).
- **REQ-011:** La acción se salta los ficheros que no se pueden borrar sin tumbar el resto del
  `install`.
- **REQ-012:** `update` lo repara también, mediante una entrada en su tabla `REPAIRS`, en el
  estado `WARN` — que aquí significa «es nuestro y sobra», igual que los otros dos casos que
  reparan en `warn`.

### Coherencia y documentación

- **REQ-013:** Los cuatro sitios de `checks.py` que dicen el tamaño del registro pasan a decir
  «catorce».
- **REQ-014:** El `CHANGELOG.md` recoge el cambio bajo `Unreleased`, respetando su CRLF.
- **REQ-015:** La tabla de comprobaciones de `docs/wiki/Integration-install.md` incorpora la fila
  nueva y su cuenta.

## Acceptance scenarios

### Scenario AC-1: máquina con huérfanos

- **Given** un `~/.claude/hooks/` con `hook_common.py`, `suggest_delegate_prompt.py`,
  `suggest_delegate_read.py` y `suggest_lint_summary.py` sueltos, más `local-delegate/` correcto
- **When** se ejecuta `local-delegate doctor`
- **Then** aparece `[WARN]` diciendo cuántos son y dónde, con la pista `local-delegate install`

### Scenario AC-2: `install` los retira y no toca nada más

- **Given** esa misma carpeta, con además `telemetry.jsonl`, `__pycache__/` y un
  `hook_de_terceros.py`
- **When** se ejecuta `local-delegate install`
- **Then** los cuatro nuestros desaparecen, y `telemetry.jsonl`, `__pycache__/`,
  `hook_de_terceros.py` y todo `local-delegate/` **siguen ahí, byte a byte iguales**

### Scenario AC-3: `--dry-run` no borra

- **Given** una carpeta con huérfanos
- **When** se ejecuta `local-delegate install --dry-run`
- **Then** se anuncia el retirado y el árbol queda **byte a byte idéntico**

### Scenario AC-4: máquina limpia

- **Given** un `~/.claude/hooks/` con solo `local-delegate/` dentro
- **When** se ejecutan `doctor` e `install`
- **Then** el check es `[ OK ]` y no se planifica ninguna acción de retirado

## Edge cases and failure behavior

- **Claude Code no instalado / directorio ilegible:** `UNKNOWN`, nunca `MISSING` ni `WARN`. No
  saber no autoriza a borrar.
- **Un fichero nuestro que no se puede borrar** (permisos, en uso): se salta, se reporta, y el
  resto del `install` continúa.
- **Un *directorio* con el nombre de uno de nuestros scripts:** no se toca. Solo se borran
  ficheros.
- **`hooks/local-delegate/` ausente:** irrelevante para este check; de eso ya se ocupa
  `scaffold.hook_files`.

## Non-functional requirements

- **Seguridad:** es la operación más destructiva del repo. Borrado por nombre exacto, solo en la
  raíz, solo ficheros, y con la lista derivada de lo que el propio paquete instala.
- **Idempotencia:** segunda pasada sin trabajo.
- **Portabilidad:** sin rutas ni comportamientos específicos de plataforma.
- **Sin dependencias nuevas.**

## Non-goals

- Borrar el directorio de hooks o su contenido en bloque.
- Tocar `telemetry.jsonl` (el backlog quiere **encender** esa telemetría, no borrarla).
- Limpiar `__pycache__`.
- Desregistrar entradas de `settings.json`: eso ya lo hace `merge_hook_settings`, y se comprobó
  que funciona — **no hay entradas duplicadas**, al contrario de lo que decía el pendiente.

## Traceability

| Requisito | Trabajo previsto | Evidencia |
|---|---|---|
| REQ-001..REQ-006 | Probe nuevo en `checks.py` | tests de los tres estados + test de no-escritura |
| REQ-007..REQ-011 | Acción de retirado en `install.py` | tests de borrado quirúrgico y de `--dry-run` |
| REQ-012 | Entrada en `REPAIRS` | test de `plan_repairs` |
| REQ-013..REQ-015 | Textos, CHANGELOG y wiki | revisión del diff y test del tamaño |
