# Handoff: Doctor detecta el plugin de Claude importado en Codex: hooks.json con modules rechazado (#668)

## Current state

- SDD status: closed; PR #677 mezclado en `main` (402f99e3) con los 22 checks en verde
- Last completed gate: memory
- Current revision: `main`

## What changed

- `codex_plugin.py`: reglas del `hooks.json` de plugin de Codex 0.169.0 y lectura de la caché de plugins.
- Check `codex.plugin` (36 checks): `warn` con el plugin de Claude habilitado en Codex, pista `codex plugin remove local-delegate@<marketplace>`.
- Fixtures en `tests/fixtures/codex_plugin`, cargadas en Codex real.

## Decisions

- No se toca el `hooks.json` del plugin de Claude: sin `modules`, Codex lo carga pero tira `args` y no expande `${user_config.ld_bin}` (medido), y el mod dejaría de cargar en Claude Code.
- Sin Codex el check es `unknown`, como todo check de cliente ausente (REQ-003 del registro).
- Un formato correcto da `ok` sin afirmar carga: la carga y la confianza se miran en Codex con `/hooks`.

## Next action

- Issue #669: entrega Codex nativa (hooks con comando completo, sin `args`; `PLUGIN_ROOT` en el entorno; revisión de confianza del usuario). Puede reutilizar `codex_plugin.check_hooks_file` para validar lo que genere.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-16-diez-issues-y-codex-nativo.md`; este handoff
- Indexes updated: ninguno
