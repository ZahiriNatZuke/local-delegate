# Specification: doctor: cada rol tiene su modelo servido

## Summary

`doctor` gains the check `service.role_models`: with the backend answering, every text role whose
model id is not in `/models` makes it `warn`, naming the id and its `LOCAL_DELEGATE_MODEL_*`
variable; the vision role missing alone is noted but stays `ok` (it only serves
`local_describe_image`).

## Requirements

- **REQ-001** — With `/models` listing every role's id, `service.role_models` is `ok`; with a text
  role's id missing it is `warn`, the detail names the role and the id, and the fix hint the
  variable (`LOCAL_DELEGATE_MODEL_MECHANICAL`, `_LONG`, `_CODE`, `_VISION`).
  - Request: "si falta, que diga qué id falta y qué variable `LOCAL_DELEGATE_MODEL_*` cambiar"
  - Verify: test tests/test_checks_role_models.py
- **REQ-002** — Only the vision id missing: `ok`, and the detail says it is not served. An empty role
  id is skipped.
  - Request: "un rol sin modelo configurado o deshabilitado (p. ej. vision opcional) no es error"
  - Verify: test tests/test_checks_role_models.py
- **REQ-003** — The ids come from `/models` both through the daemon (`/api/backend` `models`) and
  through the direct probe (`data[].id`); an id listed as an alias counts as served, and an untagged
  id counts if Ollama lists it as `<id>:latest`. The role ids are the daemon's (`/api/backend`
  `role_models`) when it sends them, this console's otherwise, and the detail says so. The backend
  down, or no list: `unknown`, with a text that does not blame a daemon on the direct probe.
  - Request: "Debe valer igual para un backend local (llama-swap) que para uno en la nube"
  - Verify: test tests/test_checks_role_models.py
- **REQ-004** — One `doctor` run asks the backend once: `service.backend` and `service.role_models`
  share the view.
  - Request: "derived: a second probe doubles the wait on a slow or down backend"
  - Verify: test tests/test_checks_role_models.py
- **REQ-005** — Title and texts in the es and en catalogs; `doctor` has no `--json`, and the
  structured outputs that read the checks (`update`'s notes) take it generically; the wiki table and
  the check counts list it; existing tests pass.
  - Request: "Revisa también si `doctor --json` o la salida estructurada necesita el campo nuevo y si hay un catálogo de mensajes es/en"
  - Verify: test tests/test_wiki.py

## Acceptance scenarios

### Scenario: a role's model is not served

- **Given** `LOCAL_DELEGATE_MODEL_CODE=qwen-x` and `/models` without `qwen-x`
- **When** the user runs `local-delegate doctor`
- **Then** `service.role_models` is `warn` and says `code: qwen-x` and `LOCAL_DELEGATE_MODEL_CODE`

## Edge cases and failure behavior

- Backend down or 401: `unknown` (`service.backend` already says why).
- Old daemon without `models`: `unknown`.

## Non-functional requirements

- No extra network call per run; no secret in the texts.

## Non-goals

- Parsing llama-swap aliases from its YAML.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
