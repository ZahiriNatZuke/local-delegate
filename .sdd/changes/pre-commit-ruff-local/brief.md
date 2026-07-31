# Brief: El hook de ruff usa el del proyecto y gitleaks sube a la ultima

## Problem

`.pre-commit-config.yaml` descargaba su propio ruff (`rev: v0.6.9`) mientras el proyecto usa el
del lock. Las dos versiones formatean distinto un `assert x == y, "mensaje largo"`, así que el
hook reformatea, el `ruff format --check` del CI lo deshace y el commit se aborta. Pasó dos veces
el 2026-07-30.

Medido antes de tocar nada:

| Dónde | Versión |
|---|---|
| `uv.lock` y `uv run ruff --version` | **0.16.0** |
| `.pre-commit-config.yaml` | **v0.6.9** |
| última de `ruff-pre-commit` | v0.16.1 (publicada el 2026-07-30) |
| `gitleaks` en el config / última | v8.18.4 / **v8.30.1** |

## Desired outcome

El hook y el CI no pueden discrepar, y la próxima subida de ruff no exige acordarse de este
fichero.

## In scope

- Los hooks de `ruff` y `ruff-format`, que pasan a locales y ejecutan el ruff del entorno.
- El `rev` de `gitleaks`, que sube a la última.
- El comentario que explica la asimetría entre los dos bloques.

## Out of scope

- Reglas de ruff, su configuración o el conjunto de ficheros que analiza.
- Hooks nuevos.
- El workflow del CI, que sigue igual.

## Constraints and risks

- **El pendiente pedía «subir el `rev`», y eso arregla el síntoma, no la causa.** La causa es
  tener **dos** fuentes de versión: subirlo funcionaría hoy y se rompería el día que ruff suba en
  el lock, que es exactamente cómo se llegó a 0.6.9. Ni siquiera casarlo con la última sería
  correcto —hoy sería v0.16.1 contra el 0.16.0 del lock—: habría que casarlo con el lock **y
  repetirlo en cada subida**.
- **`uv run` dentro de un hook de git depende de que `uv` esté en el PATH.** En un cliente gráfico
  que no herede el PATH interactivo fallaría — pero con un mensaje que dice qué pasa, a diferencia
  del fallo actual, que reformatea en silencio.
- **Un `gitleaks` doce versiones menores por detrás** se pierde reglas de detección nuevas; es un
  riesgo de seguridad pequeño pero real, y está en el mismo fichero.

## Open questions

- ~~¿Subir el `rev` o resolver la causa?~~ **Resuelto por el usuario:** hooks locales.
- ~~¿Subir también `gitleaks`?~~ **Resuelto por el usuario:** sí, en el mismo cambio.
