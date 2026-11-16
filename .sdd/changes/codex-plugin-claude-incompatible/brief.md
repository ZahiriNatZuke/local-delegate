# Brief: Doctor detecta el plugin de Claude importado en Codex: hooks.json con modules rechazado (#668)

## Problem

Codex CLI 0.169.0 lee marketplaces de Claude Code. Importado a mano, el plugin de local-delegate
queda habilitado y en caché, pero Codex rechaza su `hooks/hooks.json` por `modules` y solo lo dice
con un aviso al arrancar; el proceso termina con 0. Nada en local-delegate lo señalaba.

## Desired outcome

`doctor` detecta el plugin importado, explica que no carga ningún hook y da un comando que lo
quita sin tocar la entrada MCP. El formato que acepta Codex queda escrito, citado y probado.

## In scope

- Validador del `hooks.json` de un plugin según el parser de Codex 0.169.0.
- Check `codex.plugin` de solo lectura, textos es/en, fixtures negativas y positiva.
- Guarda de que `install` no pone el plugin en Codex; recuento y documentación.

## Out of scope

- Entrega Codex nativa, instalador, desinstalación y atribución por sesión (#669 y siguientes).
- Migración automática del plugin importado; portar `register.js`.

## Constraints and risks

- No tocar `~/.codex` real ni `~/.claude.json`: las pruebas con Codex real usan `CODEX_HOME` temporal.
- No generar `trusted_hash` ni saltar la revisión de confianza de Codex.
- Las reglas valen para Codex 0.169.0; una versión posterior puede cambiarlas (constante `CODEX_VERSION_CHECKED`).

## Open questions

- Ninguna que cambie la especificación.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-16 Original request, verbatim:

  > Resolver el issue #668 de `ZahiriNatZuke/local-delegate`: «Codex rechaza el plugin Claude importado: `modules` invalida hooks.json aunque el proceso termine correctamente». Alcance esperado (según el issue): que lo que `local-delegate` instale/genere para Codex sea un manifiesto que Codex CLI acepte; que el diagnóstico (`doctor`) detecte y explique la incompatibilidad cuando hay un plugin de Claude importado en Codex con `modules`; fixtures negativas y positivas del formato Codex soportado.
- L2 2026-11-16 Reproducido en Codex 0.169.0 real con `CODEX_HOME` temporal; validador, check, fixtures, docs y tests hechos. Queda: CI del PR.
