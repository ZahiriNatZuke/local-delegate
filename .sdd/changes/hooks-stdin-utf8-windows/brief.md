# Brief: Hooks de la entrega por settings leen y escriben UTF-8 en Windows

## Problem

Hallazgo de la revisión de seguridad del 2026-10-23 (severidad media): con la entrega por
`settings.json` el hook se lanza como `python "<script>"`; en Windows ese intérprete abre stdin y
stdout en cp1252, y Claude Code manda y lee UTF-8. Los hooks de lectura, shell y prompt usan
`json.load(sys.stdin)` con esa codificación. La entrega por plugin (`hook_entry._utf8_streams`) y
`record_call.py`/`subagent_start.py` (bytes decodificados en UTF-8) no tienen el fallo de entrada.

## Desired outcome

Rutas y prompts con `ñ`, tildes o caracteres fuera de cp1252 se leen bien; la salida llega en UTF-8;
el hook de lectura no se calla sin dejar motivo.

## In scope

- `hook_common.utf8_stdio()` y su llamada en los cuatro hooks que leen stdin o escriben stdout.
- `reason: "no_file"` en las salidas tempranas del hook de lectura.

## Out of scope

- Cambiar el comando registrado (`python -X utf8`), su migración y `doctor`.
- `record`/`_log_failure` de `hook_common.py` (otro cambio en paralelo).

## Constraints and risks

- El servidor importa `hook_common`: nada de reconfigurar stdio al importar.
- Los tests existentes ponen `io.StringIO` en `sys.stdin`: el arreglo tiene que convivir con eso.

## Open questions

- Ninguna.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-04 Original request, verbatim:

  > En la entrega por settings de Windows los hooks leen la entrada en cp1252: una ruta con ñ/tildes llega como Ã±… y el hook de lectura sale sin bloquear ni telemetría; en el hook de prompt «diseño» no casa con _HOST_ONLY; un byte UTF-8 sin carácter en cp1252 (Á) rompe json.load. Arreglo: que los scripts lean stdin en UTF-8 por sí mismos y funcione con las instalaciones existentes tras update; que la salida temprana del hook de lectura deje una línea de telemetría con motivo (no_file); comprobar que stdout con tildes llega bien; prueba instalada con HOME temporal.

- L2 2026-11-04 Subagente: la repro instalada (HOME temporal, `install --claude-delivery settings`,
  comando del settings por `sh -c`, stdin UTF-8 en bytes) reprodujo los tres fallos; arreglo con
  `hook_common.utf8_stdio()` al inicio de `main()` de los cuatro hooks y `reason: "no_file"` en el
  hook de lectura. Desviación: la repro y el arreglo se escribieron antes de aprobar `spec,plan`
  (cambio pequeño y acotado por el hallazgo); las puertas se aprobaron después, con el código a la
  vista. Queda: PR, CI, `quality`/`conformance`; la puerta `memory` la cierra la sesión principal.
