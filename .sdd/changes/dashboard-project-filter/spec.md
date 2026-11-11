# Specification: Panel: desglose y filtro por proyecto con nombres locales; fuera el conmutador del propio repo

## Summary

The dashboard shows every project by default, breaks the delegations and the saving down per
project, and filters the whole panel by one project. Readable names come from a local map in
`LOG_DIR`, never from the usage log. The own-repo switch of 0.51.0 disappears from the panel, the
API and `local_status`; the measurement scripts keep excluding the own repo.

## Decisions

- **E1 — The filter is a hash or `none`.** `?project=` accepts a 16-hex hash or `none`; any other
  value filters nothing. Reason: the panel only ever sends what `by_project` gave it.
- **E2 — `by_project` ignores the project filter.** It is what the selector offers; it follows the
  tests switch like every other figure.
- **E3 — The map is written in `project_fields`.** It is the one place where the hash exists with
  its name, in the same process and `LOG_DIR` (D12). Best effort: a busy lock or a full map writes
  nothing and never fails the caller.
- **E4 — `caller_project_kind` stays in the log.** The measurement scripts need it.
- **E5 — The backfill runs lazily in the dashboard**, on the first read that sees a hash without a
  name, once per hash and process; not at daemon start (no cost when nobody opens the panel).
- **E6 — The filter is not remembered** across reloads: the panel always opens with everything.
- **E7 — The displayed name is the raw directory name** (e.g. `D--work-shop`), the same text that
  enters the hash.
- **E8 — What the filter does not reach.** The quota, `/api/inflight`, the system and backend
  cards, `open_test_windows` and the tests counters (`excluded_tests`, `tests_in_range`) do not
  follow the project filter: none of them is computed from the rows of one project (the tests
  counters describe the whole range, as before). Documented in the wiki.
- **E9 — A panel published on the network shows the names** to whoever opens it with the
  token, as it already shows the paths of `/api/events`; the map itself never travels. Accepted
  and documented: the viewer is the user.
