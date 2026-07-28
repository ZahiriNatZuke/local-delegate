# Result review: Acotar el SDK mcp por debajo del major 2 y cerrar el punto ciego de resolucion libre

Revisión del resultado contra `spec.md`, con `main` en `04672c2` (PR #31 mergeado por squash).

## Verdict

`conforms-with-notes`

Los nueve requisitos están implementados y verificados con evidencia fresca. Las notas son
limitaciones declaradas y trabajo explícitamente diferido, no incumplimientos.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 · techo `<2` con comentario | Sí | Sí | `pyproject.toml`; el comentario explica el porqué, no el qué |
| REQ-002 · import con resolución libre | Sí | Sí | implícito en el handshake OK sobre el wheel construido |
| REQ-003 · handshake sin backend vivo | Sí | Sí | exit 0 contra un `BASE_URL` muerto a propósito |
| REQ-004 · el CI lo ejecuta | Sí | Sí | `install-smoke` pass en 13s en el PR y presente en `main` |
| REQ-005 · demostrar que falla sin el techo | Sí | Sí | contra la 0.12.1 **publicada**, no una simulación: exit 1 |
| REQ-006 · versión 0.12.2 en los cuatro sitios | Sí | Sí | `bump_version.py --check` conforme |
| REQ-007 · CHANGELOG con el síntoma | Sí | Sí | nombra `-32000` y dónde está el traceback real |
| REQ-008 · no exigir el check nuevo aún | Sí | Sí | el ruleset no se tocó; el job ya demostró que reporta |
| REQ-009 · suite contra la versión del lock | Sí | Sí | `233 passed` con `mcp 1.28.1`; y arranque OK con 1.29.0 |

Escenarios de aceptación:

- *Instalación nueva con el SDK 2.x disponible* — verificado por contraprueba: el wheel de esta
  rama resuelve `mcp 1.29.0` y responde. La comprobación definitiva (`uvx` sin pin) exige la
  0.12.2 publicada y queda pendiente de la confirmación del usuario.
- *El CI detecta el próximo major incompatible* — verificado con la 0.12.1 real.
- *Demostración de que el check muerde* — verificado, con el comando reproducible en
  `verification.md`.

## Findings

1. **La revisión del plan no fue independiente.** La hizo el mismo agente que redactó el plan, por
   una instrucción de sesión que impide lanzar subagentes sin petición explícita. Declarado en
   `plan-review.md`. Aun así detectó un hallazgo bloqueante real (F1, la caché de `uv` haciendo el
   job incapaz de fallar) y lo corrigió antes de implementar.
2. **El objetivo real todavía no está verificado donde apareció.** El reporte vino de la Mac y solo
   se cierra con `uvx local-delegate-mcp` sin pin allá, con la 0.12.2 en PyPI. Hasta entonces el
   cambio está probado, no confirmado en producción.
3. **Prevención parcial.** El techo protege de `mcp`; las otras cinco dependencias directas siguen
   sin techo. El job nuevo las cubre por **detección**, no por prevención. Ya hay señal de la
   siguiente: la suite avisa que `httpx` 2 viene en camino.
4. **Defecto colateral confirmado y no corregido a propósito:** `serverInfo.version` reporta la
   versión del SDK, no la del paquete. Declarado como no-goal en la spec; va al backlog.

## Required follow-up

Antes del cierre:

- [ ] Verificar el CI de `main` **después** del merge, no solo los checks del PR.
- [ ] Traza SDD (este archivo, `verification.md`, `handoff.md`) mergeada por PR propio.

Después del cierre, fuera de este cambio:

- [ ] **Publicar la 0.12.2** — requiere confirmación explícita del usuario. Sin publicar, el fix no
  llega a nadie: el techo vive dentro del wheel.
- [ ] Confirmar en la Mac con `uvx` sin pin.
- [ ] Backlog: migración a la API `mcp` 2.x; política de techos para el resto de dependencias;
  `serverInfo` con la versión del paquete.
