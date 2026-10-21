# Investigación — síntesis y decisiones

Fuentes: `research-code.md` (código interno) y `research-upgrade.md` (instalaciones y docs).

## Hechos

- Las 11 entradas de `DEPRECATED_NAMES` vencen en la 0.38.0: subcomando `recalcular-coste`, opción
  `--reiniciar-calibracion`, 4 variables (`LD_HOOK_READ_BLOQUEAR`, `LD_HOOK_READ_INTERRUPTOR`,
  `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO`, `LOCAL_DELEGATE_COSTE_RESPALDO`), el fichero interruptor
  viejo, la doble escritura de `enfriamiento.json` (todos `introduced` 0.35.0) y las 3 `_FAST`
  (`warn_until` 0.37.0).
- El guardián de horizonte lee `pyproject.toml` (0.37.0 hasta el bump): **no** comprueba este SDD.
  Falta un test que mida el registro real contra `"0.38.0"`.
- `scripts/bump_version.py:213-227` (`stamp_unreleased`) falla con `BumpError` si el registro queda
  `= ()` en una línea.
- Ninguna versión publicada escribió nombres viejos por su cuenta en configuración de clientes; los
  ponía el usuario a mano siguiendo la doc de la 0.34. Hook y skill viejos ya se retiran solos con
  `install`/`update` (`install.py:113-126`).
- Borrar sin más deja **fallos mudos**: el check de `doctor` y las notas de `update` se construyen
  desde `DEPRECATED_NAMES` (`checks.py:1892-1953`, `update.py:345-351`). Con la variable vieja del
  bloqueo puesta, el bloqueo se apaga sin aviso; con el interruptor viejo creado, el bloqueo se
  enciende aunque el usuario lo apagó. La Mac (0.34) salta directa a la 0.38 sin haber visto avisos.
- Esta PC ya usa solo nombres nuevos: nada que cambiar aquí.
- La lectura de ficheros de datos viejos (`cooldown._load`, `hook_common.cooled_model`, tablas de
  `legacy_names`), los temporales de hooks y `cuota-statusline.jsonl` **no tienen plazo** (REQ-006,
  REQ-008, REQ-012 del SDD anterior; tabla de la `[0.35.0]` del CHANGELOG). La nota
  `waves/A5b-2.md:127` que hablaba de retirar la de `coste-agregados.json` contradice el plan
  aprobado: manda el plan.

## Decisiones (de la sesión principal, para la spec)

- **D1.** Se borran del todo, con su código muerto: las 3 `_FAST` y la doble escritura de
  `enfriamiento.json` (`_write_legacy`, `legacy_write_enabled`, `old_keys`,
  `RETIRED_FAST_ROLE_VARIABLES`…). Los hooks de la 0.34 que sigan sin `update` dejan de ver el
  enfriamiento: se documenta («corre `update`»).
- **D2.** Los otros 7 nombres pasan a **retirados con sucesor**: dejan de tener efecto en la 0.38.0
  pero el registro conserva el nombre nuevo (campo tipo `retired_from`/`new`), y `doctor` (y donde
  hoy avise, `local_status`/`update`) dicen «X ya no tiene efecto desde la 0.38.0: usa Y», con
  `warn_until="0.40.0"` (avisa en 0.38.x, 0.39.x y 0.40.x). Cambia la regla de clases de
  `deprecations.py` (hoy un retirado no tiene `new`): la spec lo hace explícito.
- **D3.** El CLI reconoce el subcomando y la opción viejos **antes** de argparse y sale con código 2
  y un mensaje i18n que nombra el nuevo (hoy daría el error genérico de argparse).
- **D4.** `update` (y `install`) migran lo que el usuario dejó a mano en lo que el paquete ya
  gestiona: claves viejas del `env` de `~/.claude/settings.json` → nombre nuevo si el nuevo no
  existe (si existen los dos, quita el viejo), y el fichero interruptor viejo → nuevo si el nuevo no
  existe. Con copia de seguridad y `--dry-run` como el resto de `update`. **No** toca variables de
  entorno del sistema, perfiles del shell ni el lanzador: de eso avisa `doctor`.
- **D5.** La lectura dual de ficheros de datos se queda (sin plazo).
- **D6.** Test nuevo de horizonte contra `"0.38.0"` con el registro real; `bump_version` aguanta un
  registro sin `UNRELEASED` en cualquier formato.
- **D7.** CHANGELOG `[Unreleased]` con marca de incompatible, «Lo que rompe y cómo actualizar» al
  estilo de la retirada de `fast` (0.30.0); README y wiki según `research-upgrade.md` §3; tabla de
  checks de `Integration-install.md` atada a su test.
- **Fuera de alcance:** `lanzar-tanda-afinidad.ps1:30` usa `LOCAL_DELEGATE_COMMIT_IDIOMA`, que nunca
  existió → backlog.
