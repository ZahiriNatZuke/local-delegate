# Brief: doctor: cada rol tiene su modelo servido

## Problem

`doctor` only checks that `/models` of the backend answers (`service.backend`). A role whose
configured model id is not in that list passes as healthy, and every tool of that role fails later
with a model-not-found error from the backend.

## Desired outcome

A new `doctor` check compares the model id of each role (`mechanical`, `long`, `code`, `vision`)
with the ids `/models` lists, and names the missing id and the `LOCAL_DELEGATE_MODEL_*` variable to
change. Same for a local backend (llama-swap) and a cloud one (OpenAI-compatible).

## In scope

- `BackendView` carries the ids of `/models` (daemon path and direct path).
- New check `service.role_models` (group `service`), text es/en, wiki row, counts.
- Tests with a simulated `/models` (no network).

## Out of scope

- Reading llama-swap `aliases` from its config: an alias counts only if `/models` lists it
  (llama-swap's `includeAliasesInList`).
- Changing `service.backend` semantics or the backend word in the header.

## Constraints and risks

- Do not probe the backend twice in one `doctor` run: the view is memoized per `Context`.
- An old daemon without `models` in `/api/backend`: unknown, not warn.

## Open questions

- None that change the spec.

## Log

- L1 2026-11-11 Original request, verbatim:

  > «doctor no comprueba que cada rol tenga su modelo servido». Hoy `_probe_backend_models` solo mira que `/models` del backend responda. Añade una comprobación por rol (roles vigentes: `mechanical`, `long`, `code`, `vision`; el rol `fast` está retirado) que compare el id de modelo configurado para cada rol con la lista que devuelve `/models`, y si falta, que diga qué id falta y qué variable `LOCAL_DELEGATE_MODEL_*` cambiar. Debe valer igual para un backend local (llama-swap) que para uno en la nube (OpenAI-compatible). Considera: un rol sin modelo configurado o deshabilitado (p. ej. vision opcional) no es error; alias de llama-swap cuentan como servidos si `/models` los lista; nivel de la comprobación (aviso vs fallo) coherente con las demás de `doctor`. Revisa también si `doctor --json` o la salida estructurada necesita el campo nuevo y si hay un catálogo de mensajes es/en donde registrar los textos. Tests con un `/models` simulado (sin red real).
