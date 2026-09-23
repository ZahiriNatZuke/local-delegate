# Verification: El hook de prompt se dispara con eventos del sistema

- **Tests** (`tests/test_hook_recipes.py`): `test_prompt_hook_ignores_system_events` (tres prompts
  reales capturados; control positivo: el mismo cuerpo sin prefijo SÍ se clasifica como
  `summarize`) y `test_prompt_hook_still_classifies_user_prompts_mentioning_tags` (REQ-003).
- **Mutantes** (ambos revertidos):
  - `es_evento_sistema` devuelve siempre `False` → falla `assert prompt.es_evento_sistema(texto)`.
  - se quita solo el `return` temprano de `main` → falla `assert not log.exists()` (REQ-002).
- **Suite completa:** 1349 passed, 2 skipped; `ruff check` y `ruff format --check` limpios.
- **Instalado:** `uv tool install --force --reinstall --no-cache ".[llamaswap]"` (tras parar el
  daemon: el primer intento falló a medias por `os error 5` y dejó el entorno roto; se siguió el
  procedimiento de la memoria `daemon-y-uv-tool-trampas`), `local-delegate update --version 0.31.4`
  repuso los hooks, daemon arriba (pid 6372). La copia en `~/.claude/hooks/local-delegate/` es
  idéntica al repo. Ejecutado el script instalado con los payloads capturados: informe de
  subagente, task-notification y formato interactivo → silencio; «Resume este archivo de logs en
  cinco viñetas» → aviso.

## Tras la revisión de conformidad (APROBAR, sin bloqueantes)

- Atendido el hallazgo medio: `test_prompt_hook_still_warns_on_real_prompt_end_to_end` ejecuta
  `main()` con un prompt real y exige aviso por stdout y `suggested: true` en la telemetría. El
  mutante `if es_evento_sistema(prompt) or True:` que antes pasaba la suite ahora falla ahí.
- Atendido el bajo: `test_prompt_hook_matches_every_system_prefix` cubre `<cross-session-message`,
  `<system-reminder>` y espacios/saltos delante.
- CHANGELOG `[Unreleased] / Fixed` con la discontinuidad del panel; nota en
  `docs/recipes/claude-code-hooks.md`. EOL respetado (CHANGELOG CRLF, receta LF).
- Vigilar (no defecto): `<system-reminder>` y `<cross-session-message>` no tienen captura real; si
  una versión de Claude Code antepusiera uno a un prompt del usuario, ese prompt se silenciaría.
- Suite: 1351 passed, 2 skipped; ruff limpio.
- Observado en vivo tras instalar: la siguiente `<task-notification>` de la sesión llegó sin aviso.
