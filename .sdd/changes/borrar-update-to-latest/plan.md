# Implementation plan: Borrar scripts/update_to_latest.sh, que el CLI sustituyo

## Approach

Un `git rm` y una entrada de CHANGELOG. El plan es corto porque el trabajo lo es, y el research ya
descartó todo lo que podía complicarlo: sin referencias vivas, sin tests, sin workflows y sin
impacto en el paquete publicado.

Lo único que merece cuidado es **qué no se toca**: las tres menciones que quedan hablan del script
en pasado y son histórico. Reescribirlas sería falsificar el registro de por qué el repositorio
llegó a su regla actual —«lo que ejecuta el usuario va al CLI»—, que nació precisamente de este
fichero.

## Ordered tasks

### 1. Borrar el fichero

- **Ficheros:** `scripts/update_to_latest.sh`
- **Requisitos:** REQ-001, REQ-002
- **Qué:** `git rm scripts/update_to_latest.sh`.
- **Verificación:** `grep -rn "update_to_latest"` sobre el árbol, comprobando que lo que queda son
  las menciones en pasado y las trazas SDD.
- **Rollback:** `git revert`; el fichero queda en el histórico.

### 2. CHANGELOG

- **Ficheros:** `CHANGELOG.md`
- **Requisitos:** REQ-003
- **Qué:** entrada bajo `Unreleased` → `Removed` (crear la sección si no existe), diciendo qué lo
  sustituye.
- **Cuidado:** CRLF.

### 3. CI local

- **Requisitos:** REQ-004
- **Qué:** los cuatro pasos, para descartar que algo dependiera del fichero sin que el `grep` lo
  viera.

## Test strategy

- **Unit / Integration:** no aplica — se retira un fichero que no importa nadie.
- **End-to-end:** `local-delegate update --dry-run` sigue funcionando, que es la vía que lo
  sustituye. Ya se ejecutó en el change `update-version-de-donde` y se repite aquí.
- **Verificación al revés:** no aplica: no hay comportamiento que romper para ver si algún test lo
  detecta. Lo equivalente es el `grep` sobre el árbol y el CI verde.
- **Seguridad:** se retira un fichero ejecutable del repositorio; el cambio reduce superficie, no
  la amplía.

## Migration and compatibility

- **Nada que migrar.** El script no guardaba estado ni tenía lógica propia.
- **Quien tenga el hábito** verá `No such file or directory`. Coste aceptado; la wiki documenta la
  vía buena desde el PR #70.

## Revisión adversarial del plan

Dos hallazgos, los dos incorporados.

- **R-1 — la tentación de «actualizar» las menciones en pasado.** `CHANGELOG.md:86`,
  `CHANGELOG.md:450` y `docs/wiki/Remote-backend.md:98` nombran el script para explicar de dónde
  salió la regla del repositorio. Tocarlas al borrar el fichero sería borrar el porqué junto con
  la cosa, y ese porqué es lo que impide que alguien vuelva a poner un instalador en `scripts/`.
  **No se tocan**, y queda escrito.
- **R-2 — el `grep` de verificación tiene que excluir `.sdd/`.** Las trazas de changes anteriores
  lo mencionan y siempre lo harán; si no se excluyen, la comprobación de «no quedan referencias»
  daría un falso positivo permanente y no se podría cerrar nunca.

## Plan review

- [x] Cada requisito mapea a una tarea y a una verificación.
- [x] La operación destructiva —borrar un fichero versionado— es reversible con `git revert` y el
      contenido queda en el histórico.
- [x] Sin dependencias ni configuración nuevas.
- [x] Sin trabajo ajeno: no se toca `local-delegate update` ni el resto de `scripts/`.
