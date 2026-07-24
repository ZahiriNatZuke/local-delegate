# Specification: Release 0.10.0, wiki y distribución

## Summary

Publicar local-delegate 0.10.0 como release beta coherente y reproducible, con acceso remoto Mac→PC
documentado y sin dejar basura de prueba ni secretos.

## Requirements

- **REQ-001 — Higiene:** no quedan temporales, variables o telemetría exclusiva del piloto; tests
  futuros no escriben en el log real. Configuración/secretos operativos se conservan.
- **REQ-002 — Versionado:** pyproject, runtime, lockfile, server.json y changelog declaran 0.10.0.
- **REQ-003 — Documentación:** README y wiki explican remoto autenticado, topología MCP local en
  Mac/backend PC, hooks adoptados y backends estables sin placeholders en el camino principal.
- **REQ-004 — Calidad:** lock, Ruff, format, 160+ tests, dashboard JS, build, metadata, gitleaks y
  smoke de wheel/uvx pasan antes del tag.
- **REQ-005 — Integración:** `main` incorpora la rama por fast-forward y CI queda verde antes del tag.
- **REQ-006 — Publicación:** v0.10.0 aparece en PyPI y GitHub Release; `uvx` desde vacío reporta
  0.10.0 y el MCP Registry marca 0.10.0 como latest.
- **REQ-007 — Wiki/memoria:** la wiki nativa y la nota canónica de Obsidian reflejan el release,
  sus decisiones y el procedimiento remoto; los índices solo reciben un puntero si aporta recall.
- **REQ-008 — Seguridad:** no se publica la API key; publisher oficial se verifica por checksum;
  el depscore post-release no presenta alerta nueva o caída sin reportarla.

## Acceptance scenarios

### Scenario: instalación remota en Mac

- **Given** llama-swap autenticado en la PC y la key existente en Keychain de la Mac
- **When** Codex/Claude inicia `uvx local-delegate-mcp==0.10.0` con el endpoint HTTPS privado
- **Then** el MCP corre localmente en la Mac, lee paths de la Mac y ejecuta inferencia en la PC

### Scenario: publicación segura

- **Given** main y CI verdes
- **When** se empuja `v0.10.0`
- **Then** PyPI publica por OIDC; solo tras verificarlo se crean GitHub Release y registro MCP

### Scenario: fallo de release

- **Given** un check, CI o publish fallido
- **When** se detecta antes de la siguiente compuerta
- **Then** se detiene el proceso; no se fuerza ni se reutiliza un artefacto incorrecto

## Edge cases and failure behavior

- Un tag no se crea antes de CI verde.
- Un fallo antes del tag se corrige en la rama; después de publicar PyPI se corrige como 0.10.1.
- La publicación del registro es idempotente y ocurre solo cuando PyPI sirve 0.10.0.
- `.codex/`, secrets cifrados y logs de usuario nunca entran al commit/build.

## Non-functional requirements

- Python >=3.11 y transporte stdio siguen compatibles.
- La topología remota sigue privada y autenticada; no degrada la semántica de `path`.
- Cero dependencias nuevas; todos los artefactos de distribución tienen metadata válida.

## Non-goals

- 1.0.0, upgrades de backend, soporte PDF/chunking y promoción MoE.

## Traceability

REQ-001 -> tareas 1/4; REQ-002 -> tarea 2; REQ-003/007 -> tareas 2/5; REQ-004/008 -> tarea 3;
REQ-005/006 -> tarea 4.
