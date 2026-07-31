# Handoff: El hook de ruff usa el del proyecto y gitleaks sube a la ultima

## Current state

- **SDD status:** cerrado.
- **Último gate:** `memory`.
- **Revisión:** PR **#80** mergeado el 2026-07-30, `main` en `a0a061e`. Los 12 checks del PR y el
  CI completo de `main` en verde. **En `Unreleased`, sin publicar** (solo desarrollo: el fichero
  no viaja en el paquete).

## What changed

Los hooks de `ruff` en `pre-commit` pasan a `repo: local` con `entry: uv run ruff …`, así que
ejecutan el ruff del entorno del proyecto. `gitleaks` sube de `v8.18.4` a `v8.30.1`.

## Decisions

1. **No se subió el `rev`, que era lo que pedía el pendiente.** Eso arregla el síntoma y no la
   causa: la causa es tener **dos** fuentes de versión, y subirlo se rompería el día que ruff suba
   en el lock — que es exactamente cómo se llegó a 0.6.9. Ni casarlo con la última valdría: hoy
   sería `v0.16.1` contra el `0.16.0` del lock.
2. **`gitleaks` conserva su `rev` remoto, y es deliberado.** Es un binario ajeno al proyecto, no
   una dependencia suya; ahí fijar la versión sí tiene sentido. La asimetría entre los dos bloques
   está explicada **en el propio fichero**, con el bug que la originó, para que nadie la
   «arregle».
3. **El CI no usa `pre-commit`** (corre `ruff` directamente), así que el riesgo de este cambio se
   limita a la máquina de quien commitea.

## Gotchas

- **`uv run` dentro de un hook de git depende de que `uv` esté en el PATH**, y los hooks no
  siempre heredan el PATH interactivo (caso clásico: un cliente gráfico de git). Si falla, dirá
  «uv: command not found» — que al menos explica el problema, a diferencia del fallo anterior, que
  reformateaba en silencio.
- **`run --all-files` y un commit no ejercitan lo mismo:** el primero pasa todos los ficheros, el
  segundo solo los staged. Hay que probar los dos. Se vio en vivo: al commitear solo Markdown, los
  hooks de ruff salieron `(no files to check) Skipped`, que es el `types_or` funcionando.

## Next action

Siguiente del backlog: punto 6, borrar `scripts/update_to_latest.sh`, huérfano desde que
`local-delegate update` lo sustituyó y la wiki dejó de mencionarlo (PR #70).

**Pendiente operativo de antes:** los cuatro hooks huérfanos siguen en `~/.claude/hooks/` de esta
máquina; se limpian con `local-delegate install`, pendiente de autorización porque borra ficheros
del HOME real.

## Memory

- **Nota canónica:** pendiente de la nota de jornada en el vault (`projects/local-delegate/`).
- **Índices actualizados:** `CHANGELOG.md`, sección `Changed` con la marca «(solo desarrollo)».
- Sin secretos, credenciales ni datos personales.
