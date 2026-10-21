# Traspaso: restos menores

## Estado

- SDD ligero cerrado el 2026-10-21; revisión `64ee382`; entra en la 0.39.0.

## Qué cambió

- Panel: tema según el sistema mientras no se elija con el botón; booleanos `on`/`off` (#385).
- `doctor`: check `config.claude_settings` (no UTF-8 y copia `.bak` de la migración), 27 checks (#384).
- Autocompletado/instalador: 7 restos de `cli-completion` (#386).
- Test de «resolver una vez por operación» de backend-params (#383).
- Wiki: presupuesto mínimo de razonamiento del rol `code` = 4096 con Qwen3.6 (#387).

## Decisiones

- Decisiones de producto del usuario (2026-10-21): tema del sistema; WARN por no UTF-8; WARN por la
  `.bak` con sugerencia de borrarla.
- `read_text` sigue con `errors="replace"`: la lectura estricta vive solo en el check nuevo.
- Sin aviso en `backend-params set` por debajo de 4096: la medición no lo justificó.
- Sin acción: §1.15.3 (solo con caso real) y §1.15.5 (0.41.0, lo pide el test de horizonte).
