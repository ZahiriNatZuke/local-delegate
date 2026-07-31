# Specification: Borrar scripts/update_to_latest.sh, que el CLI sustituyo

## Summary

`scripts/update_to_latest.sh` quedó reducido a un envoltorio de tres líneas que delega en
`local-delegate update`. Se retira: mantener una segunda puerta de entrada al mismo comando tiene
un coste que no se ve —hay que acordarse de ella— y la vía documentada es el CLI desde el PR #70.

**Ojo con la premisa del pendiente:** decía «huérfano». No lo era. El fichero **documentaba su
propia razón de existir** (preservar el hábito de teclear `./scripts/update_to_latest.sh` en la
Mac) y su fallback a `python3 -m local_delegate` funciona — verificado. Se borra por decisión
explícita del usuario tomada con ese dato delante, no por estar muerto.

## Requirements

- **REQ-001:** `scripts/update_to_latest.sh` deja de existir en el repositorio.
- **REQ-002:** No queda ninguna referencia **viva** al script: las que lo nombran en pasado
  (`CHANGELOG.md`, `docs/wiki/Remote-backend.md`) son histórico y se conservan tal cual — borrar el
  fichero las hace más exactas, no menos.
- **REQ-003:** El `CHANGELOG.md` recoge la retirada bajo `Unreleased`, respetando su CRLF, y dice
  cuál es la vía que la sustituye.
- **REQ-004:** El CI sigue verde: ningún workflow ni test lo referencia.

## Acceptance scenarios

### Scenario AC-1: el fichero ya no está

- **Given** el repositorio tras el cambio
- **When** se busca `update_to_latest` en el árbol
- **Then** solo aparece en `CHANGELOG.md`, en `docs/wiki/Remote-backend.md` y en las trazas SDD,
  siempre en pasado, y **nunca** como un fichero ejecutable

### Scenario AC-2: la vía que lo sustituye funciona

- **Given** una máquina con el paquete instalado
- **When** se ejecuta `local-delegate update --dry-run`
- **Then** hace exactamente lo que hacía el envoltorio, que no tenía lógica propia

## Edge cases and failure behavior

- **Quien tenga el hábito de teclear la ruta** verá `No such file or directory`. Es el coste
  aceptado de la decisión; la wiki (`Remote-backend.md`) ya documenta `local-delegate update` como
  la vía, desde el PR #70.
- **Un clon viejo del repositorio** conserva su copia hasta que haga `git pull`. No hay nada que
  migrar: el script no guarda estado.

## Non-functional requirements

- **Sin impacto en el paquete publicado:** `scripts/` no viaja ni en el wheel ni en el sdist
  (`pyproject.toml:90`), así que ningún usuario instalado se ve afectado.
- **Sin impacto en el CI:** ningún workflow lo invoca (verificado con `grep` sobre `.github/`).
- **Sin impacto en los tests:** ninguno lo referencia.

## Non-goals

- Tocar `local-delegate update`, que es lo que lo sustituye.
- Tocar el resto de `scripts/`, que sigue siendo el taller del repositorio.
- Reescribir el histórico del `CHANGELOG.md`.

## Traceability

| Requisito | Trabajo previsto | Evidencia |
|---|---|---|
| REQ-001, REQ-002 | Borrar el fichero | `grep` sobre el árbol |
| REQ-003 | Entrada en el CHANGELOG | revisión del diff y conteo de CRLF |
| REQ-004 | — | los cuatro pasos del CI y los checks del PR |
