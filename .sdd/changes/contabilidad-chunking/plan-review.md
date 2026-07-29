# Revisión adversarial del plan — `contabilidad-chunking`

Fecha: 2026-07-29. Revisión hecha buscando **por qué el plan fallaría**, no confirmándolo. Cada
hallazgo se resolvió por ejecución o por lectura del historial, no por argumento.

## Hallazgo 1 — El plan apoya REQ-001 en un supuesto sobre el histórico: ¿`chunks` fue siempre `calls`?

**Riesgo:** el plan afirma que `chunks or 1` contabiliza correctamente **los 111 eventos ya
grabados**. Pero esos eventos los escribieron versiones anteriores. Si en alguna `chunks` significó
*número de trozos* en vez de *llamadas*, el histórico mentiría y REQ-001 sería falso justo donde dice
serlo.

**Verificado:** `git log -S` sobre `server.py` da dos commits que tocan el campo. En el primero que
lo introduce (`28dd5c3`, el chunking original) ya está la separación exacta de hoy:

```
695:  _inflight_start(..., chunks=len(chunks))   # el panel "En curso": trozos
780:  _log_event(..., chunks=calls)              # el LOG: llamadas reales
```

El segundo (`8e01abb`, el map-reduce) mantiene `chunks=calls`. **No hay ninguna versión en la que el
log haya escrito trozos.** El supuesto se sostiene y REQ-001 queda apoyado en evidencia, no en
lectura del código actual.

**Estado:** resuelto, no bloqueante.

## Hallazgo 2 — Mover los KPIs a `/api/stats` cambia números por una razón que el plan no menciona

**Riesgo:** el plan justifica la Tarea 4 por eliminar la duplicación, y presenta el cambio de números
como consecuencia solo de la contabilidad nueva. Hay una segunda causa oculta.

**Verificado:** `/api/events` trunca a `MAX_EVENTS = 5000` (`metrics.py:317`) mientras que
`meta.count` reporta el total real (`metrics.py:312`). El JS calcula hoy los KPIs sobre
`state.events` —la lista truncada— y muestra al lado `state.meta.count`, el total. Es decir: **en un
rango con más de 5000 eventos el panel ya se contradice hoy consigo mismo**, y sus KPIs subestiman.
`_aggregate` no trunca.

**Consecuencia:** la Tarea 4 cierra además una incoherencia latente que nadie había visto. Debe
quedar escrito, porque explica parte del salto de los números y evita que se lea como regresión.

**Acción:** anotado en el plan (migración) y en el `CHANGELOG.md`.

## Hallazgo 3 — Dos endpoints por refresco: ¿se relee el log dos veces?

**Riesgo:** si el panel pide `/api/events` y `/api/stats` en cada refresco, se dobla el coste de I/O
y parseo del JSONL.

**Verificado:** `_load` cachea por fichero contra `mtime` + `size` (`_FILE_CACHE`,
`metrics.py:62,89,105`). La segunda llamada reutiliza el parseo; solo repite el filtrado por rango en
memoria. Coste aceptable y sin cambio de diseño.

**Estado:** resuelto, no bloqueante.

## Hallazgo 4 — La Tarea 5 (paridad con `node`) puede ser sobre-ingeniería

**Duda legítima:** si los KPIs pasan a venir del servidor, el JS casi no calcula nada. ¿Justifica un
test que arranca `node`?

**Resolución:** sí, pero por un motivo más estrecho que el del plan. Lo que queda en JS son **las
series por día**, que existen precisamente porque la agrupación depende de la zona horaria del
navegador (`metrics.py:1347`). Si esas series estimasen el ahorro con una regla distinta a la del
KPI, el gráfico contradiría a la tarjeta que tiene encima — que es el mismo defecto que este change
viene a cerrar, en pequeño. El test se mantiene, con `skip` si no hay `node`, y se comprueba **al
revés** rompiendo una regla a propósito.

**Estado:** mantenido, con la justificación corregida.

## Hallazgo 5 — El tercer estado «no estimable» añade complejidad sin caso real

**Riesgo:** la Tarea 2 contempla un evento de imagen **sin** `tokens_in`, que quedaría en `0`
declarado como no estimable. Un estado más que probar y que pintar.

**Verificado:** en el log real, los 4 eventos de `local_describe_image` traen `tokens_in`. El caso es
posible (backend sin `usage`) pero no observado.

**Resolución:** se mantiene porque REQ-006 prohíbe explícitamente el número inventado, y `0` con
marca es la única salida honesta. No se le da tratamiento visual propio: basta con que no contamine
el agregado.

**Estado:** aceptado, alcance acotado.

## Hallazgo 6 — Un requisito sin verificación observable

**Riesgo:** REQ-003 dice «se distinga **a simple vista**». Ningún test automático prueba eso.

**Resolución:** queda cubierto por dos vías distintas y ambas obligatorias: la tabla con el chip de
llamadas (Tarea 6) y la verificación **manual por ejecución** con una delegación troceada real contra
el backend y el daemon reiniciado. El plan ya la exige y no se da por cerrado sin ella.

**Estado:** aceptado.

## Veredicto

**Ningún hallazgo bloqueante.** Dos cambios incorporados al plan (Hallazgo 2 en migración y
CHANGELOG; Hallazgo 4 con la justificación corregida) y un supuesto crítico —el significado histórico
de `chunks`— convertido de suposición en evidencia.
