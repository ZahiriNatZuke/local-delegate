# Specification: Codex: matriz de capacidades y alternativas para barra, comandos sin modelo y tools fijadas (#671)

## Summary

Quien usa local-delegate en Codex sabe, por una tabla con evidencia, qué hace el mod de Claude Code
y qué tiene equivalente en Codex 0.169.0. La única alternativa nativa y comprobable (tools fuera de
`tool_search`) se puede activar con `install` y se conserva en `update`; `doctor` la enseña.

## Requirements

- **REQ-001** — Hay una página de la wiki con la matriz Claude Code ↔ Codex por superficie (MCP,
  instrucciones, hooks, tools fijadas, comandos sin modelo, banda integrada, panel, atribución,
  lectura automática), con estado (implementado, configurado, cargado, probado, no disponible) y
  evidencia de código, documentación o ejecución; enlazada desde README y la portada de la wiki.
  - Request: "El entregable principal es la matriz de capacidades Claude Code ↔ Codex ... en `docs/wiki/` y referenciada desde el README"
  - Verify: review docs/wiki/Codex-capabilities.md contra research.md
- **REQ-002** — `install --codex-direct-tools` añade `"deferred"` a `omit_tools_from` de la tabla
  `[mcp_servers.local-delegate]` de Codex (o la crea con `["deferred"]`; si ya lo tenía, la deja
  byte a byte); `--no-codex-direct-tools` quita solo `"deferred"` y conserva los demás valores (una
  lista vacía desaparece); sin ninguno de los dos, `install` y `update` (también la reparación por
  `repair_install_options`, con `codex_direct_tools=None` por defecto) conservan el texto de la
  lista tal cual, en una línea o en varias, con espacios o comentarios dentro (el comentario de
  fin de línea se pierde, igual que en los plazos). La salida lleva siempre una sola clave y es
  TOML válido. Si el flag no puede tener efecto (Codex fuera de los clientes, `--no-mcp` o entrada a
  mano que no se reemplaza), `install` lo avisa. Una entrada a mano que sí se reemplaza conserva su
  lista igual que los plazos.
  - Request: "Implementa las alternativas que sean viables y verificables con fixtures"
  - Verify: test tests/test_codex_direct_tools.py
- **REQ-003** — La línea de `doctor` de la entrada MCP de Codex dice cuándo las tools van directas.
  - Request: "README/recetas/doctor alineados con capacidades reales"
  - Verify: test tests/test_codex_direct_tools.py
- **REQ-004** — Con Codex 0.169.0, la tabla con la clave hace que las tools de local-delegate estén
  en la entrada visible del modelo, y sin ella no.
  - Request: "Cada celda positiva tiene referencia de código más prueba de carga/ejecución"
  - Verify: cmd codex debug prompt-input con CODEX_HOME temporal
- **REQ-005** — Comandos sin modelo y banda de estado quedan como «no hay» en Codex con su
  alternativa más cercana (`!` y `doctor`, `/statusline` de campos fijos, panel web) y sin código
  de producto que prometa lo que Codex no expone.
  - Request: "lo que solo se pueda probar con Codex real, déjalo como prueba en vivo para el usuario, sin darlo por hecho"
  - Verify: review docs/wiki/Codex-capabilities.md
- **REQ-006** — CHANGELOG `[Unreleased]` y la opción en la wiki de instalación.
  - Request: "CHANGELOG: entrada en `[Unreleased]`"
  - Verify: review CHANGELOG.md y docs/wiki/Integration-install.md
- **REQ-007** — Los textos nuevos salen del catálogo en es y en.
  - Request: "textos de salida es+en por el catálogo"
  - Verify: test tests/test_codex_direct_tools.py y tests/test_i18n_parity.py

## Acceptance scenarios

### Scenario: activar las tools directas

- **Given** un HOME con Codex y la entrada gestionada sin la clave
- **When** se ejecuta `install --clients codex --codex-direct-tools`
- **Then** la tabla lleva `omit_tools_from = ["deferred"]` y es TOML válido

### Scenario: actualizar sin flag

- **Given** la tabla con `omit_tools_from = ["deferred", "code_mode"]` puesto a mano
- **When** se ejecuta `install` sin flag (o `update`)
- **Then** la línea sigue igual

## Edge cases and failure behavior

- `--codex-direct-tools` con una lista previa que ya contiene `deferred` la conserva tal cual.
- Lista previa que no es una lista TOML de textos: no se reemite nunca (ni sin flag), para que el
  texto capturado no meta otras claves en el bloque; con `--codex-direct-tools` se rehace desde
  vacía.
- Entrada escrita a mano (sin marcadores): manda el flujo de `--force-mcp-codex` que ya existe.
- `doctor` dice lo que pide la tabla; con `code_mode_only_strict_3p_tools` Codex lo ignora y la
  wiki lo avisa.

## Non-functional requirements

- Sin instalaciones, sin cambios de permisos, sin tocar `~/.codex` en tests; el backend apagado no
  afecta (la clave es configuración de Codex).

## Non-goals

- Un subcomando de CLI que llame a las tools para usarlo con `!` (seguimiento aparte).
- Integración con la barra de Codex (no hay API).
- Hooks nuevos en `codex_hooks.SPECS` (#669, #670).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
