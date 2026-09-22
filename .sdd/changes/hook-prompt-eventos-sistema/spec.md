# Specification: El hook de prompt se dispara con eventos del sistema

Modo ligero: cambio acotado a un hook y su test.

## Summary

Claude Code dispara `UserPromptSubmit` también con mensajes que no escribió el usuario: el informe
de un subagente (`<agent-message …>`, precedido de «Another Claude session sent a message:» en
sesión interactiva), el aviso de fin de una tarea en segundo plano (`<task-notification>`) y los
mensajes entre sesiones. Como esos textos suelen decir «summary»/«resumen», el hook les inyectaba
el aviso de delegar y los contaba como prompts en la telemetría. Observado en vivo el 2026-09-22
(cuatro disparos en una sesión con subagentes en segundo plano).

## Requirements

- **REQ-001:** el hook no emite aviso para un prompt que empieza (tras espacios) por
  `<task-notification`, `<agent-message`, `<cross-session-message`, `<system-reminder`, o por
  «Another Claude session sent a message:» seguido de una de esas etiquetas.
- **REQ-002:** esos eventos tampoco se escriben en la telemetría (no son prompts; inflarían el
  total del panel).
- **REQ-003:** un prompt del usuario que menciona esas etiquetas a mitad del texto se sigue
  clasificando como hasta ahora.

## Evidence the payload has no origin field

Captura real con un hook temporal (`claude -p --settings`, Claude Code 2.1.280): las claves son
`cwd, hook_event_name, permission_mode, prompt_id, session_id, transcript_path` y `prompt`. El
único discriminante es el comienzo de `prompt`.

## Non-goals

- Cambiar el clasificador de intención o el texto del aviso (lo hará `subagente-lector-local`).
- Reescribir la telemetría histórica, que ya incluye esos eventos sin marca.
