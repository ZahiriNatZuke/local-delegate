# Specification: El hook de ruff usa el del proyecto y gitleaks sube a la ultima

## Summary

`.pre-commit-config.yaml` descargaba su propio ruff (**v0.6.9**) mientras el proyecto usa el del
lock (**0.16.0**). Las dos versiones formatean distinto —un `assert x == y, "mensaje largo"` es el
caso que se dio—, así que el hook reformatea, el `ruff format --check` del CI lo deshace y el
commit se aborta. Pasó dos veces el 2026-07-30.

**La causa no es que la versión esté vieja: es que hay dos fuentes de versión.** Subir el `rev` lo
arregla hoy y lo rompe otra vez en cuanto ruff suba en el lock — que es exactamente cómo llegó a
estar en 0.6.9. Así que el hook pasa a ejecutar el ruff **del entorno del proyecto**, y la clase de
problema desaparece por construcción.

De paso, `gitleaks` sube de `v8.18.4` a la última: un detector de secretos doce versiones menores
por detrás se pierde reglas nuevas.

## Requirements

- **REQ-001:** Los hooks de `ruff` y `ruff-format` ejecutan el ruff **del entorno del proyecto**,
  no uno descargado por `pre-commit`.
- **REQ-002:** No queda ninguna versión de ruff escrita en `.pre-commit-config.yaml`: la única
  fuente es `uv.lock`.
- **REQ-003:** Los hooks siguen aplicando las **mismas** operaciones que antes: `check --fix` y
  `format`, sobre ficheros Python.
- **REQ-004:** El hook de `gitleaks` queda en la última versión publicada.
- **REQ-005:** El fichero conserva su comentario de cabecera con la instrucción de instalación, y
  gana una nota que explique **por qué** los hooks de ruff son locales — para que nadie los
  «arregle» devolviéndolos al repo remoto.
- **REQ-006:** Correr `pre-commit run --all-files` deja el repositorio **sin cambios**: si el hook
  y el CI estuvieran desalineados, aquí se vería.

## Acceptance scenarios

### Scenario AC-1: el hook y el CI coinciden

- **Given** el repositorio limpio y `pre-commit` instalado
- **When** se ejecuta `pre-commit run --all-files`
- **Then** todos los hooks pasan y `git status` sigue limpio — o sea, el hook no reformatea nada
  que el `ruff format --check` del CI vaya a deshacer

### Scenario AC-2: el hook usa la versión del proyecto

- **Given** el entorno del proyecto con ruff `0.16.0`
- **When** se inspecciona qué ruff ejecuta el hook
- **Then** es el mismo binario que usa `uv run ruff`, y no hay ningún `rev` de ruff en el config

### Scenario AC-3: un commit real pasa por los hooks

- **Given** un cambio commiteable
- **When** se hace `git commit`
- **Then** los hooks corren y el commit se completa sin que ningún hook reescriba ficheros

## Edge cases and failure behavior

- **Entorno del proyecto sin sincronizar:** el hook fallará al no encontrar `uv`/`ruff`. Es
  aceptable y preferible al fallo silencioso actual: en este repositorio `uv sync` ya es requisito
  para cualquier cosa, y el mensaje de error dice qué falta.
- **`gitleaks` nuevo detecta algo que el viejo no:** sería un hallazgo legítimo, no una regresión;
  se atiende antes de commitear.

## Non-functional requirements

- **Sin dependencias nuevas:** ruff ya está en el grupo de desarrollo.
- **Portabilidad:** `language: system` con `uv run` funciona igual en los tres sistemas del CI.
- **Seguridad:** el cambio *refuerza* el escaneo de secretos (gitleaks al día) y no relaja nada.

## Non-goals

- Cambiar las reglas de ruff, su configuración o el conjunto de ficheros que analiza.
- Añadir hooks nuevos.
- Tocar el workflow del CI: sigue corriendo `ruff check .` y `ruff format --check .` como hasta
  ahora.

## Traceability

| Requisito | Trabajo previsto | Evidencia |
|---|---|---|
| REQ-001..REQ-003, REQ-005 | Reescribir el bloque de ruff como `repo: local` | `pre-commit run --all-files` + inspección del config |
| REQ-004 | Subir el `rev` de gitleaks | ejecución del hook |
| REQ-006 | — | `git status` limpio tras la ejecución |
