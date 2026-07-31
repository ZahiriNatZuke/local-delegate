# Result review: observador de capabilities del cliente

## Verdict

`conforms-with-notes` — los siete requisitos están implementados y verificados; las notas son
límites de cobertura ya declarados, no incumplimientos.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 observar caps, identidad y protocolo | sí (`clients.py`, `observar_cliente`) | sí | medido con dos clientes reales |
| REQ-002 leer después del handshake | sí (salta `initialize`) | sí | el test se reescribió porque el primero no probaba nada |
| REQ-003 una línea por identidad y ejecución | sí (dedupe bajo lock) | sí | veinte mensajes → una línea |
| REQ-004 `/api/status` expone los clientes | sí (clave `clients`) | sí | verificado al revés |
| REQ-005 no altera la petición | sí (`try/except` en el middleware) | sí | dos tests, uno end-to-end |
| REQ-006 capabilities sin identidad | sí (lectura separada) | sí | por test; ningún cliente real lo ejerce todavía |
| REQ-007 no registrar identidad vacía | sí (guarda temprana) | sí | requisito nacido de la revisión del plan |

## Findings

1. **La cobertura de REQ-006 es sintética, y está bien que se sepa.** El caso «capabilities sin
   `client_info`» solo existe en la revisión 2026-07-28+, y la medición demostró que **ningún
   cliente real la negocia** (2025-11-25 y 2025-06-18). El test lo cubre; la realidad, no. Anotado
   en `verification.md`, no escondido.

2. **`streamable_http` no se ejerció en vivo.** Los dos clientes usan stdio. El middleware vive en
   `ServerRunner`, que es común a los transportes, pero eso es lectura de código. No bloquea: el
   dashboard del 9393 no recibe conexiones MCP hoy.

3. **El dedupe por identidad tiene una consecuencia real**: dos instancias del mismo cliente y
   versión cuentan como una. Es deliberado —evita atarse a `session._connection`, privado del
   SDK— y está en la spec, en el plan y en la verificación.

4. **Alcance respetado.** No entra el check de `doctor` (decisión del usuario), no se implementa
   `elicitation`, no se toca `auth`.

5. **Un acierto de método que conviene no perder:** verificar los tests al revés reveló que el test
   de REQ-002 no probaba nada. Con el defecto puesto pasaban los catorce, porque quien descartaba
   era la guarda de REQ-007. Sin ese ejercicio, el repo se habría quedado con un test decorativo
   sobre la regla que más caro cuesta descubrir rota.

## Required follow-up

- **Nada bloquea el cierre.**
- Encolado, con el dato ya en la mano: el **check de `doctor`** (change siguiente) y la evaluación
  de **`elicitation`**, que la medición desbloquea en sentido afirmativo.
