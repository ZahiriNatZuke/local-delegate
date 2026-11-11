# Brief: Panel: desglose y filtro por proyecto con nombres locales; fuera el conmutador del propio repo

## Problem

The 0.51.0 dashboard has an «own repo» switch that hides by default what the local-delegate repo
itself delegated. It only serves whoever develops the MCP; for every other user it is noise. What
is missing is the opposite: seeing which repository delegated most and filtering the panel by one.

## Desired outcome

The panel shows everything by default, has a «By project» card (delegations and saving per repo,
most first) and a project selector in the filter bar that filters every card, chart and table.
Names come from a local map `LOG_DIR/project-names.json`, never from the usage log.

## In scope

- Remove the switch, its dialog, its i18n keys, `include_self` and its counters from the API, and
  the own-repo line of `local_status`.
- `project-names.json`: written in `hook_common.project_fields`, atomic, locked, capped.
- Backfill of names for 0.51.0 rows (coordinator addition, 2026-11-11): from the directory names
  under the process's `~/.claude/projects`, lazily on the dashboard's first read.
- `?project=` on `/api/stats`, `/api/events`, `/api/hooks`; `by_project` in `/api/stats`.
- Docs (CHANGELOG, README, wiki) and tests; screenshots light and dark.

## Out of scope

- `scripts/measure_*.py` keep excluding the own repo; `caller_project_kind` and
  `self-projects.json` stay for them.
- Regenerating `docs/assets/dashboard*.png` (release step).

## Constraints and risks

- Folder names are untrusted text: XSS in the panel.
- Several processes write the map at once (daemon threads, stdio server, hooks, recompute-cost).
- Public repo: the usage log is the evidence of public issues and must stay without names.
- The hooks' hot path: recording a name must not slow or break a hook or a tool.

## Open questions

- None: the user's decisions are fixed in the request.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-11 Original request, verbatim:

  > Rehacer en el panel de local-delegate lo del «propio repo». Decisiones del usuario: 1. Quitar del panel el conmutador «Propio repo» y el apartado por defecto del propio repo (metrics.py, JS/HTML del panel, /api/* que lo acepten, i18n panel.json es/en, wiki y README). Por defecto el panel muestra todo. Las mediciones de adopción de scripts/measure_*.py SÍ siguen apartando el propio repo: no las rompas. Decide con criterio si caller_project_kind sigue haciendo falta en el log para esos scripts y si local_status/server.py mencionan el propio repo de cara al usuario (en ese caso, quítalo de lo visible). 2. Nombres legibles con un mapa local aparte: fichero LOG_DIR/project-names.json que traduce hash → nombre de la carpeta del proyecto (el mismo nombre que entra en el hash). Se escribe en el mismo sitio y momento en que se calcula el hash (mismo proceso, misma LOG_DIR del entorno del proceso, regla D12), de forma atómica y sin carreras entre daemon e hilos; nunca sale de la máquina; el log de uso sigue SIN nombres. Si el mapa falta o no tiene un hash, el panel muestra «proyecto sin nombre» (catalogado es/en). Tope de tamaño razonable del mapa. Cuida que el nombre se escape en el HTML/JS del panel (XSS). 3. Panel: un desglose «por proyecto» (delegaciones y ahorro por repo, de mayor a menor) y un filtro de proyecto que filtra todo el panel (las tarjetas, gráficos y tablas existentes), en la misma barra de filtros que ya hay. Filas viejas sin proyecto: grupo «sin proyecto». Pruebas: tests de API y de UI del panel, escape de nombres hostiles, mapa ausente/corrupto, concurrencia de escritura del mapa. Capturas en claro y oscuro.
- L2 2026-11-11 Implementation done in the same session before the spec and plan gates were
  written down (recorded deviation: the decisions were all fixed by the user, so the spec was
  written from the request and the code at hand); then the coordinator added the backfill of
  names for 0.51.0 rows. Remaining: plan review, verification, result and security review, PR.
- L3 2026-11-11 Reviews, full suite and gates done; PR #661 opened, not merged. Remaining: live
  check by the coordinator and merge.
- L4 2026-11-11 Revision on the same PR after the coordinator saw the screenshots: readable
  label from the real path (REQ-018, E11). The SDD state machine cannot reopen a closed change,
  so the revision is recorded here, in the spec, plan, verification and review.
