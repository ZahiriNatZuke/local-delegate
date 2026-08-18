# Plan review (adversarial)

## Hallazgos

### H1 — El guardián del conteo obliga a tocar seis sitios, no uno (incorporado)

El riesgo del plan se confirmó leyendo el código: `tests/test_checks.py:965` compara **cinco
afirmaciones** del docstring de `checks.py` contra `len(CHECKS)`, con un mapa número→palabra que
sólo llega a `17: "diecisiete"`. Añadir el checkers 18 obliga a:

- añadir `18: "dieciocho"` al mapa `_NUMERO`;
- cambiar los cinco textos, incluido `ver los otros {n-1}` que pasa a «diecisiete».

No es ceremonia: ese test existe porque el módulo llegó a decir «once» con doce checks dentro y
alguien planificó sobre el dato falso. Se añade a las tareas.

### H2 — Un `warn` nuevo puede volver ruidoso a `doctor` en máquinas sanas (mitigado)

Si `daemon_needs_token` devolviera `True` en cualquier puerto ocupado, el check avisaría en toda
máquina con el daemon abierto. Su docstring dice que separa «ahí hay otra cosa» de «ahí está
nuestro daemon protegido», y el plan ya obliga a comprobarlo en `daemon.daemon_requires_token`
antes de escribir nada. **Verificación obligatoria, no opcional**: es la diferencia entre un check
útil y uno que se aprende a ignorar — la lección de esta misma jornada con el hook.

### H3 — Los dos avisos son de fuerza distinta y deben leerse distinto (ya en el plan)

«No hay cabecera» es una avería segura; «la variable está vacía en el entorno de `doctor`» es una
sospecha con testigo, porque el cliente puede haberse lanzado desde otra consola. Redactarlos
igual convertiría la segunda en una certeza falsa, que es cómo se fabrica un check que la gente
desactiva.

### H4 — El check no puede pisar lo que ya dice `service.credential` (aceptado)

Los dos hablan de autenticación y podrían solaparse en el informe. No se solapan: aquel mira el
**backend** (¿tiene el proceso MCP la API key?) y este el **daemon** (¿puede el cliente entrar al
puerto?). Son dos puertas distintas del mismo camino y las dos pueden estar cerradas por separado
— de hecho hoy la del backend estaba bien y la del daemon no. Se deja explícito en el docstring
para que nadie los funda más adelante.

### H5 — Falta decidir qué pasa con `stdio` (resuelto por REQ-005)

Una entrada `stdio` no habla con el puerto del daemon, así que contarla como «ciega» aquí sería un
falso positivo, y encima duplicaría el aviso que ya da `service.credential`.

## Veredicto

Sin hallazgo bloqueante. H1 entra como tarea; H2 pasa a verificación obligatoria.
