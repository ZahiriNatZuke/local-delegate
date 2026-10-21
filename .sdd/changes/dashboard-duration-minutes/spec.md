# Especificación: duraciones del panel en minutos y horas

## Resumen

El panel (`src/local_delegate/web/metrics.py`) escribe toda duración en segundos con un decimal
(«947,2 s» en una tarea en curso). Desde ahora, a partir de 60 s se lee en minutos y segundos, y a
partir de 1 h en horas y minutos. Un solo formateador (`fmtSec`) sirve a todos los sitios: tarea en
curso, último evento, tarjeta KPI de latencia, desglose espera/inferencia y tabla de actividad.

## Requisitos

- **REQ-001 — Tramos.** `fmtSec(ms)` devuelve:
  - valor nulo, indefinido o no finito → «–» (como hoy);
  - menos de 50 ms → «< 0,1 s» (como hoy);
  - menos de 60 s *tras redondear a décimas* → segundos con un decimal (como hoy);
  - de 60 s a menos de 1 h *tras redondear a segundos enteros* → «M min S s», y «M min» si S = 0;
  - 1 h o más → «H h M min» con los minutos redondeados, y «H h» si M = 0.
- **REQ-002 — Fronteras sin valores imposibles.** El redondeo se hace en la unidad que se va a
  pintar y decide el tramo: nunca sale «60,0 s», «60 s», «0 min 60 s», «1 min 60 s» ni «60 min».
- **REQ-003 — Idioma.** Las unidades son símbolos iguales en es y en (`s`, `min`, `h`); el
  separador decimal sigue el idioma del panel (coma en es, punto en en), como hoy. Sin textos nuevos
  en el catálogo i18n.
- **REQ-004 — Un solo formateador.** Los cinco sitios que hoy llaman a `fmtSec` siguen llamándolo;
  ninguno formatea duraciones por su cuenta.
- **REQ-005 — Valor exacto en el `title`.** La tarjeta KPI de latencia, que hoy pone el valor en su
  `title`, conserva ahí los segundos exactos con un decimal («116,9 s») aunque la cifra visible pase
  a «1 min 57 s».

## Tabla de casos (verificable con node sobre la definición real)

| ms entrada | es | en | Por qué |
|---|---|---|---|
| `null` | – | – | sin dato |
| 30 | < 0,1 s | < 0.1 s | por debajo de 50 ms |
| 120 | 0,1 s | 0.1 s | tramo de segundos |
| 45 300 | 45,3 s | 45.3 s | tramo de segundos |
| 59 940 | 59,9 s | 59.9 s | justo debajo de la frontera |
| 59 960 | 1 min | 1 min | 59,96 s redondea a 60,0 → minutos |
| 60 000 | 1 min | 1 min | frontera exacta, S = 0 |
| 116 948 | 1 min 57 s | 1 min 57 s | redondeo de segundos |
| 947 200 | 15 min 47 s | 15 min 47 s | el caso de la captura del usuario |
| 120 000 | 2 min | 2 min | S = 0 se omite |
| 3 599 400 | 59 min 59 s | 59 min 59 s | justo debajo de la hora |
| 3 599 600 | 1 h | 1 h | 3599,6 s redondea a 3600 → horas |
| 3 600 000 | 1 h | 1 h | frontera exacta, M = 0 |
| 3 900 000 | 1 h 5 min | 1 h 5 min | horas y minutos |
| 9 000 000 | 2 h 30 min | 2 h 30 min | varias horas |

`title` de la tarjeta KPI de latencia con 116 948 ms: «116,9 s» (es) / «116.9 s» (en).

## Escenarios de aceptación

### Escenario: tarea larga en curso

- **Dado** una delegación en curso con `elapsed_s` = 947,2
- **Cuando** el panel pinta el indicador de la tarea en curso
- **Entonces** se lee «15 min 47 s», no «947,2 s».

### Escenario: filas largas en la actividad

- **Dado** eventos con `latency_ms` de más de 1 min y de más de 1 h
- **Cuando** se pinta la tabla de actividad
- **Entonces** salen «M min S s» y «H h M min», en claro y en oscuro, sin desbordar la celda.

## Casos límite

- Fronteras de 59,96 s, 60 s, 3599,6 s y 3600 s: en la tabla.
- Duraciones cortas: se comportan exactamente como hoy (mismos tests verdes).

## Requisitos no funcionales

- Sin dependencias nuevas. Código y comentarios nuevos en inglés. El fin de línea de `metrics.py`
  (CRLF) se conserva.
- Accesibilidad: el texto visible sigue siendo texto plano; el `title` conserva el exacto.

## Fuera de alcance

- Duraciones que no pasan por `fmtSec` (p. ej. «hace N s» del último evento, ventanas de prueba).
- Cambiar las claves del catálogo i18n, el README, la wiki o el CHANGELOG más allá de una línea en
  `[Unreleased]` › «Corrige».

## Trazabilidad

| Requisito | Tarea del plan | Verificación |
|---|---|---|
| REQ-001, REQ-002 | T1, T2 | tests con node de la tabla (es) |
| REQ-003 | T1, T2 | mismos casos con `lang="en"` |
| REQ-004 | T2 | test estático: ningún `/ 1000) + ' s'` fuera de los formateadores |
| REQ-005 | T2 | test del `title` de la tarjeta de latencia |
| Escenarios | T3 | capturas claro/oscuro con datos sembrados |
