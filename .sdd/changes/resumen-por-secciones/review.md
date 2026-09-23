# Reviews: local_summarize respeta la estructura del documento (resumen por secciones)

## Revisión del plan v1 — 2026-09-23 (`personal-sdd-plan-reviewer`)

Veredicto: `revise`. Resolución en el plan v2:

| Hallazgo | Resumen | Resolución (plan v2) |
| --- | --- | --- |
| B1 | en map-reduce el system y `max_tokens` son fijos: no llegan el reparto de palabras ni el margen de títulos | T4: `system_for`, `words_for` y `tokens_for` por trozo, también en el reintento por desborde |
| B2 | detectar títulos por trozo falla si el corte cae en una valla o en un subtítulo | T1 detecta una vez con posiciones; T4 trocea solo por esas posiciones; «Continúa la sección» para una sección partida |
| B3 | completar después de los avisos deja títulos tras la coletilla y `chars_out` mal | T2/T4: `postproceso` sobre la salida pura, antes de avisos, `chars_out` y coletilla |
| B4 | no completar con `length` incumple REQ-201/202 | T2: se completa también con `length`; solo se salta con error |
| B5 | `focus` se pierde en el reduce en prosa, y un reduce propio cambia la semántica | T3: `reduce_extra` sobre el `_guard` por defecto, sin `reduce_propio` |
| B6 | «CHANGELOG sin `length`» no podía fallar: map-reduce registra siempre `stop` | T4: `_one` guarda el `length` de cada trozo; evento y aviso; control con mock |
| B7 | la métrica por subcadena se pasa sin estructura y no mira el orden | T6: por líneas de título, en orden, contenido mínimo medible, controles a mano en los dos sentidos |
| B8 | emparejamiento sin definir; subcadenas no cumplen sus propios casos | T2: algoritmo definido (líneas de título, normalización ampliada, uno a uno en orden) con sus tests |
| N1 | dos fuentes para la normalización | T6 importa de `local_delegate.server`; el banco de T5 no cambia (línea base) |
| N2 | «≤ 3 relecturas» no puede decidir | spec REQ-208 y T8: se decide por correctas; las relecturas se informan aparte |
| N3 | línea base no comparable (variantes, hooks, README vivo) | spec: amenazas a la validez; T0 copias fijas; T8 anota la versión de hooks |
| N4 | no cambiar `--piloto` | T8: `--variantes` y `--fuentes` nuevos, informe nuevo con test |
| N5 | artefactos dependientes del momento; `focus` contra `main` | T0 copias fijas; T7 anota el fallo esperado |
| N6 | umbral de títulos distinto en spec y plan | spec REQ-201: «del mismo nivel» |
| N7 | contar también las secciones vacías | T2: `vacias` en el aviso |
| N8 | nadie comprueba `max_words` | T4 reparto que no pasa del tope; T6 mide las palabras |
| N9 | retirada poco definida; docs antes de medir | interruptor (T5); retirada escrita en T8; docs en T9 tras medir |
| N10 | `focus` en el sistema | T3: saneado y delimitado, test con varias líneas |
| N11 | guardianes del log sin nombrar | T5 los nombra |
| N12 | trazabilidad por definir | spec rellenada |
| N13 | mutantes clave | T1, T2 y T4 los listan |

## Revisión del plan v2 — 2026-09-23 (mismo revisor)

Veredicto: `revise`, con 3 bloqueantes de redacción; «no hace falta una tercera ronda completa si
se aplican tal cual». Aplicados todos, también los no bloqueantes, en el plan v2.1:

| Hallazgo | Resumen | Resolución (plan v2.1) |
| --- | --- | --- |
| V2-B1 | en el CHANGELOG, la completitud hacía pasar siempre «todas las versiones» | spec REQ-208 y T7: sin las completadas, ≥ 0,9; control en T6 que falla con la mitad completada |
| V2-B2 | el reintento por desborde volvía al separador genérico | T4: `Trozo` con títulos y continuación; `split_for` con las posiciones del documento; test con valla en el punto medio |
| V2-B3 | contenido medido hasta cualquier título: negritas del modelo dan secciones vacías | T2/T6: hasta la siguiente línea **emparejada**; casos con `**Puntos clave:**` |
| V2-N1 | puntero voraz duplica con orden invertido | T2: LCS; los fuera de orden se informan y no se insertan |
| V2-N2 | título con sufijo se duplica | T2: casa si la línea empieza por el esperado con límite de palabra |
| V2-N3 | salida cortada a mitad de un título | T2: se quita la última línea de título si hubo `length` |
| V2-N4 | `length` en map-reduce cambia series de otras tools | T5: comprobar tasas y anotar el corte de serie; `Fixed` explícito |
| V2-N5 | el 4B sin criterio | spec y T7: ≥ 0,9; si no, modo estructurado solo con rol `long` |
| V2-N6 | retirada distinta en spec y plan; el interruptor lo lee el daemon | alineadas: valor por defecto en una release; nota del lanzador |
| V2-N7 | CRLF | T0 bytes y `-text`; T1 tests con CRLF y posiciones |
| V2-N8 | la métrica comparte la función que mide | T6: resultados esperados escritos a mano |
| V2-N9 | la base comparable es V0 0/3 | T8: desglose por tarea en `verification.md` |
