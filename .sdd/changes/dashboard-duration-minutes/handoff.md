# Handoff: Duraciones del panel en minutos y horas

## Estado

Mezclado en `main` con la PR #378 (`b0ba620`). Gates spec, plan, quality y conformance aprobados;
memory al cerrar. Entra en la 0.38.0.

## Qué cambió

`fmtSec(ms)` (JS del panel en `src/local_delegate/web/metrics.py`) decide el tramo redondeando en
la unidad que pinta: menos de 60 s con un decimal («45,3 s»), de 60 s a 1 h en minutos y segundos
(«15 min 47 s»), desde 1 h en horas y minutos («1 h 5 min»). La tarjeta de latencia conserva los
segundos exactos en su `title` (`fmtSecExact`). Sirve a la tarea en curso, la tabla de actividad,
la tarjeta de latencia, el desglose espera/inferencia y los eventos de hooks.

## Decisiones

- Unidades iguales en es y en (`s`, `min`, `h`); el separador decimal sigue el idioma.
- Un solo formateador: ningún otro sitio convierte milisegundos a segundos (test estático).

## Siguiente

Nada. Memoria: vault `projects/local-delegate/jornada-2026-10-21-retirada-de-alias-y-0-38.md`.