- **E10 — `session=` gets no breakdown.** `/api/stats?session=` (the mod's status line) returns
  `by_project: []` and neither reads nor backfills the map, so nothing is spent on it when
  nobody opens the panel (E5).

## Requirements

- **REQ-001** — The panel has no «Propio repo» switch, dialog or `ld-self`; with no parameter the
  three requests carry no project filter and every row counts, the own repo included.
  - Request: "Quitar del panel el conmutador «Propio repo» y el apartado por defecto del propio repo"
  - Verify: test tests/test_metrics_project_filter.py and tests/test_dashboard_project_filter.py
- **REQ-002** — `/api/stats`, `/api/events` and `/api/hooks` ignore `include_self` and no longer
  return `excluded_self`, `self_in_range` or `unknown_project`.
  - Request: "/api/* que lo acepten"
  - Verify: test tests/test_metrics_project_filter.py
- **REQ-003** — `?project=<hash>` keeps only that project's rows and `?project=none` the rows
  without a valid hash, in the three endpoints with the same set; another value filters nothing;
  each answer says the applied filter in `project`.
  - Request: "un filtro de proyecto que filtra todo el panel"
  - Verify: test tests/test_metrics_project_filter.py
- **REQ-004** — The cost equivalent follows the project filter; `?session=` gives the session's
  figures whatever its project.
  - Request: derived: a cost of every project beside KPIs of one would contradict them; the mod's status line must keep working
  - Verify: test tests/test_metrics_project_filter.py
- **REQ-005** — `/api/stats.by_project` lists `project`, `name`, `calls`, `tokens_saved` and
  `tokens_net` per project, most delegations first; it ignores the project filter, follows the
  tests switch, and its sums equal the totals; with `session=` it is empty (E10).
  - Request: "un desglose «por proyecto» (delegaciones y ahorro por repo, de mayor a menor)"
  - Verify: test tests/test_metrics_project_filter.py
- **REQ-006** — `hook_common.project_fields` records `hash → directory name` in
  `<LOG_DIR>/project-names.json`, where LOG_DIR is the one it is given or the process's, never one
  a request names; without a salt it records nothing; the returned fields never carry the name.
  - Request: "Se escribe en el mismo sitio y momento en que se calcula el hash (mismo proceso, misma LOG_DIR del entorno del proceso, regla D12)"
  - Verify: test tests/test_project_names.py and tests/test_project_privacy.py
- **REQ-007** — The map is replaced whole (temporary file and `os.replace`) under a thread lock
  and a file lock: with several threads and several processes writing, it stays valid JSON and no
  name a writer reported as written is lost.
  - Request: "de forma atómica y sin carreras entre daemon e hilos"
  - Verify: test tests/test_project_names.py
- **REQ-008** — A missing, unreadable, corrupt or too big (over 512 KiB) map reads as empty
  without error and the next write repairs it; entries with a bad hash or a bad name are dropped;
  at most 1000 entries; a name with control characters, empty, `.`/`..` or over 255 characters is
  not recorded.
  - Request: "Tope de tamaño razonable del mapa" and "mapa ausente/corrupto"
  - Verify: test tests/test_project_names.py and tests/test_metrics_project_filter.py
- **REQ-009** — The project's name appears only in `project-names.json` and in
  `by_project[].name`: never in a usage row, the backfill, the hook telemetry, `local_status`,
  `/api/events`, `/api/hooks` or any other field of `/api/stats`.
  - Request: "nunca sale de la máquina; el log de uso sigue SIN nombres"
  - Verify: test tests/test_project_privacy.py
- **REQ-010** — The panel shows «Proyecto sin nombre» / «Unnamed project» for a hash without a
  name and «Sin proyecto» / «No project» for the rows without a project, from the i18n catalog.
  - Request: "el panel muestra «proyecto sin nombre» (catalogado es/en)" and "Filas viejas sin proyecto: grupo «sin proyecto»"
  - Verify: test tests/test_dashboard_project_filter.py
- **REQ-011** — A hostile name reaches the card escaped (no live markup) and the selector as text.
  - Request: "Cuida que el nombre se escape en el HTML/JS del panel (XSS)"
  - Verify: test tests/test_dashboard_project_filter.py
- **REQ-012** — The selector sits in the existing filter bar; choosing a project makes the three
  requests carry `project=` and the activity table, cards and charts show only its rows; the
  chosen project stays an option when the range has none of its rows; reloading shows everything.
  - Request: "en la misma barra de filtros que ya hay"
  - Verify: test tests/test_dashboard_project_filter.py
- **REQ-013** — `local_status` no longer mentions the own repo; its month figures do not change.
  - Request: "si local_status/server.py mencionan el propio repo de cara al usuario (en ese caso, quítalo de lo visible)"
  - Verify: test tests/test_status_own_repo.py
- **REQ-014** — `scripts/measure_adoption.py` and `scripts/measure_plugin_adoption.py` keep
  excluding the own repo by default; the log keeps `caller_project_kind`.
  - Request: "Las mediciones de adopción de scripts/measure_*.py SÍ siguen apartando el propio repo: no las rompas"
  - Verify: test tests/test_measure_adoption_own_repo.py and tests/test_measure_plugin_adoption_own_repo.py
- **REQ-015** — `hook_common.backfill_project_names` names the hashes the map lacks from the
  directory NAMES right under the process's projects root, with the local salt and the same name
  `project_fields` would record; it never reads a transcript, never creates a salt (none: nothing),
  stops at 5000 directories or 0.5 s, writes once under the lock and never raises. The dashboard
  calls it once per missing hash and process, and again after an incomplete pass (busy lock,
  spent budget or cap); a writer never replaces a map it could not read.
  - Request: derived: coordinator addition 2026-11-11, «relleno de las filas que ya existen»
  - Verify: test tests/test_project_names.py and tests/test_metrics_project_filter.py
- **REQ-016** — CHANGELOG (Unreleased), README and `docs/wiki/` describe the filter, the map and
  the removal, without dead anchors to the old section.
  - Request: "wiki y README"
  - Verify: review diff of CHANGELOG.md, README.md and docs/
- **REQ-017** — Screenshots of the panel with test data in light and dark mode, served by the
  metrics app on a test port, show the card and the selector legibly.
  - Request: "Capturas en claro y oscuro"
  - Verify: manual screenshots in the scratchpad

## Acceptance scenarios

### Scenario: user with two projects opens the panel

- **Given** a usage log with rows of two projects and some old rows without a project
- **When** the user opens the panel
- **Then** the KPIs count every row, «Por proyecto» lists both projects by name and «Sin proyecto»

### Scenario: filter by one project

- **Given** the panel open
- **When** the user picks a project in the selector
- **Then** every card, chart and table shows only that project and the cost follows

### Scenario: rows written by 0.51.0

- **Given** rows with `caller_project` and no map yet, and the project folders still under
  `~/.claude/projects`
- **When** the panel reads `/api/stats` the first time
- **Then** the map gets the names of the hashes of the log, and only those

## Edge cases and failure behavior

- Lock busy for 0.25 s: nothing written, next call retries. `os.replace` blocked by a reader on
  Windows: up to 5 retries, then the name waits.
- Map full: new projects stay without a name. Two directories differing only in case share a
  hash: the first name stays.
- Salt missing at backfill time: nothing happens and no salt is created.

## Non-functional requirements

- Security: names are escaped in the panel; map with user-only permissions; LOG_DIR never from a
  request.
- Privacy: no name in the log, the telemetry or the backfill.
- Performance: per process, a hash is checked against the map at most once on the hot path.
- Compatibility: the mod's `/api/stats?session=` call is unchanged; old rows count as «Sin proyecto».

## Non-goals

- Renaming projects, editing the map from the panel, or sharing names across machines.
- Changing the measurement scripts.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
