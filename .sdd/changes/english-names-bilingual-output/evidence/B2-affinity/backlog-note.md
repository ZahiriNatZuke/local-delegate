# Nota de backlog — B2-affinity (2026-10-18)

**Título:** `local_lint_summary` con los modelos grandes deja de nombrar los códigos de regla, y su
celda de afinidad salió en la 0.36.0.

**Qué pasó.** La re-evaluación en vivo de la celda `local_lint_summary → gemma4-26b-a4b` con los
prompts de la 0.36.0 (lote B2-affinity, `evidence/B2-affinity/live.md`) la rechazó en español y en
inglés, y también a `qwen36-35b-a3b`. Causa vista en las respuestas: con la orden de idioma
endurecida (B2d/B2d-fix) el 26B traduce el nombre de cada regla y omite su código («Línea demasiado
larga: 2 errores» en vez de «E501: 2»), en español en 3 de 4 casos y en 9 de 9 respuestas de esos
casos; en inglés a veces no da cifras («Several lines»). Qwen escribe prosa sin códigos. El modelo
del rol (`gemma3-4b`) sí los copia. La orden dice que los códigos se quedan tal cual, pero no pide
nombrarlos.

**Por qué importa fuera de la afinidad.** El rol largo es el 26B: los logs grandes salen con la
misma pérdida (B2e midió que el modelo solo nombra el 57 % de los códigos en logs troceados; la línea
de «no se nombran» del programa lo tapa solo en el troceado).

**Ideas (sin medir):**
1. Que la orden de lint pida explícitamente «cada entrada empieza por el código de la regla tal como
   sale en el log» (cambia el prompt: se mide con el arnés de B2d-2/B2d-3 y con `--repeat 3`).
2. Después, volver a medir la celda de afinidad de lint con
   `evidence/B2-affinity/run_affinity_live.py` y `evaluate_reevaluation.py` (la huella de lint
   depende del idioma: una celda por idioma, con un campo `language` en `matrix.Cell` y `doctor`
   que no avise por la celda del otro idioma; el diseño está en el plan, sección B2-affinity).

**Dos hallazgos del método que valen para cualquier medición futura de lint:**
- El puntuador de T6 (`analyze_benchmark.rules_with_wrong_count`) cuenta como cuentas los números de
  línea («líneas 12 y 40») y solo lee la cifra detrás del código. Por eso puso 0 a respuestas
  correctas en T6, entre ellas las dos de `qwen36-35b-a3b` que tumbaron su celda de lint en T6 (que
  igualmente fallaba por latencia). La v3 de `evaluate_reevaluation.py` lo corrige (validada en
  `scorer-v2-check.md`, 14 de 16 a mano); si se adopta, hay que llevarla a `analyze_benchmark.py`
  con sus tests y decidir si se re-puntúa T6.
- La línea `(leído server-side: …)` que añade la tool cuenta en las palabras del formato si se puntúa
  la salida de la tool y no la del modelo.
