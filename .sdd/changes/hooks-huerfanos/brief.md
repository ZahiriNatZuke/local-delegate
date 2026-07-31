# Brief: Detectar y retirar los scripts de hooks huerfanos de instalaciones anteriores

## Problem

Las instalaciones anteriores dejaban los scripts de hooks **sueltos en `~/.claude/hooks/`**,
mientras que la versión actual los pone en `~/.claude/hooks/local-delegate/`. Al reinstalar, los
nuevos se copian al subdirectorio y **los viejos se quedan ahí para siempre**: `install` solo hace
`rmtree` de `hooks/local-delegate/` (`install.py:385`), nunca de la raíz.

**Esta máquina es el caso**, verificado en vivo:

```
~/.claude/hooks/
  hook_common.py                <-- nuestro, huérfano
  suggest_delegate_prompt.py    <-- nuestro, huérfano
  suggest_delegate_read.py      <-- nuestro, huérfano
  suggest_lint_summary.py       <-- nuestro, huérfano
  local-delegate/               <-- la instalación actual, correcta
  telemetry.jsonl               <-- DATO DEL USUARIO
  __pycache__/
```

## El pendiente estaba mal diagnosticado a medias

El backlog decía que quien corriera el instalador de macOS retirado en el PR #69 «los tiene por
duplicado **y registrados dos veces**». La segunda mitad es **falsa**, y se comprobó ejecutando
contra el `settings.json` real de esta máquina —que tiene el caso—: hay **2** entradas nuestras,
las dos correctas, apuntando a `local-delegate/`. **Cero duplicados.**

El motivo está en el código de los dos instaladores, y coinciden:

- `install._is_ours()` (`install.py:215-230`) reconoce el formato heredado **por el nombre exacto
  del script** (`_SCRIPT_NAMES`), no solo por la ruta, y `merge_hook_settings` lo usa para quitar
  cualquier versión previa antes de registrar.
- El `.sh` retirado hacía lo mismo por su lado: su `existing_entries()` filtraba las entradas que
  mencionaran uno de los tres nombres, en `command` **o** en `args`.

Así que ninguno de los dos duplica registros: se reemplazan mutuamente. **Lo que nadie limpia son
los ficheros en disco.**

Y el origen tampoco es solo el `.sh` de macOS: esta máquina es Windows, así que aquí los dejó una
versión anterior del propio `install`. El problema es más general que el que describía el
pendiente, y la solución debe serlo también.

## Desired outcome

- `doctor` los detecta y los reporta como `[WARN]`, con la pista de qué comando los retira.
- `install` (y `update`, por la tabla `REPAIRS`) los retiran.
- **Nada más se toca:** `telemetry.jsonl`, `__pycache__` y cualquier hook de terceros quedan
  intactos.

## In scope

- Un check nuevo del registro, grupo `andamiaje`.
- El retirado en `install`, con la misma mecánica de acción que el resto (plan → apply, con
  `--dry-run` honesto).
- La entrada correspondiente en la tabla `REPAIRS` de `update`.

## Out of scope

- **Borrar el directorio `~/.claude/hooks/` o su contenido en bloque.** El borrado es quirúrgico y
  por nombre exacto.
- Tocar `telemetry.jsonl` — es dato del usuario, y además el backlog quiere **encender** esa
  telemetría, no borrarla.
- Tocar `__pycache__` (ni el de la raíz ni ninguno).
- Migrar nada: los hooks actuales ya están donde deben.

## Constraints and risks

- **Riesgo principal: borrar un fichero que no es nuestro.** Es la operación más destructiva que
  ha entrado en este repo. Mitigación: la lista de nombres sale del **directorio de recursos
  empaquetado** (`resources/hooks/*.py`), que es la definición de «qué instalamos nosotros», y no
  de una constante paralela que se desincronice. `_SCRIPT_NAMES` no sirve: tiene tres nombres y no
  incluye `hook_common.py`, que también quedó huérfano.
- **Nunca borrar dentro de `hooks/local-delegate/`**, que es la instalación buena. Solo la raíz.
- **`__pycache__` de la raíz puede contener los `.pyc` de los huérfanos**, pero borrarlo tocaría
  también los de un hook de terceros que viva ahí. Se deja.
- **La regla del registro:** `probe` mira y **no escribe**; quien escribe es `install`/`update`.
  Un probe que borre rompería el contrato que sostiene los tres verbos.
- **`unknown`, nunca `missing`:** si el directorio no se puede listar, no se afirma que haya
  huérfanos.

## Open questions

- ~~¿Solo avisar o también limpiar?~~ **Resuelto por el usuario:** avisar y que `install` los
  limpie, con borrado quirúrgico por nombre exacto.
