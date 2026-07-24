# Implementation plan: Release 0.10.0, wiki y distribución

## Approach

Cerrar primero higiene y metadatos en la rama ya verificada. Promover por compuertas irreversibles:
tests/build -> main/CI -> tag/PyPI -> smoke -> GitHub Release/registro/wiki -> memoria. Cada paso
externo se verifica antes del siguiente.

## Ordered tasks

1. **Higiene e aislamiento**
   - Files: `tests/conftest.py`, settings/logs/temp del host (fuera del repo).
   - Requirements: REQ-001, REQ-008.
   - Verification: suite no cambia hash del log; inventario exacto sin artefactos del piloto.
   - Recovery: backup atómico solo durante depuración; preservar logs reales y DPAPI/Keychain.
2. **Bump y documentación**
   - Files: pyproject, `__init__.py`, uv.lock, server.json, CHANGELOG, README, docs/wiki.
   - Requirements: REQ-002, REQ-003, REQ-007.
   - Verification: búsqueda global de 0.9.0 solo en historial; JSON/TOML válidos; enlaces relativos.
   - Recovery: revertir commit antes del tag.
3. **Calidad y paquete limpio**
   - Files: código/artefactos de build, SDD verification/review.
   - Requirements: REQ-004, REQ-008.
   - Verification: lock, Ruff, format, pytest, JS, build, twine/metadata si disponible, gitleaks,
     wheel en entorno vacío y diff auditado. Sin dependencias nuevas.
   - Recovery: no promover si falla; limpiar `dist` y temporales después.
4. **Promoción y publicación**
   - Systems: Git main, Actions, tag, PyPI, GitHub Release, MCP Registry, native wiki.
   - Requirements: REQ-005, REQ-006.
   - Verification: SHAs/CI, API PyPI, uvx 0.10.0, release URL, registry `isLatest`, wiki HEAD.
   - Recovery: detenerse en cada gate; si PyPI ya existe, corregir con 0.10.1.
5. **Memoria y handoff Mac**
   - Files/systems: Obsidian canónico, índices ligeros si aplica, handoff SDD.
   - Requirements: REQ-003, REQ-007.
   - Verification: releer nota y entregar comandos exactos usando Keychain, sin revelar la key.
   - Recovery: corregir nota/puntero sin tocar runtime.

## Test strategy

- Unit: suite completa 160+.
- Integration: build + instalación wheel/uvx en directorio vacío; canary remoto previo 20/20.
- End-to-end: main CI, PyPI JSON, GitHub Release, MCP Registry y wiki remota.
- Security: gitleaks staged/repo relevante, archivos sensibles excluidos, checksum publisher,
  Socket depscore post-release.

## Migration and compatibility

- No migración de datos/config; 0.10.0 mantiene variables existentes y añade API key opcional.
- La Mac se fija inicialmente a `==0.10.0`; 1.0.0 se difiere hasta completar observación real.

## Plan review

- [x] Cada requisito tiene tarea y verificación.
- [x] Operaciones irreversibles tienen compuerta y recuperación.
- [x] No hay dependencias Python nuevas; integraciones externas son explícitas.
- [x] 1.0/backend/PDF/MoE quedan fuera.
