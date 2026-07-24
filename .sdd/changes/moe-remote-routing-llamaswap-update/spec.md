# Specification: paquete de decision antes de implementar nuevas capacidades

## Summary

La siguiente fase produce evidencia reproducible y decisiones go/no-go. Ningun cambio de runtime,
modelo o version se promociona a estable por intuicion o por ser la release mas reciente.

## Requirements

- **REQ-001 — MoE correcto:** el estudio debe distinguir parametros totales, activos por token,
  residencia de pesos y offload. No definira cantidad de expertos por tipo de tarea.
- **REQ-002 — Benchmark:** gpt-oss-20b se compara contra los roles densos actuales en un corpus
  versionado, con sweep de contexto/offload y tres corridas por caso.
- **REQ-003 — Segundo candidato condicional:** Qwen3-30B-A3B solo se descarga/prueba si gpt-oss pasa
  memoria, estabilidad y calidad minimas.
- **REQ-004 — Documentos largos:** el benchmark debe detectar truncacion. PDF se evalua solo con
  extraccion reproducible; chunking/map-reduce se especifica como cambio separado si hace falta.
- **REQ-005 — Delegacion Claude:** se crea una linea base de oportunidades elegibles y se prueban
  hooks antes del gasto (`UserPromptSubmit`/`PreToolUse`), sin bloquear tools ni guardar contenido.
- **REQ-006 — Umbrales:** el resultado debe recomendar bandas por tamaño+intencion y reportar tasa
  de adopcion, falsos positivos, errores, latencia y tokens ahorrados.
- **REQ-007 — Remoto:** se valida primero MCP local en Mac con backend remoto autenticado en PC;
  MCP remoto directo queda documentado con la limitacion de paths.
- **REQ-008 — Seguridad remota:** el backend escucha solo en interfaz privada, usa API key fuera de
  loopback y nunca persiste el secreto en repo, SDD, logs o ejemplos.
- **REQ-009 — Versiones:** `llama-swap`/`llama-server` usan canal canary lado a lado, 7 dias de soak
  upstream, suite real y rollback antes de cambiar la version recomendada.
- **REQ-010 — Decision:** cada linea termina en `adopt`, `iterate` o `reject`, con evidencia y una
  implementacion posterior separada si corresponde.

## Acceptance scenarios

### MoE no se confunde con carga dinamica de expertos

- **Given** una tarea de resumen o lectura
- **When** se analiza el modelo MoE
- **Then** se reporta el top-k fijo del modelo y se optimiza offload/contexto, no un numero inventado
  de expertos para esa tarea

### Benchmark reproducible

- **Given** el mismo corpus, seed, cuantizacion y configuracion
- **When** se ejecutan tres corridas por variante
- **Then** quedan resultados JSON/CSV con calidad, memoria, throughput y latencia comparables

### Claude mejora sin ruido

- **Given** una oportunidad mecanica elegible
- **When** los hooks experimentales estan activos
- **Then** Claude recibe la sugerencia antes de Read/Bash y la adopcion aumenta sin superar 10% de
  falsos positivos en la muestra revisada

### Mac usa computo de PC y conserva `path`

- **Given** un archivo solo presente en la Mac
- **When** el MCP local de la Mac usa llama-swap remoto
- **Then** la tool procesa el archivo, el contenido no aparece en el contexto del host y la PC hace
  la inferencia autenticada

### Release inmadura

- **Given** una version de menos de 7 dias o un issue relevante abierto
- **When** corre el chequeo de upgrade
- **Then** queda en canary/hold y no cambia `RECOMMENDED_VERSIONS`

## Quantitative gates

### MoE

- pico <=14.5 GiB VRAM y <=28 GiB RAM;
- sin pagefile/shared-memory fallback ni crash en 20 iteraciones;
- decode >=10 tok/s y p95 aceptable para la clase de tarea;
- calidad >= baseline denso del rol y cero perdida silenciosa por truncacion.

### Delegation UX

- adopcion >=40% de oportunidades elegibles durante el piloto;
- falsos positivos <=10%;
- cero bloqueos automaticos; fallback claro si backend no responde;
- telemetria solo de tipo/tamaño/decision/latencia, nunca contenido.

### Remote

- 20 llamadas mixtas sin fallo de auth/reconexion;
- `path` de Mac procesado localmente;
- API sin acceso no autenticado desde la interfaz privada;
- overhead de red documentado frente al baseline local.

### Upgrade

- checksums validos, todos los roles y endpoints verdes, concurrencia/TTL sin deadlock observado,
  soak local de 24 h y rollback probado.

## Non-goals

- Entrenar routers, cambiar top-k, cachear expertos selectivamente o implementar expert parallelism.
- Exponer servicios a Internet publica.
- Meter un LLM adicional para decidir si llamar al LLM local.
- Implementar o publicar features durante esta fase de decision.

## Traceability

REQ-001..004 -> Plan 1; REQ-005..006 -> Plan 2; REQ-007..008 -> Plan 3;
REQ-009 -> Plan 4; REQ-010 -> Plan 5.
