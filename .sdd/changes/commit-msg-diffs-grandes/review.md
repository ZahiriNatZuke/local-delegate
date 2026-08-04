# Result review: local_commit_msg deja de truncar diffs grandes

## Verdict

`conforms-with-notes` — los siete requisitos están implementados y verificados; REQ-004 con dos
límites de calidad anotados que no bloquean el uso.

## Specification comparison

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 procesa el diff completo | sí | backend real | 44 archivos, 164 585 chars, `chunks: 17`. Necesitó la tarea 6 (reintento), que el plan original no preveía |
| REQ-002 trozos en frontera de archivo | sí | ejecución + tests | 12/13; el 13.º es `uv.lock`, que solo ya excede el presupuesto — el escenario 4 lo admite explícitamente |
| REQ-003 inventario completo al reduce | sí | contraste independiente | 0 discrepancias en 44 archivos contra `git diff --numstat` |
| REQ-004 formato y utilidad del mensaje | sí | backend real | El titular es correcto y utilizable; el tipo y el cuerpo, irregulares (ver findings) |
| REQ-005 el diff pequeño no cambia | sí | tests con mock | 1 llamada, sin nota de alcance |
| REQ-006 un evento con `chunks: N` | sí | tests con mock | Reutiliza la contabilidad existente sin tocarla |
| REQ-007 alcance visible | sí | backend real | Va siempre, no bajo `FEEDBACK_ENABLED`, y el porqué está escrito |

## Findings

1. **El tipo del commit no siempre acierta** (menor, aceptado). El caso coherente sale `feat`
   donde un humano pondría `fix`. La descripción de la tool ya dice que hay que revisar el mensaje
   antes de usarlo, y este cambio no altera esa expectativa.
2. **El cuerpo con viñetas aparece de forma irregular** (menor, aceptado). El formato lo declara
   opcional; el titular, que es lo que se usa, ya es correcto.
3. **El reintento por desborde cubre el map y no el reduce** (menor, anotado como límite). El
   reduce trabaja sobre prosa generada por el propio modelo, de densidad predecible, y tiene su
   bucle de reagrupación. No se declara cubierto.
4. **Dos defectos de proceso propios, encontrados y corregidos durante el trabajo**: un test que
   pasaba igual sin el cambio que medía (el de desborde irrecuperable) y otro que buscaba una
   ruta que ya estaba dentro del propio diff. Los dos se rehicieron con control positivo.
5. **Una hipótesis propia caída**: el diagnóstico de la calidad empezó suponiendo que el reduce
   copiaba la estructura del map. El espía sobre `_run_chat` mostró que el reduce era fiel a lo
   que recibía y que los dos defectos estaban en el map. Arreglar el reduce no habría servido de
   nada.

## Required follow-up

Ninguno bloqueante. Como mejora futura, evaluable ahora que hay una base medida: filtrar el ruido
del diff (lockfiles, generados, líneas de contexto sin cambiar) reduciría el número de trozos y el
coste, y quedó fuera de alcance a propósito en la spec.
