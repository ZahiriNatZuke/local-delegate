# Brief: Release 0.10.0, wiki y distribución

## Problem

La rama `codex/moe-remote-canary` contiene siete commits verificados por encima de `origin/main`,
pero el paquete público, el descriptor MCP, el changelog y la wiki siguen en 0.9.0. La capacidad
remota autenticada y el piloto de hooks no pueden probarse desde instalaciones normales hasta
publicar una versión coherente.

## Desired outcome

`main`, PyPI, GitHub Release, el registro oficial MCP y la wiki publican 0.10.0 con metadatos
coherentes, instrucciones remotas completas y verificación desde una instalación limpia. La serie
permanece beta; 1.0.0 queda para después de un periodo real de uso.

## In scope

- Limpiar artefactos de pruebas sin tocar logs, secretos o configuración operativa necesaria.
- Bump coordinado a 0.10.0 en paquete, runtime, lockfile y `server.json`.
- CHANGELOG/README/wiki con remoto, auth, canary, hooks y política de backends.
- Fast-forward a `main`, CI verde, tag, PyPI, GitHub Release, registro MCP y wiki nativa.
- Smoke de `uvx` desde directorio vacío y auditoría Socket posterior a publicación.
- Handoff exacto para configurar la Mac usando la key ya guardada en Keychain.

## Out of scope

- Promover a 1.0.0.
- Actualizar llama-swap v238 o llama-server b9925.
- Promover un modelo MoE al catálogo estable.
- Exponer el backend a Internet pública o persistir la API key en Git/docs.

## Constraints and risks

- PyPI es inmutable: si 0.10.0 se publica con error, la recuperación es 0.10.1.
- `publish.yml` solo publica PyPI; GitHub Release, wiki y registro MCP requieren pasos posteriores.
- La publicación del registro exige `mcp-publisher`; se usará el binario oficial con checksum.
- `.codex/` es contenido local del usuario y queda fuera de todos los commits.

## Open questions

- Resuelto: “0.10” se normaliza a SemVer `0.10.0`/tag `v0.10.0`.
- Resuelto: la wiki nativa existe y se actualizará desde `docs/wiki` mediante clone temporal.
