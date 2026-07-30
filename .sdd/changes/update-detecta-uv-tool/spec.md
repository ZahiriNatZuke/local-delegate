# Specification: update detecta el CLI instalado como uv tool y dice como actualizarlo

## Summary

`update` actualiza el pin, el andamiaje y el daemon, pero el ejecutable de `uv tool` se queda
donde estaba y nadie lo dice. A partir de ahora lo detecta y **da el comando exacto**, explicando
por qué no lo ejecuta él: probado en Windows, reinstalar el entorno desde el que corre el proceso
falla **y deja el CLI destruido**.

De paso, «cómo está instalado esto» pasa a tener **una sola definición** en el repo, que consumen
tanto este mensaje como el `fix_hint` del check `cli.published`.

## Requirements

### El modo de instalación, una sola vez

- **REQ-001:** Existe **una** función que responde cómo está instalado el paquete que se está
  ejecutando, con tres respuestas: instalación **editable**, instalación de **`uv tool`**, o
  **otra** (desconocida).
- **REQ-002:** La detección de `uv tool` se basa en la presencia de `uv-receipt.toml` en la raíz
  del entorno del proceso (`sys.prefix`), **no** en rutas concretas de cada sistema operativo ni
  en variables de entorno ni en ejecutar `uv`.
- **REQ-003:** La detección **nunca lanza**: cualquier fallo de lectura o de permisos se traduce a
  «otra», que es la respuesta prudente.
- **REQ-004:** La función responde por el proceso **que está corriendo**, y así se documenta: en
  una máquina pueden convivir la instalación de `uv tool` y una editable, y afirmar algo sobre la
  que no se está ejecutando sería un falso diagnóstico.
- **REQ-005:** El `fix_hint` del check `cli.published` consume esa misma función: `uv tool
  upgrade` **solo** cuando la instalación es de `uv tool`; el `git pull` + `uv sync` cuando es
  editable; y un texto genérico cuando no se reconoce, sin inventar un comando que podría no
  aplicar.

### El mensaje de `update`

- **REQ-006:** Cuando hay una versión publicada **más nueva** que la instalada y el CLI está
  instalado como `uv tool`, `update` lo dice, nombra la versión instalada y **da el comando
  exacto** `uv tool upgrade local-delegate-mcp`.
- **REQ-007:** El mensaje explica **por qué** `update` no lo hace él: reinstalaría el entorno
  desde el que se está ejecutando.
- **REQ-008:** Si no hay versión más nueva, **no aparece nada**: un aviso que sale siempre deja de
  leerse.
- **REQ-009:** El mensaje **no** cambia el plan de acciones ni el exit code; `update` sigue
  haciendo exactamente lo mismo.
- **REQ-010:** Sale por el `out` de `run_update`, no por `print`.
- **REQ-011:** Ni el mensaje ni el `fix_hint` usan caracteres fuera de cp1252.

### Documentación

- **REQ-012:** El `CHANGELOG.md` recoge el cambio bajo `Unreleased`, respetando su CRLF.
- **REQ-013:** Si la documentación publicada describe lo que hace `update`, se actualiza en el
  mismo cambio.

## Acceptance scenarios

### Scenario AC-1: instalado como `uv tool` y hay versión nueva

- **Given** un CLI instalado como `uv tool` en `0.17.0` y `0.18.0` publicada
- **When** se ejecuta `local-delegate update`
- **Then** la salida dice que está instalado como `uv tool`, nombra `0.17.0`, explica por qué
  `update` no puede actualizarlo y da `uv tool upgrade local-delegate-mcp`; el plan de acciones y
  el exit code son los mismos que sin el mensaje

### Scenario AC-2: instalado como `uv tool` y al día

- **Given** un CLI instalado como `uv tool` en la última versión publicada
- **When** se ejecuta `local-delegate update`
- **Then** no aparece ningún mensaje sobre `uv tool`

### Scenario AC-3: instalación editable

- **Given** un CLI servido desde un repo clonado en modo editable
- **When** se ejecuta `local-delegate update`
- **Then** se conserva el bloque actual de «Instalación EDITABLE» con `git pull` + `uv sync`, y
  **no** aparece el mensaje de `uv tool`

### Scenario AC-4: el `fix_hint` del `doctor` distingue los tres modos

- **Given** una instalación atrasada
- **When** se ejecuta `local-delegate doctor`
- **Then** la pista del check `cli.published` es `uv tool upgrade` si la instalación es de
  `uv tool`, `git pull` + `uv sync` si es editable, y un texto genérico si no se reconoce

## Edge cases and failure behavior

- **`uv-receipt.toml` ilegible o con TOML inválido:** se responde «otra». No saber no es motivo
  para afirmar.
- **`uv-receipt.toml` presente pero de otro paquete:** también «otra» — el entorno no es nuestro.
- **Instalación editable Y con receipt:** no puede darse en la práctica, pero si se diera, gana
  editable, que es lo que gobierna de dónde sale el código.
- **Versión instalada desconocida:** sin ella no hay comparación y no se emite el mensaje.
- **Sin red:** no hay versión publicada con la que comparar, así que no se emite el mensaje.

## Non-functional requirements

- **Sin subprocesos ni red:** la detección es una lectura de fichero local. `update` no gana ni
  una llamada nueva.
- **Portable:** nada de rutas de Windows, macOS ni Linux; el CI corre en los tres.
- **Sin dependencias nuevas:** el TOML se lee con `tomllib` (stdlib desde 3.11) o basta con
  comprobar la presencia del fichero y buscar el nombre del paquete.
- **Seguridad:** el repo **no ejecutará** el upgrade. Es la decisión que sale del experimento:
  hacerlo rompe la instalación del usuario.

## Non-goals

- Ejecutar el upgrade, en cualquiera de sus variantes.
- Reconocer `pipx`, `pip --user` o conda.
- Cambiar el pin, el andamiaje o el ciclo de vida del daemon.

## Traceability

| Requisito | Trabajo previsto | Evidencia |
|---|---|---|
| REQ-001..REQ-004 | Función de modo de instalación en `update.py` | tests con `sys.prefix` doblado |
| REQ-005 | `checks._upgrade_hint` consume la función | tests de los tres modos |
| REQ-006..REQ-011 | Mensaje en `run_update` | tests + ejecución real |
| REQ-012, REQ-013 | CHANGELOG y wiki | revisión del diff |
