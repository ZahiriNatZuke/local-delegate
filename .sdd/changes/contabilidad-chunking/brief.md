# Brief — contabilidad real del chunking y map-reduce

## Problema

El panel de ahorro es el propósito del proyecto, y **no distingue una delegación eficiente de una
que quemó la GPU dieciséis veces**. N llamadas al backend se registran como **un** evento con
`chunks: N`, y todos los KPIs derivan de `chars_in ÷ 4`. Punto de partida del backlog:
*«la contabilidad del chunking y el map-reduce sesga las métricas»*.

Además, la fase 3 del SDK `mcp` 2.x trae OpenTelemetry, y había que decidir **antes de escribir
código** si sustituye o complementa el `usage-YYYYMM.jsonl`: son dos diseños distintos.

## Resultado buscado

Que el dashboard enseñe **el coste enfrente del ahorro**, con el trabajo real que hizo la GPU, de
forma que una delegación troceada se distinga a simple vista de una directa.

## En alcance

- Contabilizar las llamadas reales al backend y los tokens reales que el backend ya reporta.
- Presentar coste y ahorro como magnitudes separadas, en el panel y en la documentación.
- Corregir el caso de `local_describe_image`, donde `chars_in` son bytes de un binario.
- Decidir y **registrar** el papel de OpenTelemetry.

## Fuera de alcance

- Montar OpenTelemetry (colector, exportador) — descartado con su porqué escrito.
- Reescribir o migrar el log histórico.
- La estrategia de troceado en sí (ventana de solapamiento, glosario acumulado del map-reduce):
  es otra deuda del backlog con su propio change.
- Telemetría de hooks y autenticación del dashboard.

## Restricciones y riesgos

- El log es **histórico y no se reescribe**: lo nuevo tiene que degradar sin inventar números.
- El formato del log solo puede **añadir** campos opcionales.
- El dashboard debe seguir funcionando **recién instalado, sin configurar servicios**.
- Riesgo principal: confundir ahorro con coste y "corregir" un KPI que estaba bien.

## Preguntas abiertas — resueltas antes de especificar

- **¿OTel sustituye, complementa o se descarta?** → **Descartado** como fuente de métricas
  (decisión del usuario, con tres razones verificadas ejecutando).
- **¿El sesgo de `local_describe_image` entra aquí?** → **Sí**: misma raíz.
