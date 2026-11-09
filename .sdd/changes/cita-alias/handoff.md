# Handoff: El verificador de citas acepta un alias o una constante del nombre citado (#616)

## Current state

- SDD status: closed (cerrado en el PR de la release 0.50.0, rama `release/0.50.0`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `1cfb3364` (PR #618, 2026-11-09T17:37:11Z)

## What changed

- La comprobación de citas de `local_explain_code` acepta una línea que usa una constante o un alias del nombre citado (`X = 'nombre'`, `a = b`, `import … as`).
- Una comparación o una expresión más larga no crean alias.

## Decisions

- Un solo nivel de alias y tope de 5 alias por nombre; una llamada indirecta (`getattr`, tabla de despacho) puede seguir dando aviso falso.

## Next action

- Ninguna para este cambio.

## Memory

- Canonical note: Sin nota aparte: lo durable va en el CHANGELOG 0.50.0, el PR y `review.md`; la jornada del 2026-11-09 del vault la escribe la sesión principal.
- Indexes updated: ninguno desde este cambio (la sesión principal actualiza el índice de jornadas).
